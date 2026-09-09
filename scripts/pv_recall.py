"""Measure PV detection against the federal register's recorded capacity.

The register states installed kW for a building. A modern module produces about
0.19-0.20 kW per square metre of module, so recorded capacity implies a module
area that the detector ought to find. This is weaker than a hand-drawn mask, but
it is real ground truth over many roofs and needs no labelling.
"""
import argparse
import asyncio
import base64
import json
import sys
from io import BytesIO
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services import map_service as ms

BASE = "http://127.0.0.1:8000"
MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
REGISTER = "ch.bfe.elektrizitaetsproduktionsanlagen"
TO_SWISS = Transformer.from_crs(4326, 2056, always_xy=True)
PANEL = {"width": 1.762, "height": 1.134, "power": 450, "gap": 0.02}
# Module area per kW for a modern crystalline module.
M2_PER_KW = 1.0 / 0.19


async def registered_plants(client, lat, lon, half=2500, limit=60):
    x, y = TO_SWISS.transform(lon, lat)
    r = await client.get(MAP + "/identify", params={
        "geometry": f"{x-half},{y-half},{x+half},{y+half}",
        "geometryType": "esriGeometryEnvelope", "layers": "all:" + REGISTER,
        "sr": 2056, "geometryFormat": "geojson", "returnGeometry": "true",
        "tolerance": 0, "mapExtent": f"{x-half*2},{y-half*2},{x+half*2},{y+half*2}",
        "imageDisplay": "1000,1000,96", "lang": "en", "limit": limit})
    r.raise_for_status()
    out = []
    for f in r.json().get("results", []):
        p = f["properties"]
        if p.get("sub_category_en") != "Photovoltaic" or not f.get("geometry"):
            continue
        power = p.get("total_power") or ""
        try:
            kw = float(str(power).split()[0].replace(",", "."))
        except (ValueError, IndexError):
            continue
        out.append((kw, shape(f["geometry"]).representative_point(), p))
    return out


async def one(client, kw, point, props, render):
    lon, lat = ms.TO_WGS84.transform(point.x, point.y)
    cap = await client.post(BASE + "/api/map/prepare",
                            json={"latitude": lat, "longitude": lon})
    if cap.status_code != 200:
        return None
    cap = cap.json()
    if len(cap.get("roof") or []) < 3:
        return None
    image_bytes = base64.b64decode(cap["image_base64"])
    settings = {"roof": cap["roof"], "objects": cap["objects"], "mode": "recommended",
                "panel": PANEL, "pixels_per_metre": cap["pixels_per_metre"],
                "approximate_roof_width": 12, "scale_verified": True,
                "angle": cap["angle"], "use_ai": True, "edge_margin": .3,
                "obstacle_margin": .4, "pv_margin": .2,
                "capture_id": cap["capture_id"]}
    res = await client.post(BASE + "/api/analyse",
                            files={"image": ("r.jpg", image_bytes, "image/jpeg")},
                            data={"settings": json.dumps(settings)})
    if res.status_code != 200:
        return None
    d = res.json()
    ppm = cap["pixels_per_metre"]
    found = 0.0
    for o in d["existing_pv"]:
        polygon = Polygon(o["polygon"]).buffer(0)
        if not polygon.is_empty:
            found += polygon.area / ppm ** 2
    expected = kw * M2_PER_KW
    if render:
        im = np.asarray(Image.open(BytesIO(image_bytes)).convert("RGB"))
        vis = im.copy()
        for q in d["proposed_panels"]:
            cv2.polylines(vis, [np.array(q, np.int32)], True, (90, 255, 90), 1)
        for o in d["existing_pv"]:
            cv2.polylines(vis, [np.array(o["polygon"], np.int32)], True, (0, 130, 255), 2)
        cv2.polylines(vis, [np.array(cap["roof"], np.int32)], True, (255, 255, 255), 1)
        Image.fromarray(vis).save(render)
    return {"address": props.get("address", "")[:34], "kw": kw,
            "expected_m2": round(expected, 1), "found_m2": round(found, 1),
            "recall": round(found / expected, 2) if expected else None,
            "proposed": d["statistics"]["additional_panel_count"],
            "lat": lat, "lon": lon}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--count", type=int, default=12)
    args = ap.parse_args()
    out = Path(args.out) if args.out else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
    rows = []
    async with httpx.AsyncClient(timeout=900) as client:
        plants = await registered_plants(client, 47.3767, 8.5241)
        # House-to-small-commercial scale, largest first.
        plants = sorted([p for p in plants if 5 <= p[0] <= 80], key=lambda p: -p[0])
        for i, (kw, point, props) in enumerate(plants[:args.count]):
            render = str(out / f"pv{i:02d}.png") if out else None
            try:
                row = await one(client, kw, point, props, render)
            except (httpx.HTTPError, ValueError) as exc:
                row = None
                print("  error", type(exc).__name__, exc)
            if row:
                rows.append(row)
                print(f"{row['address']:<34}{row['kw']:>7.1f} kW"
                      f"{row['expected_m2']:>9.1f}{row['found_m2']:>9.1f}"
                      f"{(row['recall'] or 0):>7.2f}{row['proposed']:>7}")
    if rows:
        good = [r for r in rows if r["recall"] is not None]
        detected = sum(1 for r in good if r["recall"] >= .5)
        print("-" * 74)
        print(f"roofs {len(good)} | found >=50% of expected array on {detected}"
              f" | median recall {np.median([r['recall'] for r in good]):.2f}"
              f" | total expected {sum(r['expected_m2'] for r in good):.0f} m2"
              f" found {sum(r['found_m2'] for r in good):.0f} m2")
    if out:
        (out / "pv_recall.json").write_text(json.dumps(rows, indent=1))


asyncio.run(main())
