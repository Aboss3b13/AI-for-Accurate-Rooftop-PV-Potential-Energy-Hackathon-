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
                "height_is_absolute": self.source == "swisssurface3d"}


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
