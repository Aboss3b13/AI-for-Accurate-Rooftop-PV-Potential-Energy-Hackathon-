"""Run the whole pipeline over one real building in each of ten cantons.

Sampled from the Sonnendach layer near each town so the buildings are real
housing stock, and rendered so the layout can be checked by eye rather than
from summary numbers alone.
"""
import asyncio
import base64
import json
import sys
import time
from io import BytesIO
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image
from shapely.geometry import Polygon, shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.services import map_service as ms

BASE = "http://127.0.0.1:8000"
MAP = "https://api3.geo.admin.ch/rest/services/all/MapServer"
PANEL = {"width": 1.762, "height": 1.134, "power": 450, "gap": 0.02}
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("cantons")

PLACES = [
    ("ZH Zurich", 47.3769, 8.5417), ("BE Bern", 46.9480, 7.4474),
    ("VD Lausanne", 46.5197, 6.6323), ("TI Lugano", 46.0037, 8.9511),
    ("GR Chur", 46.8508, 9.5320), ("AG Aarau", 47.3910, 8.0455),
    ("SG StGallen", 47.4245, 9.3767), ("LU Luzern", 47.0502, 8.3093),
    ("VS Sion", 46.2331, 7.3606), ("NE Neuchatel", 46.9925, 6.9310),
]


async def sample(client, lat, lon, low=70, high=400):
    x, y = ms.TO_SWISS.transform(lon, lat)
    r = await client.get(MAP + "/identify", params={
        "geometry": f"{x-300},{y-300},{x+300},{y+300}",
        "geometryType": "esriGeometryEnvelope", "layers": "all:" + ms.ROOF_LAYER,
        "sr": 2056, "geometryFormat": "geojson", "returnGeometry": "true",
        "tolerance": 0, "mapExtent": f"{x-400},{y-400},{x+400},{y+400}",
        "imageDisplay": "1000,1000,96", "limit": 60, "lang": "en"})
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
    rows, problems = [], []
    header = (f"{'canton':<14}{'src':<5}{'faces':>6}{'panels':>7}{'kWp':>7}"
              f"{'kWh/yr':>9}{'roof m2':>9}{'win':>5}{'obs':>5}{'s':>6}")
    print(header)
    print("-" * len(header))
    async with httpx.AsyncClient(timeout=900) as client:
        for name, lat, lon in PLACES:
            found = await sample(client, lat, lon)
            if not found:
                problems.append(f"{name}: no roof sampled")
                continue
            rlat, rlon = found
            start = time.time()
            cap = await client.post(BASE + "/api/map/prepare",
                                    json={"latitude": rlat, "longitude": rlon})
            if cap.status_code != 200:
                problems.append(f"{name}: prepare {cap.status_code}")
                continue
            cap = cap.json()
            if len(cap.get("roof") or []) < 3:
                problems.append(f"{name}: no roof outline")
                continue
            image = base64.b64decode(cap["image_base64"])
            settings = {"roof": cap["roof"], "objects": cap["objects"],
                        "mode": "recommended", "panel": PANEL,
                        "pixels_per_metre": cap["pixels_per_metre"],
                        "approximate_roof_width": 12, "scale_verified": True,
                        "angle": cap["angle"], "use_ai": True, "edge_margin": .3,
                        "obstacle_margin": .4, "pv_margin": .2,
                        "capture_id": cap["capture_id"]}
            res = await client.post(BASE + "/api/analyse",
                                    files={"image": ("r.jpg", image, "image/jpeg")},
                                    data={"settings": json.dumps(settings)})
            elapsed = time.time() - start
            if res.status_code != 200:
                problems.append(f"{name}: analyse {res.status_code} {res.text[:90]}")
                continue
            d = res.json()
            s = d["statistics"]
            ppm = cap["pixels_per_metre"]
            source = "3D" if any("swissBUILDINGS3D" in w for w in cap["warnings"]) else "SD"
            windows = sum(1 for o in d["obstacles"] if o.get("source") == "image")
            outline = Polygon(cap["roof"]).area / ppm ** 2
            print(f"{name:<14}{source:<5}{len(d['faces']):>6}"
                  f"{s['additional_panel_count']:>7}{s.get('additional_kwp') or 0:>7.1f}"
                  f"{s.get('annual_energy_kwh') or 0:>9.0f}{s.get('surface_area_m2') or 0:>9.0f}"
                  f"{windows:>5}{len(d['obstacles']):>5}{elapsed:>6.1f}")
            rows.append({"canton": name, "lat": rlat, "lon": rlon, "source": source,
                         "faces": len(d["faces"]),
                         "panels": s["additional_panel_count"],
                         "kwp": s.get("additional_kwp"),
                         "kwh": s.get("annual_energy_kwh"),
                         "surface_m2": s.get("surface_area_m2"),
                         "outline_m2": round(outline, 1), "windows": windows,
                         "obstacles": len(d["obstacles"]), "seconds": round(elapsed, 1)})
            # Outline and analysed roof must describe the same thing.
            if s.get("surface_area_m2") and outline > s["surface_area_m2"] * 1.6:
                problems.append(f"{name}: outline {outline:.0f} m2 far exceeds "
                                f"analysed {s['surface_area_m2']:.0f} m2")
            for panel in d["proposed_panels"]:
                if not Polygon(cap["roof"]).buffer(1).contains(Polygon(panel).centroid):
                    problems.append(f"{name}: a module sits outside the roof outline")
                    break
            visual = np.asarray(Image.open(BytesIO(image)).convert("RGB")).copy()
            for q in d["proposed_panels"]:
                cv2.polylines(visual, [np.array(q, np.int32)], True, (90, 255, 90), 1)
            for o in d["obstacles"]:
                colour = (0, 200, 255) if o.get("source") == "image" else (255, 140, 0)
                cv2.polylines(visual, [np.array(o["polygon"], np.int32)], True, colour, 2)
            for o in d["existing_pv"]:
                cv2.polylines(visual, [np.array(o["polygon"], np.int32)], True, (0, 90, 255), 2)
            cv2.polylines(visual, [np.array(cap["roof"], np.int32)], True, (255, 255, 255), 2)
            Image.fromarray(visual).save(OUT / f"{name.split()[0]}.png")
    (OUT / "cantons.json").write_text(json.dumps(rows, indent=1))
    print()
    if problems:
        print("PROBLEMS:")
        for p in problems:
            print("  -", p)
    else:
        print(f"No problems across {len(rows)} cantons.")


asyncio.run(main())
