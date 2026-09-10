"""Compare frozen checkpoints on the same spatially separated segmentation split."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
import torch
from ultralytics import YOLO
from training.evaluate_pixels import scores


def evaluate(model_path, root, split, confidence=.25):
    root = Path(root)
    model = YOLO(str(model_path))
    torch.set_num_threads(4)
    totals = np.zeros(3, dtype=np.int64)
    records = []
    for path in sorted((root / "images" / split).glob("*.jpg")):
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        truth = np.zeros((h, w), np.uint8)
        predicted = np.zeros_like(truth)
        for line in (root / "labels" / split / (path.stem + ".txt")).read_text().splitlines():
            values = list(map(float, line.split()))
            points = np.asarray(values[1:]).reshape(-1, 2) * [w, h]
            cv2.fillPoly(truth, [np.rint(points).astype(np.int32)], 1)
        result = model.predict(image, imgsz=640, conf=confidence, retina_masks=True, verbose=False, device=0 if torch.cuda.is_available() else "cpu")[0]
        if result.masks is not None:
            for polygon in result.masks.xy:
                cv2.fillPoly(predicted, [np.rint(polygon).astype(np.int32)], 1)
        counts = [int(((truth == 1) & (predicted == 1)).sum()),
                  int(((truth == 0) & (predicted == 1)).sum()),
                  int(((truth == 1) & (predicted == 0)).sum())]
        totals += counts
        records.append({"image": path.name, **scores(*counts), "counts": counts})
    if not records:
        raise ValueError("Evaluation split has no images")
    return {"model": str(model_path), "sha256": hashlib.sha256(Path(model_path).read_bytes()).hexdigest(),
        "split": split, "tiles": len(records), "confidence": confidence, "imgsz": 640,
        "retina_masks": True, "pixel_counts": dict(zip(["tp","fp","fn"], map(int, totals))),
        "metrics": scores(*map(int, totals)), "images": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", required=True)
    parser.add_argument("--data", default="data/yolo")
    parser.add_argument("--split", choices=["val", "test"], default="val")
    parser.add_argument("--confidence", type=float, default=.25)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    reports = [evaluate(p, args.data, args.split, args.confidence) for p in args.models]
    Path(args.output).write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print(json.dumps([{k:v for k,v in report.items() if k != "images"} for report in reports], indent=2))
