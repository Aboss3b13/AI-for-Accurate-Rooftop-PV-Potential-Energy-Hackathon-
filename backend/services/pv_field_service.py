"""Existing PV arrays found by colour, to back up the segmentation model.

The trained checkpoint is good on its own test split but misses large arrays on
real captures: on a Binzstrasse warehouse whose roof is half covered in modules
it returned three small patches, and 396 new modules were proposed straight on
top of the existing array.

Silicon under anti-reflective coating is strongly blue where clay, concrete,
gravel and bitumen are red- or brown-dominant, so an array separates from its
own roof on the blue-minus-red axis. The split is found with Otsu rather than a
fixed cut, because roofs differ, and the result is only believed when the bright
class is blue in absolute terms as well as relative ones - otherwise the bluer
half of a plain grey roof would be called an array.

Unlike the rooflight test this compares against the whole roof, not a local
neighbourhood: an array is metres across, and a local background subtraction
cancels exactly the large uniform regions being looked for.
"""

import cv2
import numpy as np
from shapely.geometry import Polygon

# The bright class must be genuinely blue, not merely the bluer half of grey.
# A plain Oerlikon roof split its parapet and a shaded band at +15; the arrays
# on a Binzstrasse warehouse sit at +30.
MIN_ABSOLUTE_BLUE = 18.0
# ...and the two classes must actually be distinct populations.
MIN_SEPARATION = 14.0
# When even the darker class is this blue, both sides of the split are array.
# Measured on a roof region that is all modules: the darker modules sit at +17
# against a plain roof's zero, and the two classes are only 11 apart - which the
# separation guard would otherwise read as "no array here" and return nothing.
COVERED_DARK_BLUE = 12.0
# A roof that is nearly all "bright" has no contrast to learn from; it is more
# likely blue-grey sheeting than a fully covered array. A real full-coverage
# roof is refused here, which is the safer of the two mistakes.
MAX_BRIGHT_SHARE = 0.92
# An array is at least a couple of modules.
MIN_AREA_M2 = 3.0
MAX_ARRAYS = 30
EDGE_MARGIN_M = 0.3
# Modules carry cell and frame lines, so an array is never smoother than the
# roof it sits on. This rejects smooth blue-grey metal sheeting.
MIN_TEXTURE_RATIO = 1.0
# An array is a compact block of modules. The same Oerlikon roof produced a
# ragged edge band at 0.45; the real arrays measured 0.61 and above.
MIN_SOLIDITY = 0.55
# Second route, for a dark array on a red-tile roof. There the modules never
# reach the absolute blue floor - a Gruenmattstrasse roof runs -38 to +1 on that
# axis - but they are 20 units bluer and 65 grey levels darker than the tiles
# around them. An array is always darker than its roof; the parapet band that
# once passed for one was lighter, which is what separates the two.
MIN_RELATIVE_BLUE = 12.0
MIN_DARKNESS = 25.0
MIN_DARK_SEPARATION = 30.0
MAX_DARK_SHARE = 0.60
# Gaps between module rows, and the odd vent standing inside an array, should
# not break one field into fragments.
CLOSE_M = 1.2
MAX_HOLE_M2 = 15.0


def _mask_from(polygon, shape) -> np.ndarray:
    mask = np.zeros(shape, np.uint8)
    if polygon.geom_type == "MultiPolygon":
        for part in polygon.geoms:
            mask |= _mask_from(part, shape)
        return mask
    if polygon.is_empty or polygon.geom_type != "Polygon":
        return mask
    cv2.fillPoly(mask, [np.array(polygon.exterior.coords, np.int32)], 1)
    for interior in polygon.interiors:
        cv2.fillPoly(mask, [np.array(interior.coords, np.int32)], 0)
    return mask


def split_threshold(values: np.ndarray) -> tuple[float, float, float, float, float]:
    """Otsu split of the roof's blue-minus-red values, in original units.

    Returns the threshold, the mean of each class, their separation and the
    bright class's share. The dark class matters: if it is array-blue too, the
    split fell inside one array rather than between array and roof.
    """
    low, high = (float(v) for v in np.percentile(values, [1, 99]))
    span = max(high - low, 1e-6)
    scaled = np.clip((values - low) / span * 255, 0, 255).astype(np.uint8)
    level, _ = cv2.threshold(
        scaled.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    threshold = low + level / 255.0 * span
    bright = values[values >= threshold]
    dark = values[values < threshold]
    if bright.size == 0 or dark.size == 0:
        return threshold, 0.0, 0.0, 0.0, 0.0
    return (threshold, float(bright.mean()), float(bright.mean() - dark.mean()),
            float(bright.size) / values.size, float(dark.mean()))


def fill_small_holes(mask: np.ndarray, max_pixels: int) -> np.ndarray:
    """Close interior gaps an array should not be broken by, keeping real ones."""
    if max_pixels <= 0:
        return mask
    holes = (mask == 0).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(holes, 4)
    filled = mask.copy()
    border = set(labels[0].tolist()) | set(labels[-1].tolist())
    border |= set(labels[:, 0].tolist()) | set(labels[:, -1].tolist())
    for index in range(1, count):
        # A hole touching the frame is outside the array, not inside it.
        if index in border or stats[index, 4] > max_pixels:
            continue
        filled[labels == index] = 1
    return filled


def detect(
    image: np.ndarray,
    roof: Polygon,
    pixels_per_metre: float,
    exclude: list[Polygon] | None = None,
) -> list[dict]:
    """Return existing-array polygons in image pixels."""
    if roof.is_empty or pixels_per_metre <= 0:
        return []
    rgb = image.astype(np.float32)
    inside = _mask_from(roof, rgb.shape[:2])
    edge = max(1, int(round(EDGE_MARGIN_M * pixels_per_metre)))
    inside = cv2.erode(inside, np.ones((edge * 2 + 1, edge * 2 + 1), np.uint8))
    for other in exclude or []:
        if not other.is_empty and other.geom_type == "Polygon":
            inside[_mask_from(other, rgb.shape[:2]).astype(bool)] = 0
    core = inside.astype(bool)
    if int(core.sum()) < int(MIN_AREA_M2 * pixels_per_metre**2):
        return []

    blue = rgb[..., 2] - rgb[..., 0]
    grey = rgb.mean(2)
    roof_blue = float(np.median(blue[core]))
    roof_grey = float(np.median(grey[core]))
    threshold, bright_mean, separation, share, dark_mean = split_threshold(blue[core])
    covered = dark_mean >= COVERED_DARK_BLUE
    blue_route = covered or not (
        bright_mean < MIN_ABSOLUTE_BLUE or separation < MIN_SEPARATION
        or share > MAX_BRIGHT_SHARE)

    # Darkness read the same way: "bright" here means the darker class.
    dark_cut, dark_side, dark_sep, dark_share, _ = split_threshold(-grey[core])
    # Only where the blue cue cannot work. Darkness is the weaker signal: on a
    # light gravel roof it sweeps in shade and darker bare roof, which inflated
    # a Binzstrasse warehouse from an accurate 1,621 m2 to 2,035 m2.
    dark_route = (not blue_route
                  and dark_sep >= MIN_DARK_SEPARATION
                  and dark_share <= MAX_DARK_SHARE
                  and (-dark_side) <= roof_grey - MIN_DARKNESS)
    if not blue_route and not dark_route:
        return []
    if covered:
        # Both classes are array-blue, so Otsu divided one array into its
        # brighter and darker modules instead of separating it from the roof.
        # On a face that is all array the two are 11 apart, the separation guard
        # rejects it, and every module is missed. Take the whole blue field; the
        # texture and solidity checks still have to agree it is an array.
        threshold = float(np.percentile(blue[core], 2))

    hit = np.zeros(core.shape, np.uint8)
    if blue_route:
        hit |= (core & (blue >= threshold)).astype(np.uint8)
    if dark_route:
        hit |= (core & (grey <= -dark_cut)).astype(np.uint8)
    # Open first to drop speckle, then close the gaps between module rows so an
    # array reads as one region rather than a comb of stripes.
    hit = cv2.morphologyEx(hit, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    # Close across a module row, so the gaps between rows do not split one array
    # into a comb of stripes.
    span = max(3, int(round(CLOSE_M * pixels_per_metre)) | 1)
    hit = cv2.morphologyEx(hit, cv2.MORPH_CLOSE, np.ones((span, span), np.uint8))
    hit = fill_small_holes(hit, int(MAX_HOLE_M2 * pixels_per_metre**2))
    if not hit.any():
        return []

    texture = np.abs(cv2.Laplacian(rgb.mean(2), cv2.CV_32F, ksize=3))
    roof_texture = float(np.median(texture[core])) or 1.0
    cell = 1.0 / (pixels_per_metre**2)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(hit, 8)
    found = []
    for index in range(1, count):
        pixels = stats[index, 4]
        if pixels * cell < MIN_AREA_M2:
            continue
        part = labels == index
        if float(texture[part].mean()) / roof_texture < MIN_TEXTURE_RATIO:
            continue
        # Either strongly blue in its own right, or darker than the roof while
        # still being relatively bluer than it. Shade is darker too, which the
        # texture ratio above is there to refuse.
        mean_blue = float(blue[part].mean())
        mean_grey = float(grey[part].mean())
        if not (mean_blue >= MIN_ABSOLUTE_BLUE
                or (mean_blue - roof_blue >= MIN_RELATIVE_BLUE
                    and roof_grey - mean_grey >= MIN_DARKNESS)):
            continue
        contours, _ = cv2.findContours(
            part.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        if not contours:
            continue
        contour = max(contours, key=cv2.contourArea)
        epsilon = max(1.0, 0.01 * cv2.arcLength(contour, True))
        approx = cv2.approxPolyDP(contour, epsilon, True).reshape(-1, 2)
        if len(approx) < 3:
            continue
        polygon = Polygon([(float(x), float(y)) for x, y in approx])
        if not polygon.is_valid:
            polygon = polygon.buffer(0)
        if polygon.geom_type != "Polygon" or polygon.is_empty:
            continue
        # Measured from the component's own pixels, not the traced outline:
        # findContours drops holes, so a hollow ring would otherwise trace as a
        # filled rectangle and score a perfect solidity.
        hull = polygon.convex_hull.area
        if hull <= 0 or pixels / hull < MIN_SOLIDITY:
            continue
        found.append(
            {
                "geometry": polygon,
                "area_m2": round(polygon.area * cell, 2),
                "blue_shift": round(float(blue[part].mean()), 1),
                "darker_than_roof": round(roof_grey - float(grey[part].mean()), 1),
            }
        )
    found.sort(key=lambda o: -o["area_m2"])
    return found[:MAX_ARRAYS]
