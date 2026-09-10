"""Lining map geometry up with the roof the photograph actually shows."""

import numpy as np
import pytest

from backend.services.image_alignment import MIN_GAIN, estimate_shift
from backend.services.surface_analysis import GeoReference

PPM = 10.0
SIZE = 240


def photo_with_roof(x0, y0, x1, y1, seed=3):
    """A dark ground with one bright rectangular roof on it."""
    rng = np.random.default_rng(seed)
    image = np.full((SIZE, SIZE, 3), 40, np.float32) + rng.normal(0, 3, (SIZE, SIZE, 3))
    image[y0:y1, x0:x1] = 190 + rng.normal(0, 3, (y1 - y0, x1 - x0, 3))
    return np.clip(image, 0, 255).astype(np.uint8)


def rectangle(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_an_offset_outline_is_pulled_onto_the_roof():
    image = photo_with_roof(70, 90, 170, 180)
    # The map puts the roof 2.5 m north of where the photograph shows it.
    result = estimate_shift(image, rectangle(70, 65, 170, 155), PPM)
    assert result["applied"] is True
    assert result["shift_m"][0] == pytest.approx(0.0, abs=0.3)
    assert result["shift_m"][1] == pytest.approx(2.5, abs=0.3)


def test_an_outline_already_on_the_roof_is_left_alone():
    image = photo_with_roof(70, 90, 170, 180)
    result = estimate_shift(image, rectangle(70, 90, 170, 180), PPM)
    assert result["applied"] is False
    assert result["shift_px"] == (0.0, 0.0)


def test_a_shift_beyond_the_search_window_is_refused():
    """The true correction is outside the window, so no answer is given.

    Reaching the wall of the search means the real optimum lies further out;
    returning the wall position would be a guess dressed as a measurement.
    """
    image = photo_with_roof(70, 120, 170, 210)
    # Outline sits 5 m clear of the roof, with only blank ground within reach.
    result = estimate_shift(image, rectangle(70, 20, 170, 70), PPM, search_m=1.0)
    assert result["applied"] is False
    assert result["shift_px"] == (0.0, 0.0)


def test_aligning_to_noise_on_blank_ground_is_refused():
    """An outline over featureless ground scores near zero, so any flicker of
    noise beats it by a wide ratio. Ratio alone is therefore not enough."""
    image = photo_with_roof(70, 150, 170, 230)
    result = estimate_shift(image, rectangle(60, 15, 160, 65), PPM, search_m=1.5)
    assert result["applied"] is False


def test_a_featureless_photograph_yields_no_shift():
    flat = np.full((SIZE, SIZE, 3), 128, np.uint8)
    result = estimate_shift(flat, rectangle(70, 90, 170, 180), PPM)
    assert result["applied"] is False


def test_a_marginal_gain_is_not_acted_on():
    image = photo_with_roof(70, 90, 170, 180)
    result = estimate_shift(image, rectangle(71, 91, 171, 181), PPM)
    if result["applied"]:
        assert result["gain"] >= MIN_GAIN


def test_nonsense_input_is_survivable():
    image = photo_with_roof(70, 90, 170, 180)
    assert estimate_shift(image, [], PPM)["applied"] is False
    assert estimate_shift(image, rectangle(0, 0, 10, 10), 0)["applied"] is False


# --- the correction has to apply to both directions ------------------------

def grid(shift=(0.0, 0.0)):
    return {"bbox": [2600000.0, 1200000.0, 2600100.0, 1200100.0],
            "pixels_per_metre": PPM, "shift_px": shift}


def test_map_and_image_round_trip_through_the_offset():
    geo = GeoReference(grid((7.0, -3.0)))
    east, north = 2600042.0, 1200061.0
    x, y = geo.pixel(east, north)
    back_e, back_n = geo.world(x, y)
    assert float(back_e) == pytest.approx(east, abs=1e-6)
    assert float(back_n) == pytest.approx(north, abs=1e-6)


def test_the_offset_actually_moves_the_geometry():
    plain = GeoReference(grid())
    shifted = GeoReference(grid((7.0, -3.0)))
    east, north = 2600042.0, 1200061.0
    x0, y0 = plain.pixel(east, north)
    x1, y1 = shifted.pixel(east, north)
    assert float(x1 - x0) == pytest.approx(7.0)
    assert float(y1 - y0) == pytest.approx(-3.0)


def test_a_capture_without_an_offset_behaves_as_before():
    geo = GeoReference({"bbox": [2600000.0, 1200000.0, 2600100.0, 1200100.0],
                        "pixels_per_metre": PPM})
    x, y = geo.pixel(2600010.0, 1200090.0)
    assert (float(x), float(y)) == pytest.approx((100.0, 100.0))
