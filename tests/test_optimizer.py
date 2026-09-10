import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union
from backend.services.panel_optimizer import optimise_panels
from backend.schemas.analysis import PanelConfig, AnalysisSettings
from backend.services.geometry_service import build_usable


def test_rectangular_capacity_is_real_packing():
    panel = PanelConfig(width=1, height=2, gap=0)
    panels, _ = optimise_panels(box(0, 0, 100, 100), 10, panel)
    assert len(panels) == 50


@pytest.mark.parametrize("angle", [0, 17, 45, 90])
def test_every_panel_inside_exclusions_and_no_overlap(angle):
    roof = Polygon([(0, 0), (240, 0), (240, 70), (100, 70), (100, 180), (0, 180)])
    settings = AnalysisSettings(roof=list(roof.exterior.coords), panel=PanelConfig())
    obstacles = [
        {"kind": "chimney", "polygon": [(30, 30), (65, 30), (65, 65), (30, 65)]}
    ]
    usable, _ = build_usable(roof, obstacles, 10, settings)
    panels, _ = optimise_panels(usable, 10, settings.panel, angle)
    assert len(panels) > 0
    polygons = [Polygon(p) for p in panels]
    assert all(usable.buffer(1e-7).covers(p) for p in polygons)
    assert sum(p.area for p in polygons) == pytest.approx(unary_union(polygons).area)


def test_empty_roof_returns_zero():
    panels, _ = optimise_panels(box(0, 0, 1, 1), 10, PanelConfig())
    assert panels == []
