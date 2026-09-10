"""Run the whole pipeline over a spread of real Zurich buildings and render each."""

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
from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services import map_service as ms

BASE = "http://127.0.0.1:8000"
MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("zurich")
PANEL = {"width": 1.762, "height": 1.134, "power": 450, "gap": 0.02}

# Districts across the city, with the roof size band to sample in each.
SPOTS = [
    ("01 Altstadt", 47.3717, 8.5423, 80, 300),
    ("02 Enge", 47.3640, 8.5290, 60, 900),
    ("03 Wiedikon", 47.3710, 8.5150, 60, 900),
    ("04 Aussersihl", 47.3780, 8.5230, 150, 600),
    ("05 Industrie", 47.3890, 8.5180, 300, 2500),
    ("06 Unterstrass", 47.3900, 8.5400, 100, 400),
    ("07 Hottingen", 47.3690, 8.5670, 100, 400),
    ("08 Seefeld", 47.3560, 8.5510, 100, 400),
    ("09 Altstetten", 47.3910, 8.4880, 60, 1500),
    ("11 Oerlikon", 47.4100, 8.5450, 200, 900),
]


async def pick(client, lat, lon, low, high):
    x, y = ms.TO_SWISS.transform(lon, lat)
    r = await client.get(
        MAP + "/identify",
        params={
            "geometry": f"{x - 250},{y - 250},{x + 250},{y + 250}",
            "geometryType": "esriGeometryEnvelope",
            "layers": "all:" + ms.ROOF_LAYER, "sr": 2056,
            "geometryFormat": "geojson", "returnGeometry": "true", "tolerance": 0,
            "mapExtent": f"{x - 300},{y - 300},{x + 300},{y + 300}",
            "imageDisplay": "1000,1000,96", "limit": 50,
        },
    )
    best = None
    for f in r.json().get("results", []):
        if not f.get("geometry"):
            continue
        g = shape(f["geometry"])
        if g.geom_type == "MultiPolygon":
            g = max(g.geoms, key=lambda q: q.area)
        if low <= g.area <= high and (best is None or g.area > best.area):
            best = g
    if best is None:
        return None
    p = best.representative_point()
    return ms.TO_WGS84.transform(p.x, p.y)[::-1]


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    async with httpx.AsyncClient(timeout=900) as client:
        for name, lat, lon, low, high in SPOTS:
            found = await pick(client, lat, lon, low, high)
            if not found:
                rows.append({"name": name, "error": "no roof in band"})
                continue
            rlat, rlon = found
            cap = await client.post(BASE + "/api/map/prepare",
                                    json={"latitude": rlat, "longitude": rlon})
            if cap.status_code != 200:
                rows.append({"name": name, "error": f"prepare {cap.status_code}"})
                continue
            cap = cap.json()
            settings = {
                "roof": cap["roof"], "objects": cap["objects"], "mode": "recommended",
                "panel": PANEL, "pixels_per_metre": cap["pixels_per_metre"],
                "approximate_roof_width": 12, "scale_verified": True,
                "angle": cap["angle"], "use_ai": True, "edge_margin": 0.3,
                "obstacle_margin": 0.4, "pv_margin": 0.2,
                "capture_id": cap["capture_id"],
            }
            image_bytes = base64.b64decode(cap["image_base64"])
            res = await client.post(BASE + "/api/analyse",
                                    files={"image": ("r.jpg", image_bytes, "image/jpeg")},
                                    data={"settings": json.dumps(settings)})
            if res.status_code != 200:
                rows.append({"name": name, "error": f"analyse {res.status_code} {res.text[:120]}"})
                continue
            d = res.json()
            im = np.asarray(Image.open(BytesIO(image_bytes)).convert("RGB"))
            vis = im.copy()
            for q in d["proposed_panels"]:
                cv2.polylines(vis, [np.array(q, np.int32)], True, (90, 255, 90), 1)
            for o in d["obstacles"]:
                colour = (255, 40, 40) if o.get("source") == "terrain" else (255, 150, 0)
                cv2.polylines(vis, [np.array(o["polygon"], np.int32)], True, colour, 2)
            for o in d["existing_pv"]:
                cv2.polylines(vis, [np.array(o["polygon"], np.int32)], True, (0, 130, 255), 2)
            cv2.polylines(vis, [np.array(cap["roof"], np.int32)], True, (255, 255, 255), 1)
            Image.fromarray(vis).save(OUT / f"{name.split()[0]}.png")
            s, sd = d["statistics"], d.get("sonnendach") or {}
            rows.append({
                "name": name, "lat": round(rlat, 6), "lon": round(rlon, 6),
                "faces": len(d.get("faces") or []),
                "surface_m2": s.get("surface_area_m2"),
                "panels": s["additional_panel_count"], "kwp": s.get("additional_kwp"),
                "energy": s.get("annual_energy_kwh"),
                "pv": len(d["existing_pv"]), "obstacles": len(d["obstacles"]),
                "terrain": sum(1 for o in d["obstacles"] if o.get("source") == "terrain"),
                "windows": sum(1 for o in d["obstacles"] if o.get("source") == "image"),
                "official_m2": sd.get("official_area_m2"),
                "official_kwh": sd.get("official_annual_energy_kwh"),
                "screened_m2": (sd.get("breakdown_m2") or {}).get("faces_screened_out"),
                "shortfall_pct": sd.get("energy_shortfall_percent"),
            })
    (OUT / "survey.json").write_text(json.dumps(rows, indent=1))
    head = f"{'district':<16}{'m2':>8}{'faces':>6}{'pan':>5}{'kWp':>7}{'PV':>4}{'obs':>5}{'win':>5}{'gnd':>5}{'screened':>10}{'short%':>8}"
    print(head)
    print("-" * len(head))
    for r in rows:
        if "error" in r:
            print(f"{r['name']:<16}  ERROR: {r['error']}")
            continue
        print(f"{r['name']:<16}{r['surface_m2'] or 0:>8.0f}{r['faces']:>6}{r['panels']:>5}"
              f"{r['kwp'] or 0:>7.1f}{r['pv']:>4}{r['obstacles']:>5}{r['windows']:>5}"
              f"{r['terrain']:>5}{r['screened_m2'] or 0:>10.0f}{r['shortfall_pct'] or 0:>8.1f}")


asyncio.run(main())
