# Train and evaluate SolarFit

The source Swiss dataset provides **binary masks of PV installations**, not chimney/skylight/dormer annotations. Connected components become installation polygons; they do not reliably count individual modules. Never train a four-class detector by pretending the unlabelled obstacles are labelled negatives.

## Prepare the supplied dataset

Download [version 1 from Kaggle](https://www.kaggle.com/datasets/jeanprbt/swiss-solar-panels-segmentation) and extract into `data/raw`. It must contain `images/*.jpg` and matching `labels/*.png`.

```powershell
.venv/Scripts/python.exe training/prepare_dataset.py
```

This converts nonzero binary regions into simplified YOLO segmentation polygons. Components below 12 pixels are dropped; external contours do not represent holes. Source images are grouped by integer kilometre coordinates across capture years before the deterministic split. This reduces nearby-image leakage; broader region holdouts are still needed for robust claims. The converter tiles 1000×1000 imagery into 512-pixel patches and retains 20% of empty patches. It writes a source/split manifest and a single-class YAML. Do not change conversion settings within the same output folder; select a fresh `--output`.

Prepared dataset v1: 758 source images → 915 train / 63 validation / 172 test tiles. Tile counts include the deterministic negative sampling. The small validation geography is a limitation.

## RTX 4070 laptop (8 GB)

```powershell
.venv/Scripts/python.exe training/train_yolo.py --model yolo11s-seg.pt --imgsz 512 --batch 4 --epochs 40 --install
```

Mixed precision is enabled; workers default to 2 for Windows; RAM caching is off. For a faster baseline use `--model yolo11n-seg.pt --batch 8 --epochs 12`. Use `--device cpu` if CUDA is unavailable. Training is never launched by the website. A full training run is separate from fast inference. `TRAIN_MODEL.bat` runs the default training and installs best weights after successful completion.

Replace `models/rooftop_best.pt` with a trusted **YOLO11 segmentation** checkpoint. Supported names are `existing_pv`, `chimney`, `skylight`, `other_obstacle`, and optional `dormer`. Generic COCO checkpoints are deliberately rejected. A changed checkpoint is reloaded on the next analysis. PyTorch weights are executable pickle-based artifacts; load only trusted files.

## Evaluation

```powershell
.venv/Scripts/python.exe training/evaluate.py --split test
```

Results go to `models/evaluation.json`: box and mask precision, recall, mAP50, mAP50–95, plus timing. No capacity accuracy can be inferred from segmentation mAP alone.

If you collect installation ground truth, pass `--capacity-truth capacity-pairs.json` containing records like:

```json
[{"predicted":{"usable_area_m2":43,"panel_count":18,"kwp":8.1},"truth":{"usable_area_m2":40,"panel_count":17,"kwp":7.65}}]
```

The script reports mean absolute usable-area, panel-count and capacity error. No capacity evaluation is fabricated when these measurements are absent.

## Add obstacle coverage

Annotate complete roof scenes for the four classes using instance polygons. Keep geographically separated train, validation and test sets. Use `training/dataset.yaml` as a template and train with `--data path/to/dataset.yaml`. Evaluate each class and use realistic shadowed/low-resolution screenshots before claiming automatic obstacle coverage.
