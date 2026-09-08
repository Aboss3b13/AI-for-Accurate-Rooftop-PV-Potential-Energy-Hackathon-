import os
import logging


class SamRefiner:
    def __init__(self):
        self.model = None

    def refine(self, image, detections):
        if os.getenv("USE_SAM_REFINEMENT", "false").lower() != "true" or not detections:
            return detections, None
        try:
            from ultralytics import SAM

            path = os.getenv("SAM_MODEL_PATH", "models/sam2_t.pt")
            if not os.path.isfile(path):
                raise FileNotFoundError("SAM checkpoint is missing")
            if self.model is None:
                self.model = SAM(path)
            boxes = []
            for item in detections:
                xs, ys = zip(*item["polygon"])
                boxes.append([min(xs), min(ys), max(xs), max(ys)])
            result = self.model(image, bboxes=boxes, verbose=False)[0]
            if result.masks is not None and len(result.masks.xy) == len(detections):
                detections = [
                    dict(item, polygon=mask.tolist())
                    for item, mask in zip(detections, result.masks.xy)
                    if len(mask) >= 3
                ]
            return detections, None
        except Exception as exc:
            logging.warning("SAM refinement skipped: %s", exc)
            return detections, "SAM refinement unavailable; original YOLO masks used."
