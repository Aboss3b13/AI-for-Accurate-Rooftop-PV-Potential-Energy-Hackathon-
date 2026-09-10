"""Pixel IoU/F1/recall on the held-out, geographically grouped PV tiles.

Ground truth is the converted YOLO polygon mask (small objects and holes were
lost in dataset conversion). Metrics describe PV occupancy, not individual panels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from ultralytics import YOLO


def scores(tp, fp, fn):
    def ratio(a, b):
        return a / b if b else None
    return {"iou": ratio(tp, tp+fp+fn), "f1": ratio(2*tp, 2*tp+fp+fn),
            "precision": ratio(tp, tp+fp), "recall": ratio(tp, tp+fn)}


def main(args):
    root = Path(args.data)
    records = json.loads((root / "split_manifest.json").read_text())
    groups = {}
    for row in records:
        if row["group"] in groups and groups[row["group"]] != row["split"]:
            raise ValueError("Geographic group leakage in split manifest")
        groups[row["group"]] = row["split"]
    test_sources = {Path(r["source"]).stem for r in records if r["split"] == "test"}
    images = sorted((root / "images/test").glob("*.jpg"))
    if not images:
        raise ValueError("No test tiles found")
    model = YOLO(args.model)
    tp = fp = fn = 0
    for i, path in enumerate(images):
        if path.stem.rsplit("_", 2)[0] not in test_sources:
            raise ValueError(f"Test tile not assigned to test manifest: {path.name}")
        image = cv2.imread(str(path))
        h, w = image.shape[:2]
        truth, predicted = np.zeros((h, w), np.uint8), np.zeros((h, w), np.uint8)
        for line in (root / "labels/test" / (path.stem+".txt")).read_text().splitlines():
            values = list(map(float, line.split()))
            if values[0] != 0:
                continue
            points = np.asarray(values[1:]).reshape(-1, 2) * [w, h]
            cv2.fillPoly(truth, [np.rint(points).astype(np.int32)], 1)
        result = model.predict(image, imgsz=640, conf=args.confidence, verbose=False)[0]
        if result.masks is not None:
            for polygon, cls in zip(result.masks.xy, result.boxes.cls.cpu().numpy()):
                if cls == 0:
                    cv2.fillPoly(predicted, [np.rint(polygon).astype(np.int32)], 1)
        tp += int(((truth == 1) & (predicted == 1)).sum())
        fp += int(((truth == 0) & (predicted == 1)).sum())
        fn += int(((truth == 1) & (predicted == 0)).sum())
        if (i+1) % 40 == 0:
            print(f"Evaluated {i+1}/{len(images)} test tiles", flush=True)
    report = {"split": "test", "tiles": len(images), "image_size": 640,
        "confidence_threshold": args.confidence, "geographic_group_overlap": 0,
        "model_sha256": hashlib.sha256(Path(args.model).read_bytes()).hexdigest(),
        "pixel_counts": {"tp": tp, "fp": fp, "fn": fn}, "micro_pixel_metrics": scores(tp, fp, fn),
        "limitations": "Converted polygon masks, not original binary masks. Adjacent kilometre groups may occur across splits. Negative tiles were subsampled during conversion. Does not establish national generalisation or obstacle/capacity accuracy."}
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/yolo")
    parser.add_argument("--model", default="models/rooftop_best.pt")
    parser.add_argument("--confidence", type=float, default=.25)
    parser.add_argument("--output", default="models/pixel-evaluation.json")
    main(parser.parse_args())
