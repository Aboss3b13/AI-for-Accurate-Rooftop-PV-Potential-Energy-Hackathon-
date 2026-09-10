import io
import json
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_unexpected_prepare_error_is_json_and_logged(monkeypatch, caplog):
    import backend.map_routes as routes
    async def broken(_):
        raise RuntimeError("diagnostic failure")
    monkeypatch.setattr(routes, "prepare_capture", broken)
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/map/prepare", json={"latitude": 47, "longitude": 8})
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert "server log" in response.json()["detail"]
    assert "diagnostic failure" in caplog.text


def test_health_identifies_running_backend_and_source_changes(monkeypatch):
    import backend.main as main
    health = client.get("/api/health").json()
    assert health["backend_revision"] == main.LOADED_REVISION
    assert "shadow_preview" in health["capabilities"]
    monkeypatch.setattr(main, "source_revision", lambda: "changed")
    assert client.get("/api/health").json()["restart_required"]


def image_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (200, 150), "gray").save(stream, format="PNG")
    return stream.getvalue()


def test_upload_to_capacity():
    settings = {
        "roof": [[10, 10], [190, 10], [190, 140], [10, 140]],
        "pixels_per_metre": 10,
        "scale_verified": True,
        "use_ai": False,
    }
    response = client.post(
        "/api/analyse",
        files={"image": ("roof.png", image_bytes(), "image/png")},
        data={"settings": json.dumps(settings)},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["statistics"]["additional_panel_count"] > 0
    assert (
        result["statistics"]["additional_kwp"] == len(result["proposed_panels"]) * 0.45
    )
    assert result["confidence"]["mean_detection"] is None


def test_bad_geometry_and_corrupt_upload():
    response = client.post(
        "/api/analyse",
        files={"image": ("roof.png", b"bad", "image/png")},
        data={"settings": json.dumps({"roof": [[0, 0], [100, 0], [100, 100]]})},
    )
    assert response.status_code == 422
    response = client.post(
        "/api/analyse",
        files={"image": ("roof.png", image_bytes(), "image/png")},
        data={
            "settings": json.dumps(
                {"roof": [[0, 0], [300, 0], [100, 100]], "use_ai": False}
            )
        },
    )
    assert response.status_code == 422
