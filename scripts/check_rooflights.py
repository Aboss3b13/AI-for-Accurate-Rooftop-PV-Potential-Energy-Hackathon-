"""Check roof-window detection over real Swiss roofs, for misses and false alarms."""

import asyncio
import base64
import sys
from io import BytesIO
from pathlib import Path

import httpx
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.schemas.map import MapSelection
from backend.services import map_service as ms

MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
PLACES = [
    ("Zurich (yours)", 47.376171086404476, 8.524092630886432, False),
    ("Winterthur", 47.5000, 8.7241, True),
    ("Bern", 46.9530, 7.4300, True),
    ("Lausanne", 46.5210, 6.6320, True),
    ("Lugano", 46.0050, 8.9520, True),
    ("Chur", 46.8500, 9.5300, True),
    ("Brugg", 47.4810, 8.2070, True),
    ("St Gallen", 47.4245, 9.3767, True),
]


async def a_house(client, lat, lon):
    x, y = ms.TO_SWISS.transform(lon, lat)
    r = await client.get(
        MAP + "/identify",
        params={
            "geometry": f"{x - 150},{y - 150},{x + 150},{y + 150}",
            "geometryType": "esriGeometryEnvelope",
            "layers": "all:" + ms.ROOF_LAYER,
            "sr": 2056,
            "geometryFormat": "geojson",
            "returnGeometry": "true",
            "tolerance": 0,
            "mapExtent": f"{x - 200},{y - 200},{x + 200},{y + 200}",
            "imageDisplay": "1000,1000,96",
            "limit": 50,
        },
    )
    shapes = [shape(f["geometry"]) for f in r.json()["results"] if f.get("geometry")]
    houses = [g for g in shapes if 30 <= g.area <= 250] or shapes
    if not houses:
        return None
    point = max(houses, key=lambda g: g.area).representative_point()
    return ms.TO_WGS84.transform(point.x, point.y)[::-1]


async def main():
    problems = []
    async with httpx.AsyncClient(timeout=180) as client:
        print(f"{'place':<16}{'roof m2':>9}{'windows':>9}{'raised':>8}{'blocked m2':>12}{'%':>7}")
        print("-" * 62)
        for name, lat, lon, sample in PLACES:
            if sample:
                found = await a_house(client, lat, lon)
                if not found:
                    problems.append(f"{name}: no roof nearby")
                    continue
                lat, lon = found
            cap = await ms.prepare_capture(MapSelection(latitude=lat, longitude=lon))
            if len(cap["roof"]) < 3:
                problems.append(f"{name}: no roof outline")
                continue
            roof = Polygon(cap["roof"])
            ppm = cap["pixels_per_metre"]
            lights = [o for o in cap["objects"] if o["source"] == "image"]
            raised = [o for o in cap["objects"] if o["source"] == "elevation"]
            blocked = sum(Polygon(o["polygon"]).area for o in cap["objects"]) / ppm**2
            roof_m2 = roof.area / ppm**2
            share = 100 * blocked / roof_m2
            print(
                f"{name:<16}{roof_m2:>9.1f}{len(lights):>9}{len(raised):>8}"
                f"{blocked:>12.1f}{share:>7.1f}"
            )
            if share > 45:
                problems.append(f"{name}: {share:.0f}% of the roof blocked")
            for o in lights:
                if Polygon(o["polygon"]).area / ppm**2 > 8:
                    problems.append(f"{name}: a 'roof window' larger than 8 m2")
                    break
    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Roof-window detection looks sane on every roof.")


asyncio.run(main())
