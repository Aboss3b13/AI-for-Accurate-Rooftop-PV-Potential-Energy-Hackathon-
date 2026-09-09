"""Explainable planning rules. No invented demand, payback or structural approval."""
import math
from shapely.geometry import Polygon
from shapely.ops import unary_union
from shapely import STRtree


def dimensions(local):
    if local.is_empty or local.area == 0:
        return {"length_m": 0., "width_m": 0.}
    ring = list(local.minimum_rotated_rectangle.exterior.coords)
    lengths = sorted(math.dist(a, b) for a, b in zip(ring, ring[1:]))
    return {"length_m": round(lengths[-1], 2), "width_m": round(lengths[0], 2)}


def assess_face(plane, solar, sunlight, settings):
    reasons, cautions = [], []
    description = plane.describe()
    if plane.source == "projected_2d":
        reasons.append("Roof pitch is unknown; a projected outline is insufficient for a recommended installation.")
    if description.get("geometry_conflict"):
        reasons.append("Official roof angles and a well-supported height fit disagree; verify the current roof.")
    if description.get("area_disagreement_fraction", 0) > .2:
        reasons.append("Calculated roof dimensions disagree with the official surface area by more than 20%.")
    if description["pitch_deg"] > 65:
        reasons.append("Pitch exceeds the prototype's 65-degree roof-installation screening limit.")
    irradiation = solar.get("irradiation_kwh_m2_year")
    if irradiation is not None and irradiation < settings.minimum_irradiation:
        reasons.append(f"Official annual irradiation is below the {settings.minimum_irradiation:g} kWh/m² screening threshold.")
    if irradiation is None:
        cautions.append("Official annual irradiation is unavailable; solar suitability is unverified.")
    if not sunlight.get("available"):
        cautions.append("Nearby shade could not be assessed: " + sunlight.get("reason", "missing height data"))
    elif sunlight.get("coverage_fraction", 1) < .98:
        cautions.append("Some surrounding height samples are missing; shade coverage is partial.")
    return {"status": "not_recommended" if reasons else "needs_review" if cautions else "suitable",
            "eligible": not reasons, "reasons": reasons, "cautions": cautions,
            "rules": {"minimum_irradiation_kwh_m2": settings.minimum_irradiation,
                      "minimum_direct_sun_access": settings.minimum_sun_access,
                      "minimum_array_panels": settings.minimum_array_panels, "maximum_pitch_deg": 65}}


def grouped_panels(rings, gap, minimum):
    """Discard isolated tiny groups instead of scattering single modules."""
    if not rings or minimum <= 1:
        return rings
    polygons = [Polygon(ring) for ring in rings]
    tree = STRtree(polygons)
    parents = list(range(len(rings)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    first, second = tree.query(polygons, predicate="dwithin", distance=gap+.05)
    for a, b in zip(first, second):
        parents[root(int(a))] = root(int(b))
    groups = {}
    for i in range(len(rings)):
        groups.setdefault(root(i), []).append(i)
    neighbours = [[] for _ in rings]
    for a, b in zip(first, second):
        if a != b:
            neighbours[int(a)].append(int(b))
    ordered = []
    for group in sorted(groups.values(), key=lambda g: (-len(g), min(g))):
        if len(group) < minimum:
            continue
        queue, seen = [min(group)], {min(group)}
        for i in queue:
            ordered.append(i)
            for j in sorted(neighbours[i]):
                if j not in seen:
                    seen.add(j)
                    queue.append(j)
    return [rings[i] for i in ordered]


def building_assessment(settings, faces, count, energy, physical_count):
    demand, existing = settings.annual_consumption_kwh, settings.existing_generation_kwh
    gap = max(0., demand-existing) if demand is not None and existing is not None else None
    if gap == 0:
        status = "annual_target_met"
        title = "No additional panels needed for the entered annual energy target"
    elif count == 0 and physical_count == 0:
        status, title = "no_space", "No additional array fits the available roof space"
    elif count == 0:
        status, title = "not_recommended", "No layout passes the current suitability rules"
    elif settings.layout_policy == "physical":
        status, title = "physical_preview", "Physical fit only — not an installation recommendation"
    else:
        status = "needs_review" if any(f["assessment"]["status"] == "needs_review" and f["panels"] for f in faces) else "potential"
        title = "Solar potential found; some site data needs review" if status == "needs_review" else "Suitable roof space found for an additional array"
    return {"status": status, "title": title, "layout_policy": settings.layout_policy,
            "physical_panel_capacity": physical_count, "proposed_panel_count": count,
            "annual_consumption_kwh": demand, "existing_generation_kwh": existing,
            "remaining_annual_target_kwh": gap,
            "annual_target_coverage_percent": round(100*energy/gap, 1) if gap and energy is not None else None,
            "demand_note": "Annual energy balance only; it does not establish hourly self-sufficiency or financial payback." if gap is not None else
                "Whether more panels are needed is unknown. Enter annual electricity use and existing annual PV production (0 if none) to size an annual-energy target.",
            "factors": [
                {"factor": "Roof dimensions, pitch and orientation", "basis": "Official face geometry; DSM height validation; physical module dimensions"},
                {"factor": "Climate and distant terrain shading", "basis": "Sonnendach annual irradiation, where available; source model and acquisition dates apply"},
                {"factor": "Nearby buildings, trees and roof structures", "basis": "120 m DSM horizon sampling and seasonal sun paths; static vegetation and coarse raster limits apply"},
                {"factor": "Existing PV and rooftop obstacles", "basis": "YOLO masks, elevation, image heuristics and user corrections"},
                {"factor": "Snow, wind and structural loads", "basis": "Not assessed; requires construction details and engineering checks"},
                {"factor": "Grid connection, tariffs, ownership and payback", "basis": "Not assessed; requires site-specific and financial inputs"}]}


def _number(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def sonnendach_comparison(context_faces, faces, settings, annual_energy_kwh, panel_count):
    """Compare the official Sonnendach potential with what actually fits.

    Sonnendach publishes, per roof face, a suitable area (flaeche) and an annual
    yield (stromertrag). It does not subtract the panels already installed, nor
    chimneys, roof windows or dormers - which is the gap this challenge is about.

    The headline pair is Sonnendach's own numbers against what SolarFit can
    place. The breakdown is kept strictly on SolarFit's measured roof surface so
    that its parts add up; the two area definitions differ, and that difference
    is reported as its own line rather than being hidden inside the margins.
    """
    official_area = 0.0
    official_energy = 0.0
    for face in context_faces:
        area = _number(face["properties"].get("flaeche"))
        energy = _number(face["properties"].get("stromertrag"))
        if area:
            official_area += area
        if energy:
            official_energy += energy
    module_area = panel_count * settings.panel.width * settings.panel.height

    measured = screened = existing = obstructed = shaded = 0.0
    for face in faces:
        measured += face["local"].area
        if not face["assessment"]["eligible"]:
            screened += face["local"].area
            continue
        # A chimney's footprint is also in shade, and marks can overlap each
        # other. Count every square metre once, against the first cause.
        pv, blockers = [], []
        for obj in face["objects"]:
            polygon = Polygon(obj["polygon"])
            if not polygon.is_valid:
                polygon = polygon.buffer(0)
            if polygon.is_empty:
                continue
            (pv if obj["kind"] == "existing_pv" else blockers).append(polygon)
        pv_area = unary_union(pv).intersection(face["local"]) if pv else Polygon()
        blocked = unary_union(blockers).intersection(face["local"]) if blockers else Polygon()
        blocked = blocked.difference(pv_area)
        shade = face["shaded"].difference(unary_union([pv_area, blocked]))
        existing += pv_area.area
        obstructed += blocked.area
        shaded += shade.area
    # Everything left on eligible faces: edge setbacks, obstacle clearances and
    # the fact that a rectangular module cannot fill an irregular shape.
    fitting = max(0.0, measured - module_area - screened - existing - obstructed - shaded)

    def share(value):
        return round(100 * value / official_area, 1) if official_area else None

    return {
        "official_area_m2": round(official_area, 1),
        "official_annual_energy_kwh": round(official_energy) if official_energy else None,
        "measured_surface_m2": round(measured, 1),
        "definition_difference_m2": round(official_area - measured, 1) if official_area else None,
        "fitted_module_area_m2": round(module_area, 1),
        "fitted_annual_energy_kwh": round(annual_energy_kwh)
            if annual_energy_kwh is not None else None,
        "area_shortfall_m2": round(official_area - module_area, 1) if official_area else None,
        "area_shortfall_percent": share(official_area - module_area),
        "energy_shortfall_percent": round(
            100 * (official_energy - annual_energy_kwh) / official_energy, 1
        ) if official_energy and annual_energy_kwh is not None else None,
        # These five plus the fitted module area sum to measured_surface_m2.
        "breakdown_m2": {
            "faces_screened_out": round(screened, 1),
            "existing_pv": round(existing, 1),
            "roof_obstacles": round(obstructed, 1),
            "shaded": round(shaded, 1),
            "margins_and_module_fit": round(fitting, 1),
        },
        "basis": "Sonnendach suitable area and annual yield for this building, "
                 "against the modules SolarFit can actually place. The breakdown "
                 "is measured on SolarFit's own roof surface, face by face.",
    }
