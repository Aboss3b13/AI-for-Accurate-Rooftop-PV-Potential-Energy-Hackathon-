import numpy as np
from fastapi.testclient import TestClient
from shapely.geometry import box, shape
from backend.main import app
from backend.services.roof_plane import RoofPlane
from backend.services.runtime_cache import captures
from backend.services.sunlight_service import analyse_sunlight, instantaneous_shadow, public_sunlight


def test_shadow_direction_and_unknown_coverage():
    roof = box(197, 197, 203, 203)
    plane = RoofPlane.from_slopes(200, 200, 10, source="swisssurface3d")
    heights = np.zeros((400, 400))
    heights[180:220, 210:215] = 40  # wall east of roof
    profile = analyse_sunlight(roof, plane, dict(heights=heights, minx=0, maxy=400, step=1), 47, 8)
    local = plane.local_geometry(roof)
    east, _ = instantaneous_shadow(profile, local, plane.normal, np.array([.8, 0, .6]))
    west, _ = instantaneous_shadow(profile, local, plane.normal, np.array([-.8, 0, .6]))
    assert east.area == local.area
    assert west.is_empty
    night, _ = instantaneous_shadow(profile, local, plane.normal, np.array([0., 0., -1.]))
    assert night.equals(local)
    profile["direction_coverage"][:] = 0
    shaded, unknown = instantaneous_shadow(profile, local, plane.normal, np.array([.8, 0, .6]))
    assert shaded.is_empty and unknown.equals(local)
    assert "horizons" not in public_sunlight(profile)


def test_preview_endpoint_validation_fallback_and_night():
    plane = RoofPlane.from_slopes(5, 5)
    captures.put("shadow-test", {"latitude": 47, "longitude": 8,
        "grid": {"bbox": [0, 0, 10, 10], "pixels_per_metre": 10, "width": 100, "height": 100},
        "faces": [{"geometry": box(0, 0, 10, 10), "plane": plane}]})
    client = TestClient(app)
    response = client.get("/api/map/shadow/shadow-test")
    assert response.status_code == 200
    assert shape(response.json()["unknown"]).area == 10000
    assert shape(response.json()["shade"]).is_empty
    assert client.get("/api/map/shadow/missing").status_code == 410
    assert client.get("/api/map/shadow/shadow-test?month=13").status_code == 422
    assert client.get("/api/map/shadow/shadow-test?hour_utc=nan").status_code == 422
