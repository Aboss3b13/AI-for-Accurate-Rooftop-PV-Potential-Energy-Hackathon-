import json
from pathlib import Path
import pytest
from shapely.geometry import Point, box
from backend.services.map_service import connected_roof_members, feature_planes, merge_building


def plane(identifier, geometry, egid=None):
    return {"id": str(identifier)+":0", "geometry": geometry,
            "properties": {"building_id": identifier, "gwr_egid": egid}}


def test_connected_sections_are_joined_but_detached_and_corner_neighbours_are_not():
    planes = [plane(1, box(0, 0, 10, 10)), plane(2, box(10, 0, 20, 10)),
              plane(3, box(20, 10, 25, 15)), plane(4, box(0, 12, 10, 20))]
    assert [p["id"] for p in connected_roof_members(planes)] == ["1:0", "2:0"]


def test_different_known_buildings_remain_separate_even_with_a_shared_wall():
    planes = [plane(1, box(0, 0, 10, 10), 100), plane(2, box(10, 0, 20, 10), 200)]
    assert len(connected_roof_members(planes)) == 1
    planes[1]["properties"]["gwr_egid"] = 100
    assert len(connected_roof_members(planes)) == 2


def test_suhr_screenshot_roof_includes_both_sections_and_attached_entry_roof():
    from backend.services.map_service import TO_SWISS
    features = json.loads((Path(__file__).parent / "fixtures/suhr_roofs.json").read_text())
    click = Point(*TO_SWISS.transform(8.08003827243237, 47.379927789848225))
    planes = feature_planes(features, click)
    merged = merge_building(planes, click)
    assert set(merged["source_building_ids"]) == {2324632, 778013, 676104, 1410478}
    assert len(merged["member_ids"]) >= 12
    assert merged["geometry"].area == pytest.approx(258.79, abs=.5)
    # Clicking the lower section must select the same complete roof.
    lower = next(p for p in planes if p["properties"]["building_id"] == 778013)
    other_click = lower["geometry"].representative_point()
    again = merge_building(feature_planes(features, other_click), other_click)
    assert set(again["member_ids"]) == set(merged["member_ids"])
