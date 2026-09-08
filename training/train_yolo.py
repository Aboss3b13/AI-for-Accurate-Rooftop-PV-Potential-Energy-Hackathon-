import argparse
import shutil
from pathlib import Path
import torch
from ultralytics import YOLO


def main():
    parser = argparse.ArgumentParser(
        description="Train actual YOLO11 instance segmentation on rooftop masks."
    )
    parser.add_argument("--data", default="data/yolo/dataset.yaml")
    parser.add_argument(
        "--model",
        choices=["yolo11n-seg.pt", "yolo11s-seg.pt"],
        default="yolo11s-seg.pt",
    )
    parser.add_argument("--imgsz", type=int, default=512)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--device", default="0" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--name", default="solarfit")
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument(
        "--install",
        action="store_true",
        help="Copy best checkpoint into models/rooftop_best.pt",
    )
    args = parser.parse_args()
    torch.set_num_threads(4)
    model = YOLO(args.model)
    model.train(
        data=args.data,
        imgsz=args.imgsz,
        epochs=args.epochs,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        amp=True,
        cache=False,
        project=str(Path("runs/segment").resolve()),
        name=args.name,
        seed=42,
        patience=12,
        degrees=30,
        fliplr=0.5,
        flipud=0.5,
        close_mosaic=5,
        plots=True,
    )
    if args.install:
        target = Path("models/rooftop_best.pt")
        target.parent.mkdir(exist_ok=True)
        shutil.copy2(model.trainer.best, target)
        print(f"Installed {target}. Restart or analyse again to reload.")


if __name__ == "__main__":
    main()
