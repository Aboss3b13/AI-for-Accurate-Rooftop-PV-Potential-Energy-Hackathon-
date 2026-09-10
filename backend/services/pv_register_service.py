"""Registered PV for a building, from the federal production-plant register.

Why infer from a photograph what Switzerland already records? Sonnendach carries
each roof's federal building identifier (EGID), and the SFOE register of
electricity production plants is keyed by the same identifier. Matching the two
gives the installed capacity, the plant type and the commissioning date as
recorded fact rather than as a detection.

It gives capacity, not geometry: the register says a 5.25 kW array exists, never
which part of the roof it covers. Locating it on the roof still needs the image.
So this does not replace the vision model - it checks it, and it catches the
case the model is worst at, an array it failed to see at all.

Coverage is not total either. The register holds plants in the guarantee-of-
origin system: larger installations are obliged to register, small private ones
appear only if they were registered or subsidised. Absence is therefore weak
evidence, and is reported as unknown rather than as none.
"""

import re

import httpx

API = "https://api3.geo.admin.ch/rest/services/all/MapServer"
LAYER = "ch.bfe.elektrizitaetsproduktionsanlagen"
PHOTOVOLTAIC = "photovoltaic"
MAX_ENTRIES = 50
# Capacity arrives as text: "5.25 kW", "1.4 MW".
POWER = re.compile(r"([\d.,]+)\s*([kKmM])?[wW]")
SCALE = {"k": 1.0, "m": 1000.0}


class RegisterUnavailable(Exception):
    """The register could not be read; the caller carries on without it."""


def parse_power_kw(text) -> float | None:
    """Return kilowatts from the register's free-text power field."""
    if text is None:
        return None
    match = POWER.search(str(text))
    if not match:
        return None
    try:
        value = float(match.group(1).replace(",", "."))
    except ValueError:
        return None
    return value * SCALE.get((match.group(2) or "k").lower(), 1.0)


def summarise(entries: list[dict]) -> dict:
    """Fold the register rows for one building into a single statement."""
    plants = []
    for entry in entries:
        properties = entry.get("properties", entry)
        category = str(properties.get("sub_category_en") or "").strip().lower()
        if category != PHOTOVOLTAIC:
            continue
        plants.append(
            {
                "power_kw": parse_power_kw(properties.get("total_power")),
                "commissioned": properties.get("beginning_of_operation"),
                "mounting": properties.get("plant_type_en"),
                "address": properties.get("address"),
            }
        )
    known = [p["power_kw"] for p in plants if p["power_kw"] is not None]
    return {
        "known": bool(plants),
        "plant_count": len(plants),
        "total_power_kw": round(sum(known), 2) if known else None,
        "plants": plants[:MAX_ENTRIES],
        "basis": "SFOE register of electricity production plants, matched on the "
                 "federal building identifier (EGID).",
        "coverage_note": "The register covers plants in the guarantee-of-origin "
                         "system. A small private array may be absent, so no entry "
                         "is not proof that the roof is bare.",
    }


async def registered_pv(client: httpx.AsyncClient, egids) -> dict:
    """Look up every PV plant recorded against these building identifiers."""
    wanted = []
    for egid in egids or []:
        try:
            number = int(float(egid))
        except (TypeError, ValueError):
            continue
        if number > 0 and number not in wanted:
            wanted.append(number)
    if not wanted:
        return {**summarise([]), "known": False, "egids": []}
    entries = []
    try:
        for egid in wanted[:4]:
            response = await client.get(
                API + "/find",
                params={
                    "layer": LAYER, "searchField": "egid", "searchText": str(egid),
                    "contains": "false", "sr": 2056, "geometryFormat": "geojson",
                    "returnGeometry": "false", "lang": "en", "limit": MAX_ENTRIES,
                },
            )
            response.raise_for_status()
            entries.extend(response.json().get("results", []))
    except (httpx.HTTPError, ValueError) as exc:
        raise RegisterUnavailable("The federal plant register could not be reached") from exc
    return {**summarise(entries), "egids": wanted}
