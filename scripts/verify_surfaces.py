"""Live Swiss end-to-end smoke check; needs internet and the installed model.

Run: .venv/Scripts/python.exe -m scripts.verify_surfaces
No browser automation, screenshots or synthetic production results.
"""
import asyncio
import base64
import io
import json
import time
from pathlib import Path
import httpx
from PIL import Image
from shapely.geometry import Polygon, shape
from backend.services.map_service import prepare_capture
from backend.schemas.map import MapSelection
from backend.schemas.analysis import AnalysisSettings
from backend.main import analyse
from scripts.sanity_check import a_building_near, PLACES


async def main():
    reports = []
    async with httpx.AsyncClient(timeout=60) as client:
        for name, lat, lon in [PLACES[0], PLACES[2], PLACES[6]]:
            point = await a_building_near(client, lat, lon)
            if point is None:
                raise RuntimeError(f"No building returned for {name}")
            start = time.perf_counter()
            selection = MapSelection(latitude=point[0], longitude=point[1])
            capture = await prepare_capture(selection)
            capture_seconds = time.perf_counter()-start
            image = Image.open(io.BytesIO(base64.b64decode(capture["image_base64"]))).convert("RGB")
            settings = AnalysisSettings(capture_id=capture["capture_id"], roof=capture["roof"],
                objects=capture["objects"], pixels_per_metre=capture["pixels_per_metre"],
                scale_verified=True, angle=capture["angle"])
            result = analyse(image, settings)
            for face in result["faces"]:
                usable = shape(face["local_usable"])
                for ring in face["local_panels"]:
                    assert usable.buffer(1e-7).covers(Polygon(ring)), face["id"]
                if face["geometry_source"] != "projected_2d":
                    assert abs(face["surface_area_m2"] - face["projected_area_m2"] * face["diagnostics"]["surface_area_factor"]) < .1
            assert sum(f["additional_panel_count"] for f in result["faces"]) == len(result["proposed_panels"])
            start = time.perf_counter()
            repeat = await prepare_capture(selection)
            assert repeat["capture_id"] == capture["capture_id"]
            repeat_result = analyse(image, settings)
            assert repeat_result["proposed_panels"] == result["proposed_panels"]
            report = {"place": name, "latitude": point[0], "longitude": point[1],
                "capture_seconds": round(capture_seconds, 3), "warm_total_seconds": round(time.perf_counter()-start, 3),
                "model": result["model"], "statistics": result["statistics"],
                "faces": [{k: f[k] for k in ["id", "pitch_deg", "official_pitch_deg", "geometry_source", "surface_area_m2", "additional_panel_count", "solar", "diagnostics"]} for f in result["faces"]]}
            reports.append(report)
            print(json.dumps({k: v for k, v in report.items() if k != "faces"}), flush=True)
    Path(".cache").mkdir(exist_ok=True)
    Path(".cache/surface-verification.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")


if __name__ == "__main__":
    asyncio.run(main())
