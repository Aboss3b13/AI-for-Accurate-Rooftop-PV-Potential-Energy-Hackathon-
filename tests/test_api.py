import io
import json
from PIL import Image
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


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
