import httpx
from fastapi import APIRouter, HTTPException, Query
from backend.schemas.map import MapSelection
from backend.services.map_service import (
    MapServiceError,
    prepare_capture,
    search_locations,
)

router = APIRouter(prefix="/api/map", tags=["Swiss satellite map"])


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
