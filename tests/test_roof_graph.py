"""Which faces belong to the clicked building, and why.

Sonnendach's building_id groups records, not structures. These cover the cases
that distinguish a physically attached roof from one that merely shares an id.
"""

import numpy as np
import pytest
from shapely.geometry import Point, box

from backend.services import map_service
from backend.services.roof_graph import (
    MIN_SHARED_EDGE_M,
    overview,
    rejected_summary,
    select_connected,
)


def face(name, geometry, building=7, egid=None, click=False):
    properties = {"building_id": building}
    if egid is not None:
        properties["gwr_egid"] = egid
    return {"id": name, "geometry": geometry, "properties": properties,
            "contains_click": click, "distance": 0.0}


def ids(planes):
    return sorted(p["id"] for p in planes)


# --- 1-3: the shapes the app is expected to handle every day ----------------

def test_a_single_flat_roof_selects_itself():
    only = face("a", box(0, 0, 12, 8), click=True)
    accepted, decisions = select_connected([only])
    assert ids(accepted) == ["a"]
    assert decisions[0]["reason"] == "contains the click"


def test_two_pitches_of_one_gable_stay_together():
    north = face("n", box(0, 0, 12, 5), click=True)
    south = face("s", box(0, 5, 12, 10))
    assert ids(select_connected([north, south])[0]) == ["n", "s"]


def test_a_multi_face_roof_is_traversed_end_to_end():
    faces = [face("a", box(0, 0, 6, 6)), face("b", box(6, 0, 12, 6), click=True),
             face("c", box(12, 0, 18, 6)), face("d", box(18, 0, 24, 6))]
    assert ids(select_connected(faces)[0]) == ["a", "b", "c", "d"]


# --- 4: the regression this module exists for -------------------------------

def test_a_disconnected_polygon_sharing_the_building_id_is_rejected():
    """The reported bug: one building_id, two unconnected roofs.

    Seeding the selection from every face sharing the id put the far polygon in
    before any geometry was consulted, and a loop that only adds could never
    remove it.
    """
    faces = [face("a", box(0, 0, 10, 6)), face("b", box(10, 0, 20, 6), click=True),
             face("c", box(20, 0, 30, 6)), face("d", box(30, 0, 40, 6)),
             face("x", box(200, 200, 210, 206))]
    accepted, decisions = select_connected(faces)
    assert ids(accepted) == ["a", "b", "c", "d"]
    refused = next(d for d in decisions if d["id"] == "x")
    assert refused["accepted"] is False
    assert "no physical connection" in refused["reason"]
    # Same record, so the summary must say a same-id polygon was dropped.
    assert rejected_summary(decisions)["rejected_sharing_building_id"] == 1


def test_the_whole_pipeline_refuses_the_disconnected_polygon():
    faces = [face("b", box(2640300, 1232900, 2640320, 1232920), click=True),
             face("x", box(2640500, 1232900, 2640520, 1232920))]
    merged = map_service.merge_building(faces, Point(2640310, 1232910))
    assert merged["member_ids"] == ["b"]
    assert merged["selection_summary"]["rejected_sharing_building_id"] == 1


# --- 5-6: attachment versus mere proximity ----------------------------------

def test_a_physically_attached_extension_is_kept():
    main = face("main", box(0, 0, 20, 12), click=True)
    garage = face("garage", box(20, 2, 28, 9))   # shares a 7 m edge
    accepted, _ = select_connected([main, garage])
    assert ids(accepted) == ["garage", "main"]


def test_a_neighbour_across_a_gap_is_refused():
    main = face("main", box(0, 0, 20, 12), click=True)
    neighbour = face("next", box(24, 0, 40, 12))
    assert ids(select_connected([main, neighbour])[0]) == ["main"]


def test_a_corner_touch_is_not_an_attachment():
    main = face("main", box(0, 0, 10, 10), click=True)
    corner = face("corner", box(10, 10, 20, 20))
    assert ids(select_connected([main, corner])[0]) == ["main"]


def test_a_shorter_edge_than_the_minimum_is_refused():
    main = face("main", box(0, 0, 10, 10), click=True)
    sliver = face("sliver", box(10, 0, 14, MIN_SHARED_EDGE_M / 3))
    assert ids(select_connected([main, sliver])[0]) == ["main"]


def test_a_different_egid_is_not_absorbed():
    main = face("main", box(0, 0, 10, 10), egid=111, click=True)
    other = face("other", box(10, 0, 20, 10), egid=222)
    accepted, decisions = select_connected([main, other])
    assert ids(accepted) == ["main"]
    assert "EGID 222" in next(d for d in decisions if d["id"] == "other")["reason"]


# --- measured elevation as the second opinion -------------------------------

def test_measured_surface_can_veto_a_touching_pair():
    main = face("main", box(0, 0, 10, 10), click=True)
    over_a_gap = face("far", box(10, 0, 20, 10))
    # Geometry alone joins them: they share a 10 m edge on paper.
    assert ids(select_connected([main, over_a_gap])[0]) == ["far", "main"]
    # Measured elevation says the strip between them is not building.
    accepted, decisions = select_connected([main, over_a_gap], bridge=lambda a, b: False)
    assert ids(accepted) == ["main"]
    assert "no building surface bridges" in next(
        d for d in decisions if d["id"] == "far")["reason"]


def test_measured_surface_confirms_a_real_join():
    main = face("main", box(0, 0, 10, 10), click=True)
    attached = face("attached", box(10, 0, 20, 10))
    accepted, _ = select_connected([main, attached], bridge=lambda a, b: True)
    assert ids(accepted) == ["attached", "main"]


def test_without_terrain_the_bridge_is_not_guessed():
    from backend.services.elevation_service import bridge_tester
    assert bridge_tester(np.zeros((4, 4)), None, 0.0, 0.0) is None


# --- traversal order and overview -------------------------------------------

def test_the_click_decides_the_starting_face():
    left = face("left", box(0, 0, 10, 10))
    right = face("right", box(10, 0, 20, 10), click=True)
    accepted, decisions = select_connected([left, right])
    assert next(d for d in decisions if d["id"] == "right")["reason"] == "contains the click"
    assert ids(accepted) == ["left", "right"]


def test_the_overview_outline_covers_the_accepted_faces_only():
    faces = [face("a", box(0, 0, 10, 6), click=True), face("b", box(10, 0, 20, 6)),
             face("x", box(100, 100, 110, 106))]
    accepted, _ = select_connected(faces)
    shape = overview(accepted)
    assert shape.area == pytest.approx(120.0)
    assert not shape.intersects(box(100, 100, 110, 106))


def test_every_candidate_is_accounted_for():
    faces = [face("a", box(0, 0, 10, 6), click=True), face("x", box(50, 50, 60, 56))]
    _, decisions = select_connected(faces)
    assert {d["id"] for d in decisions} == {"a", "x"}
    assert all(d["reason"] for d in decisions)
    assert all("building_id" in d for d in decisions)


def test_no_planes_is_survivable():
    assert select_connected([]) == ([], [])
    assert overview([]) is None
