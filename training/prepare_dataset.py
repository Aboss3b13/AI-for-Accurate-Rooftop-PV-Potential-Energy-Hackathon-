"""Convert Swiss binary masks to YOLO polygons; split geographic groups before tiling."""

import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import yaml


def polygons(mask):
    contours, _ = cv2.findContours(
        (mask > 0).astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    output = []
    h, w = mask.shape
    for contour in contours:
        if cv2.contourArea(contour) < 12:
            continue
        contour = cv2.approxPolyDP(contour, 0.8, True).reshape(-1, 2)
        if len(contour) >= 3:
            output.append(
                "0 " + " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in contour)
            )
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="data/raw")
    parser.add_argument("--output", default="data/yolo")
    parser.add_argument("--tile-size", type=int, default=512)
    args = parser.parse_args()
    root, target = Path(args.source), Path(args.output)
    counts = {"train": 0, "val": 0, "test": 0}
    records = []
    for split in counts:
        for folder in ["images", "labels"]:
            (target / folder / split).mkdir(parents=True, exist_ok=True)
    for image_path in sorted((root / "images").glob("*")):
        mask_path = root / "labels" / f"{image_path.stem}.png"
        if not mask_path.exists():
            continue
        image = cv2.imread(str(image_path))
        mask = cv2.imread(str(mask_path), cv2.IMREAD_GRAYSCALE)
        if image is None or mask is None or image.shape[:2] != mask.shape:
            raise ValueError(f"Unmatched image/mask: {image_path.name}")
        # Group by integer kilometre coordinates, across capture years.
        coordinates = image_path.stem.rsplit("_", 1)[-1].split("-")
        group = "-".join(str(int(float(c))) for c in coordinates)
        bucket = int(hashlib.sha256(group.encode()).hexdigest()[:8], 16) % 10
        split = "test" if bucket == 0 else "val" if bucket == 1 else "train"
        h, w = mask.shape
        stride = args.tile_size
        for y in range(0, h, stride):
            for x in range(0, w, stride):
                patch = image[y : y + stride, x : x + stride]
                labels = polygons(mask[y : y + stride, x : x + stride])
                name = f"{image_path.stem}_{x}_{y}"
                # Keep 20% of genuinely empty tiles; never split a source across sets.
                if (
                    not labels
                    and int(hashlib.sha256(name.encode()).hexdigest()[:8], 16) % 5
                ):
                    continue
                cv2.imwrite(str(target / "images" / split / f"{name}.jpg"), patch)
                (target / "labels" / split / f"{name}.txt").write_text(
                    "\n".join(labels), encoding="utf-8"
                )
                counts[split] += 1
        records.append({"source": image_path.name, "group": group, "split": split})
    config = {
        "path": str(target.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {0: "existing_pv"},
    }
    (target / "dataset.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (target / "split_manifest.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    print(json.dumps(counts))
    print(target / "dataset.yaml")


if __name__ == "__main__":
    main()
