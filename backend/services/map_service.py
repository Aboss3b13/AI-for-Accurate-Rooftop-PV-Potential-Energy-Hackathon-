"""Swiss roof lookup and metric aerial capture. No screenshot/zoom scale guessing."""

import base64
import html
import io
import math
import hashlib
import uuid
import json
import re
from datetime import datetime, timezone

import httpx
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Point, Polygon, mapping, shape
from shapely.ops import transform, unary_union

from backend.schemas.map import MapSelection
import numpy as np

from backend.services.elevation_service import ElevationUnavailable, roof_model
from backend.services.roof_plane import RoofPlane, official_plane
from backend.services.runtime_cache import captures, prepared, geodata, imagery
from backend.services.rooflight_service import detect as detect_rooflights

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
    key = (path, json.dumps(params, sort_keys=True))
    cached = geodata.get(key)
    if cached is not None:
        return json.loads(json.dumps(cached))
    response = await client.get(API + path, params=params)
    response.raise_for_status()
    data = response.json()
    if "error" in data:
        raise MapServiceError("The Swiss map service could not complete this lookup.")
    geodata.put(key, data)
    return json.loads(json.dumps(data))


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
        "facets": geometries,
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
                    "properties": {**props, "_source_projected_area": geometry.area},
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
    key = selection.model_dump_json()
    cached = prepared.get(key)
    if cached is not None and captures.get(cached["capture_id"]) is not None:
        return cached
    return prepared.put(key, await _prepare_capture(selection))


async def _prepare_capture(selection: MapSelection) -> dict:
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
        else:
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
                    f"Loaded {selected['merged_planes']} individual Sonnendach roof faces. "
                    "Each face is optimised independently."
                )
        if selected is None:
            warnings.append(
                "No automatic roof boundary selected. Scale is calibrated; draw the roof in the editor."
            )
        geometry = selected["geometry"] if selected else None
        members = []
        if selected is not None:
            building = selected["properties"].get("building_id")
            members = ([p for p in planes if p["properties"].get("building_id") == building]
                       if planes and building is not None and
                       (not selection.roof_id or selection.roof_id.startswith("building:")) else [selected])
        members.sort(key=lambda p: p["id"])
        all_geometry = unary_union([p["geometry"] for p in members]) if members else geometry
        if len(members) > 1:
            selected = {**selected, "merged_planes": len(members)}
            whole = {**whole, "geometry": all_geometry}
        grid = capture_grid(all_geometry, click, selection.span_m)
        model_planes = [official_plane(p["geometry"], p["properties"]) for p in members]
        sunlight = [{"available": False, "reason": "Surrounding height data unavailable."} for _ in members]
        image_key = json.dumps(grid, sort_keys=True)
        image_content = imagery.get(image_key)
        if image_content is None:
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
            image_content = imagery.put(image_key, response.content)
        detected = []
        if geometry is not None:
            # The height model sees chimneys and dormers the PV-only model cannot.
            facets = [p["geometry"] for p in members]
            try:
                model = await roof_model(client, facets, all_geometry.bounds, [p["properties"] for p in members])
                detected, model_planes = model["obstacles"], model["planes"]
                sunlight = model["sunlight"]
            except ElevationUnavailable as exc:
                warnings.append(
                    f"Roof superstructures could not be measured ({exc}). "
                    "Mark chimneys and roof windows by hand."
                )
        image = Image.open(io.BytesIO(image_content)).convert("RGB")
        if image.size != (grid["width"], grid["height"]):
            raise MapServiceError(
                "The map image size did not match its scale. Please retry."
            )
        encoded = io.BytesIO()
        image.save(encoded, format="JPEG", quality=95)
    props = selected["properties"] if selected else {}
    roof_pixels = (
        pixel_ring(geometry.exterior.coords, grid) if geometry is not None else []
    )
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
    if geometry is not None and roof_pixels:
        # Flush roof windows never reach the height model; the photo shows them.
        outline = transform(lambda x, y: ((np.asarray(x)-grid["bbox"][0])*grid["pixels_per_metre"],
                                           (grid["bbox"][3]-np.asarray(y))*grid["pixels_per_metre"]), all_geometry)
        if outline.is_valid:
            already = [Polygon(o["polygon"]) for o in objects]
            already = [p for p in already if p.is_valid]
            for light in detect_rooflights(
                np.asarray(image), outline, grid["pixels_per_metre"], already
            ):
                clipped = light["geometry"].intersection(outline)
                if clipped.geom_type != "Polygon" or clipped.is_empty:
                    continue
                ring = [[round(x, 4), round(y, 4)] for x, y in clipped.exterior.coords]
                ring = ring[:-1] if ring[0] == ring[-1] else ring
                if len(ring) < 3:
                    continue
                objects.append(
                    {
                        "polygon": ring,
                        "kind": "skylight",
                        "source": "image",
                    }
                )
    for obstacle in detected if geometry is not None else []:
        clipped = obstacle["geometry"].intersection(all_geometry)
        if clipped.geom_type != "Polygon" or clipped.area < MIN_HOLE_AREA_M2:
            continue
        clipped = bounded_simplify(clipped) or clipped.convex_hull
        polygon = pixel_ring(clipped.exterior.coords, grid)
        if len(polygon) < 3 or not Polygon(polygon).is_valid:
            continue
        objects.append(
            {
                "polygon": polygon,
                "kind": obstacle["kind"],
                "source": "terrain" if obstacle.get("below_roof") else "elevation",
                "height_m": obstacle["height_m"],
            }
        )
    ground = [o for o in objects if o["source"] == "terrain"]
    if ground:
        warnings.append(
            f"Excluded {len(ground)} area(s) lying more than 1.5 m below the roof face. "
            "An official roof outline can span a whole block and take in its courtyard."
        )
    raised = [o for o in objects if o["source"] == "elevation"]
    lights = [o for o in objects if o["source"] == "image"]
    if raised:
        warnings.append(
            f"Measured {len(raised)} raised roof structures from the swisstopo height model."
        )
    if lights:
        warnings.append(
            f"Found {len(lights)} likely roof windows by their reflection in the aerial photo. "
            "Check them against the image and mark anything missed."
        )
    if not raised and not lights:
        warnings.append(
            "No roof structures found. That is not proof the roof is clear - "
            "mark any chimneys or roof windows yourself."
        )
    capture_id = uuid.uuid4().hex
    faces = [{**p, "plane": plane, "sunlight": sun} for p, plane, sun in zip(members, model_planes, sunlight)]
    # Hash the decoded JPEG, exactly as the analyse endpoint receives it.
    decoded = Image.open(io.BytesIO(encoded.getvalue())).convert("RGB")
    captures.put(capture_id, {"faces": faces, "grid": grid,
                 "image_hash": hashlib.sha256(decoded.tobytes()).hexdigest(),
                 "warnings": list(warnings), "default_angle": alignment(geometry) if geometry is not None else 0})
    return {
        "capture_id": capture_id,
        "roof_faces": [{**public_plane(p), "roof": pixel_ring(p["geometry"].exterior.coords, grid),
                        "plane": plane.describe()} for p, plane in zip(members, model_planes)],
        "image_base64": base64.b64encode(encoded.getvalue()).decode(),
        "mime_type": "image/jpeg",
        "roof": roof_pixels,
        "objects": objects,
        "pixels_per_metre": grid["pixels_per_metre"],
        "angle": alignment(geometry) if geometry is not None else 0,
        "candidates": [
            public_plane(p)
            for p in members
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
            "roof_area_m2": round(all_geometry.area, 2) if all_geometry is not None else None,
            "pitch_deg": props.get("neigung"),
            "azimuth_deg": props.get("ausrichtung"),
            "roof_data_updated": props.get("datum_aenderung"),
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "scale_basis": "LV95 map metres, independent of display zoom. Each reliable DSM face is packed in true surface metres; unavailable faces use a labelled projected fallback.",
            "source_url": "https://map.geo.admin.ch/",
        },
    }
