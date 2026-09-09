"""Sources surveyed years apart, and what that implies for one roof."""

from datetime import date

import pytest

from backend.services import vintage_service as vs


def test_year_is_read_from_the_swisstopo_tile_name():
    assert vs.tile_year("swissimage-dop10_2022_2681-1247_0.1_2056.tif") == 2022
    assert vs.tile_year("swisssurface3d-raster_2018_2683-1247_0.5_2056_5728.tif") == 2018
    assert vs.tile_year("https://data.geo.admin.ch/x/swissalti3d_2019_2681-1250_0.5.tif") == 2019
    assert vs.tile_year("no-year-here.tif") is None
    assert vs.tile_year(None) is None


def test_swiss_dates_are_parsed_and_bad_ones_refused():
    assert vs.swiss_date("25.07.2014") == date(2014, 7, 25)
    assert vs.swiss_date("31.02.2014") is None
    assert vs.swiss_date("2014-07-25") is None
    assert vs.swiss_date(None) is None


def test_an_array_newer_than_the_photo_is_called_out():
    notes = vs.findings(
        {"imagery_year": 2019, "surface_year": 2019},
        {"plants": [{"commissioned": "25.07.2021", "power_kw": 25.5}]},
    )
    assert any("cannot appear in this image" in n for n in notes)
    assert any("25.5 kW" in n for n in notes)


def test_an_array_older_than_the_photo_is_not_flagged():
    notes = vs.findings(
        {"imagery_year": 2022, "surface_year": 2022},
        {"plants": [{"commissioned": "25.07.2014", "power_kw": 5.25}]},
    )
    assert not any("cannot appear" in n for n in notes)


def test_sources_far_apart_in_time_are_reported():
    notes = vs.findings({"imagery_year": 2019, "surface_year": 2024}, {})
    assert any("years apart" in n for n in notes)


def test_sources_close_in_time_say_nothing():
    assert vs.findings({"imagery_year": 2024, "surface_year": 2024}, {}) == []


def test_missing_years_are_survivable():
    assert vs.findings({}, {}) == []
    assert vs.findings({"imagery_year": None}, {"plants": [{"commissioned": None}]}) == []


def test_confidence_is_per_input_not_one_headline():
    rows = vs.confidence({"imagery_year": date.today().year}, {"known": True}, 4, 4)
    by_input = {r["input"]: r for r in rows}
    assert by_input["Roof-plane fit"]["level"] == "high"
    assert by_input["Existing PV presence"]["level"] == "high"
    # Position is never recorded by any dataset, so it can never be high.
    assert by_input["Existing PV position"]["level"] == "medium"
    assert by_input["Regulatory compliance"]["level"] == "not assessed"


def test_an_old_photo_lowers_only_freshness():
    rows = {r["input"]: r for r in vs.confidence({"imagery_year": 2015}, {}, 4, 4)}
    assert rows["Aerial freshness"]["level"] == "low"
    assert rows["Roof geometry"]["level"] == "high"


def test_unfitted_faces_lower_the_plane_confidence():
    rows = {r["input"]: r for r in vs.confidence({}, {}, 0, 4)}
    assert rows["Roof-plane fit"]["level"] == "low"
