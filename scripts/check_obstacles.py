"""Report height-model obstacle detection across real Swiss houses."""

import asyncio
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shapely.geometry import Point, shape
from shapely.ops import unary_union

from backend.services import elevation_service as es
from backend.services import map_service as ms

MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
PLACES = [
    ("Zurich", 47.37673821772424, 8.541378513794966, False),
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


async def facets_at(client, lat, lon):
    x, y = ms.TO_SWISS.transform(lon, lat)
    click = Point(x, y)
    data = await ms.get_json(
        client,
        "/MapServer/identify",
        {
            "geometry": f"{x},{y}",
            "geometryType": "esriGeometryPoint",
            "layers": "all:" + ms.ROOF_LAYER,
            "sr": 2056,
            "geometryFormat": "geojson",
            "returnGeometry": "true",
            "tolerance": 0,
            "lang": "en",
            "mapExtent": f"{x - 100},{y - 100},{x + 100},{y + 100}",
            "imageDisplay": "1000,1000,96",
        },
    )
    features = data.get("results", [])
    planes = ms.feature_planes(features, click)
    if not planes:
        return []
    building = planes[0]["properties"].get("building_id")
    if building is not None:
        siblings = await ms.get_json(
            client,
            "/MapServer/find",
            {
                "layer": ms.ROOF_LAYER,
                "searchField": "building_id",
                "searchText": str(building),
                "contains": "false",
                "sr": 2056,
                "geometryFormat": "geojson",
                "returnGeometry": "true",
                "lang": "en",
                "limit": 100,
            },
        )
        features += siblings.get("results", [])
    return [p["geometry"] for p in ms.feature_planes(features, click)]


async def main():
    problems = []
    async with httpx.AsyncClient(timeout=180) as client:
        print(f"{'place':<12}{'roof m2':>9}{'found':>7}{'chim':>6}{'blocked m2':>12}{'%':>7}  tallest")
        print("-" * 68)
        for name, lat, lon, sample in PLACES:
            if sample:
                found = await a_house(client, lat, lon)
                if not found:
                    problems.append(f"{name}: no roof nearby")
                    continue
                lat, lon = found
            facets = await facets_at(client, lat, lon)
            if not facets:
                problems.append(f"{name}: no facets")
                continue
            merged = unary_union(facets)
            obstacles = await es.roof_obstacles(client, facets, merged.bounds)
            blocked = sum(o["area_m2"] for o in obstacles)
            chimneys = sum(1 for o in obstacles if o["kind"] == "chimney")
            tallest = max((o["height_m"] for o in obstacles), default=0.0)
            share = 100 * blocked / merged.area
            print(
                f"{name:<12}{merged.area:>9.1f}{len(obstacles):>7}{chimneys:>6}"
                f"{blocked:>12.1f}{share:>7.1f}  {tallest:.1f} m"
            )
            if share > 40:
                problems.append(f"{name}: {share:.0f}% of the roof flagged as obstacle")
            for o in obstacles:
                if not merged.buffer(0.5).contains(o["geometry"].centroid):
                    problems.append(f"{name}: obstacle detected outside the roof")
                    break
    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
        sys.exit(1)
    print("Obstacle detection looks sane on every roof.")


asyncio.run(main())
