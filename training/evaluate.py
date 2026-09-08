import argparse
import json
from pathlib import Path
import torch
from ultralytics import YOLO


def capacity_metrics(rows):
    keys = ["usable_area_m2", "panel_count", "kwp"]
    return (
        {
            key + "_mae": sum(abs(r["predicted"][key] - r["truth"][key]) for r in rows)
            / len(rows)
            for key in keys
        }
        if rows
        else {}
    )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--model", default="models/rooftop_best.pt")
    p.add_argument("--data", default="data/yolo/dataset.yaml")
    p.add_argument("--split", choices=["val", "test"], default="test")
    p.add_argument(
        "--capacity-truth",
        help="JSON list of paired predicted/truth usable_area_m2, panel_count, kwp",
    )
    p.add_argument("--output", default="models/evaluation.json")
    args = p.parse_args()
    torch.set_num_threads(4)
    result = YOLO(args.model).val(
        data=args.data,
        split=args.split,
        imgsz=512,
        batch=4,
        device=0 if torch.cuda.is_available() else "cpu",
        workers=0,
        plots=True,
        project=str(Path("runs/segment").resolve()),
        name="evaluation",
    )
    report = {
        "split": args.split,
        "metrics": result.results_dict,
        "speed_ms": result.speed,
        "capacity_metrics": capacity_metrics(
            json.loads(Path(args.capacity_truth).read_text())
        )
        if args.capacity_truth
        else None,
        "limitations": "PV regions only. No obstacle or installation ground truth supplied; capacity accuracy is not established.",
    }
    Path(args.output).write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
