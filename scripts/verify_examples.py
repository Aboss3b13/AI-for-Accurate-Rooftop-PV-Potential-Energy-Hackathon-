"""Exercise the actual HTTP pipeline and save a reproducible result illustration."""

import json
import time
from pathlib import Path
import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
examples = json.loads((ROOT / "frontend/public/examples/manifest.json").read_text())
reports = []
fig, axes = plt.subplots(1, 3, figsize=(15, 5), facecolor="#f5f7f3")
client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=90)
for axis, case in zip(axes, examples):
    image_path = ROOT / "frontend/public" / case["image"].lstrip("/")
    modes = {}
    for mode in ["conservative", "recommended", "maximum"]:
        config = {k: case[k] for k in ["roof", "objects", "pixels_per_metre"]}
        config.update(scale_verified=True, mode=mode)
        start = time.perf_counter()
        response = client.post(
            "/api/analyse",
            files={"image": (image_path.name, image_path.read_bytes(), "image/jpeg")},
            data={"settings": json.dumps(config)},
        )
        response.raise_for_status()
        result = response.json()
        modes[mode] = {
            "statistics": result["statistics"],
            "http_ms": round((time.perf_counter() - start) * 1000, 1),
        }
        assert (
            len(result["proposed_panels"])
            == result["statistics"]["additional_panel_count"]
        )
        if mode == "recommended":
            recommended = result
    axis.imshow(Image.open(image_path))
    axis.add_patch(
        Polygon(
            case["roof"], closed=True, fill=False, edgecolor="#d9ffa0", linewidth=1.5
        )
    )
    for object_ in recommended["existing_pv"]:
        axis.add_patch(
            Polygon(
                object_["polygon"],
                closed=True,
                facecolor="#60c4ff",
                edgecolor="#b5e2ff",
                alpha=0.7,
            )
        )
    for object_ in recommended["obstacles"]:
        axis.add_patch(
            Polygon(
                object_["polygon"],
                closed=True,
                facecolor="#f9a45d",
                edgecolor="#fff0d6",
                alpha=0.8,
            )
        )
    for panel in recommended["proposed_panels"]:
        axis.add_patch(
            Polygon(
                panel,
                closed=True,
                facecolor="#95d964",
                edgecolor="#dbffb2",
                linewidth=0.6,
                alpha=0.8,
            )
        )
    stats = recommended["statistics"]
    axis.set_title(
        case["name"]
        + "\n"
        + f"{stats['additional_panel_count']} additional panels · {stats['additional_kwp']:.2f} kWp",
        fontsize=12,
        color="#244f3d",
        pad=16,
    )
    axis.axis("off")
    reports.append(
        {
            "example": case["name"],
            "modes": modes,
            "model": recommended["model"],
            "confidence": recommended["confidence"],
            "warnings": recommended["warnings"],
        }
    )
fig.suptitle(
    "SolarFit · actual model + geometric packing output", fontsize=19, color="#204f3d"
)
fig.text(
    0.5,
    0.06,
    "Green: proposed modules   |   Blue: detected PV regions   |   Orange: manually marked obstacles\nSWISSIMAGE / swisstopo via Jean Perbet’s Swiss dataset. 2D estimates, not verified installation plans.",
    ha="center",
    fontsize=9,
    color="#657963",
)
fig.subplots_adjust(top=0.75, bottom=0.23, wspace=0.12)
(ROOT / "docs").mkdir(exist_ok=True)
fig.savefig(ROOT / "docs/analysis-preview.png", dpi=140, facecolor=fig.get_facecolor())
(ROOT / "models/benchmark.json").write_text(
    json.dumps(reports, indent=2), encoding="utf-8"
)
print(json.dumps(reports, indent=2))
