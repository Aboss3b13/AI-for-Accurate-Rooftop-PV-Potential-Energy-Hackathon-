from typing import Protocol
from PIL.Image import Image


class RoofDetector(Protocol):
    """Future roof segmentation providers return original-image pixel coordinates."""

    def detect(self, image: Image) -> list[tuple[float, float]] | None: ...
