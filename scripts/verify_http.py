"""Verify the server the browser actually uses, including the shadow slider."""
import base64
import json
from pathlib import Path
import httpx
from scripts.benchmark_roofs import CASES


def main():
    results = []
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as client:
        health = client.get("/api/health").raise_for_status().json()
        assert "shadow_preview" in health["capabilities"] and not health["restart_required"]
        assert client.get("/").status_code == 200
        for name, lat, lon in CASES:
            capture = client.post("/api/map/prepare", json={"latitude": lat, "longitude": lon}).raise_for_status().json()
            settings = {k: capture[k] for k in ("capture_id", "roof", "objects", "pixels_per_metre", "angle")}
            settings["scale_verified"] = True
            result = client.post("/api/analyse",
                files={"image": ("roof.jpg", base64.b64decode(capture["image_base64"]), "image/jpeg")},
                data={"settings": json.dumps(settings)}).raise_for_status().json()
            previews = 0
            for month in (1, 6, 12):
                for hour in (0, .5, 7, 12, 23.5):
                    preview = client.get(f"/api/map/shadow/{capture['capture_id']}",
                        params={"month": month, "hour_utc": hour}).raise_for_status().json()
                    assert "shade" in preview and "unknown" in preview
                    previews += 1
            row = {"case": name, "panels": result["statistics"]["additional_panel_count"], "successful_shadow_requests": previews}
            results.append(row)
            print(json.dumps(row), flush=True)
        assert client.get("/api/map/shadow/expired").status_code == 410
        response = client.post("/api/map/prepare", json={"latitude": 0, "longitude": 0})
        assert response.status_code == 422 and "detail" in response.json()
    Path(".cache/http-verification.json").write_text(json.dumps({"health": health, "results": results}, indent=2), encoding="utf-8")
    print("Live HTTP preparation, analysis, 45 shadow requests and error responses passed.")


if __name__ == "__main__":
    main()
