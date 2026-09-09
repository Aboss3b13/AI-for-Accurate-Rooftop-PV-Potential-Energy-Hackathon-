"""How old each source is, and what that disagreement implies.

Five datasets answer for one roof and none of them were surveyed on the same
day. swisstopo flies imagery and the surface model on multi-year cycles; the
federal plant register updates monthly; Sonnendach carries its own revision
date. Two perfectly correct sources can therefore describe different buildings.

The case that actually costs a user money is narrow and checkable: an array
commissioned after the aerial photo was taken cannot appear in it, so the
detector is not wrong to miss it and the roof is not as empty as it looks.
"""

import re
from datetime import date

import httpx

STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections"
IMAGERY_COLLECTION = "ch.swisstopo.swissimage-dop10"
TO_WGS84_YEAR = re.compile(r"_((?:19|20)\d{2})_")
SWISS_DATE = re.compile(r"^(\d{2})\.(\d{2})\.((?:19|20)\d{2})$")
# Below this the sources are close enough that survey drift is not worth a note.
STALE_YEARS = 3


def tile_year(name) -> int | None:
    """swisstopo names every tile with the year it was surveyed."""
    if not name:
        return None
    match = TO_WGS84_YEAR.search(str(name).rsplit("/", 1)[-1])
    return int(match.group(1)) if match else None


def swiss_date(text) -> date | None:
    """Parse the dd.mm.yyyy dates used by Sonnendach and the plant register."""
    match = SWISS_DATE.match(str(text or "").strip())
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


async def imagery_year(client: httpx.AsyncClient, bounds_wgs84) -> int | None:
    """Newest aerial survey published over this footprint."""
    west, south, east, north = bounds_wgs84
    try:
        response = await client.get(
            f"{STAC}/{IMAGERY_COLLECTION}/items",
            params={"bbox": f"{west},{south},{east},{north}", "limit": 50},
        )
        response.raise_for_status()
        years = []
        for feature in response.json().get("features", []):
            stamp = (feature.get("properties") or {}).get("datetime") or ""
            year = tile_year(feature.get("id")) or (
                int(stamp[:4]) if stamp[:4].isdigit() else None
            )
            if year:
                years.append(year)
        return max(years) if years else None
    except (httpx.HTTPError, ValueError, KeyError):
        return None


def findings(vintage: dict, register: dict) -> list[str]:
    """Statements worth showing the user, and nothing else."""
    notes = []
    photo = vintage.get("imagery_year")
    surface = vintage.get("surface_year")

    newer = []
    for plant in (register or {}).get("plants", []):
        commissioned = swiss_date(plant.get("commissioned"))
        if photo and commissioned and commissioned.year > photo:
            newer.append((commissioned, plant))
    if newer:
        when = max(c for c, _ in newer)
        power = sum(p.get("power_kw") or 0 for _, p in newer)
        notes.append(
            f"An installation registered in {when.year} is newer than the {photo} "
            "aerial survey, so it cannot appear in this image"
            + (f" ({power:g} kW)" if power else "")
            + ". Treat the roof as more occupied than the photograph shows."
        )
    if photo and surface and abs(photo - surface) >= STALE_YEARS:
        notes.append(
            f"The aerial image ({photo}) and the height model ({surface}) are "
            f"{abs(photo - surface)} years apart. A roof changed between the two "
            "surveys can look inconsistent between structures and the photo."
        )
    if photo and date.today().year - photo >= STALE_YEARS + 2:
        notes.append(
            f"The most recent aerial survey here is from {photo}. Anything built "
            "since then is invisible to the image."
        )
    return notes


def confidence(vintage: dict, register: dict, fitted_faces: int, faces: int) -> list[dict]:
    """Confidence attached to each input, rather than one invented headline."""
    photo = vintage.get("imagery_year")
    age = (date.today().year - photo) if photo else None
    geometry = "high" if faces and fitted_faces == faces else (
        "medium" if fitted_faces else "low")
    freshness = "low" if age is None else (
        "high" if age <= 2 else "medium" if age <= 4 else "low")
    return [
        {"input": "Roof geometry", "level": "high",
         "note": "Official Sonnendach faces"},
        {"input": "Roof-plane fit", "level": geometry,
         "note": f"{fitted_faces} of {faces} face(s) fitted to the height model"},
        {"input": "Aerial freshness", "level": freshness,
         "note": f"Survey year {photo}" if photo else "Survey year unknown"},
        {"input": "Existing PV presence", "level": "high" if register.get("known") else "low",
         "note": "Federal plant register" if register.get("known")
                 else "No register entry; small arrays need not be registered"},
        {"input": "Existing PV position", "level": "medium",
         "note": "Located from the image; no dataset records where panels sit"},
        {"input": "Raised structures", "level": "high",
         "note": "Measured against each face's own plane"},
        {"input": "Flush rooflights", "level": "medium",
         "note": "Colour heuristic; no height signal exists"},
        {"input": "Local shading", "level": "medium",
         "note": "Static height model, not an hourly weather simulation"},
        {"input": "Structural capacity", "level": "not assessed",
         "note": "Requires construction details"},
        {"input": "Regulatory compliance", "level": "not assessed",
         "note": "Clearances here are planning assumptions"},
    ]
