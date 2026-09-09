"""A face whose height fit is weak still deserves a shade answer."""

import math

import numpy as np
import pytest
from shapely.geometry import box

from backend.services.roof_plane import official_plane

FACE = box(2600000, 1200000, 2600008, 1200006)
OFFICIAL = {"neigung": 30, "ausrichtung": 0, "flaeche": 55.4}


def samples(count, spread=0.0, base=500.0, seed=1):
    """DSM points lying on the official 30-degree face, scattered by `spread`."""
    rng = np.random.default_rng(seed)
    xs = rng.uniform(2600000, 2600008, count)
    ys = rng.uniform(1200000, 1200006, count)
    centre_y = FACE.centroid.coords[0][1]
    # The face's own slope, so a clean cloud really is planar.
    heights = (base + math.tan(math.radians(30)) * (ys - centre_y)
               + rng.normal(0, spread, count))
    return xs, ys, heights


def test_a_clean_face_is_anchored_from_its_own_deck():
    plane = official_plane(FACE, OFFICIAL, None, samples(200, spread=0.05))
    assert plane.describe()["height_is_absolute"] is True
    assert plane.diagnostics["height_anchor"] == "measured"


def test_a_noisy_face_still_gets_an_approximate_anchor():
    # Scatter far wider than the deck tolerance: the strict test must fail.
    plane = official_plane(FACE, OFFICIAL, None, samples(200, spread=3.0))
    assert plane.diagnostics["height_anchor"] == "approximate"
    # Shade screening needs a height, and now has one, honestly labelled.
    assert plane.describe()["height_is_absolute"] is True


def test_a_small_face_is_anchored_rather_than_skipped():
    plane = official_plane(FACE, OFFICIAL, None, samples(8, spread=0.05))
    assert plane.diagnostics["height_anchor"] == "approximate"
    assert plane.describe()["height_is_absolute"] is True


def test_too_few_samples_still_refuses():
    plane = official_plane(FACE, OFFICIAL, None, samples(3, spread=0.05))
    assert plane.describe()["height_is_absolute"] is False


def test_no_samples_at_all_refuses():
    plane = official_plane(FACE, OFFICIAL, None, None)
    assert plane.describe()["height_is_absolute"] is False


def test_the_approximate_anchor_sits_inside_the_measured_heights():
    xs, ys, heights = samples(200, spread=3.0)
    plane = official_plane(FACE, OFFICIAL, None, (xs, ys, heights))
    anchor = plane.diagnostics["height_anchor_m"]
    assert float(np.min(heights)) - 20 <= anchor <= float(np.max(heights)) + 20


def test_an_approximate_anchor_is_reported_as_a_caution():
    from backend.schemas.analysis import AnalysisSettings
    from backend.services.suitability_service import assess_face

    plane = official_plane(FACE, OFFICIAL, None, samples(200, spread=3.0))
    settings = AnalysisSettings(roof=[(0, 0), (10, 0), (10, 10)])
    result = assess_face(
        plane,
        {"irradiation_kwh_m2_year": 1200},
        {"available": True, "coverage_fraction": 1.0, "height_anchor": "approximate"},
        settings,
    )
    assert any("anchored approximately" in c for c in result["cautions"])
