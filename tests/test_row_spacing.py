"""Flat roofs carry tilted racks, and a rack shades the one behind it."""

import math

import pytest
from shapely.geometry import box

from backend.schemas.analysis import PanelConfig
from backend.services.panel_optimizer import (
    flat_roof_layout,
    optimise_panels,
    row_gap,
)

PANEL = PanelConfig()


def count(usable, **kw):
    panels, _ = optimise_panels(usable, 1, kw.pop("panel", PANEL), 0, None, **kw)
    return len(panels)


def test_a_tilted_module_takes_less_depth_than_its_length():
    depth, _ = flat_roof_layout(PANEL, PANEL.height)
    assert depth == pytest.approx(PANEL.height * math.cos(math.radians(15)), rel=1e-6)
    assert depth < PANEL.height


def test_the_row_gap_is_the_shadow_the_design_sun_casts():
    gap = row_gap(PANEL, 15, PANEL.height)
    expected = (PANEL.height * math.sin(math.radians(15))
                / math.tan(math.radians(PANEL.design_sun_altitude_deg)))
    assert gap == pytest.approx(expected, rel=1e-6)
    # On the Swiss plateau that gap is comparable to the module itself.
    assert 1.0 < gap < 1.8


def test_a_steeper_tilt_needs_a_wider_gap():
    assert row_gap(PANEL, 25, PANEL.height) > row_gap(PANEL, 10, PANEL.height)


def test_a_lower_design_sun_needs_a_wider_gap():
    low = PanelConfig(design_sun_altitude_deg=15)
    high = PanelConfig(design_sun_altitude_deg=30)
    assert row_gap(low, 15, PANEL.height) > row_gap(high, 15, PANEL.height)


def test_a_flush_module_needs_no_row_gap():
    flush = PanelConfig(flat_roof_tilt_deg=0)
    depth, gap = flat_roof_layout(flush, PANEL.height)
    assert gap == 0.0
    assert depth == pytest.approx(PANEL.height)


def test_an_explicit_gap_overrides_the_calculation():
    fixed = PanelConfig(row_gap_m=0.5)
    _, gap = flat_roof_layout(fixed, PANEL.height)
    assert gap == 0.5


def test_racks_fit_fewer_modules_than_a_flush_block():
    roof = box(0, 0, 30, 30)
    flush = count(roof, tilted=False)
    racked = count(roof, tilted=True)
    assert racked < flush
    # Row pitch is close to twice the footprint, so roughly half the modules.
    assert 0.35 < racked / flush < 0.75


def test_a_pitched_roof_is_untouched_by_row_spacing():
    roof = box(0, 0, 20, 12)
    assert count(roof, tilted=False) == count(roof)


def test_rows_really_are_separated_on_a_flat_roof():
    panels, _ = optimise_panels(box(0, 0, 30, 30), 1, PANEL, 0, None, tilted=True)
    assert panels
    # Distinct row positions, and neighbouring rows a clear gap apart.
    lows = sorted({round(min(y for _, y in ring), 3) for ring in panels})
    assert len(lows) >= 3
    depth, gap = flat_roof_layout(PANEL, PANEL.height)
    steps = [b - a for a, b in zip(lows, lows[1:])]
    assert min(steps) >= depth + gap - 0.05


def test_modules_within_a_row_stay_shoulder_to_shoulder():
    panels, _ = optimise_panels(box(0, 0, 30, 30), 1, PANEL, 0, None, tilted=True)
    first = min(round(min(y for _, y in ring), 3) for ring in panels)
    row = sorted(min(x for x, _ in ring) for ring in panels
                 if round(min(y for _, y in ring), 3) == first)
    steps = [b - a for a, b in zip(row, row[1:])]
    assert steps and max(steps) <= PANEL.width + PANEL.gap + 0.05
