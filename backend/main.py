from backend.services.planning_service import planning_constraints
import io
import json
import time
import logging
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from backend.runtime_version import source_revision
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool
from backend.schemas.analysis import AnalysisSettings
from backend.services.geometry_service import polygon_from_points, build_usable, geojson
from backend.services.panel_optimizer import optimise_panels
from backend.services.yolo_service import yolo, obstacle_yolo
from backend.services.energy_service import capacity
from backend.services.confidence_service import summarise_confidence
from backend.map_routes import router as map_router
from backend.services.surface_analysis import analyse_surfaces

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
app = FastAPI(title="SolarFit", version="1.2.0")
app.include_router(map_router)
LOADED_REVISION = source_revision()
Image.MAX_IMAGE_PIXELS = 25_000_000


@app.exception_handler(Exception)
async def unexpected_error(request, exc):
    logging.getLogger("uvicorn.error").error("Unhandled request failure: %s %s", request.method, request.url.path,
                                           exc_info=(type(exc), exc, exc.__traceback__))
    return JSONResponse(status_code=500, content={"detail":
        "SolarFit could not process this roof. Retry or select the roof again. The server log contains the diagnostic details."})


@app.get("/api/health")
def health():
    return {"app": "SolarFit", "version": "1.2.0", "backend_revision": LOADED_REVISION,
            "restart_required": LOADED_REVISION != source_revision(), "capabilities": ["shadow_preview"],
            "geometry": "official_roof_surfaces_with_sunlight_screening", "status": "ok", "model": yolo.status(),
            "obstacle_model": obstacle_yolo.status()}


def analyse(image, settings):
    start = time.perf_counter()
    roof = polygon_from_points(settings.roof, strict=True)
    w, h = image.size
    for points in [settings.roof] + [o.polygon for o in settings.objects] + list(settings.face_overrides.values()) + ([settings.building_override] if settings.building_override else []):
        polygon_from_points(points, strict=True)
        if any(x < 0 or y < 0 or x > w or y > h for x, y in points):
            raise ValueError("Polygon coordinates must be inside the uploaded image.")
    ppm = settings.pixels_per_metre or (
        (roof.bounds[2] - roof.bounds[0]) / settings.approximate_roof_width
    )
    if settings.use_ai:
        detected, warnings, model = yolo.detect(image)
        warnings = list(warnings)
        if obstacle_yolo.status()["available"]:
            obstacles, obstacle_warnings, obstacle_model = obstacle_yolo.detect(image)
            detected = [*detected, *obstacles]
            warnings.extend(obstacle_warnings)
            model = {**model, "obstacle_model": obstacle_model}
    else:
        detected, warnings, model = (
            [],
            ["AI disabled: using manually marked objects only."],
            yolo.status(),
        )
    objects = [
        dict(x)
        for x in detected
        if settings.capture_id or polygon_from_points(x["polygon"]).intersection(roof).area > 1
    ]
    objects += [
        dict(polygon=o.polygon, kind=o.kind, confidence=None, source=o.source, height_m=o.height_m)
        for o in settings.objects
    ]
    if settings.capture_id:
        return analyse_surfaces(image, settings, objects, warnings, model, start)
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
        "planning_constraints": planning_constraints(settings),
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
