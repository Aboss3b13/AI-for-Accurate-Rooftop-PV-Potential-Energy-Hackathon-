# SolarFit Swiss PV baseline

**Model:** YOLO11n-seg, approximately 2.84 million parameters. Checkpoint: `rooftop_best.pt` (~6 MB). Trained locally on 8 September 2026 with an NVIDIA GeForce RTX 4070 Laptop GPU (8 GB VRAM), PyTorch 2.10.0+cu128 and Ultralytics 8.4.144.

## Intended use and scope

Hackathon demonstration and research on segmenting existing PV **installation regions** in top-down Swiss aerial imagery. This model has one class: `0: existing_pv`. It does **not** detect chimneys, skylights, dormers, roof boundaries or general obstacles. Supply those as manual exclusions in SolarFit until a fully annotated model is available. A PV region can contain many modules.

## Data and training

- Source: Jean Perbet’s [Swiss solar panels segmentation dataset](https://www.kaggle.com/datasets/jeanprbt/swiss-solar-panels-segmentation), version 1, Kaggle-listed CC0. Imagery: SWISSIMAGE / swisstopo, 10 cm/pixel.
- 758 source image/mask pairs. Grouped by integer kilometre location across capture years before deterministic splitting. See `split-manifest.json` for each source assignment.
- 579 train / 59 validation / 120 test source images; conversion yields 915 / 63 / 172 tiles respectively after 512-pixel tiling and negative sampling.
- Binary masks converted to external connected-component polygons; components under 12 pixels dropped. Holes are not represented by the conversion. Region boundaries at tile edges may be truncated.
- Initial weights: Ultralytics `yolo11n-seg.pt`. Trained 12 epochs, image size 512, batch 8, AMP, 2 data-loader workers, seed 42, rotations ±30°, horizontal/vertical flips, default YOLO augmentation and optimiser. Best validation checkpoint installed.
- Training time recorded in history: about 293 seconds, excluding environment downloads, initialisation and final evaluation. Training allocated approximately 1.12 GB GPU memory in the progress report; total desktop/GPU usage is higher.

Reproduce with `training/prepare_dataset.py` then `training/train_yolo.py --model yolo11n-seg.pt --imgsz 512 --batch 8 --epochs 12 --name solarfit_baseline --install`. Hardware/library differences may change results.

## Held-out test evaluation

172 test tiles, evaluated at 512 px, batch 4, on the RTX 4070. Exact values are in `evaluation.json`.

| Metric | Boxes | Segmentation masks |
|---|---:|---:|
| Precision | 0.653 | 0.659 |
| Recall | 0.728 | 0.731 |
| mAP50 | 0.730 | **0.736** |
| mAP50–95 | 0.543 | **0.528** |

Reported batched inference: **5.82 ms/image**, excluding preprocessing and postprocessing. This is not end-to-end upload latency. The application runs at 640 px by default and includes geometry/packing; measured HTTP timings for actual examples are in `benchmark.json`. First-use model/CUDA loading is materially slower than subsequent requests; layout-only recalculations reuse detections.

Validation mask mAP50 was approximately 0.710 and mask mAP50–95 0.487. The best checkpoint was selected on validation, not test performance. Test data was used for this final evaluation only. Example selection was for UI demonstration and is not independent accuracy evidence.

## Limitations

Additional pixel occupancy evaluation at the application's 640 px input and
0.25 confidence threshold is recorded in [pixel-evaluation.json](pixel-evaluation.json):
IoU 0.560, F1 0.718, precision 0.615, recall 0.861 across 172 test tiles.
These are micro-aggregated pixel metrics against converted polygon masks, which
omit holes and tiny components. They differ from the instance metrics above.
Kilometre groups have zero split overlap; adjacent groups can still cross splits.
Reproduce with `python -m training.evaluate_pixels`.

Precision and recall show that both missed PV and false positives remain. The dataset is geographically narrow; the grouping reduces direct tile leakage but does not establish robustness across countries, sensors, seasons or screenshot styles. Heavy shadows, small panels, perspective, map overlays and screenshot rescaling can reduce performance. Test mask performance does not prove correct additional-panel counts.

No obstacle, roof-plane, usable-area or installable-capacity ground truth was supplied. **Capacity MAE and obstacle accuracy are unavailable**, not zero. Confidence values are uncalibrated detector scores. Roof structural suitability, pitch, access and regulatory clearances require separate review.

Ultralytics model/software licensing applies (AGPL-3.0 or commercial terms). Load only trusted checkpoint files.
