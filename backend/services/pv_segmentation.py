"""Overlapping native-resolution views preserve small arrays on large captures."""
from shapely.geometry import Polygon
from shapely.ops import unary_union
import math


def detection_views(image, tile=640, overlap=160):
    yield image, 0, 0
    if max(image.size) <= 768:
        return
    tile = max(tile, math.ceil(max(image.size)/3))
    overlap = tile // 4
    def starts(length):
        return sorted(set([*range(0, max(1, length-tile+1), tile-overlap), max(0, length-tile)]))
    for y in starts(image.height):
        for x in starts(image.width):
            yield image.crop((x, y, min(image.width, x+tile), min(image.height, y+tile))), x, y


def merge_detections(objects):
    """Combine overlapping same-class masks from full image and tile passes."""
    merged = []
    for obj in sorted(objects, key=lambda o: -o["confidence"]):
        polygon = Polygon(obj["polygon"]).buffer(0)
        if polygon.is_empty or polygon.geom_type != "Polygon":
            continue
        hits = [i for i, old in enumerate(merged) if old["kind"] == obj["kind"]
                and polygon.intersection(old["geometry"]).area / min(polygon.area, old["geometry"].area) > .5]
        if hits:
            polygon = unary_union([polygon] + [merged[i]["geometry"] for i in hits])
            obj = {**obj, "confidence": max([obj["confidence"]] + [merged[i]["confidence"] for i in hits])}
            merged = [old for i, old in enumerate(merged) if i not in hits]
        merged.append({**obj, "geometry": polygon})
    return [{**{k: v for k, v in obj.items() if k != "geometry"},
             "polygon": list(obj["geometry"].exterior.coords)[:-1]} for obj in merged]
