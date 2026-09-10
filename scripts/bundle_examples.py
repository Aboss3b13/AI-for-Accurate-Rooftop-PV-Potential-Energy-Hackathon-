"""Reproduce the bundled crops from the attributed Swiss aerial dataset."""

import json
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
raw = ROOT / "data/raw/images"
out = ROOT / "frontend/public/examples"
out.mkdir(parents=True, exist_ok=True)
cases = [
    {
        "name": "Open roof plane",
        "source": "swissimage-dop10_2021_2575.0-1206.0.jpg",
        "crop": (390, 420, 840, 600),
        "roof": [(439, 466), (740, 466), (784, 529), (430, 527)],
        "objects": [],
    },
    {
        "name": "Existing solar",
        "source": "swissimage-dop10_2021_2708.0-1095.4.jpg",
        "crop": (205, 45, 435, 260),
        "roof": [(237, 91), (377, 201), (250, 214)],
        "objects": [],
    },
    {
        "name": "Rooftop obstacles",
        "source": "swissimage-dop10_2021_2575.0-1206.0.jpg",
        "crop": (20, 375, 245, 550),
        "roof": [(50, 411), (189, 409), (188, 460), (98, 460)],
        "objects": [
            {
                "kind": "chimney",
                "polygon": [(119, 443), (128, 443), (128, 455), (119, 455)],
            },
            {
                "kind": "skylight",
                "polygon": [(150, 442), (163, 442), (163, 456), (150, 456)],
            },
        ],
    },
]
manifest = []
for i, case in enumerate(cases):
    source = raw / case["source"]
    x, y, _, _ = case["crop"]
    Image.open(source).crop(case["crop"]).save(out / f"case-{i + 1}.jpg", quality=95)
    shift = lambda points: [[a - x, b - y] for a, b in points]
    manifest.append(
        {
            "name": case["name"],
            "image": f"/examples/case-{i + 1}.jpg",
            "roof": shift(case["roof"]),
            "objects": [dict(o, polygon=shift(o["polygon"])) for o in case["objects"]],
            "pixels_per_metre": 10,
            "source": case["source"],
            "note": "SWISSIMAGE aerial crop · 10 cm/pixel. Roof outline is manually prepared; obstacle marks, when present, are manual. PV detections come from the installed model. 2D roof-plane estimate.",
        }
    )
(out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
print(f"Bundled {len(manifest)} aerial examples.")
