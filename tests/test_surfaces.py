import hashlib
import math
import uuid
import numpy as np
import pytest
from PIL import Image
from shapely.geometry import Polygon, box, shape
from shapely.ops import transform
from backend.main import analyse
from backend.schemas.analysis import AnalysisSettings, PanelConfig
from backend.services.roof_plane import RoofPlane, plane_from_fit
from backend.services.elevation_service import fit_plane
from backend.services.surface_analysis import GeoReference, deduplicate
from backend.services.runtime_cache import captures
from backend.services.panel_optimizer import optimise_panels


@pytest.mark.parametrize("a,b", [(0, 0), (math.tan(math.pi/6), 0), (.4, -.8)])
def test_world_local_world_roundtrip_and_orthonormal_axes(a, b):
    p = RoofPlane.from_slopes(2640300, 1232900, 450, a, b)
    basis = np.column_stack((p.u, p.v, p.normal))
    np.testing.assert_allclose(basis.T @ basis, np.eye(3), atol=1e-12)
    for point in [(2640301.123456, 1232903.654321), (2640270, 1232910)]:
        local = p.to_local(*point)
        np.testing.assert_allclose(p.to_world(*local), point, atol=1e-8, rtol=0)
        xyz = p.xyz(*local)
        assert xyz[2] == pytest.approx(450+a*(point[0]-2640300)+b*(point[1]-1232900))


@pytest.mark.parametrize("pitch", [0, 30, 55])
def test_true_surface_area_including_flat_and_thirty_degree_roof(pitch):
    roof = box(2640300, 1232900, 2640310, 1232906)
    plane = RoofPlane.from_slopes(2640300, 1232900, 400, 0, math.tan(math.radians(pitch)))
    local = plane.local_geometry(roof)
    assert local.area == pytest.approx(60/math.cos(math.radians(pitch)))
    assert plane.world_geometry(local).symmetric_difference(roof).area < 1e-7


def test_panel_dimensions_are_surface_dimensions_after_projecting_back():
    plane = RoofPlane.from_slopes(2640300, 1232900, 400, math.tan(math.pi/6), .2)
    roof = plane.local_geometry(box(2640300, 1232900, 2640315, 1232912))
    panel = PanelConfig(width=1, height=2, gap=.05)
    rings, _ = optimise_panels(roof, 1, panel, 17)
    assert rings
    for ring in rings:
        xyz = [plane.xyz(*point) for point in ring]
        sides = sorted(float(np.linalg.norm(xyz[i]-xyz[(i+1)%4])) for i in range(4))
        assert sides == pytest.approx([1, 1, 2, 2])
        assert roof.buffer(1e-8).covers(Polygon(ring))


def test_shared_plane_fit_rejects_rooftop_plant_and_recovers_slope():
    rows, cols = np.indices((40, 40))
    heights = 450 + cols*.5*math.tan(math.pi/6) - rows*.5*.2
    heights[8:25, 8:32] += 3
    fitted = fit_plane(heights, np.ones((40, 40), dtype=bool))
    plane = plane_from_fit(box(2640300, 1232880, 2640320, 1232900), fitted, 2640300, 1232900)
    assert plane.source == "swisssurface3d"
    assert -plane.normal[0]/plane.normal[2] == pytest.approx(math.tan(math.pi/6), abs=1e-8)
    assert -plane.normal[1]/plane.normal[2] == pytest.approx(.2, abs=1e-8)
    assert plane.diagnostics["point_count"] == 1600


def fixture_building(yields=(900, 1400), fallback=False):
    image = Image.new("RGB", (400, 250), "gray")
    grid = {"bbox": [2640300, 1232875, 2640340, 1232900], "pixels_per_metre": 10,
            "width": 400, "height": 250}
    geo = GeoReference(grid)
    faces = []
    for i in range(2):
        roof = box(2640302+i*17, 1232880, 2640316+i*17, 1232896)
        plane = RoofPlane.from_slopes(*roof.centroid.coords[0], 440+i*10,
                    math.tan(math.pi/6)*(1 if i else -1), .1,
                    "projected_2d" if fallback else "swisssurface3d")
        if fallback:
            plane = RoofPlane.from_slopes(*roof.centroid.coords[0])
        faces.append({"id": str(i), "geometry": roof, "plane": plane,
                      "properties": {"mstrahlung": yields[i], "klasse": 3}})
    identifier = uuid.uuid4().hex
    captures.put(identifier, {"faces": faces, "grid": grid,
                  "image_hash": hashlib.sha256(image.tobytes()).hexdigest(), "warnings": [], "default_angle": 0})
    settings = AnalysisSettings(capture_id=identifier, roof=[(20, 40), (330, 40), (330, 200), (20, 200)],
                                pixels_per_metre=10, scale_verified=True, use_ai=False)
    return image, settings, faces, geo


def test_multiface_obstacles_and_panels_stay_on_independent_surfaces():
    image, settings, faces, geo = fixture_building()
    obstacle = box(2640308, 1232884, 2640311, 1232888)
    pixels = list(transform(geo.pixel, obstacle).exterior.coords)[:-1]
    settings = settings.model_copy(update={"objects": AnalysisSettings(roof=settings.roof, objects=[
        {"polygon": pixels, "kind": "chimney", "source": "elevation"},
        {"polygon": pixels, "kind": "chimney", "source": "manual"}]).objects})
    result = analyse(image, settings)
    assert len(result["faces"]) == 2
    assert len(result["obstacles"]) == 1
    assert result["statistics"]["additional_panel_count"] == sum(f["additional_panel_count"] for f in result["faces"])
    assert result["statistics"]["surface_area_m2"] > result["statistics"]["projected_area_m2"]
    for face in result["faces"]:
        usable = shape(face["local_usable"])
        originals = next(f for f in faces if f["id"] == face["id"])
        polys = [Polygon(r) for r in face["local_panels"]]
        for i, polygon in enumerate(polys):
            assert usable.buffer(1e-8).covers(polygon)
            world = originals["plane"].world_geometry(polygon)
            assert originals["geometry"].buffer(1e-8).covers(world)
            assert world.intersection(obstacle).area < 1e-7
            assert all(polygon.intersection(other).area < 1e-7 for other in polys[i+1:])
    assert len([f for f in result["map_overlay"]["features"] if f["properties"]["layer"] == "panels"]) == result["statistics"]["additional_panel_count"]


def test_energy_priority_requires_real_data_and_only_changes_allocation_with_limit():
    image, settings, _, _ = fixture_building()
    result = analyse(image, settings)
    assert result["objective_comparison"]["capacity"] == result["objective_comparison"]["energy"]
    limited = analyse(image, settings.model_copy(update={"objective": "energy", "max_panels": 10}))
    assert limited["statistics"]["additional_panel_count"] == 10
    assert next(f for f in limited["faces"] if f["id"] == "1")["additional_panel_count"] == 10
    assert limited["statistics"]["annual_energy_kwh"] == round(10*.45*1400*.8)
    image, settings, _, _ = fixture_building(yields=(None, None))
    result = analyse(image, settings)
    assert not result["energy_available"]
    assert result["statistics"]["annual_energy_kwh"] is None
    with pytest.raises(ValueError, match="unavailable"):
        analyse(image, settings.model_copy(update={"objective": "energy"}))


def test_missing_height_falls_back_and_edited_face_keeps_other_faces():
    image, settings, _, _ = fixture_building(fallback=True)
    result = analyse(image, settings)
    assert result["statistics"]["fallback_faces"] == 2
    assert result["statistics"]["surface_area_m2"] == result["statistics"]["projected_area_m2"]
    edited = settings.model_copy(update={"face_overrides": {"0": [(20, 40), (60, 40), (60, 200), (20, 200)]}})
    changed = analyse(image, edited)
    assert next(f for f in changed["faces"] if f["id"] == "0")["surface_area_m2"] < next(f for f in result["faces"] if f["id"] == "0")["surface_area_m2"]
    assert next(f for f in changed["faces"] if f["id"] == "1")["additional_panel_count"] == next(f for f in result["faces"] if f["id"] == "1")["additional_panel_count"]


def test_capture_mismatch_and_expiry_are_actionable():
    image, settings, _, _ = fixture_building()
    with pytest.raises(ValueError, match="does not match"):
        analyse(Image.new("RGB", image.size, "blue"), settings)
    with pytest.raises(ValueError, match="expired"):
        analyse(image, settings.model_copy(update={"capture_id": "a"*32}))


def test_pv_and_reflection_are_deduplicated_without_losing_evidence():
    objects = [{"polygon": list(box(0, 0, 5, 5).exterior.coords), "source": "yolo", "kind": "existing_pv"},
               {"polygon": list(box(1, 1, 3, 3).exterior.coords), "source": "image", "kind": "skylight"}]
    merged = deduplicate(objects)
    assert len(merged) == 1 and merged[0]["kind"] == "existing_pv"
    assert merged[0]["sources"] == ["image", "yolo"]
    assert merged[0]["kinds"] == ["existing_pv", "skylight"]


def test_map_analysis_api_serialises_local_and_geographic_results():
    import io
    from fastapi.testclient import TestClient
    from backend.main import app
    image, settings, _, _ = fixture_building()
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    response = TestClient(app).post("/api/analyse", files={"image": ("roof.png", stream.getvalue(), "image/png")},
                                    data={"settings": settings.model_dump_json()})
    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["faces"]) == 2
    polygon = next(f["geometry"] for f in result["map_overlay"]["features"] if f["properties"]["layer"] == "panels")
    lon, lat = polygon["coordinates"][0][0]
    assert 5 < lon < 11 and 45 < lat < 49
    matrix = np.array(result["faces"][0]["diagnostics"]["local_to_world"])
    inverse = np.array(result["faces"][0]["diagnostics"]["world_to_local"])
    np.testing.assert_allclose(matrix @ inverse, np.eye(4), atol=1e-8)


def test_pv_does_not_absorb_touching_awning_or_manual_obstacle():
    objects = [
        {"polygon": list(box(0, 0, 5, 5).exterior.coords), "source": "yolo", "kind": "existing_pv"},
        {"polygon": list(box(4, 0, 12, 5).exterior.coords), "source": "image", "kind": "skylight"},
        {"polygon": list(box(11, 0, 16, 5).exterior.coords), "source": "elevation", "kind": "other_obstacle"},
        {"polygon": list(box(1, 1, 2, 2).exterior.coords), "source": "manual", "kind": "skylight"},
    ]
    result = deduplicate(objects)
    pv = [o for o in result if o["kind"] == "existing_pv"]
    assert len(pv) == 1 and pv[0]["geometry"].area == 25
    assert any(o["source"] == "manual" for o in result)
    assert any(o["kind"] == "other_obstacle" for o in result)


def test_hirschlistrasse_pv_boundary_survives_obstacle_fusion():
    import json
    from pathlib import Path
    from shapely.ops import unary_union
    data = json.loads((Path(__file__).parent / "fixtures/hirschlistrasse_detection.json").read_text())
    expected = unary_union([Polygon(o["polygon"]) for o in data["objects"] if o["kind"] == "existing_pv"])
    result = deduplicate(data["objects"])
    actual = unary_union([o["geometry"] for o in result if o["kind"] == "existing_pv"])
    assert actual.symmetric_difference(expected).area < 1e-6
    assert actual.area / data["pixels_per_metre"]**2 < 30
    assert any(o["kind"] == "other_obstacle" for o in result)
