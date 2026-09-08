"""Sanity check: run the whole map -> analysis pipeline over a spread of real Swiss roofs.

Picks buildings straight out of the Sonnendach layer near a set of towns, so the
sample is real housing stock rather than hand-chosen easy cases.
"""

import asyncio
import base64
import json
import sys

import httpx
from pyproj import Transformer
from shapely.geometry import shape

BASE = "http://127.0.0.1:8000"
LAYER = "ch.bfe.solarenergie-eignung-daecher"
MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
TO_SWISS = Transformer.from_crs(4326, 2056, always_xy=True)
TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)

PLACES = [
    ("Zurich centre", 47.3769, 8.5417),
    ("Winterthur", 47.5000, 8.7241),
    ("Bern Laenggasse", 46.9530, 7.4300),
    ("Lausanne", 46.5210, 6.6320),
    ("Lugano", 46.0050, 8.9520),
    ("Chur", 46.8500, 9.5300),
    ("Brugg", 47.4810, 8.2070),
    ("St Gallen", 47.4245, 9.3767),
]
PANEL = {"width": 1.762, "height": 1.134, "power": 450, "gap": 0.02}


async def a_building_near(client, lat, lon):
    """Return a point that actually sits on a roof polygon near this place."""
    x, y = TO_SWISS.transform(lon, lat)
    r = await client.get(
        MAP + "/identify",
        params={
            "geometry": f"{x - 150},{y - 150},{x + 150},{y + 150}",
            "geometryType": "esriGeometryEnvelope",
            "layers": "all:" + LAYER,
            "sr": 2056,
            "geometryFormat": "geojson",
            "returnGeometry": "true",
            "tolerance": 0,
            "mapExtent": f"{x - 200},{y - 200},{x + 200},{y + 200}",
            "imageDisplay": "1000,1000,96",
            "limit": 50,
        },
    )
    r.raise_for_status()
    shapes = [shape(f["geometry"]) for f in r.json()["results"] if f.get("geometry")]
    if not shapes:
        return None
    # Prefer a house-sized roof over the largest block in the frame.
    houses = [g for g in shapes if 30 <= g.area <= 250] or shapes
    point = max(houses, key=lambda g: g.area).representative_point()
    lon2, lat2 = TO_WGS84.transform(point.x, point.y)
    return lat2, lon2


async def analyse(client, capture):
    settings = {
        "roof": capture["roof"],
        "objects": capture["objects"],
        "mode": "recommended",
        "panel": PANEL,
        "pixels_per_metre": capture["pixels_per_metre"],
        "approximate_roof_width": 12,
        "scale_verified": True,
        "angle": capture["angle"],
        "annual_specific_yield": 950,
        "use_ai": True,
        "edge_margin": 0.3,
        "obstacle_margin": 0.4,
        "pv_margin": 0.2,
    }
    r = await client.post(
        BASE + "/api/analyse",
        files={"image": ("roof.jpg", base64.b64decode(capture["image_base64"]), "image/jpeg")},
        data={"settings": json.dumps(settings)},
    )
    return r


def square_around(lat, lon, half_m=7.0):
    """A hand-drawn-looking square, as if clicked corner by corner on the map."""
    x, y = TO_SWISS.transform(lon, lat)
    corners = [
        (x - half_m, y - half_m),
        (x + half_m, y - half_m),
        (x + half_m, y + half_m),
        (x - half_m, y + half_m),
    ]
    return [
        {"latitude": la, "longitude": lo}
        for lo, la in (TO_WGS84.transform(cx, cy) for cx, cy in corners)
    ]


async def main():
    failures = []
    async with httpx.AsyncClient(timeout=180) as client:
        print(f"{'place':<18}{'mode':<10}{'planes':>7}{'roof m2':>9}{'usable':>9}{'panels':>8}{'kWp':>8}{'use%':>7}")
        print("-" * 76)
        for name, lat, lon in PLACES:
            found = await a_building_near(client, lat, lon)
            if not found:
                failures.append(f"{name}: no roof polygon found nearby")
                continue
            rlat, rlon = found
            for mode, body in (
                ("automatic", {"latitude": rlat, "longitude": rlon}),
                ("drawn", {"latitude": rlat, "longitude": rlon, "polygon": square_around(rlat, rlon)}),
            ):
                r = await client.post(BASE + "/api/map/prepare", json=body)
                if r.status_code != 200:
                    failures.append(f"{name}/{mode}: prepare {r.status_code} {r.text[:120]}")
                    continue
                cap = r.json()
                if len(cap["roof"]) < 3:
                    failures.append(f"{name}/{mode}: no roof outline returned")
                    continue
                ar = await analyse(client, cap)
                if ar.status_code != 200:
                    failures.append(f"{name}/{mode}: analyse {ar.status_code} {ar.text[:120]}")
                    continue
                s = ar.json()["statistics"]
                print(
                    f"{name:<18}{mode:<10}{cap['provenance']['merged_planes']:>7}"
                    f"{s['roof_area_m2']:>9.1f}{s['usable_area_m2']:>9.1f}"
                    f"{s['additional_panel_count']:>8}{s['additional_kwp']:>8.2f}"
                    f"{s['roof_utilisation']:>7.1f}"
                )
                if s["usable_area_m2"] > s["roof_area_m2"] + 0.01:
                    failures.append(f"{name}/{mode}: usable area exceeds roof area")
                if s["roof_utilisation"] > 95:
                    failures.append(f"{name}/{mode}: implausible {s['roof_utilisation']}% coverage")
    print()
    if failures:
        print(f"{len(failures)} PROBLEM(S):")
        for f in failures:
            print("  -", f)
        sys.exit(1)
    print("All roofs passed.")


asyncio.run(main())
