"""Every fact must name where it came from, and how strongly it is known."""

from shapely.geometry import box

from backend.services.suitability_service import data_provenance


class Plane:
    def __init__(self, source):
        self.source = source


def faces(count=2, source="swisssurface3d"):
    return [{"plane": Plane(source), "local": box(0, 0, 4, 4)} for _ in range(count)]


OBJECTS = [
    {"kind": "existing_pv", "source": "image"},
    {"kind": "chimney", "source": "elevation"},
    {"kind": "other_obstacle", "source": "terrain"},
    {"kind": "skylight", "source": "image"},
    {"kind": "chimney", "source": "manual"},
]
MODEL = {"model": "rooftop_best.pt"}


def entries(register=None):
    return {
        e["fact"]: e
        for e in data_provenance(register or {"known": False}, faces(), OBJECTS, MODEL)
    }


def test_only_the_unobservable_parts_are_inferred():
    inferred = {f for f, e in entries().items() if e["kind"] == "inferred"}
    assert inferred == {"Where the existing array sits", "Flush roof windows"}


def test_roof_geometry_and_irradiation_are_measured_not_predicted():
    found = entries()
    assert found["Roof outline, pitch and orientation"]["kind"] == "measured"
    assert found["Annual irradiation"]["kind"] == "measured"
    assert found["Chimneys, dormers and roof structures"]["kind"] == "measured"


def test_shading_and_layout_are_calculated():
    found = entries()
    assert found["Sun position and local shading"]["kind"] == "calculated"
    assert found["Module layout"]["kind"] == "calculated"


def test_a_registered_installation_is_reported_as_measured_fact():
    found = entries({"known": True, "plant_count": 1, "total_power_kw": 5.25})
    detail = found["Existing PV on this building"]["detail"]
    assert "1 plant" in detail and "5.25 kW" in detail


def test_an_unregistered_building_does_not_claim_the_roof_is_bare():
    detail = entries()["Existing PV on this building"]["detail"]
    assert "not proof" in detail


def test_every_entry_names_a_source():
    for entry in data_provenance({"known": False}, faces(), OBJECTS, MODEL):
        assert entry["source"]
        assert entry["kind"] in {"measured", "calculated", "inferred", "supplied"}
