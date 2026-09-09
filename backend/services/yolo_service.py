import hashlib
import os
from pathlib import Path
from threading import Lock
from collections import OrderedDict
import logging
from .sam_service import SamRefiner
from .pv_segmentation import detection_views, merge_detections

CLASSES = {"existing_pv", "chimney", "skylight", "other_obstacle", "dormer"}
ALIASES = {
    "solar_panel": "existing_pv",
    "solar_panels": "existing_pv",
    "pv": "existing_pv",
}


class YoloService:
    def __init__(self):
        self.model = None
        self.signature = None
        self.lock = Lock()
        self.cache = OrderedDict()
        self.device = "cpu"
        self.refiner = SamRefiner()

    def status(self):
        path = Path(os.getenv("MODEL_PATH", "models/rooftop_best.pt"))
        return {
            "available": path.is_file(),
            "model": path.name,
            "device": self.device,
            "classes": list(self.model.names.values())
            if self.model is not None
            else [],
        }

    def detect(self, image):
        path = Path(os.getenv("MODEL_PATH", "models/rooftop_best.pt"))
        if not path.is_file():
            return (
                [],
                [
                    "No trained rooftop model installed. Mark existing PV and obstacles manually."
                ],
                self.status(),
            )
        signature = (str(path.resolve()), path.stat().st_mtime_ns)
        key = hashlib.sha256(str(image.size).encode() + image.tobytes()).hexdigest()
        with self.lock:
            try:
                if self.signature != signature:
                    import torch
                    from ultralytics import YOLO

                    self.model = YOLO(str(path), task="segment")
                    if self.model.task != "segment":
                        raise ValueError("Checkpoint must be a segmentation model")
                    names = {
                        ALIASES.get(str(n), str(n)) for n in self.model.names.values()
                    }
                    if not names or not names.issubset(CLASSES):
                        raise ValueError(
                            "Model classes must be rooftop classes; generic COCO weights cannot detect PV"
                        )
                    requested = os.getenv("DEVICE", "auto")
                    self.device = (
                        ("0" if torch.cuda.is_available() else "cpu")
                        if requested == "auto"
                        else requested
                    )
                    if not torch.cuda.is_available():
                        self.device = "cpu"
                    torch.set_num_threads(min(4, os.cpu_count() or 1))
                    self.signature = signature
                    self.cache.clear()
                if key in self.cache:
                    self.cache.move_to_end(key)
                    return self.cache[key]
                kwargs = dict(
                    imgsz=int(os.getenv("INFERENCE_SIZE", "640")),
                    conf=float(os.getenv("DETECTION_CONFIDENCE", ".25")),
                    verbose=False,
                    retina_masks=True,
                )
                warnings = []
                objects = []
                for view, offset_x, offset_y in detection_views(image):
                    try:
                        result = self.model.predict(view, device=self.device, **kwargs)[0]
                    except RuntimeError:
                        self.device = "cpu"
                        self.model.to("cpu")
                        result = self.model.predict(view, device="cpu", **kwargs)[0]
                        warnings.append("GPU inference failed; CPU fallback used.")
                    if result.masks is None:
                        continue
                    for mask, cls, confidence in zip(
                        result.masks.xy,
                        result.boxes.cls.tolist(),
                        result.boxes.conf.tolist(),
                    ):
                        kind = str(self.model.names[int(cls)])
                        kind = ALIASES.get(kind, kind)
                        if len(mask) >= 3:
                            objects.append(
                                {
                                    "polygon": [[float(x)+offset_x, float(y)+offset_y] for x, y in mask],
                                    "kind": kind,
                                    "confidence": confidence,
                                    "source": "yolo",
                                }
                            )
                objects = merge_detections(objects)
                objects, sam_warning = self.refiner.refine(image, objects)
                if sam_warning:
                    warnings.append(sam_warning)
                names = {ALIASES.get(str(n), str(n)) for n in self.model.names.values()}
                if not {"chimney", "skylight", "other_obstacle"}.issubset(names):
                    warnings.append(
                        "This model detects PV only or has incomplete obstacle coverage. Mark rooftop obstacles manually."
                    )
                if not objects:
                    warnings.append(
                        "No objects detected by this model. This does not confirm the roof is clear."
                    )
                output = (objects, warnings, self.status())
                self.cache[key] = output
                while len(self.cache) > 8:
                    self.cache.popitem(last=False)
                return output
            except Exception as exc:
                logging.exception("Detection failed")
                return (
                    [],
                    [
                        f"AI unavailable: {exc}. Manual geometry analysis remains available."
                    ],
                    dict(self.status(), available=False),
                )


yolo = YoloService()
