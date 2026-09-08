from shapely.geometry import Polygon, mapping
from shapely.ops import unary_union
from shapely import make_valid

MODE_FACTORS = {"conservative": 1.5, "recommended": 1.0, "maximum": 0.5}


def polygon_from_points(points, *, strict=False):
    polygon = Polygon(points)
    if strict and (not polygon.is_valid or polygon.area < 4):
        raise ValueError(
            "Draw a non-crossing roof polygon with at least three distinct points."
        )
    return make_valid(polygon)


def build_usable(roof, detections, ppm, settings):
    factor = MODE_FACTORS[settings.mode]
    inner = roof.buffer(-settings.edge_margin * factor * ppm, join_style=2)
    exclusions = []
    for item in detections:
        geometry = polygon_from_points(item["polygon"]).intersection(roof)
        margin = (
            settings.pv_margin
            if item["kind"] == "existing_pv"
            else settings.obstacle_margin
        )
        exclusions.append(geometry.buffer(margin * factor * ppm, join_style=2))
    usable = inner.difference(unary_union(exclusions)) if exclusions else inner
    return usable, roof.difference(usable)


def geojson(geometry):
    return mapping(geometry)
