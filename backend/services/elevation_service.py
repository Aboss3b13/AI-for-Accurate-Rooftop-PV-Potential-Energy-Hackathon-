"""Roof superstructure detection from the swisstopo swissSURFACE3D height model.

The shipped YOLO checkpoint is trained on Swiss masks that label PV only, so it
cannot find chimneys. The national 0.5 m surface model can: it measures the roof
surface itself, and anything standing proud of a roof face is a superstructure.
Each Sonnendach facet gets its own least-squares plane, so a pitched roof is
measured against its own slope instead of a single average height.

Flush features - roof windows set into the pitch, flat vents - do not rise above
the surface and are invisible here. They still need marking by hand.
"""

import asyncio
from pathlib import Path

import cv2
import httpx
import numpy as np
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon

STAC = "https://data.geo.admin.ch/api/stac/v0.9/collections"
COLLECTION = "ch.swisstopo.swisssurface3d-raster"
TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "dsm"
DSM_STEP_M = 0.5

# A superstructure must clear the roof face by this much to count. Flat-roof
# rooflight kerbs sit around 0.3 m, so the floor is set just under that.
MIN_HEIGHT_M = 0.28
# The plane is fitted to this share of the height spread: the roof deck.
BASE_PERCENTILE = 50.0
# ...and the cut-off rises with the roughness of that deck.
NOISE_SIGMAS = 4.0
# ...and be at least this large, so single noisy cells are ignored.
MIN_AREA_M2 = 0.35
MAX_AREA_FRACTION = 0.5
MAX_OBSTACLES = 40
# A chimney or vent is small and tall; anything broader reads as a dormer.
CHIMNEY_MAX_AREA_M2 = 2.5
PAD_M = 2.0
MAX_TILES = 4
# Each tile is ~13 MB and covers a square kilometre; keep the cache bounded.
CACHE_LIMIT_BYTES = 2_000_000_000

Image.MAX_IMAGE_PIXELS = 80_000_000


class ElevationUnavailable(Exception):
    """The height model could not be read; the caller carries on without it."""


async def tile_hrefs(client: httpx.AsyncClient, bounds) -> list[str]:
    minx, miny, maxx, maxy = bounds
    west, south = TO_WGS84.transform(minx, miny)
    east, north = TO_WGS84.transform(maxx, maxy)
    response = await client.get(
        f"{STAC}/{COLLECTION}/items",
        params={"bbox": f"{west},{south},{east},{north}"},
    )
    response.raise_for_status()
    hrefs = []
    for feature in response.json().get("features", []):
        for asset in feature.get("assets", {}).values():
            href = asset.get("href", "")
            if asset.get("type", "").startswith("image/tiff") and href.endswith(".tif"):
                hrefs.append(href)
    return hrefs


def prune_cache() -> None:
    """Drop the least recently used tiles once the cache outgrows its budget."""
    tiles = sorted(CACHE.glob("*.tif"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in tiles)
    while tiles and total > CACHE_LIMIT_BYTES:
        oldest = tiles.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)


async def cached_tile(client: httpx.AsyncClient, href: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / href.rsplit("/", 1)[-1]
    if path.exists() and path.stat().st_size > 0:
        path.touch()
        return path
    response = await client.get(href, follow_redirects=True, timeout=180)
    response.raise_for_status()
    temporary = path.with_suffix(".part")
    temporary.write_bytes(response.content)
    temporary.replace(path)
    prune_cache()
    return path


def tile_origin(path: Path) -> tuple[float, float]:
    """swisstopo names each tile by its lower-left LV95 kilometre."""
    for part in path.stem.split("_"):
        east, _, north = part.partition("-")
        if east.isdigit() and north.isdigit() and len(east) == 4:
            return float(east) * 1000, float(north) * 1000
    raise ElevationUnavailable("Cannot place height tile " + path.name)


def mosaic(paths: list[Path], bounds) -> tuple[np.ndarray, float, float]:
    """Cut the requested window out of one or more tiles, in LV95 metres."""
    minx, miny, maxx, maxy = bounds
    width = int(round((maxx - minx) / DSM_STEP_M))
    height = int(round((maxy - miny) / DSM_STEP_M))
    if width < 4 or height < 4:
        raise ElevationUnavailable("Roof is too small for the 0.5 m height model")
    out = np.full((height, width), np.nan, dtype=np.float32)
    for path in paths:
        try:
            with Image.open(path) as image:
                tile = np.asarray(image, dtype=np.float32)
        except (OSError, ValueError) as exc:
            raise ElevationUnavailable("Height tile could not be read") from exc
        ox, oy = tile_origin(path)
        rows, cols = tile.shape[:2]
        top = oy + rows * DSM_STEP_M
        # Overlap of this tile with the requested window, in output cells.
        col0 = max(0, int(round((ox - minx) / DSM_STEP_M)))
        row0 = max(0, int(round((maxy - top) / DSM_STEP_M)))
        src_col0 = max(0, int(round((minx - ox) / DSM_STEP_M)))
        src_row0 = max(0, int(round((top - maxy) / DSM_STEP_M)))
        take_w = min(width - col0, cols - src_col0)
        take_h = min(height - row0, rows - src_row0)
        if take_w <= 0 or take_h <= 0:
            continue
        patch = tile[src_row0 : src_row0 + take_h, src_col0 : src_col0 + take_w]
        target = out[row0 : row0 + take_h, col0 : col0 + take_w]
        np.copyto(target, patch, where=np.isnan(target))
    if bool(np.isnan(out).all()):
        raise ElevationUnavailable("No height data covers this roof")
    return out, minx, maxy


def facet_mask(polygon, shape, minx: float, maxy: float) -> np.ndarray:
    mask = np.zeros(shape, dtype=np.uint8)
    if polygon.geom_type == "MultiPolygon":
        for part in polygon.geoms:
            mask |= facet_mask(part, shape, minx, maxy).astype(np.uint8)
        return mask.astype(bool)
    if polygon.geom_type != "Polygon" or polygon.is_empty:
        return mask.astype(bool)
    rings = [polygon.exterior] + list(polygon.interiors)
    for index, ring in enumerate(rings):
        points = np.array(
            [
                [(x - minx) / DSM_STEP_M, (maxy - y) / DSM_STEP_M]
                for x, y in ring.coords
            ],
            dtype=np.int32,
        )
        cv2.fillPoly(mask, [points], 0 if index else 1)
    return mask.astype(bool)


def plane_residual(heights: np.ndarray, mask: np.ndarray) -> np.ndarray | None:
    """Fit the roof face to its own slope, then measure what stands above it.

    Superstructures only ever push the surface up, so the fit is anchored to the
    lower part of the height spread. A symmetric fit is dragged upward by a big
    rooftop plant room until nothing stands out from it any more - on one flat
    industrial roof that left a 1.13 m spread and 40% of cells "raised".
    """
    valid = mask & np.isfinite(heights)
    if int(valid.sum()) < 12:
        return None
    rows, cols = np.nonzero(valid)
    z = heights[valid].astype(np.float64)
    design = np.column_stack(
        [cols.astype(np.float64), rows.astype(np.float64), np.ones(z.size)]
    )
    keep = np.ones(z.size, dtype=bool)
    residual = np.zeros(z.size)
    for _ in range(6):
        if int(keep.sum()) < 8:
            return None
        solution, *_ = np.linalg.lstsq(design[keep], z[keep], rcond=None)
        residual = z - design @ solution
        # Keep the lower part of the spread, so the plane settles on the roof
        # deck rather than splitting the difference with whatever sits on it.
        cut = float(np.percentile(residual, BASE_PERCENTILE))
        keep = residual <= max(cut, 0.05)
    out = np.full(heights.shape, np.nan, dtype=np.float32)
    out[valid] = residual.astype(np.float32)
    return out


def rise_threshold(residual: np.ndarray, mask: np.ndarray) -> float:
    """How far above the fitted face a cell must sit before it counts.

    Never below MIN_HEIGHT_M, and lifted on a rough or poorly fitted face so
    that noise does not become a rooftop full of imaginary chimneys.
    """
    base = residual[mask & np.isfinite(residual)]
    if base.size == 0:
        return MIN_HEIGHT_M
    deck = base[base <= np.percentile(base, BASE_PERCENTILE)]
    if deck.size < 8:
        return MIN_HEIGHT_M
    spread = float(np.median(np.abs(deck - np.median(deck))))
    return max(MIN_HEIGHT_M, NOISE_SIGMAS * 1.4826 * spread)


def detect(
    heights: np.ndarray, minx: float, maxy: float, facets: list[Polygon]
) -> list[dict]:
    """Return superstructure polygons in LV95 metres, with height and class."""
    raised = np.zeros(heights.shape, dtype=np.uint8)
    depth = np.zeros(heights.shape, dtype=np.float32)
    kernel = np.ones((3, 3), np.uint8)
    for facet in facets:
        mask = facet_mask(facet, heights.shape, minx, maxy)
        if not mask.any():
            continue
        residual = plane_residual(heights, mask)
        if residual is None:
            continue
        # A cell on a ridge straddles two faces, so it stands proud of both and
        # would be flagged on either. Fit on the whole face, judge only its core,
        # or every ridge line reads as a structure and welds them into one blob.
        core = cv2.erode(mask.astype(np.uint8), kernel).astype(bool)
        threshold = rise_threshold(residual, mask)
        hit = core & np.isfinite(residual) & (residual > threshold)
        raised[hit] = 1
        depth[hit] = np.maximum(depth[hit], residual[hit])
    if not raised.any():
        return []
    # Close pinholes inside a chimney. Deliberately no opening: a 3x3 erosion
    # deletes a 1 m chimney outright, and the area filter below removes speckle.
    raised = cv2.morphologyEx(raised, cv2.MORPH_CLOSE, kernel)
    roof_area = sum(f.area for f in facets) or 1.0
    contours, _ = cv2.findContours(raised, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    found = []
    for contour in contours:
        # Scale simplification to the structure: a fixed epsilon flattens a
        # 1 m chimney's four-cell contour into a line and loses it entirely.
        epsilon = min(0.8, 0.05 * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(approx) < 3:
            x, y, w, h = cv2.boundingRect(contour)
            approx = np.array(
                [[x, y], [x + w - 1, y], [x + w - 1, y + h - 1], [x, y + h - 1]]
            )
        patch = np.zeros(raised.shape, np.uint8)
        cv2.drawContours(patch, [contour], -1, 1, -1)
        rises = depth[patch.astype(bool)]
        rise = float(rises.max()) if rises.size else 0.0
        ring = [
            (minx + (c + 0.5) * DSM_STEP_M, maxy - (r + 0.5) * DSM_STEP_M)
            for c, r in approx
        ]
        polygon = Polygon(ring)
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        # The contour traces cell centres, so it stops half a cell short of the
        # structure on every side. Grow it back, which also errs on the safe side.
        polygon = polygon.buffer(DSM_STEP_M / 2, join_style=2)
        if polygon.geom_type != "Polygon" or not polygon.is_valid:
            continue
        area = polygon.area
        if area < MIN_AREA_M2 or area > roof_area * MAX_AREA_FRACTION:
            continue
        found.append(
            {
                "geometry": polygon,
                "height_m": round(rise, 2),
                "area_m2": round(area, 2),
                "kind": "chimney" if area <= CHIMNEY_MAX_AREA_M2 else "other_obstacle",
            }
        )
    found.sort(key=lambda o: -o["area_m2"])
    return found[:MAX_OBSTACLES]


async def roof_obstacles(
    client: httpx.AsyncClient, facets: list[Polygon], bounds
) -> list[dict]:
    """Fetch the height model over this roof and return its superstructures."""
    if not facets:
        return []
    minx, miny, maxx, maxy = bounds
    window = (minx - PAD_M, miny - PAD_M, maxx + PAD_M, maxy + PAD_M)
    try:
        hrefs = await tile_hrefs(client, window)
        if not hrefs:
            raise ElevationUnavailable("No height model published for this location")
        paths = [await cached_tile(client, href) for href in hrefs[:MAX_TILES]]
        heights, ox, oy = await asyncio.to_thread(mosaic, paths, window)
        return await asyncio.to_thread(detect, heights, ox, oy, facets)
    except (httpx.HTTPError, ValueError, OSError) as exc:
        raise ElevationUnavailable("The height model could not be reached") from exc
