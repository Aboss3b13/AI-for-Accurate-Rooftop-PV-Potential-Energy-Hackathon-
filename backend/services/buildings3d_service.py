"""swissBUILDINGS3D roof surfaces, streamed a tile at a time.

The bulk distribution is not usable interactively: the CityGML tile covering the
test area is 251 MB and dated 2019. swisstopo also publishes the same model as
3D Tiles for streaming, and there the tile over one city block is about 136 KB
and dated 2026, which is what this reads.

A tile is a batched glTF: Draco-compressed triangles, one batch id per vertex,
and a batch table carrying EGID, roof height and building use. That gives the
two things Sonnendach cannot: the footprint of the structure the user actually
clicked, and its roof faces as measured geometry rather than as a record group.

Positions arrive in the glTF frame and reach LV95 through the transform the
3D Tiles spec prescribes - node TRS, then y-up to z-up, then the tile's
RTC_CENTER, then ECEF to LV95. Getting that order wrong still lands in the right
city, so it is checked against the batch table's own DACH_MAX: the two agree to
within a centimetre per building.
"""

import json
import math
import struct
from pathlib import Path

import httpx
import numpy as np
from pyproj import Transformer
from shapely.geometry import MultiPoint, Polygon
from shapely.ops import unary_union

SERVICE = "https://3d.geo.admin.ch/ch.swisstopo.swissbuildings3d.3d/v1/"
CACHE = Path(__file__).resolve().parents[2] / ".cache" / "b3dm"
TO_LV95 = Transformer.from_crs("EPSG:4978", "EPSG:2056", always_xy=True)
TO_WGS84 = Transformer.from_crs("EPSG:4978", "EPSG:4979", always_xy=True)
FROM_WGS84 = Transformer.from_crs(4326, 2056, always_xy=True)

GLTF_JSON, GLTF_BIN = 0x4E4F534A, 0x004E4942
# glTF is y-up; 3D Tiles is z-up.
Y_UP_TO_Z_UP = np.array([[1.0, 0, 0], [0, 0, -1.0], [0, 1.0, 0]])

# A roof face points upwards; walls and soffits do not.
MIN_ROOF_NORMAL_Z = 0.30
# Triangles join one face when their normals and offsets agree this closely.
NORMAL_TOLERANCE_DEG = 12.0
OFFSET_TOLERANCE_M = 0.40
MIN_FACE_AREA_M2 = 3.0
# Bridge the seams left by triangulation without merging separate roof areas.
SEAM_M = 0.15
# One plane split by cutting is rejoined within these limits.
JOIN_GAP_M = 0.5
JOIN_HEIGHT_M = 1.5
MAX_TRAVERSAL = 24
CACHE_LIMIT_BYTES = 300_000_000


class Buildings3DUnavailable(Exception):
    """The 3D model could not be read; the caller falls back to Sonnendach."""


def _quaternion_matrix(q) -> np.ndarray:
    x, y, z, w = q
    return np.array([
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ])


def _prune_cache() -> None:
    files = sorted(CACHE.glob("*.b3dm"), key=lambda p: p.stat().st_mtime)
    total = sum(p.stat().st_size for p in files)
    while files and total > CACHE_LIMIT_BYTES:
        oldest = files.pop(0)
        total -= oldest.stat().st_size
        oldest.unlink(missing_ok=True)


async def _json(client: httpx.AsyncClient, url: str) -> dict:
    response = await client.get(url, timeout=60, follow_redirects=True)
    response.raise_for_status()
    return response.json()


async def tile_url(client: httpx.AsyncClient, latitude: float, longitude: float) -> str:
    """Walk the tileset tree down to the content covering this point."""
    lat, lon = math.radians(latitude), math.radians(longitude)

    def covers(node) -> bool:
        region = (node.get("boundingVolume") or {}).get("region")
        if not region:
            return True
        west, south, east, north = region[:4]
        return west <= lon <= east and south <= lat <= north

    url = SERVICE + "tileset.json"
    for _ in range(MAX_TRAVERSAL):
        document = await _json(client, url)
        base = url.rsplit("/", 1)[0] + "/"
        stack = [document.get("root") or document]
        target = None
        while stack:
            node = stack.pop()
            if not covers(node):
                continue
            content = node.get("content") or {}
            uri = content.get("uri") or content.get("url")
            if uri:
                target = uri if uri.startswith("http") else base + uri
                break
            stack.extend(node.get("children") or [])
        if target is None:
            raise Buildings3DUnavailable("No 3D building tile covers this point")
        if target.endswith(".json"):
            url = target
            continue
        return target
    raise Buildings3DUnavailable("3D building tileset nested deeper than expected")


async def cached_tile(client: httpx.AsyncClient, url: str) -> bytes:
    CACHE.mkdir(parents=True, exist_ok=True)
    name = "_".join(url.rsplit("/", 4)[-4:]).replace("/", "_")
    path = CACHE / name
    if path.exists() and path.stat().st_size > 0:
        path.touch()
        return path.read_bytes()
    response = await client.get(url, timeout=120, follow_redirects=True)
    response.raise_for_status()
    path.write_bytes(response.content)
    _prune_cache()
    return response.content


def parse_tile(data: bytes) -> dict:
    """Decode one b3dm into LV95 triangles plus its batch attributes."""
    import DracoPy

    if data[:4] != b"b3dm":
        raise Buildings3DUnavailable("Not a batched 3D model tile")
    _, _, feature_json, feature_bin, batch_json, batch_bin = struct.unpack(
        "<IIIIII", data[4:28])
    offset = 28
    feature = json.loads(data[offset:offset + feature_json] or b"{}")
    offset += feature_json + feature_bin
    batch = json.loads(data[offset:offset + batch_json] or b"{}")
    offset += batch_json + batch_bin
    glb = data[offset:]
    if glb[:4] != b"glTF":
        raise Buildings3DUnavailable("Tile carries no glTF payload")
    total = struct.unpack("<I", glb[8:12])[0]
    cursor, chunks = 12, {}
    while cursor < total:
        length, kind = struct.unpack("<II", glb[cursor:cursor + 8])
        cursor += 8
        chunks[kind] = (cursor, length)
        cursor += length
    start, length = chunks[GLTF_JSON]
    document = json.loads(glb[start:start + length])
    start, length = chunks[GLTF_BIN]
    buffer = glb[start:start + length]

    node = (document.get("nodes") or [{}])[0]
    rotation = _quaternion_matrix(node["rotation"]) if "rotation" in node else np.eye(3)
    translation = np.array(node.get("translation", [0.0, 0.0, 0.0]))
    scale = np.array(node.get("scale", [1.0, 1.0, 1.0]))
    centre = np.array(feature.get("RTC_CENTER", [0.0, 0.0, 0.0]))

    points, triangles, ids = [], [], []
    for mesh in document.get("meshes", []):
        for primitive in mesh.get("primitives", []):
            draco = (primitive.get("extensions") or {}).get(
                "KHR_draco_mesh_compression")
            if not draco:
                continue
            view = document["bufferViews"][draco["bufferView"]]
            begin = view.get("byteOffset", 0)
            decoded = DracoPy.decode(buffer[begin:begin + view["byteLength"]])
            local = np.asarray(decoded.points, dtype=np.float64)
            base = sum(len(p) for p in points)
            points.append(local * scale)
            triangles.append(np.asarray(decoded.faces, dtype=np.int64) + base)
            attribute = draco["attributes"].get("_BATCHID")
            batch_ids = np.zeros(len(local))
            if attribute is not None:
                raw = decoded.get_attribute_by_unique_id(attribute)
                values = np.asarray(raw["data"] if isinstance(raw, dict) else raw)
                if values.size >= len(local):
                    batch_ids = values.reshape(len(local), -1)[:, 0]
            ids.append(batch_ids)
    if not points:
        raise Buildings3DUnavailable("Tile contains no decodable geometry")

    local = np.vstack(points)
    # The order the 3D Tiles specification prescribes. Checked against the batch
    # table's own DACH_MAX, which it reproduces to a centimetre per building.
    world = (Y_UP_TO_Z_UP @ ((rotation @ local.T).T + translation).T).T + centre
    east, north, _ = TO_LV95.transform(world[:, 0], world[:, 1], world[:, 2])
    _, _, height = TO_WGS84.transform(world[:, 0], world[:, 1], world[:, 2])
    return {
        "vertices": np.column_stack([east, north, height]),
        "faces": np.vstack(triangles),
        "batch": np.concatenate(ids).astype(int),
        "attributes": batch,
    }


def building_batches(tile: dict, point, buffer_m: float = 0.0) -> list[int]:
    """Batch ids whose footprint covers the clicked point."""
    vertices, faces, batch = tile["vertices"], tile["faces"], tile["batch"]
    hits = []
    for identifier in np.unique(batch[faces[:, 0]]):
        mask = batch[faces[:, 0]] == identifier
        pts = vertices[np.unique(faces[mask])][:, :2]
        if len(pts) < 3:
            continue
        hull = MultiPoint([tuple(p) for p in pts]).convex_hull
        if hull.buffer(buffer_m).covers(point):
            hits.append(int(identifier))
    return hits


def _triangle_normals(vertices, faces):
    a, b, c = (vertices[faces[:, i]] for i in range(3))
    normals = np.cross(b - a, c - a)
    lengths = np.linalg.norm(normals, axis=1)
    good = lengths > 1e-9
    normals[good] /= lengths[good][:, None]
    return normals, lengths / 2.0, a


def roof_faces(tile: dict, identifier: int) -> list[dict]:
    """Group a building's upward triangles into planar roof faces."""
    vertices, faces, batch = tile["vertices"], tile["faces"], tile["batch"]
    mine = faces[batch[faces[:, 0]] == identifier]
    if not len(mine):
        return []
    normals, areas, anchors = _triangle_normals(vertices, mine)
    upward = normals[:, 2] >= MIN_ROOF_NORMAL_Z
    if not upward.any():
        return []
    offsets = np.einsum("ij,ij->i", normals, anchors)
    cosine = math.cos(math.radians(NORMAL_TOLERANCE_DEG))
    groups: list[dict] = []
    order = np.argsort(-areas)
    for index in order:
        if not upward[index]:
            continue
        normal, offset = normals[index], offsets[index]
        for group in groups:
            if (float(np.dot(group["normal"], normal)) >= cosine
                    and abs(group["offset"] - offset) <= OFFSET_TOLERANCE_M):
                group["indices"].append(index)
                break
        else:
            groups.append({"normal": normal, "offset": float(offset),
                           "indices": [index], "height": float(anchors[index][2])})
    out = []
    for group in groups:
        pieces = []
        for index in group["indices"]:
            ring = vertices[mine[index]][:, :2]
            triangle = Polygon(ring)
            if triangle.is_valid and triangle.area > 1e-6:
                pieces.append(triangle)
        if not pieces:
            continue
        group["height"] = float(np.mean([vertices[mine[i]][:, 2].mean()
                                         for i in group["indices"]]))
        shape = unary_union(pieces).buffer(SEAM_M).buffer(-SEAM_M)
        for part in (shape.geoms if shape.geom_type == "MultiPolygon" else [shape]):
            if part.geom_type != "Polygon" or part.area < MIN_FACE_AREA_M2:
                continue
            normal = group["normal"]
            pitch = math.degrees(math.acos(min(1.0, abs(float(normal[2])))))
            azimuth = (math.degrees(math.atan2(float(normal[0]), float(normal[1])))
                       % 360) if pitch > 0.5 else None
            out.append({
                "geometry": part.simplify(0.05, preserve_topology=True),
                "normal": normal.tolist(),
                "height_m": group["height"],
                "pitch_deg": round(pitch, 2),
                "azimuth_deg": round(azimuth, 2) if azimuth is not None else None,
            })
    return _topmost(out)


def _topmost(faces: list[dict]) -> list[dict]:
    """Keep, at every point of the plan, only the highest surface.

    A building solid carries balconies, terraces and floor slabs as well as its
    roof, and they stack: summed blindly, one Hottingen building reported 294%
    of its own footprint as roof. Seen from above only the top one is roof, so
    each face is cut against everything already accepted above it.
    """
    covered = None
    kept = []
    for face in sorted(faces, key=lambda f: -f["height_m"]):
        shape = face["geometry"]
        if covered is not None:
            shape = shape.difference(covered)
        parts = shape.geoms if shape.geom_type == "MultiPolygon" else [shape]
        for part in parts:
            if part.geom_type != "Polygon" or part.area < MIN_FACE_AREA_M2:
                continue
            normal = face["normal"]
            kept.append({**face, "geometry": part.simplify(0.05, preserve_topology=True),
                         "projected_area_m2": round(part.area, 2),
                         "surface_area_m2": round(
                             part.area / max(abs(float(normal[2])), 1e-6), 2)})
        covered = shape if covered is None else unary_union([covered, shape])
    return _join_coplanar(kept)


def _join_coplanar(faces: list[dict]) -> list[dict]:
    """Rejoin one physical plane that triangulation and cutting split up.

    Differencing stacked surfaces leaves a plane in pieces, and packing each
    piece separately charges an edge setback to boundaries that are not edges.
    """
    cosine = math.cos(math.radians(NORMAL_TOLERANCE_DEG))
    groups: list[dict] = []
    for face in sorted(faces, key=lambda f: -f["projected_area_m2"]):
        normal = np.asarray(face["normal"])
        for group in groups:
            if (float(np.dot(np.asarray(group["normal"]), normal)) >= cosine
                    and abs(group["height_m"] - face["height_m"]) <= JOIN_HEIGHT_M
                    and group["shape"].dwithin(face["geometry"], JOIN_GAP_M)):
                group["shape"] = unary_union([group["shape"], face["geometry"]])
                break
        else:
            groups.append({**face, "shape": face["geometry"]})
    out = []
    for group in groups:
        shape = group["shape"].buffer(SEAM_M).buffer(-SEAM_M)
        for part in (shape.geoms if shape.geom_type == "MultiPolygon" else [shape]):
            if part.geom_type != "Polygon" or part.area < MIN_FACE_AREA_M2:
                continue
            normal = group["normal"]
            out.append({k: v for k, v in group.items() if k != "shape"} | {
                "geometry": part.simplify(0.05, preserve_topology=True),
                "projected_area_m2": round(part.area, 2),
                "surface_area_m2": round(
                    part.area / max(abs(float(normal[2])), 1e-6), 2)})
    out.sort(key=lambda f: -f["projected_area_m2"])
    return out


def footprint(tile: dict, identifier: int) -> Polygon | None:
    vertices, faces, batch = tile["vertices"], tile["faces"], tile["batch"]
    mine = faces[batch[faces[:, 0]] == identifier]
    if not len(mine):
        return None
    pieces = [Polygon(vertices[t][:, :2]) for t in mine]
    pieces = [p for p in pieces if p.is_valid and p.area > 1e-6]
    if not pieces:
        return None
    shape = unary_union(pieces).buffer(0.05).buffer(-0.05)
    # Kept whole: a building solid can project to several parts, and dropping
    # all but the largest understates the footprint and hides real roof.
    if shape.geom_type not in {"Polygon", "MultiPolygon"} or shape.is_empty:
        return None
    return shape


def attributes_for(tile: dict, identifier: int) -> dict:
    table = tile.get("attributes") or {}
    out = {}
    for key, values in table.items():
        if isinstance(values, list) and identifier < len(values):
            out[key] = values[identifier]
    return out


async def building_at(client: httpx.AsyncClient, latitude: float, longitude: float):
    """Footprint, roof faces and attributes for the building under this point."""
    from shapely.geometry import Point

    url = await tile_url(client, latitude, longitude)
    tile = parse_tile(await cached_tile(client, url))
    x, y = FROM_WGS84.transform(longitude, latitude)
    point = Point(x, y)
    hits = building_batches(tile, point) or building_batches(tile, point, 1.5)
    if not hits:
        raise Buildings3DUnavailable("No 3D building covers this point")
    identifier = max(hits, key=lambda b: (footprint(tile, b) or Polygon()).area)
    outline = footprint(tile, identifier)
    if outline is None:
        raise Buildings3DUnavailable("The 3D building has no usable footprint")
    return {
        "batch_id": identifier,
        "footprint": outline,
        "faces": roof_faces(tile, identifier),
        "attributes": attributes_for(tile, identifier),
        "tile_url": url,
    }


def sonnendach_attributes(face_geometry, sonnendach_planes) -> dict:
    """Borrow solar attributes from the official face this surface sits on.

    swissBUILDINGS3D measures the roof; it says nothing about irradiation. The
    Sonnendach face with the largest overlap carries that, so each measured
    surface inherits the solar record of the roof it physically coincides with.
    """
    best, score = None, 0.0
    for plane in sonnendach_planes or []:
        try:
            overlap = face_geometry.intersection(plane["geometry"]).area
        except Exception:
            continue
        if overlap > score:
            best, score = plane, overlap
    if best is None:
        return {}
    share = score / max(face_geometry.area, 1e-9)
    return {**best["properties"], "_sonnendach_overlap": round(share, 3),
            "_sonnendach_face": best["id"]}


def as_roof_planes(building: dict, click, sonnendach_planes=None) -> list[dict]:
    """Present measured roof faces in the shape the analysis pipeline expects."""
    members = []
    attributes = building.get("attributes") or {}
    egid = attributes.get("EGID")
    for index, face in enumerate(building.get("faces") or []):
        geometry = face["geometry"]
        solar = sonnendach_attributes(geometry, sonnendach_planes)
        properties = {
            **solar,
            "gwr_egid": egid if egid else solar.get("gwr_egid"),
            "building_id": solar.get("building_id"),
            # Sonnendach records aspect as -180..180 with south at zero.
            "neigung": face["pitch_deg"],
            "ausrichtung": (None if face["azimuth_deg"] is None
                            else round((face["azimuth_deg"] - 180 + 180) % 360 - 180, 2)),
            "_source_projected_area": face["projected_area_m2"],
            "_geometry_source": "swissbuildings3d",
            "_roof_height_m": face.get("height_m"),
        }
        members.append({
            "id": f"b3d:{building['batch_id']}:{index}",
            "geometry": geometry,
            "properties": properties,
            "contains_click": bool(geometry.covers(click)),
            "distance": geometry.distance(click),
        })
    members.sort(key=lambda p: (not p["contains_click"], p["distance"],
                                -p["geometry"].area))
    return members
