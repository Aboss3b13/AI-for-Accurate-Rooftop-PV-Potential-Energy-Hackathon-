"""Reuse detections and packing on independent, physical roof surfaces."""
import hashlib
import math
import time
import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, mapping
from shapely.ops import transform, unary_union
from backend.services.runtime_cache import captures
from backend.services.geometry_service import build_usable, polygon_from_points
from backend.services.panel_optimizer import optimise_panels
from backend.services.energy_service import capacity
from backend.services.confidence_service import summarise_confidence

TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)


def parts(geometry):
    if geometry.is_empty:
        return []
    if geometry.geom_type == "Polygon":
        return [geometry]
    return [p for g in getattr(geometry, "geoms", []) for p in parts(g)]


class GeoReference:
    def __init__(self, grid):
        self.x, _, _, self.y = grid["bbox"]
        self.ppm = grid["pixels_per_metre"]

    def world(self, x, y, z=None):
        return self.x + np.asarray(x)/self.ppm, self.y - np.asarray(y)/self.ppm

    def pixel(self, x, y, z=None):
        return (np.asarray(x)-self.x)*self.ppm, (self.y-np.asarray(y))*self.ppm


def solar_data(props, override=None):
    def number(key):
        try:
            value = float(props.get(key))
            return value if math.isfinite(value) and value >= 0 else None
        except (TypeError, ValueError):
            return None
    irradiation = number("mstrahlung")
    if irradiation is not None and irradiation > 3000:
        irradiation = None
    return {"irradiation_kwh_m2_year": irradiation, "suitability_class": number("klasse"),
            "specific_yield_kwh_kwp": override if override is not None else
                (irradiation * .8 if irradiation is not None else None),
            "yield_source": "User supplied specific yield" if override is not None else
                ("Sonnendach irradiation × 0.80 performance ratio (planning estimate)" if irradiation is not None else None),
            "performance_ratio": .8 if irradiation is not None and override is None else None}


def deduplicate(objects):
    """Union overlapping evidence; PV wins over heuristic window classification.

    Manual annotations keep their kind when merged with automatic obstacles.
    Touching boundaries alone do not merge separate detections.
    """
    pending = [{**o, "geometry": polygon_from_points(o["polygon"])} for o in objects]
    pending.sort(key=lambda o: (o["kind"] != "existing_pv", o.get("source") != "manual"))
    merged = []
    for item in pending:
        geometry = item["geometry"]
        if geometry.is_empty:
            continue
        hits = [old for old in merged if old["geometry"].intersection(geometry).area > 1e-6]
        if hits:
            first = hits[0]
            geometry = unary_union([geometry] + [h["geometry"] for h in hits])
            sources = sorted(set([item.get("source", "unknown")] + [s for h in hits for s in h["sources"]]))
            for hit in hits:
                merged.remove(hit)
            item = {**first, "geometry": geometry, "sources": sources,
                    "kinds": sorted(set([item["kind"]] + [k for h in hits for k in h["kinds"]])),
                    "height_m": max([item.get("height_m") or 0] + [h.get("height_m") or 0 for h in hits]) or None}
        else:
            item = {**item, "sources": [item.get("source", "unknown")], "kinds": [item["kind"]]}
        merged.append(item)
    return merged


def analyse_surfaces(image, settings, objects, warnings, model, start=None):
    start = start or time.perf_counter()
    context = captures.get(settings.capture_id)
    if context is None:
        raise ValueError("Map capture expired. Click the building again to reload its roof model.")
    if (image.size != (context["grid"]["width"], context["grid"]["height"])
            or hashlib.sha256(image.tobytes()).hexdigest() != context["image_hash"]):
        raise ValueError("This image does not match the roof model. Reload the map capture.")
    if not math.isclose(settings.pixels_per_metre or 0, context["grid"]["pixels_per_metre"], rel_tol=1e-5):
        raise ValueError("Map scale is fixed by its georeferencing. Restore the map scale or upload the image separately.")
    geo = GeoReference(context["grid"])
    warnings = list(dict.fromkeys(context["warnings"] + warnings))
    ids = {f["id"] for f in context["faces"]}
    if set(settings.face_overrides) - ids:
        raise ValueError("An edited face does not belong to this building.")
    merged = deduplicate(objects)
    for obj in merged:
        obj["world"] = transform(geo.world, obj["geometry"])
    clip = transform(geo.world, Polygon(settings.building_override)) if settings.building_override else None
    occupied = Polygon()
    faces = []
    # Overlapping official projections are assigned to the upper face, avoiding
    # physically impossible modules under an overhanging/dormer roof.
    ordered = sorted(context["faces"], key=lambda f: (-f["plane"].origin[2], f["id"]))
    for face in ordered:
        plane = face["plane"]
        world = face["geometry"]
        if face["id"] in settings.face_overrides:
            world = transform(geo.world, Polygon(settings.face_overrides[face["id"]]))
        if clip is not None:
            world = world.intersection(clip)
        overlap = world.intersection(occupied).area
        world = world.difference(occupied)
        occupied = unary_union([occupied, world])
        local = plane.local_geometry(world)
        local_objects = []
        for obj in merged:
            for part in parts(obj["world"].intersection(world)):
                if part.area < 1e-6:
                    continue
                local_objects.append({k: v for k, v in obj.items() if k not in {"geometry", "world", "polygon"}} |
                    {"polygon": list(plane.local_geometry(part).exterior.coords)[:-1]})
        usable, excluded = build_usable(local, local_objects, 1, settings)
        angle = 0.
        if not local.is_empty:
            coords = list(local.minimum_rotated_rectangle.exterior.coords)
            a, b = max(zip(coords, coords[1:]), key=lambda pair: math.dist(*pair))
            angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
        # Existing alignment control acts as an offset from automatic face alignment.
        angle -= settings.angle - context["default_angle"]
        diagnostics = plane.describe()
        panels, orientation = optimise_panels(usable, 1, settings.panel, angle, diagnostics)
        solar = solar_data(face["properties"], settings.annual_specific_yield)
        diagnostics.update(overlapping_projection_removed_m2=overlap, alignment_deg=angle)
        faces.append({"id": face["id"], "plane": plane, "world": world, "local": local,
                      "objects": local_objects, "usable": usable, "excluded": excluded,
                      "panels": panels, "orientation": orientation, "diagnostics": diagnostics, "solar": solar,
                      "official_pitch_deg": face["properties"].get("neigung"),
                      "official_azimuth_deg": ((float(face["properties"]["ausrichtung"]) + 180) % 360)
                          if face["properties"].get("ausrichtung") is not None else None})
    available = all(f["solar"]["specific_yield_kwh_kwp"] is not None for f in faces) and bool(faces)
    if settings.objective == "energy" and not available:
        raise ValueError("Annual-energy optimisation is unavailable: some faces have no irradiation or supplied yield.")
    original_counts = {f["id"]: len(f["panels"]) for f in faces}
    def allocation(objective):
        ordered_faces = sorted(faces, key=lambda f: (
            -(f["solar"]["specific_yield_kwh_kwp"] or 0) if objective == "energy" else -len(f["panels"]), f["id"]))
        remaining = settings.max_panels if settings.max_panels is not None else sum(original_counts.values())
        counts = {}
        for f in ordered_faces:
            counts[f["id"]] = min(remaining, original_counts[f["id"]])
            remaining -= counts[f["id"]]
        return counts
    comparisons = {}
    for objective in ["capacity", "energy"] if available else ["capacity"]:
        counts = allocation(objective)
        comparisons[objective] = {"panel_count": sum(counts.values()),
            "additional_kwp": sum(counts.values()) * settings.panel.power / 1000,
            "annual_energy_kwh": round(sum(counts[f["id"]] * settings.panel.power / 1000 *
                (f["solar"]["specific_yield_kwh_kwp"] or 0) for f in faces)) if available else None}
    chosen = allocation(settings.objective)
    features, public_faces, image_panels = [], [], []
    def feature(geometry, layer, face_id, **properties):
        if not geometry.is_empty:
            features.append({"type": "Feature", "properties": {"layer": layer, "face_id": face_id, **properties},
                             "geometry": mapping(transform(TO_WGS84.transform, geometry))})
    for f in faces:
        plane = f["plane"]
        f["panels"] = f["panels"][:chosen[f["id"]]]
        surface_area, projected_area = f["local"].area, f["world"].area
        stats = {"projected_area_m2": round(projected_area, 2), "surface_area_m2": round(surface_area, 2),
                 "usable_area_m2": round(f["usable"].area, 2), "additional_panel_count": len(f["panels"]),
                 "existing_pv_regions": sum(o["kind"] == "existing_pv" for o in f["objects"]),
                 "obstacle_count": sum(o["kind"] != "existing_pv" for o in f["objects"]),
                 **capacity(len(f["panels"]), settings.panel.power, f["solar"]["specific_yield_kwh_kwp"])}
        feature(f["world"], "roof", f["id"], **f["solar"])
        feature(plane.world_geometry(f["usable"]), "usable", f["id"])
        feature(plane.world_geometry(f["excluded"]), "excluded", f["id"])
        for obj in f["objects"]:
            feature(plane.world_geometry(Polygon(obj["polygon"])), "pv" if obj["kind"] == "existing_pv" else "obstacles", f["id"])
        for ring in f["panels"]:
            world_panel = plane.world_geometry(Polygon(ring))
            feature(world_panel, "panels", f["id"])
            image_panels.append(list(transform(geo.pixel, world_panel).exterior.coords)[:-1])
        public_faces.append({"id": f["id"], **stats, "geometry_source": plane.source,
            "pitch_deg": f["diagnostics"]["pitch_deg"] if plane.source != "projected_2d" else None,
            "azimuth_deg": f["diagnostics"]["azimuth_deg"] if plane.source != "projected_2d" else None,
            "official_pitch_deg": f["official_pitch_deg"], "official_azimuth_deg": f["official_azimuth_deg"],
            "solar": f["solar"], "orientation": f["orientation"],
            "local_roof": mapping(f["local"]), "local_usable": mapping(f["usable"]),
            "local_objects": f["objects"], "local_panels": f["panels"],
            "diagnostics": {**f["diagnostics"], **stats}})
    fallback = sum(f["plane"].source == "projected_2d" for f in faces)
    if fallback:
        warnings.append(f"3D roof geometry unavailable or unreliable for {fallback} face(s). Those faces use projected 2D geometry.")
    if settings.boundary_edited or settings.face_overrides:
        warnings.append("Boundary corrections reuse the original fitted planes. Recheck pitch when moving a boundary onto a different surface.")
    if clip is not None:
        warnings.append("The whole-building edit crops official faces; extensions outside them require a separately drawn map roof.")
    warnings.append("Planning estimate: DSM and imagery dates may differ. Structure, local shadows and installation compliance are not assessed.")
    if available:
        warnings.append("Annual energy uses face-average irradiation with an assumed 80% performance ratio, or your supplied yield; it is not a production guarantee.")
    surface = sum(f["local"].area for f in faces)
    count = len(image_panels)
    display_objects = []
    outline = unary_union([f["world"] for f in faces])
    for obj in merged:
        for part in parts(obj["world"].intersection(outline)):
            display_objects.append({k: v for k, v in obj.items() if k not in {"geometry", "world", "polygon"}} |
                {"polygon": list(transform(geo.pixel, part).exterior.coords)[:-1]})
    return {"roof": mapping(transform(geo.pixel, outline)),
            "usable_area": mapping(transform(geo.pixel, unary_union([f["plane"].world_geometry(f["usable"]) for f in faces]))),
            "excluded_area": mapping(transform(geo.pixel, unary_union([f["plane"].world_geometry(f["excluded"]) for f in faces]))),
            "proposed_panels": image_panels,
            "existing_pv": [o for o in display_objects if o["kind"] == "existing_pv"],
            "obstacles": [o for o in display_objects if o["kind"] != "existing_pv"],
            "faces": public_faces, "map_overlay": {"type": "FeatureCollection", "features": features},
            "objective": settings.objective, "energy_available": available,
            "objective_comparison": comparisons,
            "objective_note": "Both objectives fill all faces without a panel limit. With a limit, energy prioritises higher-yield faces; capacity fills larger layouts first.",
            "model": model, "warnings": list(dict.fromkeys(warnings)), "confidence": summarise_confidence(display_objects), "mode": settings.mode,
            "statistics": {"existing_pv_regions": sum(o["kind"] == "existing_pv" for o in display_objects),
                "additional_panel_count": count, **capacity(count, settings.panel.power),
                "annual_energy_kwh": comparisons[settings.objective]["annual_energy_kwh"],
                "roof_area_m2": round(surface, 2), "surface_area_m2": round(surface, 2),
                "projected_area_m2": round(sum(f["world"].area for f in faces), 2),
                "usable_area_m2": round(sum(f["usable"].area for f in faces), 2),
                "roof_utilisation": round(count*settings.panel.width*settings.panel.height/surface*100, 1) if surface else 0,
                "pixels_per_metre": geo.ppm, "approximate": bool(fallback), "fallback_faces": fallback,
                "orientation": "per face", "elapsed_ms": round((time.perf_counter()-start)*1000)}}
