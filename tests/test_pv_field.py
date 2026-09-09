"""Existing arrays found by colour, and the roofs that must not be mistaken for one."""

import cv2
import numpy as np
import pytest
from shapely.geometry import Polygon, box

from backend.services import pv_field_service as pv

PPM = 10.0
SIZE = 240
ROOF = box(10, 10, SIZE - 10, SIZE - 10)


def roof_image(red=150, green=140, blue=132, noise=4.0, seed=3):
    """A grey-brown roof: red-dominant, lightly textured."""
    rng = np.random.default_rng(seed)
    image = np.zeros((SIZE, SIZE, 3), np.float32)
    for channel, level in enumerate((red, green, blue)):
        image[..., channel] = level + rng.normal(0, noise, (SIZE, SIZE))
    return np.clip(image, 0, 255).astype(np.uint8)


def put_array(image, x0, y0, x1, y1, seed=5):
    """A module field: strongly blue, and textured by its cell and frame lines."""
    rng = np.random.default_rng(seed)
    patch = image[y0:y1, x0:x1].astype(np.float32)
    patch[..., 0] = 95 + rng.normal(0, 3, patch.shape[:2])
    patch[..., 1] = 105 + rng.normal(0, 3, patch.shape[:2])
    patch[..., 2] = 140 + rng.normal(0, 3, patch.shape[:2])
    patch[::11, :, :] -= 45   # frame lines between module rows
    patch[:, ::11, :] -= 45
    image[y0:y1, x0:x1] = np.clip(patch, 0, 255).astype(np.uint8)
    return image


def test_a_module_field_is_found():
    image = put_array(roof_image(), 60, 60, 180, 170)
    found = pv.detect(image, ROOF, PPM)
    assert len(found) == 1
    assert found[0]["area_m2"] == pytest.approx(120 * 110 / PPM**2, rel=0.25)
    assert found[0]["blue_shift"] > pv.MIN_ABSOLUTE_BLUE


def test_a_bare_roof_claims_nothing():
    # Otsu always splits; the guards must stop that becoming a detection.
    assert pv.detect(roof_image(), ROOF, PPM) == []


def test_sun_and_shade_on_a_bare_roof_is_not_an_array():
    # Shaded roof is bluer as well as darker, which is the obvious false positive.
    image = roof_image().astype(np.float32)
    image[:, : SIZE // 2] *= 0.55
    image[:, : SIZE // 2, 2] += 6
    assert pv.detect(np.clip(image, 0, 255).astype(np.uint8), ROOF, PPM) == []


def test_a_ragged_edge_band_is_rejected():
    # The Oerlikon failure: a bluish parapet ring, solid enough in colour but
    # nothing like the compact block a module field forms.
    image = roof_image()
    ring = np.zeros((SIZE, SIZE), np.uint8)
    cv2.rectangle(ring, (14, 14), (SIZE - 14, SIZE - 14), 1, 7)
    image[ring.astype(bool)] = (95, 105, 145)
    assert pv.detect(image, ROOF, PPM) == []


def test_smooth_blue_sheeting_is_rejected_on_texture():
    image = roof_image()
    image[60:180, 60:170] = (95, 105, 145)  # flat colour, no module lines
    assert pv.detect(image, ROOF, PPM) == []


def test_something_far_too_small_is_not_an_array():
    image = put_array(roof_image(), 100, 100, 112, 112)
    assert pv.detect(image, ROOF, PPM) == []


def test_regions_already_known_are_not_reported_again():
    image = put_array(roof_image(), 60, 60, 180, 170)
    assert pv.detect(image, ROOF, PPM, [box(50, 50, 190, 180)]) == []


def test_an_empty_roof_is_survivable():
    assert pv.detect(roof_image(), Polygon(), PPM) == []
    assert pv.detect(roof_image(), ROOF, 0) == []


def test_the_split_reports_its_own_separation():
    rng = np.random.default_rng(0)
    values = np.concatenate([rng.normal(-5, 2, 500), rng.normal(30, 2, 500)])
    threshold, bright, separation, share = pv.split_threshold(values)
    assert -5 < threshold < 30, threshold
    assert bright == pytest.approx(30, abs=1)
    assert separation == pytest.approx(35, abs=2)
    assert share == pytest.approx(0.5, abs=0.05)
