"""The Sonnendach baseline comparison: the challenge's headline output."""

import pytest
from shapely.geometry import Polygon, box

from backend.schemas.analysis import AnalysisSettings
from backend.services.suitability_service import sonnendach_comparison


def settings(**kw):
    return AnalysisSettings(roof=[(0, 0), (10, 0), (10, 10)], **kw)


def face(area, *, eligible=True, objects=(), shaded=0.0):
    side = area**0.5
    return {
        "local": box(0, 0, side, side),
        "assessment": {"eligible": eligible},
        "objects": list(objects),
        "shaded": box(0, 0, shaded**0.5, shaded**0.5) if shaded else Polygon(),
    }


def official(area, energy):
    return {"properties": {"flaeche": area, "stromertrag": energy}}


def test_reports_the_official_baseline_and_what_actually_fits():
    config = settings()
    result = sonnendach_comparison(
        [official(100.0, 20000.0)], [face(100.0)], config, 12000.0, 20
    )
    assert result["official_area_m2"] == 100.0
    assert result["official_annual_energy_kwh"] == 20000
    module_area = 20 * config.panel.width * config.panel.height
    assert result["fitted_module_area_m2"] == pytest.approx(module_area, abs=0.05)
    assert result["fitted_annual_energy_kwh"] == 12000
    assert result["energy_shortfall_percent"] == pytest.approx(40.0, abs=0.1)


def test_the_breakdown_adds_up_to_the_measured_surface():
    config = settings()
    faces = [
        face(60.0, objects=[{"kind": "existing_pv", "polygon": [(0, 0), (3, 0), (3, 3), (0, 3)]}]),
        face(40.0, eligible=False),
    ]
    result = sonnendach_comparison([official(120.0, 20000.0)], faces, config, 9000.0, 10)
    total = sum(result["breakdown_m2"].values()) + result["fitted_module_area_m2"]
    assert total == pytest.approx(result["measured_surface_m2"], abs=0.2)


def test_a_screened_out_face_is_named_as_the_reason():
    config = settings()
    faces = [face(50.0, eligible=False), face(50.0)]
    result = sonnendach_comparison([official(100.0, 20000.0)], faces, config, 5000.0, 5)
    assert result["breakdown_m2"]["faces_screened_out"] == pytest.approx(50.0, abs=0.1)


def test_existing_panels_and_obstacles_are_separated():
    config = settings()
    faces = [
        face(
            100.0,
            objects=[
                {"kind": "existing_pv", "polygon": [(0, 0), (4, 0), (4, 4), (0, 4)]},
                {"kind": "chimney", "polygon": [(5, 5), (6, 5), (6, 6), (5, 6)]},
            ],
        )
    ]
    result = sonnendach_comparison([official(100.0, 20000.0)], faces, config, 8000.0, 10)
    assert result["breakdown_m2"]["existing_pv"] == pytest.approx(16.0, abs=0.1)
    assert result["breakdown_m2"]["roof_obstacles"] == pytest.approx(1.0, abs=0.1)


def test_the_two_area_definitions_are_reconciled_not_hidden():
    config = settings()
    # Sonnendach says 200 m2; SolarFit measures 100 m2 of roof surface.
    result = sonnendach_comparison([official(200.0, 20000.0)], [face(100.0)], config, 9000.0, 10)
    assert result["definition_difference_m2"] == pytest.approx(100.0, abs=0.2)
    assert result["breakdown_m2"]["margins_and_module_fit"] < 100.0


def test_a_building_without_official_figures_is_survivable():
    result = sonnendach_comparison(
        [{"properties": {}}], [face(50.0)], settings(), None, 4
    )
    assert result["official_area_m2"] == 0.0
    assert result["official_annual_energy_kwh"] is None
    assert result["energy_shortfall_percent"] is None


def test_overlapping_shade_and_obstacles_are_counted_once():
    # A chimney standing in shade belongs to one cause, not both. Counting it
    # twice made the parts exceed the roof they were measured on.
    config = settings()
    faces = [
        {
            "local": box(0, 0, 10, 10),
            "assessment": {"eligible": True},
            "objects": [{"kind": "chimney", "polygon": [(0, 0), (5, 0), (5, 5), (0, 5)]}],
            "shaded": box(0, 0, 10, 5),
        }
    ]
    result = sonnendach_comparison([official(100.0, 20000.0)], faces, config, 5000.0, 2)
    parts = result["breakdown_m2"]
    assert parts["roof_obstacles"] == pytest.approx(25.0, abs=0.1)
    assert parts["shaded"] == pytest.approx(25.0, abs=0.1)
    total = sum(parts.values()) + result["fitted_module_area_m2"]
    assert total <= result["measured_surface_m2"] + 0.2


def test_existing_panels_win_over_an_overlapping_obstacle_mark():
    config = settings()
    faces = [
        {
            "local": box(0, 0, 10, 10),
            "assessment": {"eligible": True},
            "objects": [
                {"kind": "existing_pv", "polygon": [(0, 0), (4, 0), (4, 4), (0, 4)]},
                {"kind": "chimney", "polygon": [(0, 0), (4, 0), (4, 4), (0, 4)]},
            ],
            "shaded": Polygon(),
        }
    ]
    result = sonnendach_comparison([official(100.0, 20000.0)], faces, config, 5000.0, 2)
    assert result["breakdown_m2"]["existing_pv"] == pytest.approx(16.0, abs=0.1)
    assert result["breakdown_m2"]["roof_obstacles"] == pytest.approx(0.0, abs=0.1)
