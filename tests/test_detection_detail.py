import math
import numpy as np
from PIL import Image
from shapely.geometry import box, Polygon
from backend.services.pv_segmentation import detection_views, merge_detections
from backend.services.sunlight_service import horizon_angles, AZIMUTH_STEP_DEG


def test_overlapping_views_cover_large_roof_and_bound_upload_cost():
    image = Image.new("RGB", (1280, 1000))
    views = list(detection_views(image))
    assert len(views) > 1
    from shapely.ops import unary_union
    assert unary_union([box(x, y, x+v.width, y+v.height) for v, x, y in views[1:]]).area == image.width*image.height
    assert len(list(detection_views(Image.new("RGB", (5000, 5000))))) <= 17


def test_tile_masks_merge_without_counting_the_same_array_twice():
    def obj(geometry, score):
        return dict(polygon=list(geometry.exterior.coords), confidence=score, kind="existing_pv", source="yolo")
    merged = merge_detections([obj(box(0, 0, 10, 10), .8), obj(box(4, 0, 12, 10), .7), obj(box(20, 0, 25, 5), .9)])
    assert len(merged) == 2
    assert sum(Polygon(o["polygon"]).area for o in merged) == 145


def test_nearby_small_obstacle_is_seen_by_3d_rays():
    heights = np.zeros((400, 400))
    heights[200, 201] = 10.85  # half a metre east of the roof sample
    angles, coverage = horizon_angles(np.array([[100., 100., 10.]]), heights, 0, 200, .5, radius=10)
    east = round(90 / AZIMUTH_STEP_DEG)
    assert angles[0, east] > math.radians(40)
    assert coverage[0, east] == 1
