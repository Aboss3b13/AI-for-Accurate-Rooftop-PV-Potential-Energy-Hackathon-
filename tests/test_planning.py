import pytest
from shapely.geometry import box, Polygon
from backend.schemas.analysis import AnalysisSettings
from backend.services.geometry_service import build_usable
from backend.services.panel_optimizer import optimise_panels
from backend.services.surface_analysis import solar_data
from backend.services.planning_service import planning_constraints


@pytest.mark.parametrize("mode", ["conservative", "recommended", "maximum"])
def test_rwa_clearance_survives_modes_and_packing(mode):
    settings = AnalysisSettings(roof=list(box(0, 0, 20, 20).exterior.coords)[:-1], mode=mode)
    opening = box(8, 8, 10, 10)
    usable, _ = build_usable(box(0, 0, 20, 20), [{"kind": "rwa", "polygon": list(opening.exterior.coords)}], 1, settings)
    panels, _ = optimise_panels(usable, 1, settings.panel, 0)
    assert panels
    assert all(Polygon(p).distance(opening) >= 2 - 1e-8 for p in panels)
    assert planning_constraints(settings)["status"] == "Not certified"


def test_rwa_outside_face_still_excludes_neighbouring_space():
    settings = AnalysisSettings(roof=list(box(0, 0, 10, 10).exterior.coords)[:-1], edge_margin=0)
    usable, _ = build_usable(box(0, 0, 10, 10), [{"kind": "rwa", "polygon": list(box(10.5, 3, 11.5, 4).exterior.coords)}], 1, settings)
    assert not usable.covers(box(9, 3, 10, 4))


def test_performance_ratio_energy_zero_and_override():
    assert solar_data({"mstrahlung": 1000}, performance_ratio=.7)["specific_yield_kwh_kwp"] == 700
    assert solar_data({"mstrahlung": 0}, performance_ratio=.7)["specific_yield_kwh_kwp"] == 0
    result = solar_data({"mstrahlung": 1000}, override=900, performance_ratio=.7)
    assert result["specific_yield_kwh_kwp"] == 900
    assert result["performance_ratio"] is None
