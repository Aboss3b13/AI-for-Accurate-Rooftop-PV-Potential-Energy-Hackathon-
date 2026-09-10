"""Which roof faces physically belong to the building the user clicked.

Sonnendach's building_id groups faces by record, not by structure. Two roofs on
opposite sides of a courtyard can carry the same id, and seeding a selection
with every face that shares one pulls unrelated polygons into the analysis - a
growth loop that only ever adds can never take them back out.

So the id is treated as a source of candidates and nothing more. Faces become a
graph, the traversal starts at the face under the click, and a face joins only
when geometry says it is attached: a shared edge of real length, or genuine
overlap. Proximity alone is not attachment, and neither is a shared corner.

Every candidate keeps the reason it was accepted or refused, because the
question "why is this roof part of my building?" has to be answerable.
"""

from shapely.ops import unary_union

# A survey gap between two faces of one roof, and the length of common edge
# that separates a real join from a passing corner.
TOUCH_TOLERANCE_M = 0.35
MIN_SHARED_EDGE_M = 1.5
MIN_OVERLAP_M2 = 0.5


def _identity(plane) -> str | None:
    egid = plane["properties"].get("gwr_egid")
    return str(egid) if egid else None


def link_reason(a, b, tolerance=TOUCH_TOLERANCE_M) -> str | None:
    """Why these two faces are one structure, or None if they are not."""
    first, second = a["geometry"], b["geometry"]
    overlap = first.intersection(second).area
    if overlap > MIN_OVERLAP_M2:
        return f"overlaps {b['id']} by {overlap:.1f} m²"
    if first.distance(second) <= tolerance:
        shared = first.boundary.intersection(second.buffer(tolerance)).length
        if shared >= MIN_SHARED_EDGE_M:
            return f"shares a {shared:.1f} m edge with {b['id']}"
    return None


def select_connected(planes, bridge=None, tolerance=TOUCH_TOLERANCE_M):
    """Grow the clicked face outwards through physical contact.

    `bridge(a, b)` is an optional second opinion from measured elevation: it is
    asked only about pairs geometry already accepts, and can veto a link where
    the surface between the two faces is not building at all.

    Returns the accepted faces and a decision record for every candidate.
    """
    if not planes:
        return [], []
    anchor = next((p for p in planes if p.get("contains_click")), planes[0])
    known = {_identity(anchor)} - {None}

    accepted = [anchor]
    accepted_ids = {anchor["id"]}
    decisions = {anchor["id"]: {"id": anchor["id"], "accepted": True,
                                "reason": "contains the click",
                                "building_id": anchor["properties"].get("building_id"),
                                "egid": _identity(anchor), "contains_click": True}}
    for plane in planes:
        decisions.setdefault(plane["id"], {
            "id": plane["id"], "accepted": False,
            "reason": "no physical connection to the clicked roof",
            "building_id": plane["properties"].get("building_id"),
            "egid": _identity(plane),
            "contains_click": bool(plane.get("contains_click"))})

    changed = True
    while changed:
        changed = False
        for plane in planes:
            if plane["id"] in accepted_ids:
                continue
            egid = _identity(plane)
            if egid and known and egid not in known:
                decisions[plane["id"]]["reason"] = (
                    f"a different building (EGID {egid})")
                continue
            for member in accepted:
                reason = link_reason(plane, member, tolerance)
                if not reason:
                    continue
                if bridge is not None and not bridge(plane, member):
                    decisions[plane["id"]]["reason"] = (
                        f"touches {member['id']} but no building surface bridges them")
                    continue
                accepted.append(plane)
                accepted_ids.add(plane["id"])
                if egid:
                    known.add(egid)
                decisions[plane["id"]].update(accepted=True, reason=reason)
                changed = True
                break

    order = {p["id"]: i for i, p in enumerate(planes)}
    accepted.sort(key=lambda p: order.get(p["id"], 0))
    return accepted, [decisions[p["id"]] for p in planes]


def rejected_summary(decisions) -> dict:
    """Counts for the warning line, so a dropped roof is never silent."""
    refused = [d for d in decisions if not d["accepted"]]
    shared_id = [d for d in refused
                 if d["building_id"] is not None
                 and any(a["building_id"] == d["building_id"]
                         for a in decisions if a["accepted"])]
    return {"candidates": len(decisions),
            "accepted": sum(1 for d in decisions if d["accepted"]),
            "rejected": len(refused),
            "rejected_sharing_building_id": len(shared_id)}


def overview(accepted):
    """One outline for the map only. Calculations stay per face."""
    if not accepted:
        return None
    return unary_union([p["geometry"] for p in accepted])
