from typing import Literal
from pydantic import BaseModel, Field, model_validator
import math

Point = tuple[float, float]


class PanelConfig(BaseModel):
    width: float = Field(1.134, ge=0.5, le=3)
    height: float = Field(1.762, ge=0.5, le=4)
    power: float = Field(450, ge=50, le=1000)
    gap: float = Field(0.02, ge=0, le=0.5)


class MarkedObject(BaseModel):
    source: Literal["manual", "map", "elevation"] = "manual"
    polygon: list[Point] = Field(min_length=3, max_length=200)
    kind: Literal["existing_pv", "chimney", "skylight", "other_obstacle"] = (
        "other_obstacle"
    )
    # Metres the superstructure rises above its roof face, when measured.
    height_m: float | None = Field(None, ge=0, le=50)


class AnalysisSettings(BaseModel):
    roof: list[Point] = Field(min_length=3, max_length=200)
    pixels_per_metre: float | None = Field(None, ge=0.5, le=2000)
    approximate_roof_width: float = Field(12, ge=1, le=200)
    scale_verified: bool = False
    mode: Literal["conservative", "recommended", "maximum"] = "recommended"
    panel: PanelConfig = Field(default_factory=PanelConfig)
    objects: list[MarkedObject] = Field(default_factory=list, max_length=100)
    angle: float = Field(0, ge=-180, le=180)
    annual_specific_yield: float | None = Field(None, ge=0, le=3000)
    edge_margin: float = Field(0.3, ge=0, le=3)
    obstacle_margin: float = Field(0.4, ge=0, le=3)
    pv_margin: float = Field(0.2, ge=0, le=3)
    use_ai: bool = True

    @model_validator(mode="after")
    def finite_coordinates(self):
        for polygon in [self.roof] + [o.polygon for o in self.objects]:
            if any(not math.isfinite(v) for point in polygon for v in point):
                raise ValueError("Coordinates must be finite")
        return self
