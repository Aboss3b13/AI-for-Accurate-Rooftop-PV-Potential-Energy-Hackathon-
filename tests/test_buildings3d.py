"""Roof surfaces read from swissBUILDINGS3D, without touching the network."""

import math

import numpy as np
import pytest
from shapely.geometry import Point, Polygon, box

from backend.services import buildings3d_service as b3


def gable(width=10.0, depth=8.0, eaves=400.0, ridge=404.0, batch=0, x0=0.0, y0=0.0):
    """Two pitches meeting at a ridge, as a triangle soup with batch ids."""
    half = depth / 2
    v = np.array([
        [x0, y0, eaves], [x0 + width, y0, eaves],
        [x0, y0 + half, ridge], [x0 + width, y0 + half, ridge],
        [x0, y0 + depth, eaves], [x0 + width, y0 + depth, eaves],
    ])
    f = np.array([[0, 1, 3], [0, 3, 2], [2, 3, 5], [2, 5, 4]])
    return v, f, np.full(len(v), batch)


def tile_from(*buildings, attributes=None):
    vertices, faces, batch = [], [], []
    for v, f, b in buildings:
        faces.append(f + sum(len(x) for x in vertices))
        vertices.append(v)
        batch.append(b)
    return {"vertices": np.vstack(vertices), "faces": np.vstack(faces),
            "batch": np.concatenate(batch).astype(int),
            "attributes": attributes or {}}


# --- geometry extraction ----------------------------------------------------

def test_a_gable_yields_two_pitched_faces():
    tile = tile_from(gable())
    faces = b3.roof_faces(tile, 0)
    assert len(faces) == 2
    for face in faces:
        assert 20 < face["pitch_deg"] < 60
        # A pitched surface is larger than its shadow on the ground.
        assert face["surface_area_m2"] > face["projected_area_m2"]


def test_a_flat_roof_is_one_face_without_an_azimuth():
    v = np.array([[0, 0, 400.0], [10, 0, 400.0], [10, 8, 400.0], [0, 8, 400.0]])
    f = np.array([[0, 1, 2], [0, 2, 3]])
    tile = tile_from((v, f, np.zeros(4)))
    faces = b3.roof_faces(tile, 0)
    assert len(faces) == 1
    assert faces[0]["pitch_deg"] == pytest.approx(0, abs=0.5)
    assert faces[0]["azimuth_deg"] is None
    assert faces[0]["projected_area_m2"] == pytest.approx(80, abs=1)


def test_true_surface_area_follows_the_pitch():
    tile = tile_from(gable(width=10, depth=8, eaves=400, ridge=402))
    face = b3.roof_faces(tile, 0)[0]
    expected = face["projected_area_m2"] / math.cos(math.radians(face["pitch_deg"]))
    assert face["surface_area_m2"] == pytest.approx(expected, rel=0.02)


def test_a_lower_terrace_under_a_roof_is_not_counted_twice():
    """A solid carries balconies and slabs; only the top one is roof."""
    upper = (np.array([[0, 0, 410.0], [10, 0, 410.0], [10, 8, 410.0], [0, 8, 410.0]]),
             np.array([[0, 1, 2], [0, 2, 3]]), np.zeros(4))
    lower = (np.array([[0, 0, 404.0], [10, 0, 404.0], [10, 8, 404.0], [0, 8, 404.0]]),
             np.array([[0, 1, 2], [0, 2, 3]]), np.zeros(4))
    tile = tile_from(upper, lower)
    total = sum(f["projected_area_m2"] for f in b3.roof_faces(tile, 0))
    assert total == pytest.approx(80, abs=2)


def test_walls_are_not_roof():
    wall = (np.array([[0, 0, 400.0], [10, 0, 400.0], [10, 0, 410.0], [0, 0, 410.0]]),
            np.array([[0, 1, 2], [0, 2, 3]]), np.zeros(4))
    assert b3.roof_faces(tile_from(wall), 0) == []


def test_only_the_asked_building_is_returned():
    tile = tile_from(gable(batch=0), gable(batch=1, x0=40))
    first = b3.roof_faces(tile, 0)
    second = b3.roof_faces(tile, 1)
    assert first and second
    assert max(f["geometry"].bounds[2] for f in first) < 40
    assert min(f["geometry"].bounds[0] for f in second) >= 40


# --- picking the clicked building -------------------------------------------

def test_the_batch_under_the_click_is_found():
    tile = tile_from(gable(batch=0), gable(batch=1, x0=40))
    assert b3.building_batches(tile, Point(5, 4)) == [0]
    assert b3.building_batches(tile, Point(45, 4)) == [1]


def test_a_click_off_every_building_finds_nothing():
    tile = tile_from(gable(batch=0))
    assert b3.building_batches(tile, Point(500, 500)) == []


def test_the_footprint_keeps_every_part_of_the_solid():
    tile = tile_from(gable(batch=0), gable(batch=0, x0=40))
    shape = b3.footprint(tile, 0)
    # Discarding all but the largest part understates the building.
    assert shape.area == pytest.approx(160, abs=5)


# --- attributes and the adapter into the pipeline ---------------------------

def test_attributes_are_read_for_the_right_batch():
    tile = tile_from(gable(batch=0), gable(batch=1, x0=40),
                     attributes={"EGID": [111, 222], "DACH_MAX": [404.0, 409.0]})
    assert b3.attributes_for(tile, 1) == {"EGID": 222, "DACH_MAX": 409.0}


def test_solar_attributes_come_from_the_overlapping_official_face():
    official = [{"id": "s1", "geometry": box(0, 0, 10, 8),
                 "properties": {"mstrahlung": 1200, "building_id": 9}},
                {"id": "s2", "geometry": box(100, 100, 110, 108),
                 "properties": {"mstrahlung": 400, "building_id": 9}}]
    got = b3.sonnendach_attributes(box(1, 1, 9, 7), official)
    assert got["mstrahlung"] == 1200
    assert got["_sonnendach_face"] == "s1"


def test_a_surface_with_no_official_face_gets_no_invented_irradiation():
    assert b3.sonnendach_attributes(box(0, 0, 5, 5), []) == {}


def test_the_adapter_presents_faces_the_pipeline_can_read():
    tile = tile_from(gable(batch=0), attributes={"EGID": [4242]})
    building = {"batch_id": 0, "footprint": b3.footprint(tile, 0),
                "faces": b3.roof_faces(tile, 0),
                "attributes": b3.attributes_for(tile, 0)}
    members = b3.as_roof_planes(building, Point(5, 2), [])
    assert members
    for member in members:
        assert member["id"].startswith("b3d:")
        assert member["properties"]["gwr_egid"] == 4242
        assert member["properties"]["_geometry_source"] == "swissbuildings3d"
        # Sonnendach records aspect as -180..180.
        aspect = member["properties"]["ausrichtung"]
        assert aspect is None or -180 <= aspect <= 180
    assert any(m["contains_click"] for m in members)


# --- failure is survivable --------------------------------------------------

def test_a_tile_that_is_not_a_model_is_refused():
    with pytest.raises(b3.Buildings3DUnavailable):
        b3.parse_tile(b"not a b3dm payload at all........")


def test_a_building_with_no_geometry_returns_nothing():
    tile = tile_from(gable(batch=0))
    assert b3.roof_faces(tile, 7) == []
    assert b3.footprint(tile, 7) is None


def test_the_rotation_helper_is_a_rotation():
    matrix = b3._quaternion_matrix([-0.2622, 0.6939, 0.3044, 0.5976])
    assert np.allclose(matrix @ matrix.T, np.eye(3), atol=1e-3)
    assert np.linalg.det(matrix) == pytest.approx(1.0, abs=1e-3)
