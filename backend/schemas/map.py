from pydantic import BaseModel, Field


class MapPoint(BaseModel):
    latitude: float = Field(ge=45.7, le=47.95)
    longitude: float = Field(ge=5.85, le=10.65)


class MapSelection(BaseModel):
    latitude: float = Field(ge=45.7, le=47.95)
    longitude: float = Field(ge=5.85, le=10.65)
    roof_id: str | None = Field(
        default=None, max_length=80, pattern=r"^(?:\d+:\d+|building:\d+)$"
    )
    capture_only: bool = False
    span_m: float = Field(default=64, ge=20, le=150)
    # An outline drawn on the map, used instead of the official roof lookup.
    polygon: list[MapPoint] | None = Field(default=None, min_length=3, max_length=200)
