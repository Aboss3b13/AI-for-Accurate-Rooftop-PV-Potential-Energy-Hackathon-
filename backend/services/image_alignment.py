"""Line the map geometry up with the roof as the photograph actually shows it.

SWISSIMAGE is orthorectified against the terrain, not against buildings, so a
building leans away from the point the camera was over. Its roof is therefore
drawn a couple of metres from where its coordinates put it, and the distance
grows with height. Measured on real captures: a Binzstrasse warehouse is 2.9 m
out, a Ruemlang house 1.8 m, and in different directions.

That is not cosmetic. Roof outline, chimneys and terrain exclusions come from
map coordinates while existing arrays and rooflights are found in the image, so
an uncorrected offset applies each set to the wrong part of the other's roof.

The correction is a single translation per capture, found by sliding the roof
outline over the image's own edges and keeping the position where it sits on
them best. It is only believed when it clearly beats leaving the geometry where
it was, and when the best position is not at the edge of the search - there the
true optimum lies further out and the answer would be a guess.
"""

import cv2
import numpy as np

# A building leans by roughly its height times the tangent of the off-nadir
# angle, so a few metres covers the range worth searching.
SEARCH_M = 4.0
STEP_PX = 1
# The shifted outline must sit on this much more edge than the unshifted one.
MIN_GAIN = 1.15
# Points sampled along the outline; enough for a stable score, few enough to
# keep the search interactive.
MAX_SAMPLES = 1200
# The winning position must sit on real structure. Without this, an outline
# starting on blank ground scores near zero, any flicker of noise beats it by a
# wide ratio, and the estimator confidently aligns to nothing.
STRONG_EDGE_PERCENTILE = 90
MIN_EDGE_FRACTION = 0.35


def _boundary_points(ring, spacing=1.0):
    """Evenly spaced points along a closed polygon boundary, in pixels."""
    points = np.asarray(ring, dtype=np.float64)
    if len(points) < 3:
        return np.empty((0, 2))
    closed = np.vstack([points, points[:1]])
    segments = np.diff(closed, axis=0)
    lengths = np.hypot(segments[:, 0], segments[:, 1])
    total = float(lengths.sum())
    if total <= 0:
        return np.empty((0, 2))
    count = int(min(MAX_SAMPLES, max(32, total / max(spacing, 0.5))))
    targets = np.linspace(0, total, count, endpoint=False)
    walked = np.concatenate([[0.0], np.cumsum(lengths)])
    out = []
    for distance in targets:
        index = int(np.searchsorted(walked, distance, side="right") - 1)
        index = min(max(index, 0), len(segments) - 1)
        along = (distance - walked[index]) / max(lengths[index], 1e-9)
        out.append(closed[index] + along * segments[index])
    return np.asarray(out)


def edge_strength(image) -> np.ndarray:
    """Where the photograph has structure, smoothed so a near miss still scores."""
    grey = cv2.GaussianBlur(np.asarray(image, dtype=np.float32).mean(2), (3, 3), 0)
    gx = cv2.Sobel(grey, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(grey, cv2.CV_32F, 0, 1, ksize=3)
    return cv2.GaussianBlur(np.hypot(gx, gy), (0, 0), 1.5)


def estimate_shift(image, ring, pixels_per_metre, search_m=SEARCH_M) -> dict:
    """Translation in pixels that puts the outline on the roof in the image."""
    blank = {"shift_px": (0.0, 0.0), "shift_m": (0.0, 0.0),
             "applied": False, "gain": None,
             "reason": "no usable outline", "search_m": search_m}
    if pixels_per_metre <= 0:
        return blank
    points = _boundary_points(ring)
    if not len(points):
        return blank
    edges = edge_strength(image)
    height, width = edges.shape
    reach = int(round(search_m * pixels_per_metre))
    if reach < 1:
        return {**blank, "reason": "search window smaller than a pixel"}

    def score(dx, dy):
        xs = np.rint(points[:, 0] + dx).astype(int)
        ys = np.rint(points[:, 1] + dy).astype(int)
        inside = (xs >= 0) & (xs < width) & (ys >= 0) & (ys < height)
        if inside.sum() < len(points) * 0.6:
            return -1.0
        return float(edges[ys[inside], xs[inside]].mean())

    strong = float(np.percentile(edges, STRONG_EDGE_PERCENTILE))
    here = score(0, 0)
    best, best_dx, best_dy = here, 0, 0
    for dy in range(-reach, reach + 1, STEP_PX):
        for dx in range(-reach, reach + 1, STEP_PX):
            value = score(dx, dy)
            if value > best:
                best, best_dx, best_dy = value, dx, dy
    gain = best / here if here > 0 else None

    if here <= 0:
        return {**blank, "reason": "the image has no edges to align to"}
    if gain is None or gain < MIN_GAIN:
        return {**blank, "gain": round(gain, 3) if gain else None,
                "reason": "the outline already sits on the roof"}
    if strong <= 0 or best < MIN_EDGE_FRACTION * strong:
        return {**blank, "gain": round(gain, 3),
                "reason": "no position puts the outline on real structure"}
    if max(abs(best_dx), abs(best_dy)) >= reach:
        # The peak is against the wall of the search; the real one is further
        # out and this would be a guess.
        return {**blank, "gain": round(gain, 3),
                "reason": f"best fit reached the {search_m:g} m search limit"}
    return {"shift_px": (float(best_dx), float(best_dy)),
            "shift_m": (round(best_dx / pixels_per_metre, 2),
                        round(best_dy / pixels_per_metre, 2)),
            "applied": True, "gain": round(gain, 3),
            "reason": "aligned to the roof edges in the photograph",
            "search_m": search_m}
