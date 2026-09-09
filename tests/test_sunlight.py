import math
import numpy as np
import pytest
from shapely.geometry import box, Polygon
from backend.services.roof_plane import RoofPlane, official_plane
from backend.services.sunlight_service import solar_position, analyse_sunlight, sunlight_exclusions
from backend.services.suitability_service import grouped_panels
from backend.main import analyse
from test_surfaces import fixture_building


def test_official_angles_preserve_slope_when_dsm_fit_fails():
    face = box(0, 0, 10, 10)
    unreliable = RoofPlane.from_slopes(5, 5)
    plane = official_plane(face, {"neigung": 30, "ausrichtung": 0}, unreliable)
    assert plane.source == "sonnendach"
    assert plane.describe()["pitch_deg"] == pytest.approx(30)
    assert plane.describe()["azimuth_deg"] == pytest.approx(180)
    assert plane.local_geometry(face).area == pytest.approx(100/math.cos(math.pi/6))
    assert not plane.describe()["height_is_absolute"]


@pytest.mark.parametrize("official,compass", [(-180, 0), (-90, 90), (0, 180), (90, 270)])
def test_official_compass_conversion(official, compass):
    plane = official_plane(box(0, 0, 10, 10), {"neigung": 30, "ausrichtung": official})
    assert plane.describe()["azimuth_deg"] == pytest.approx(compass, abs=1e-8)


def test_official_height_anchor_ignores_raised_structures():
    x, y = np.meshgrid(np.arange(.5, 10, .5), np.arange(.5, 10, .5))
    z = 100 + math.tan(math.pi/6)*(y-5)  # south-facing roof rises northward
    z[:7] += 3
    plane = official_plane(box(0, 0, 10, 10), {"neigung": 30, "ausrichtung": 0},
                           samples=(x.ravel(), y.ravel(), z.ravel()))
    assert plane.origin[2] == pytest.approx(100)
    assert plane.describe()["height_is_absolute"]


def test_sun_direction_changes_with_season_time_and_longitude():
    summer = solar_position(47, 0, 172, np.array([9., 12., 15.]))
    winter = solar_position(47, 0, 355, np.array([12.]))
    assert summer[0, 0] > 0 and summer[2, 0] < 0
    assert summer[1, 1] < 0  # noon sun is south in Switzerland
    assert summer[1, 2] > winter[0, 2]
    np.testing.assert_allclose(np.linalg.norm(summer, axis=1), np.ones(3), atol=1e-10)
    east = solar_position(47, 15, 172, np.array([12.]))
    assert east[0, 0] < summer[1, 0]  # solar noon occurs earlier further east


def test_neighbour_building_casts_more_winter_shade_than_summer():
    roof = box(197, 197, 203, 203)
    plane = RoofPlane.from_slopes(200, 200, 10, source="swisssurface3d")
    heights = np.zeros((400, 400), dtype=np.float32)
    terrain = {"heights": heights, "minx": 0, "maxy": 400, "step": 1}
    clear = analyse_sunlight(roof, plane, terrain, 47, 8)
    assert clear["mean_direct_sun_access"] == pytest.approx(1)
    heights[220:230, 100:300] = 40  # taller building south of the roof
    shaded = analyse_sunlight(roof, plane, terrain, 47, 8)
    assert shaded["mean_direct_sun_access"] < .8
    assert shaded["winter_direct_sun_access"] < shaded["mean_direct_sun_access"]
    assert shaded["coverage_fraction"] == 1
    assert sunlight_exclusions(shaded, plane.local_geometry(roof), .8).area > 0


def test_missing_height_data_is_unknown_not_unshaded():
    roof = box(197, 197, 203, 203)
    plane = RoofPlane.from_slopes(200, 200, 10, source="swisssurface3d")
    profile = analyse_sunlight(roof, plane, {"heights": np.full((400, 400), np.nan),
                               "minx": 0, "maxy": 400, "step": 1}, 47, 8)
    assert not profile["available"]
    assert profile["mean_direct_sun_access"] is None


def test_small_disconnected_panel_groups_are_not_recommended():
    rings = [list(box(i*1.02, 0, i*1.02+1, 2).exterior.coords)[:-1] for i in range(4)]
    rings.append(list(box(20, 0, 21, 2).exterior.coords)[:-1])
    kept = grouped_panels(rings, .02, 4)
    assert len(kept) == 4
    assert max(Polygon(p).bounds[2] for p in kept) < 10


def test_poor_irradiation_blocks_recommendation_but_retains_physical_preview():
    image, settings, _, _ = fixture_building(yields=(300, 1400))
    recommended = analyse(image, settings)
    poor = next(f for f in recommended["faces"] if f["id"] == "0")
    assert poor["additional_panel_count"] == 0
    assert poor["physical_panel_count"] > 0
    assert poor["assessment"]["status"] == "not_recommended"
    preview = analyse(image, settings.model_copy(update={"layout_policy": "physical"}))
    assert next(f for f in preview["faces"] if f["id"] == "0")["additional_panel_count"] > 0
    assert preview["assessment"]["status"] == "physical_preview"


def test_annual_demand_target_limits_panels_and_existing_generation_can_meet_it():
    image, settings, _, _ = fixture_building()
    limited = analyse(image, settings.model_copy(update={"annual_consumption_kwh": 5000, "existing_generation_kwh": 1000}))
    assert 4000 <= limited["statistics"]["annual_energy_kwh"] < 4505
    assert limited["statistics"]["additional_panel_count"] == 8
    met = analyse(image, settings.model_copy(update={"annual_consumption_kwh": 5000, "existing_generation_kwh": 5000}))
    assert met["statistics"]["additional_panel_count"] == 0
    assert met["assessment"]["status"] == "annual_target_met"
    unknown = analyse(image, settings)
    assert unknown["assessment"]["remaining_annual_target_kwh"] is None
