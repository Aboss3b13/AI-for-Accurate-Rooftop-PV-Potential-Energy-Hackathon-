"""Unioning face geometry must survive a self-touching projected ring."""

import pytest
from shapely.geometry import Polygon, box

from backend.services.surface_analysis import safe_union


def bowtie():
    # Self-intersecting: GEOS refuses to union this as-is.
    return Polygon([(0, 0), (4, 4), (4, 0), (0, 4)])


def test_a_self_touching_face_does_not_fail_the_union():
    result = safe_union([box(0, 0, 2, 2), bowtie()])
    assert not result.is_empty
    assert result.is_valid


def test_empty_input_is_an_empty_polygon():
    assert safe_union([]).is_empty
    assert safe_union([Polygon(), None]).is_empty


def test_valid_geometry_is_unioned_normally():
    result = safe_union([box(0, 0, 2, 2), box(2, 0, 4, 2)])
    assert result.area == pytest.approx(8.0)


def test_the_repair_keeps_the_area_it_can():
    result = safe_union([bowtie()])
    assert result.is_valid
    assert result.area == pytest.approx(8.0, abs=0.5)
