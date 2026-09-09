"""Local geometric sunlight screening, not an annual electricity simulation.

NOAA solar equations; twelve representative days, half-hour UTC samples.
DSM rays include nearby roofs, trees and terrain. Regional climate and distant
terrain are supplied separately by Sonnendach irradiation, never multiplied by
this direct-sun score (which would count source shading twice).
"""
import calendar
from datetime import date
import math
import numpy as np
from shapely import contains_xy, box
from shapely.ops import unary_union

RADIUS_M = 120.
AZIMUTH_STEP_DEG = 2.5
MAX_SURFACE_SAMPLES = 1500


def solar_position(latitude, longitude, day, hour_utc):
    """Return ENU unit direction using NOAA's fractional-year approximation."""
    gamma = 2*np.pi/365 * (day - 1 + (hour_utc - 12)/24)
    decl = (.006918 - .399912*np.cos(gamma) + .070257*np.sin(gamma)
            - .006758*np.cos(2*gamma) + .000907*np.sin(2*gamma)
            - .002697*np.cos(3*gamma) + .00148*np.sin(3*gamma))
    equation = 229.18*(.000075 + .001868*np.cos(gamma) - .032077*np.sin(gamma)
                      - .014615*np.cos(2*gamma) - .040849*np.sin(2*gamma))
    hour_angle = np.radians((hour_utc*60 + equation + 4*longitude)/4 - 180)
    lat = math.radians(latitude)
    east = -np.cos(decl)*np.sin(hour_angle)
    north = np.cos(lat)*np.sin(decl) - np.sin(lat)*np.cos(decl)*np.cos(hour_angle)
    up = np.sin(lat)*np.sin(decl) + np.cos(lat)*np.cos(decl)*np.cos(hour_angle)
    return np.column_stack((east, north, up))


def sampled_sun(latitude, longitude, normal):
    directions, weights, months = [], [], []
    for month in range(1, 13):
        hours = np.arange(4., 20.01, .5)
        day = date(2025, month, 21).timetuple().tm_yday
        rays = solar_position(latitude, longitude, day, hours)
        incidence = rays @ normal
        valid = (rays[:, 2] > math.sin(math.radians(5))) & (incidence > 0)
        directions.extend(rays[valid])
        # Geometric beam weighting only: no weather or irradiance fabrication.
        weights.extend(incidence[valid]*calendar.monthrange(2025, month)[1])
        months.extend([month]*int(valid.sum()))
    return np.asarray(directions), np.asarray(weights), np.asarray(months)


def horizon_angles(points_xyz, heights, minx, maxy, step, radius=RADIUS_M):
    """Horizon above each surface point; missing samples remain unknown."""
    azimuths = np.radians(np.arange(0, 360, AZIMUTH_STEP_DEG))
    # Match DSM detail near the roof so short chimneys are not skipped between
    # metre-spaced rays. Far-field spacing bounds the interactive workload.
    distances = np.unique(np.concatenate((np.arange(.5, 20., .5), np.arange(20., radius+.01, 1.))))
    distances = distances[distances <= radius]
    dx = np.sin(azimuths)[:, None]*distances
    dy = np.cos(azimuths)[:, None]*distances
    horizons, coverage = [], []
    for start in range(0, len(points_xyz), 48):
        points = points_xyz[start:start+48]
        cols = np.floor((points[:, 0, None, None]+dx-minx)/step).astype(int)
        rows = np.floor((maxy-points[:, 1, None, None]-dy)/step).astype(int)
        inside = (rows >= 0) & (cols >= 0) & (rows < heights.shape[0]) & (cols < heights.shape[1])
        z = heights[np.clip(rows, 0, heights.shape[0]-1), np.clip(cols, 0, heights.shape[1]-1)]
        valid = inside & np.isfinite(z)
        # 15 cm panel standoff plus 10 cm DSM uncertainty allowance.
        angle = np.arctan2(z-points[:, 2, None, None]-.25, distances)
        angle = np.where(valid, angle, -np.pi/2)
        horizons.append(np.maximum(0, angle.max(axis=2)))
        coverage.append(valid.mean(axis=2))
    return np.concatenate(horizons), np.concatenate(coverage)


def analyse_sunlight(geometry, plane, terrain, latitude, longitude):
    anchor = plane.diagnostics.get("height_anchor")
    if terrain is None or not plane.describe()["height_is_absolute"]:
        return {"available": False, "reason": "No reliable absolute roof height or surrounding DSM.", "radius_m": RADIUS_M}
    local = plane.local_geometry(geometry)
    if local.is_empty:
        return {"available": False, "reason": "Empty roof face.", "radius_m": RADIUS_M}
    cell = max(.5, math.sqrt(local.area/MAX_SURFACE_SAMPLES))
    minx, miny, maxx, maxy = local.bounds
    # Bounding-box area, rather than polygon area, bounds work on narrow faces.
    cell = max(cell, math.sqrt((maxx-minx)*(maxy-miny)/MAX_SURFACE_SAMPLES))
    xx, yy = np.meshgrid(np.arange(minx+cell/2, maxx, cell), np.arange(miny+cell/2, maxy, cell))
    inside = contains_xy(local, xx, yy)
    s, t = xx[inside], yy[inside]
    if not len(s):
        return {"available": False, "reason": "Face is too small for sunlight sampling.", "radius_m": RADIUS_M}
    xyz = plane.origin + s[:, None]*plane.u + t[:, None]*plane.v
    horizons, coverage = horizon_angles(xyz, **terrain)
    rays, weights, months = sampled_sun(latitude, longitude, plane.normal)
    if not len(weights) or weights.sum() <= 0:
        return {"available": False, "reason": "No front-face sun samples.", "radius_m": RADIUS_M}
    azimuth = np.degrees(np.arctan2(rays[:, 0], rays[:, 1])) % 360
    bins = np.rint(azimuth/AZIMUTH_STEP_DEG).astype(int) % horizons.shape[1]
    visible = np.arcsin(rays[:, 2])[None, :] > horizons[:, bins]
    score = (visible*weights).sum(axis=1)/weights.sum()
    known = (coverage[:, bins]*weights).sum(axis=1)/weights.sum() >= .98
    winter = np.isin(months, [11, 12, 1, 2])
    winter_score = (visible[:, winter]*weights[winter]).sum(axis=1)/weights[winter].sum() if winter.any() else None
    return {"available": bool(known.any()), "reason": None if known.any() else "Surrounding height coverage is incomplete.",
            "height_anchor": anchor,
            "radius_m": RADIUS_M, "cell_size_m": cell, "azimuth_step_deg": AZIMUTH_STEP_DEG,
            "representative_days": 12, "sun_samples": len(weights),
            "coverage_fraction": float(known.mean()), "local_x": s, "local_y": t,
            "access": score, "known": known, "horizons": horizons, "direction_coverage": coverage,
            "mean_direct_sun_access": float(score[known].mean()) if known.any() else None,
            "winter_direct_sun_access": float(winter_score[known].mean()) if winter_score is not None and known.any() else None,
            "method": "DSM horizon rays; incidence-weighted direct sun on 12 representative days, not annual energy loss"}


def sunlight_exclusions(profile, roof, minimum_access):
    """Block heavily shaded sampled cells; unknown cells are disclosed separately."""
    if not profile.get("available"):
        return roof.intersection(box(0, 0, 0, 0))
    blocked = profile["known"] & (profile["access"] < minimum_access)
    half = profile["cell_size_m"]/2
    s, t = profile["local_x"][blocked], profile["local_y"][blocked]
    return unary_union(box(s-half, t-half, s+half, t+half)).intersection(roof)


def public_sunlight(profile):
    return {k: v for k, v in profile.items() if k not in {"local_x", "local_y", "access", "known", "horizons", "direction_coverage"}}


def instantaneous_shadow(profile, roof, normal, ray):
    """Reuse cached horizons for a single sun direction; return shade and unknown."""
    empty = roof.difference(roof)
    if "horizons" not in profile:
        return empty, roof
    if ray[2] <= 0 or float(np.dot(normal, ray)) <= 0:
        return roof, empty
    azimuth = math.degrees(math.atan2(ray[0], ray[1])) % 360
    index = round(azimuth / AZIMUTH_STEP_DEG) % profile["horizons"].shape[1]
    known = profile["direction_coverage"][:, index] >= .98
    blocked = known & (math.asin(float(np.clip(ray[2], -1, 1))) <= profile["horizons"][:, index])
    half = profile["cell_size_m"] / 2

    def cells(mask):
        return unary_union([box(x-half, y-half, x+half, y+half)
            for x, y in zip(profile["local_x"][mask], profile["local_y"][mask])]).intersection(roof)

    # Unsampled slivers are also unknown, never silently clear.
    return cells(blocked), roof.difference(cells(known))
