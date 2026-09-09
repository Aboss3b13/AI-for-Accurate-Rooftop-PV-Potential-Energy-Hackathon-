import httpx
from fastapi import APIRouter, HTTPException, Query
from backend.schemas.map import MapSelection
from backend.services.map_service import (
    MapServiceError,
    prepare_capture,
    search_locations,
)

router = APIRouter(prefix="/api/map", tags=["Swiss satellite map"])


@router.get("/shadow/{capture_id}")
def shadow(capture_id: str, month: int = Query(default=6, ge=1, le=12),
           hour_utc: float = Query(default=12, ge=0, le=23.5)):
    """Illustrative shadows on the original surveyed faces; no energy adjustment."""
    from datetime import date
    import numpy as np
    from shapely import make_valid
    from shapely.geometry import mapping
    from shapely.ops import transform, unary_union
    from backend.services.runtime_cache import captures
    from backend.services.surface_analysis import GeoReference
    from backend.services.sunlight_service import solar_position, instantaneous_shadow
    context = captures.get(capture_id)
    if context is None:
        raise HTTPException(410, "Map capture expired. Select the building again.")
    if "latitude" not in context:
        raise HTTPException(422, "Recapture this roof to enable the sun preview.")
    ray = solar_position(context["latitude"], context["longitude"],
                         date(2025, month, 21).timetuple().tm_yday, np.array([hour_utc]))[0]
    shade, unknown = [], []
    for face in context["faces"]:
        plane = face["plane"]
        a, b = instantaneous_shadow(face.get("sunlight", {}),
            plane.local_geometry(face["geometry"]), plane.normal, ray)
        shade.append(make_valid(plane.world_geometry(a)))
        unknown.append(make_valid(plane.world_geometry(b)))
    geo = GeoReference(context["grid"])
    return {"shade": mapping(transform(geo.pixel, unary_union(shade))),
            "unknown": mapping(transform(geo.pixel, unary_union(unknown))),
            "sun_elevation_deg": round(float(np.degrees(np.arcsin(ray[2]))), 1),
            "month": month, "hour_utc": hour_utc,
            "note": "Representative 21st day; original roof geometry and static DSM. Annual energy is unchanged."}


@router.get("/search")
async def search(q: str = Query(min_length=2, max_length=160)):
    if len(q.split()) > 10:
        raise HTTPException(
            422, "Search for one address or place using at most 10 words."
        )
    try:
        return {"results": await search_locations(q)}
    except (httpx.HTTPError, ValueError, MapServiceError) as exc:
        raise HTTPException(
            503,
            "Address search is unavailable. You can still navigate the map manually.",
        ) from exc


@router.post("/prepare")
async def prepare(selection: MapSelection):
    try:
        return await prepare_capture(selection)
    except MapServiceError as exc:
        raise HTTPException(422, str(exc)) from exc
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise HTTPException(
            503,
            "Swiss map data is unavailable right now. Retry, capture a manual area, or use image upload.",
        ) from exc
