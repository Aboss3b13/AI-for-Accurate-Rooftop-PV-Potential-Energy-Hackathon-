"""Orthonormal roof coordinates. World XY: LV95 metres; Z: DSM LN02 metres.

Local u/v are surface metres, never image pixels. Using a nearby origin avoids
loss of precision at Swiss eastings of roughly 2.6 million metres.
"""
from dataclasses import dataclass, field
import math
import numpy as np
from shapely.ops import transform


@dataclass
class RoofPlane:
    origin: np.ndarray
    u: np.ndarray
    v: np.ndarray
    normal: np.ndarray
    source: str = "projected_2d"
    diagnostics: dict = field(default_factory=dict)

    @classmethod
    def from_slopes(cls, x, y, z=0., a=0., b=0., source="projected_2d", diagnostics=None):
        normal = np.array([-a, -b, 1.], dtype=np.float64)
        normal /= np.linalg.norm(normal)
        # An eastward tangent, followed by its orthogonal northward tangent.
        u = np.array([1., 0., a], dtype=np.float64)
        u /= np.linalg.norm(u)
        v = np.cross(normal, u)
        return cls(np.array([x, y, z], dtype=np.float64), u, v, normal,
                   source, diagnostics or {})

    def to_local(self, x, y, z=None):
        dx, dy = np.asarray(x) - self.origin[0], np.asarray(y) - self.origin[1]
        dz = -(self.normal[0] * dx + self.normal[1] * dy) / self.normal[2]
        return (dx*self.u[0] + dy*self.u[1] + dz*self.u[2],
                dx*self.v[0] + dy*self.v[1] + dz*self.v[2])

    def to_world(self, s, t, z=None):
        s, t = np.asarray(s), np.asarray(t)
        return (self.origin[0] + s*self.u[0] + t*self.v[0],
                self.origin[1] + s*self.u[1] + t*self.v[1])

    def xyz(self, s, t):
        return self.origin + s*self.u + t*self.v

    def local_geometry(self, geometry):
        return transform(self.to_local, geometry)

    def world_geometry(self, geometry):
        return transform(self.to_world, geometry)

    def describe(self):
        pitch = math.degrees(math.acos(float(np.clip(self.normal[2], -1, 1))))
        matrix = np.eye(4)
        matrix[:3, :] = np.column_stack((self.u, self.v, self.normal, self.origin))
        return {**self.diagnostics, "source": self.source,
                "origin_lv95_ln02": self.origin.tolist(), "u": self.u.tolist(),
                "v": self.v.tolist(), "normal": self.normal.tolist(),
                "pitch_deg": pitch,
                "azimuth_deg": (math.degrees(math.atan2(self.normal[0], self.normal[1])) % 360)
                    if pitch > .1 else None,
                "azimuth_convention": "clockwise from north; flat faces have no azimuth",
                "surface_area_factor": 1 / float(self.normal[2]),
                "local_to_world": matrix.tolist(),
                "world_to_local": np.linalg.inv(matrix).tolist(),
                "height_is_absolute": self.diagnostics.get("height_is_absolute", self.source == "swisssurface3d")}


def plane_from_fit(geometry, fitted, minx, maxy, step=.5):
    x, y = geometry.centroid.coords[0]
    fallback = {"point_count": 0, "inlier_count": 0, "rmse_m": None}
    if fitted:
        fallback.update({k: v for k, v in fitted.items() if k != "residual"})
        col, row, intercept = fitted["coefficients"]
        a, b = col / step, -row / step
        z = col*((x-minx)/step-.5) + row*((maxy-y)/step-.5) + intercept
        if (fitted["rank"] == 3 and fitted["inlier_count"] >= 12
                and fitted["rmse_m"] <= .25 and math.hypot(a, b) < math.tan(math.radians(75))):
            return RoofPlane.from_slopes(x, y, z, a, b, "swisssurface3d", fallback)
    fallback["fallback_reason"] = "Insufficient or unreliable DSM plane; packing in projected metres."
    return RoofPlane.from_slopes(x, y, diagnostics=fallback)


def official_plane(geometry, properties, measured=None, samples=None):
    """Use surveyed Sonnendach angles instead of flattening a failed DSM fit.

    Official aspect is south=0, east=-90. DSM anchors height independently:
    it must not change roof dimensions just because a dormer dominates samples.
    """
    try:
        pitch = float(properties["neigung"])
        aspect = float(properties.get("ausrichtung", 0) if pitch < .1 else properties["ausrichtung"])
        if not math.isfinite(pitch + aspect) or not (0 <= pitch < 85 and -180 <= aspect <= 180):
            raise ValueError("Invalid official angles")
    except (KeyError, TypeError, ValueError):
        return measured or RoofPlane.from_slopes(*geometry.centroid.coords[0])
    azimuth = math.radians((aspect + 180) % 360)
    slope = math.tan(math.radians(pitch))
    a, b = -slope*math.sin(azimuth), -slope*math.cos(azimuth)
    x, y = geometry.centroid.coords[0]
    details = {"angle_source": "Sonnendach official roof face", "height_is_absolute": False,
               "point_count": 0, "geometry_conflict": False,
               "roof_record_updated": properties.get("datum_aenderung")}
    try:
        expected = float(properties["flaeche"])*geometry.area/float(properties.get("_source_projected_area", geometry.area))
        derived = geometry.area/math.cos(math.radians(pitch))
        if expected > 0 and math.isfinite(expected):
            details.update(reported_surface_area_m2=expected, derived_surface_area_m2=derived,
                           area_disagreement_fraction=abs(derived-expected)/expected)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    z = 0.
    if measured:
        details.update({"dsm_fit": measured.describe(), "point_count": measured.diagnostics.get("point_count", 0)})
        dsm = measured.describe()
        difference = abs(dsm["pitch_deg"] - pitch)
        az_difference = abs(((dsm["azimuth_deg"] or 0) - math.degrees(azimuth) + 180) % 360 - 180)
        details.update(pitch_disagreement_deg=difference, azimuth_disagreement_deg=az_difference)
        details["geometry_conflict"] = bool(measured.source == "swisssurface3d"
            and details["point_count"] >= 80 and (difference > 15 or (pitch > 10 and dsm["pitch_deg"] > 10 and az_difference > 35)))
    if samples is not None:
        xs, ys, heights = samples
        offsets = heights - a*(xs-x) - b*(ys-y)
        offsets = offsets[np.isfinite(offsets)]
        details["point_count"] = int(offsets.size)
        if offsets.size >= 12:
            z = float(np.percentile(offsets, 25))
            residual = offsets - z
            deck = residual[np.abs(residual) <= .35]
            details.update(height_anchor_m=z, height_inlier_count=int(deck.size),
                           height_rmse_m=float(np.sqrt(np.mean(deck**2))) if deck.size else None)
            details["height_is_absolute"] = bool(deck.size >= 12 and deck.size/offsets.size >= .4)
            details["height_anchor"] = "measured" if details["height_is_absolute"] else None
        if not details["height_is_absolute"] and offsets.size >= 6:
            # Shading needs to know roughly how high the roof sits, not how well
            # its slope was recovered. Refusing the strict deck test left 36% of
            # faces with no shade screening at all, which is worse than an
            # approximate one that says so.
            z = float(np.median(offsets))
            details.update(height_anchor_m=z, height_anchor="approximate",
                           height_is_absolute=True)
    details["plane_equation"] = {"a_dz_dx": a, "b_dz_dy": b, "z_at_origin": z}
    return RoofPlane.from_slopes(x, y, z, a, b, "sonnendach", details)
