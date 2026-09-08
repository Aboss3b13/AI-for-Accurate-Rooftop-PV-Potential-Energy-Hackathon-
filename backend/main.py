import io
import json
import time
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from backend.schemas.analysis import AnalysisSettings
from backend.services.geometry_service import polygon_from_points, build_usable, geojson
from backend.services.panel_optimizer import optimise_panels
from backend.services.yolo_service import yolo
from backend.services.energy_service import capacity
from backend.services.confidence_service import summarise_confidence

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
app = FastAPI(title="SolarFit", version="1.0.0")
Image.MAX_IMAGE_PIXELS = 25_000_000


@app.get("/api/health")
def health():
    return {"app": "SolarFit", "status": "ok", "model": yolo.status()}


def analyse(image, settings):
    start = time.perf_counter()
    roof = polygon_from_points(settings.roof, strict=True)
    w, h = image.size
    for points in [settings.roof] + [o.polygon for o in settings.objects]:
        polygon_from_points(points, strict=True)
        if any(x < 0 or y < 0 or x > w or y > h for x, y in points):
            raise ValueError("Polygon coordinates must be inside the uploaded image.")
    ppm = settings.pixels_per_metre or (
        (roof.bounds[2] - roof.bounds[0]) / settings.approximate_roof_width
    )
    if settings.use_ai:
        detected, warnings, model = yolo.detect(image)
    else:
        detected, warnings, model = (
            [],
            ["AI disabled: using manually marked objects only."],
            yolo.status(),
        )
    objects = [
        dict(x)
        for x in detected
        if polygon_from_points(x["polygon"]).intersection(roof).area > 1
    ]
    objects += [
        dict(polygon=o.polygon, kind=o.kind, confidence=None, source="manual")
        for o in settings.objects
    ]
    usable, excluded = build_usable(roof, objects, ppm, settings)
    panels, orientation = optimise_panels(usable, ppm, settings.panel, settings.angle)
    confidence = summarise_confidence(objects)
    if not settings.scale_verified or settings.pixels_per_metre is None:
        warnings.append(
            "Approximate scale: calibrate a known distance before interpreting physical area or capacity."
        )
    if confidence["uncertain_objects"]:
        warnings.append(
            f"{confidence['uncertain_objects']} uncertain objects; estimated panel count may vary."
        )
    warnings.append(
        "2D planning estimate: roof pitch, shading, structure, access and electrical design require on-site assessment."
    )
    return {
        "roof": geojson(roof),
        "existing_pv": [x for x in objects if x["kind"] == "existing_pv"],
        "obstacles": [x for x in objects if x["kind"] != "existing_pv"],
        "usable_area": geojson(usable),
        "excluded_area": geojson(excluded),
        "proposed_panels": panels,
        "model": model,
        "warnings": warnings,
        "confidence": confidence,
        "mode": settings.mode,
        "statistics": {
            "existing_pv_regions": sum(x["kind"] == "existing_pv" for x in objects),
            "additional_panel_count": len(panels),
            **capacity(
                len(panels), settings.panel.power, settings.annual_specific_yield
            ),
            "roof_area_m2": round(roof.area / ppm**2, 2),
            "usable_area_m2": round(usable.area / ppm**2, 2),
            "roof_utilisation": round(
                len(panels)
                * settings.panel.width
                * settings.panel.height
                / (roof.area / ppm**2)
                * 100,
                1,
            ),
            "pixels_per_metre": round(ppm, 4),
            "approximate": not (settings.scale_verified and settings.pixels_per_metre),
            "orientation": orientation,
            "elapsed_ms": round((time.perf_counter() - start) * 1000),
        },
    }


@app.post("/api/analyse")
async def analyse_roof(image: UploadFile = File(...), settings: str = Form(...)):
    try:
        config = AnalysisSettings.model_validate_json(settings)
        content = await image.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024:
            raise HTTPException(413, "Image exceeds 20 MB.")
        source = Image.open(io.BytesIO(content))
        if source.format not in {"PNG", "JPEG", "WEBP"}:
            raise ValueError("Use a PNG, JPG or WebP image.")
        if source.width * source.height > 25_000_000:
            raise ValueError("Image exceeds 25 megapixels. Crop to the roof first.")
        source = ImageOps.exif_transpose(source).convert("RGB")
        return await run_in_threadpool(analyse, source, config)
    except HTTPException:
        raise
    except (
        ValueError,
        ValidationError,
        UnidentifiedImageError,
        Image.DecompressionBombError,
    ) as exc:
        raise HTTPException(422, str(exc)) from exc


dist = ROOT / "frontend" / "dist"
if dist.exists():
    app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
