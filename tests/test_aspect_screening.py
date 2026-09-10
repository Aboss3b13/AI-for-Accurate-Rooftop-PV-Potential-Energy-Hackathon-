"""A pitched roof turned towards the pole is not worth mounting on."""

import pytest

from backend.schemas.analysis import AnalysisSettings
from backend.services.suitability_service import (
    ASPECT_MATTERS_ABOVE_DEG,
    NORTH_SECTOR_DEG,
    assess_face,
)


class Plane:
    """Minimal stand-in for a fitted roof plane."""

    def __init__(self, pitch, azimuth, source="swisssurface3d"):
        self.source = source
        self.diagnostics = {"height_anchor": "measured"}
        self._describe = {"pitch_deg": pitch, "azimuth_deg": azimuth,
                          "height_is_absolute": True, "geometry_conflict": False,
                          "area_disagreement_fraction": 0.0}

    def describe(self):
        return dict(self._describe)


SETTINGS = AnalysisSettings(roof=[(0, 0), (10, 0), (10, 10)])
SUN = {"available": True, "coverage_fraction": 1.0, "height_anchor": "measured"}


def judge(pitch, azimuth, irradiation=1100):
    return assess_face(Plane(pitch, azimuth),
                       {"irradiation_kwh_m2_year": irradiation}, SUN, SETTINGS)


def test_a_south_pitch_is_recommended():
    assert judge(30, 175)["eligible"] is True


def test_a_north_pitch_is_refused_even_with_passing_irradiation():
    # The Ruemlang case: 352 degrees, 840 kWh/m2, cleared the irradiation
    # screen at 800 and took 25 modules.
    result = judge(28, 352, irradiation=840)
    assert result["eligible"] is False
    assert any("north" in r for r in result["reasons"])


def test_due_north_is_refused():
    assert judge(30, 0)["eligible"] is False
    assert judge(30, 360)["eligible"] is False


@pytest.mark.parametrize("azimuth", [90, 175, 185, 270])
def test_east_south_and_west_pitches_are_kept(azimuth):
    assert judge(30, azimuth)["eligible"] is True


def test_the_sector_edge_is_where_it_says_it_is():
    inside = NORTH_SECTOR_DEG - 1
    outside = NORTH_SECTOR_DEG + 1
    assert judge(30, inside)["eligible"] is False
    assert judge(30, outside)["eligible"] is True


def test_a_flat_roof_keeps_its_aspect_out_of_it():
    # A flat face has no meaningful aspect; Sonnendach still records one.
    shallow = ASPECT_MATTERS_ABOVE_DEG - 5
    assert judge(shallow, 0)["eligible"] is True


def test_a_face_without_a_recorded_aspect_is_not_refused_for_it():
    result = assess_face(Plane(30, None), {"irradiation_kwh_m2_year": 1100},
                         SUN, SETTINGS)
    assert not any("north" in r for r in result["reasons"])


def test_the_rule_is_reported_with_the_result():
    rules = judge(30, 175)["rules"]
    assert rules["north_sector_deg"] == NORTH_SECTOR_DEG
    assert rules["aspect_matters_above_pitch_deg"] == ASPECT_MATTERS_ABOVE_DEG
