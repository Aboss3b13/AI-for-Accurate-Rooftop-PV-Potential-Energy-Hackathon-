import asyncio
import io
import json

import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from shapely.geometry import Point, Polygon, box, mapping as mapping_of

from backend.main import app
from backend.schemas.map import MapSelection
from backend.services import map_service
from backend.services.map_service import (
    capture_grid,
    pixel_ring,
    feature_planes,
    alignment,
)


def test_metric_capture_scale_and_pixel_origin():
    roof = box(2640300, 1232900, 2640320, 1232910)
    grid = capture_grid(roof, roof.centroid)
    minx, miny, maxx, maxy = grid["bbox"]
    assert (maxx - minx) * grid["pixels_per_metre"] == pytest.approx(grid["width"])
    assert (maxy - miny) * grid["pixels_per_metre"] == pytest.approx(grid["height"])
    pixels = pixel_ring(roof.exterior.coords, grid)
    assert Polygon(pixels).area / grid["pixels_per_metre"] ** 2 == pytest.approx(
        roof.area
    )
    assert pixel_ring([(minx, maxy), (maxx, maxy), (maxx, miny)], grid) == [
        [0, 0],
        [grid["width"], 0],
        [grid["width"], grid["height"]],
    ]


def test_large_roof_downsamples_without_changing_scale():
    roof = box(2600000, 1200000, 2600250, 1200100)
    grid = capture_grid(roof, roof.centroid)
    assert grid["width"] <= 1280
    assert grid["pixels_per_metre"] < 10
    assert Polygon(pixel_ring(roof.exterior.coords, grid)).area / grid[
        "pixels_per_metre"
    ] ** 2 == pytest.approx(roof.area, rel=1e-5)


def test_click_selects_correct_component_preserving_holes():
    from shapely.geometry import MultiPolygon, mapping

    first = Polygon(
        [(0, 0), (20, 0), (20, 20), (0, 20)], holes=[[(5, 5), (8, 5), (8, 8), (5, 8)]]
    )
    feature = {
        "featureId": 42,
        "geometry": mapping(MultiPolygon([first, box(30, 0, 40, 10)])),
        "properties": {"neigung": 30},
    }
    planes = feature_planes([feature, feature], Point(35, 5))
    assert len(planes) == 2
    assert planes[0]["id"] == "42:1"
    assert len(planes[1]["geometry"].interiors) == 1
    assert abs(alignment(box(0, 0, 20, 10))) == pytest.approx(0)


def test_prepare_uses_authoritative_geometry_and_wms_grid(monkeypatch):
    x, y = map_service.TO_SWISS.transform(7.97, 47.245)
    feature = {
        "featureId": 123,
        "geometry": {
            "type": "Polygon",
            "coordinates": [
                [
                    [x - 5, y - 5],
                    [x + 5, y - 5],
                    [x + 5, y + 5],
                    [x - 5, y + 5],
                    [x - 5, y - 5],
                ]
            ],
        },
        "properties": {"building_id": 9, "neigung": 20},
    }
    calls = []

    def handler(request):
        calls.append(request)
        if request.url.host == "wms.geo.admin.ch":
            q = request.url.params
            assert q["CRS"] == "EPSG:2056"
            stream = io.BytesIO()
            Image.new("RGB", (int(q["WIDTH"]), int(q["HEIGHT"])), "gray").save(
                stream, format="JPEG"
            )
            return httpx.Response(
                200, content=stream.getvalue(), headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(200, json={"results": [feature]})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        map_service.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    result = asyncio.run(
        map_service.prepare_capture(MapSelection(latitude=47.245, longitude=7.97))
    )
    assert result["selected_roof_id"] == "123:0"
    assert result["pixels_per_metre"] == 10
    assert Polygon(result["roof"]).area / 100 == pytest.approx(100)
    paths = [r.url.path for r in calls]
    assert paths.count("/rest/services/ech/MapServer/identify") == 1
    assert paths.count("/rest/services/ech/MapServer/find") == 1
    assert paths.count("/") == 1  # the WMS image
    # The height model is consulted for chimneys, and its absence is survivable.
    assert any("swisssurface3d" in str(r.url) for r in calls)
    assert any("could not be measured" in w for w in result["warnings"])
    assert result["provenance"]["pitch_deg"] == 20


def test_map_routes_reject_outside_coverage_and_report_failure(monkeypatch):
    from backend import map_routes

    client = TestClient(app)
    assert (
        client.post(
            "/api/map/prepare", json={"latitude": 0, "longitude": 0}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/map/prepare",
            json={"latitude": 47, "longitude": 8, "roof_id": "http://bad"},
        ).status_code
        == 422
    )

    async def unavailable(_):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(map_routes, "prepare_capture", unavailable)
    response = client.post("/api/map/prepare", json={"latitude": 47, "longitude": 8})
    assert response.status_code == 503
    assert "image upload" in response.json()["detail"]


def test_missing_roof_returns_calibrated_manual_capture(monkeypatch):
    def handler(request):
        if request.url.host == "wms.geo.admin.ch":
            q = request.url.params
            stream = io.BytesIO()
            Image.new("RGB", (int(q["WIDTH"]), int(q["HEIGHT"]))).save(
                stream, format="JPEG"
            )
            return httpx.Response(
                200, content=stream.getvalue(), headers={"content-type": "image/jpeg"}
            )
        return httpx.Response(200, json={"results": []})

    original = httpx.AsyncClient
    monkeypatch.setattr(
        map_service.httpx,
        "AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    result = asyncio.run(
        map_service.prepare_capture(MapSelection(latitude=47, longitude=8))
    )
    assert result["roof"] == []
    assert result["pixels_per_metre"] == 10
    assert result["warnings"]
    assert result["provenance"]["roof_source"] is None


def _plane(geometry, identifier, building):
    return {
        "id": identifier,
        "geometry": geometry,
        "properties": {"building_id": building, "neigung": 30, "ausrichtung": 10},
        "contains_click": False,
        "distance": 0.0,
    }


def test_merge_building_unions_every_plane_of_the_clicked_building():
    # Two facets of one roof, plus a neighbouring building that must not merge in.
    left = box(2640300, 1232900, 2640310, 1232910)
    right = box(2640310, 1232900, 2640320, 1232910)
    neighbour = box(2640400, 1232900, 2640410, 1232910)
    planes = [
        _plane(left, "1:0", 7),
        _plane(right, "1:1", 7),
        _plane(neighbour, "2:0", 9),
    ]
    merged = map_service.merge_building(planes, Point(2640305, 1232905))
    assert merged["id"] == "building:7"
    assert merged["merged_planes"] == 2
    assert merged["geometry"].area == pytest.approx(left.area + right.area)
    # Pitch and azimuth describe one facet, so they must not survive the merge.
    assert merged["properties"]["neigung"] is None
    assert merged["properties"]["ausrichtung"] is None


def test_merge_building_keeps_a_lone_plane_untouched():
    only = _plane(box(2640300, 1232900, 2640310, 1232910), "1:0", 7)
    merged = map_service.merge_building([only], Point(2640305, 1232905))
    assert merged is only


def test_merge_building_prefers_the_component_under_the_click():
    near = box(2640300, 1232900, 2640310, 1232910)
    far = box(2640380, 1232900, 2640420, 1232940)
    planes = [_plane(near, "1:0", 7), _plane(far, "1:1", 7)]
    merged = map_service.merge_building(planes, Point(2640305, 1232905))
    # Detached components cannot form one outline; the clicked one wins over the larger.
    assert merged["geometry"].area == pytest.approx(near.area)


def test_small_facets_survive_for_merging_but_are_not_click_targets():
    tiny = box(2640300, 1232900, 2640300.8, 1232900.8)
    big = box(2640301, 1232900, 2640311, 1232910)
    features = [
        {"featureId": 1, "geometry": json.loads(json.dumps(mapping_of(tiny)))},
        {"featureId": 2, "geometry": json.loads(json.dumps(mapping_of(big)))},
    ]
    planes = feature_planes(features, Point(2640305, 1232905))
    assert len(planes) == 2
    assert min(p["geometry"].area for p in planes) < map_service.MIN_CANDIDATE_AREA_M2
