"""Deterministic physical grid search. Coordinates are pixels; dimensions are metres."""

import math
import numpy as np
import shapely
from shapely.affinity import rotate

MAX_CANDIDATES = 120_000
OFFSET_STEPS = 4


def optimise_panels(usable, ppm, panel, angle=0):
    if usable.is_empty:
        return [], "portrait"
    origin = usable.centroid.coords[0]
    aligned = rotate(usable, -angle, origin=origin)
    minx, miny, maxx, maxy = aligned.bounds
    best, orientation = [], "portrait"
    for name, w, h in [
        ("portrait", panel.width, panel.height),
        ("landscape", panel.height, panel.width),
    ]:
        width, height = w * ppm, h * ppm
        dx, dy = (w + panel.gap) * ppm, (h + panel.gap) * ppm
        count = math.ceil((maxx - minx) / dx) * math.ceil((maxy - miny) / dy)
        if count > MAX_CANDIDATES:
            raise ValueError(
                "Scale creates too many candidate panels. Check your measurement or select a smaller roof."
            )
        for ox in np.arange(OFFSET_STEPS) / OFFSET_STEPS:
            for oy in np.arange(OFFSET_STEPS) / OFFSET_STEPS:
                xs = np.arange(minx + ox * dx, maxx - width + 1e-7, dx)
                ys = np.arange(miny + oy * dy, maxy - height + 1e-7, dy)
                if not len(xs) or not len(ys):
                    continue
                xx, yy = np.meshgrid(xs, ys)
                candidates = shapely.box(
                    xx.ravel(), yy.ravel(), xx.ravel() + width, yy.ravel() + height
                )
                valid = candidates[shapely.covers(aligned, candidates)]
                if len(valid) > len(best):
                    best, orientation = list(valid), name
    return [
        list(rotate(p, angle, origin=origin).exterior.coords)[:-1] for p in best
    ], orientation
