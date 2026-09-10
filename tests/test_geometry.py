import pytest
from shapely.geometry import box
from backend.services.geometry_service import polygon_from_points, build_usable
from backend.schemas.analysis import AnalysisSettings
from backend.services.energy_service import capacity
from backend.services.confidence_service import summarise_confidence


def test_crossed_roof_rejected():
    with pytest.raises(ValueError):
        polygon_from_points([(0, 0), (100, 100), (0, 100), (100, 0)], strict=True)


def test_margins_modes_and_holes():
    roof = box(0, 0, 100, 100)
    settings = AnalysisSettings(roof=list(roof.exterior.coords))
    objects = [
        {"kind": "existing_pv", "polygon": [(30, 30), (50, 30), (50, 50), (30, 50)]}
    ]
    areas = []
    for mode in ["conservative", "recommended", "maximum"]:
        settings.mode = mode
        usable, excluded = build_usable(roof, objects, 10, settings)
        assert usable.area + excluded.area == pytest.approx(roof.area)
        assert usable.intersection(box(30, 30, 50, 50)).area == 0
        areas.append(usable.area)
    assert areas[0] < areas[1] < areas[2]


def test_no_invented_confidence_or_energy():
    assert summarise_confidence([])["mean_detection"] is None
    assert capacity(20, 450) == {"additional_kwp": 9.0, "annual_energy_kwh": None}
    assert capacity(20, 450, 1000)["annual_energy_kwh"] == 9000
