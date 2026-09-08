"""Swiss roof lookup and metric aerial capture. No screenshot/zoom scale guessing."""

import base64
import html
import io
import math
import re
from datetime import datetime, timezone

import httpx
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union

from backend.schemas.map import MapSelection

API = "https://api3.geo.admin.ch/rest/services/ech"
ROOF_LAYER = "ch.bfe.solarenergie-eignung-daecher"
IMAGERY_LAYER = "ch.swisstopo.swissimage"
TO_SWISS = Transformer.from_crs(4326, 2056, always_xy=True)
TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)
MAX_IMAGE_SIZE = 1280
TARGET_PPM = 10.0
CAPTURE_PADDING_M = 8.0
GAP_CLOSE_M = 0.5
MAX_VERTICES = 200
MAX_CANDIDATES = 48
MIN_PLANE_AREA_M2 = 0.25
MIN_CANDIDATE_AREA_M2 = 2.0
MIN_HOLE_AREA_M2 = 0.25
MIN_DRAWN_AREA_M2 = 1.0


class MapServiceError(Exception):
    pass


async def get_json(client: httpx.AsyncClient, path: str, params: dict) -> dict:
    response = await client.get(API + path, params=params)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise MapServiceError("The Swiss map service could not complete this lookup.")
    return data


async def search_locations(query: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=20) as client:
        data = await get_json(
            client,
            "/SearchServer",
            {
                "searchText": query,
                "type": "locations",
                "sr": 4326,
                "limit": 7,
                "lang": "en",
            },
        )
    return [
        {
            "label": html.unescape(re.sub(r"<[^>]+>", "", item["attrs"]["label"])),
            "latitude": item["attrs"]["lat"],
            "longitude": item["attrs"]["lon"],
            "is_address": item["attrs"].get("origin") == "address",
        }
        for item in data.get("results", [])
        if "lat" in item.get("attrs", {})
    ]


def bounded_simplify(polygon: Polygon) -> Polygon | None:
    """Preserve topology while keeping the editable vertex count workable."""
    simplified = polygon.simplify(0.025, preserve_topology=True)
    tolerance = 0.05
    while len(simplified.exterior.coords) > MAX_VERTICES and tolerance <= 1:
        simplified = polygon.simplify(tolerance, preserve_topology=True)
        tolerance *= 2
    return simplified if len(simplified.exterior.coords) <= MAX_VERTICES else None


def drawn_plane(selection: MapSelection) -> dict:
    """Turn an outline drawn on the map into a roof, bypassing the official lookup."""
    ring = [
        TO_SWISS.transform(point.longitude, point.latitude)
        for point in selection.polygon
    ]
    polygon = Polygon(ring)
    if not polygon.is_valid or polygon.area < MIN_DRAWN_AREA_M2:
        raise MapServiceError(
            "Draw a non-crossing outline of at least 1 m². Click each corner, then finish."
        )
    simplified = bounded_simplify(polygon)
    if simplified is None:
        raise MapServiceError("That outline has too many points. Draw a simpler shape.")
    return {
        "id": "drawn",
        "geometry": simplified,
        "properties": {},
        "contains_click": True,
        "distance": 0.0,
    }


def merge_building(planes: list[dict], click: Point) -> dict | None:
    """Union every Sonnendach plane of the clicked building into one roof outline.

    Sonnendach splits a roof into one facet per pitch/azimuth - 58 of them on a
    Zurich block. Analysing only the clicked facet reports a fraction of the roof,
    so the whole building is merged and the facets stay available as candidates.
    """
    if not planes:
        return None
    anchor = planes[0]
    building = anchor["properties"].get("building_id")
    members = (
        [p for p in planes if p["properties"].get("building_id") == building]
        if building is not None
        else [anchor]
    )
    if len(members) == 1:
        return anchor
    geometries = [p["geometry"] for p in members]
    merged = unary_union(geometries)
    if merged.geom_type != "Polygon":
        # Facets that only touch at a corner need a hairline close to join.
        closed = unary_union([g.buffer(GAP_CLOSE_M) for g in geometries]).buffer(
            -GAP_CLOSE_M
        )
        if closed.geom_type == "Polygon" and closed.area >= merged.area * 0.95:
            merged = closed
    if merged.geom_type != "Polygon":
        parts = [g for g in merged.geoms if g.geom_type == "Polygon"]
        covering = [g for g in parts if g.covers(click)]
        merged = max(covering or parts, key=lambda g: g.area)
    simplified = bounded_simplify(merged)
    if simplified is None or simplified.area < anchor["geometry"].area:
        return anchor
    return {
        "id": f"building:{building}",
        "geometry": simplified,
        "properties": {
            **anchor["properties"],
            # Pitch and azimuth belong to a single facet, not to the merged roof.
            "neigung": None,
            "ausrichtung": None,
        },
        "contains_click": True,
        "distance": 0.0,
        "merged_planes": len(members),
    }


def feature_planes(features: list[dict], click: Point) -> list[dict]:
    planes = []
    seen = set()
    for feature in features:
        if not feature.get("geometry"):
            continue
        geometry = shape(feature["geometry"])
        parts = (
            list(geometry.geoms) if geometry.geom_type == "MultiPolygon" else [geometry]
        )
        props = feature.get("properties", feature.get("attributes", {}))
        for index, part in enumerate(parts):
            if (
                part.geom_type != "Polygon"
                or not part.is_valid
                or part.area < MIN_PLANE_AREA_M2
            ):
                continue
            identifier = f"{feature.get('featureId', feature.get('id'))}:{index}"
            if identifier in seen:
                continue
            seen.add(identifier)
            simplified = bounded_simplify(part)
            if simplified is None:
                continue
            planes.append(
                {
                    "id": identifier,
                    "geometry": simplified,
                    "properties": props,
                    "contains_click": part.covers(click),
                    "distance": part.distance(click),
                }
            )
    return sorted(
        planes,
        key=lambda p: (not p["contains_click"], p["distance"], p["geometry"].area),
    )


def public_plane(plane: dict) -> dict:
    props = plane["properties"]
    return {
        "id": plane["id"],
        "geometry": mapping(transform(TO_WGS84.transform, plane["geometry"])),
        "projected_area_m2": round(plane["geometry"].area, 2),
        "pitch_deg": props.get("neigung"),
        "azimuth_deg": props.get("ausrichtung"),
        "plane_number": props.get("df_nummer"),
        "building_id": props.get("building_id"),
        "contains_click": plane["contains_click"],
    }


def capture_grid(geometry: Polygon | None, center: Point, span_m=64) -> dict:
    if geometry is not None:
        minx, miny, maxx, maxy = geometry.bounds
        width = maxx - minx + CAPTURE_PADDING_M * 2
        height = maxy - miny + CAPTURE_PADDING_M * 2
        cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    else:
        width = height = span_m
        cx, cy = center.x, center.y
    if max(width, height) > 1000:
        raise MapServiceError(
            "This roof is too large for one capture. Select a smaller roof plane."
        )
    ppm = min(TARGET_PPM, MAX_IMAGE_SIZE / max(width, height))
    pixel_width = max(256, math.ceil(width * ppm))
    pixel_height = max(256, math.ceil(height * ppm))
    half_w, half_h = pixel_width / ppm / 2, pixel_height / ppm / 2
    return {
        "bbox": [cx - half_w, cy - half_h, cx + half_w, cy + half_h],
        "width": pixel_width,
        "height": pixel_height,
        "pixels_per_metre": ppm,
    }


def pixel_ring(coords, grid: dict) -> list[list[float]]:
    minx, _, _, maxy = grid["bbox"]
    ppm = grid["pixels_per_metre"]
    points = [
        [round((x - minx) * ppm, 4), round((maxy - y) * ppm, 4)] for x, y, *_ in coords
    ]
    return points[:-1] if points[0] == points[-1] else points


def alignment(geometry: Polygon) -> float:
    coords = list(geometry.minimum_rotated_rectangle.exterior.coords)
    start, end = max(
        zip(coords, coords[1:]),
        key=lambda pair: Point(pair[0]).distance(Point(pair[1])),
    )
    angle = math.degrees(math.atan2(-(end[1] - start[1]), end[0] - start[0]))
    return round((angle + 90) % 180 - 90, 2)


async def prepare_capture(selection: MapSelection) -> dict:
    x, y = TO_SWISS.transform(selection.longitude, selection.latitude)
    click = Point(x, y)
    warnings = []
    planes = []
    whole = None
    selected = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(35, connect=10)) as client:
        if selection.polygon is not None:
            selected = drawn_plane(selection)
            warnings.append(
                "Using the outline you drew. Scale comes from the map, so area and capacity stay metric."
            )
        elif not selection.capture_only:
            data = await get_json(
                client,
                "/MapServer/identify",
                {
                    "geometry": f"{x},{y}",
                    "geometryType": "esriGeometryPoint",
                    "layers": "all:" + ROOF_LAYER,
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
            found = feature_planes(features, click)
            if found:
                building = found[0]["properties"].get("building_id")
                if building is not None:
                    try:
                        siblings = await get_json(
                            client,
                            "/MapServer/find",
                            {
                                "layer": ROOF_LAYER,
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
                    except (httpx.HTTPError, ValueError, MapServiceError):
                        warnings.append(
                            "Other roof planes could not be loaded; the clicked plane is available."
                        )
            planes = feature_planes(features, click)
            whole = merge_building(planes, click)
            if selection.roof_id:
                selected = (
                    whole
                    if whole is not None and whole["id"] == selection.roof_id
                    else next((p for p in planes if p["id"] == selection.roof_id), None)
                )
                if selected is None:
                    raise MapServiceError(
                        "That roof plane is no longer available. Click the building again."
                    )
            else:
                selected = whole
            if selected is not None and selected.get("merged_planes", 1) > 1:
                warnings.append(
                    f"Merged {selected['merged_planes']} Sonnendach roof planes into one outline. "
                    "Click a single plane on the map to analyse just that facet."
                )
        if selected is None:
            warnings.append(
                "No automatic roof boundary selected. Scale is calibrated; draw the roof in the editor."
            )
        geometry = selected["geometry"] if selected else None
        grid = capture_grid(geometry, click, selection.span_m)
        response = await client.get(
            "https://wms.geo.admin.ch/",
            params={
                "SERVICE": "WMS",
                "REQUEST": "GetMap",
                "VERSION": "1.3.0",
                "LAYERS": IMAGERY_LAYER,
                "STYLES": "",
                "CRS": "EPSG:2056",
                "BBOX": ",".join(map(str, grid["bbox"])),
                "WIDTH": grid["width"],
                "HEIGHT": grid["height"],
                "FORMAT": "image/jpeg",
            },
        )
        response.raise_for_status()
        if not response.headers.get("content-type", "").startswith("image/"):
            raise MapServiceError(
                "The aerial-image service did not return an image. Try again shortly."
            )
        image = Image.open(io.BytesIO(response.content)).convert("RGB")
        if image.size != (grid["width"], grid["height"]):
            raise MapServiceError(
                "The map image size did not match its scale. Please retry."
            )
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG", quality=95)
    props = selected["properties"] if selected else {}
    objects = []
    if geometry is not None:
        for ring in geometry.interiors:
            hole = Polygon(ring).simplify(0.05, preserve_topology=True)
            if hole.geom_type != "Polygon" or hole.area < MIN_HOLE_AREA_M2:
                continue
            polygon = pixel_ring(hole.exterior.coords, grid)
            # Rounding to pixels can collapse a sliver into a degenerate ring.
            if len(polygon) < 3 or not Polygon(polygon).is_valid:
                continue
            objects.append(
                {
                    "polygon": polygon,
                    "kind": "other_obstacle",
                    "source": "map",
                }
            )
    return {
        "image_base64": base64.b64encode(encoded.getvalue()).decode(),
        "mime_type": "image/jpeg",
        "roof": pixel_ring(geometry.exterior.coords, grid)
        if geometry is not None
        else [],
        "objects": objects,
        "pixels_per_metre": grid["pixels_per_metre"],
        "angle": alignment(geometry) if geometry is not None else 0,
        "candidates": [
            public_plane(p)
            for p in planes
            if p["geometry"].area >= MIN_CANDIDATE_AREA_M2
        ][:MAX_CANDIDATES],
        "building_outline": public_plane(whole) if whole else None,
        "selected_roof_id": selected["id"] if selected else None,
        "warnings": warnings,
        "provenance": {
            "imagery": "SWISSIMAGE / swisstopo",
            "roof_source": (
                "Drawn on the map by you"
                if selection.polygon is not None
                else "Sonnendach / Swiss Federal Office of Energy"
                if selected
                else None
            ),
            "crs": "EPSG:2056",
            "bbox": grid["bbox"],
            "image_width": grid["width"],
            "image_height": grid["height"],
            "pixels_per_metre": grid["pixels_per_metre"],
            "latitude": selection.latitude,
            "longitude": selection.longitude,
            "feature_id": selected["id"] if selected else None,
            "building_id": props.get("building_id"),
            "merged_planes": selected.get("merged_planes", 1) if selected else 0,
            "roof_area_m2": round(geometry.area, 2) if geometry is not None else None,
            "pitch_deg": props.get("neigung"),
            "azimuth_deg": props.get("ausrichtung"),
            "roof_data_updated": props.get("datum_aenderung"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "scale_basis": "Map-projected metres in LV95, independent of display zoom. Packing uses the 2D plan view.",
            "source_url": "https://map.geo.admin.ch/",
        },
    }
