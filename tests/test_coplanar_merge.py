"""Sonnendach splits one roof plane into strips; packing them apart fits nothing."""

import pytest
from shapely.geometry import box

from backend.services.map_service import merge_coplanar


def face(identifier, geometry, pitch, azimuth, area=None, yield_kwh=None, irradiation=None):
    return {
        "id": identifier,
        "geometry": geometry,
        "properties": {
            "neigung": pitch, "ausrichtung": azimuth,
            "flaeche": area if area is not None else geometry.area,
            "stromertrag": yield_kwh, "mstrahlung": irradiation,
        },
    }


def test_touching_strips_of_one_plane_become_one_surface():
    strips = [
        face("1:0", box(0, 0, 6.5, 1.6), 30, 180),
        face("2:0", box(0, 1.6, 6.5, 3.2), 30, 180),
        face("3:0", box(0, 3.2, 6.5, 4.8), 30, 182),
    ]
    merged = merge_coplanar(strips)
    assert len(merged) == 1
    assert merged[0]["geometry"].area == pytest.approx(6.5 * 4.8, abs=0.1)
    assert merged[0]["merged_faces"] == 3


def test_opposite_pitches_of_a_gable_stay_apart():
    # A panel cannot span a ridge, so these must not be joined.
    north = face("1:0", box(0, 0, 8, 4), 35, 0)
    south = face("2:0", box(0, 4, 8, 8), 35, 180)
    assert len(merge_coplanar([north, south])) == 2


def test_distant_faces_of_the_same_pitch_stay_apart():
    a = face("1:0", box(0, 0, 4, 4), 30, 180)
    b = face("2:0", box(20, 0, 24, 4), 30, 180)
    assert len(merge_coplanar([a, b])) == 2


def test_flat_faces_are_never_joined():
    # Two levels of a stepped flat roof share pitch 0 and the same recorded
    # aspect while being metres apart in height. Joining them made a 2,800 m2
    # industrial roof fit nothing at all.
    a = face("1:0", box(0, 0, 5, 5), 0, -180)
    b = face("2:0", box(5, 0, 10, 5), 0, -180)
    assert len(merge_coplanar([a, b])) == 2


def test_official_totals_are_summed_and_irradiation_reweighted():
    a = face("1:0", box(0, 0, 10, 1), 30, 180, area=100.0, yield_kwh=10000.0, irradiation=1000)
    b = face("2:0", box(0, 1, 10, 2), 30, 180, area=300.0, yield_kwh=30000.0, irradiation=1400)
    merged = merge_coplanar([a, b])[0]["properties"]
    assert merged["flaeche"] == pytest.approx(400.0)
    assert merged["stromertrag"] == pytest.approx(40000.0)
    # Area-weighted, not a plain average of 1000 and 1400.
    assert merged["mstrahlung"] == pytest.approx(1300, abs=1)


def test_a_single_face_is_returned_untouched():
    only = [face("1:0", box(0, 0, 4, 4), 30, 180)]
    assert merge_coplanar(only) is only


def test_faces_without_a_recorded_pitch_are_left_alone():
    a = face("1:0", box(0, 0, 4, 4), None, None)
    b = face("2:0", box(4, 0, 8, 4), None, None)
    assert len(merge_coplanar([a, b])) == 2
