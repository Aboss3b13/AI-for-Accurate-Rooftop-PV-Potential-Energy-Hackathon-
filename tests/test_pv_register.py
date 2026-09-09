"""The federal plant register: recorded fact, used to check the detector."""

import httpx
import pytest

from backend.services.pv_register_service import (
    RegisterUnavailable,
    parse_power_kw,
    registered_pv,
    summarise,
)


def row(power="5.25 kW", category="Photovoltaic", **extra):
    return {"properties": {"total_power": power, "sub_category_en": category,
                           "beginning_of_operation": "25.07.2014",
                           "plant_type_en": "Attached", **extra}}


def client_returning(payload, calls=None):
    def handler(request):
        if calls is not None:
            calls.append(request.url.params.get("searchText"))
        return httpx.Response(200, json=payload)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_power_is_read_from_the_registers_free_text():
    assert parse_power_kw("5.25 kW") == pytest.approx(5.25)
    assert parse_power_kw("1.4 MW") == pytest.approx(1400.0)
    assert parse_power_kw("12,5 kW") == pytest.approx(12.5)
    assert parse_power_kw(None) is None
    assert parse_power_kw("not a number") is None


def test_only_photovoltaic_plants_are_counted():
    result = summarise([row(), row(power="900 kW", category="Hydroelectric power")])
    assert result["plant_count"] == 1
    assert result["total_power_kw"] == pytest.approx(5.25)


def test_capacities_on_one_building_are_added():
    result = summarise([row("5.25 kW"), row("3.75 kW")])
    assert result["total_power_kw"] == pytest.approx(9.0)


def test_no_entry_is_reported_as_unknown_not_as_none():
    result = summarise([])
    assert result["known"] is False
    assert result["total_power_kw"] is None
    # Absence is weak evidence: small private arrays need not be registered.
    assert "not proof" in result["coverage_note"]


def test_lookup_matches_on_building_identifier():
    import asyncio

    calls = []

    async def go():
        async with client_returning({"results": [row()]}, calls) as client:
            return await registered_pv(client, [146005])

    result = asyncio.run(go())
    assert calls == ["146005"]
    assert result["known"] is True
    assert result["total_power_kw"] == pytest.approx(5.25)
    assert result["egids"] == [146005]


def test_unusable_identifiers_are_skipped_without_a_request():
    import asyncio

    calls = []

    async def go():
        async with client_returning({"results": []}, calls) as client:
            return await registered_pv(client, [None, "", "abc", 0])

    result = asyncio.run(go())
    assert calls == []
    assert result["known"] is False


def test_a_failing_register_raises_rather_than_inventing_an_answer():
    import asyncio

    def handler(request):
        return httpx.Response(503)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await registered_pv(client, [146005])

    with pytest.raises(RegisterUnavailable):
        asyncio.run(go())


def test_the_register_and_the_image_check_each_other():
    """The register knows whether an array exists; the image knows where."""
    from backend.services.suitability_service import data_provenance

    class Plane:
        source = "swisssurface3d"

    faces = [{"plane": Plane(), "local": None}]
    registered = {"known": True, "plant_count": 1, "total_power_kw": 25.5}
    entry = {
        e["fact"]: e
        for e in data_provenance(registered, faces, [], {"model": "m.pt"})
    }
    # Capacity is recorded fact; position is not recorded anywhere.
    assert entry["Existing PV on this building"]["kind"] == "measured"
    assert entry["Where the existing array sits"]["kind"] == "inferred"
    assert "never position" in entry["Where the existing array sits"]["detail"]
