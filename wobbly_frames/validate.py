"""Quality control: geometry, border, opening, composition and commercial usability.
Validation runs on the *exact* rounded geometry that is exported."""
from __future__ import annotations

import numpy as np

from . import geometry as G
from .engine import S, MARGIN

RULES = dict(
    min_border_abs=0.032 * S,      # never thinner than 3.2% of short side
    min_border_rel=0.58,           # >= 58% of the thinnest nominal side border
    min_open_area=0.30,            # opening >= 30% of the silhouette area
    min_open_dim=0.45,             # opening min dimension >= 45% of silhouette's
    min_solidity_outer=0.955,      # area / convex hull (no dents / blobs)
    min_solidity_inner=0.955,
    min_rectangularity=0.86,       # area / bbox area (rectangle family, not blob)
    max_turn_smooth=40.0,          # degrees between flattened segments
    max_turn_rough=75.0,
    max_turn_handcut=100.0,
    max_center_offset=0.012 * S,
    border_evenness=0.42,          # min local border >= 42% of max local border (per side)
)


def _side_border_profile(outer, inner, nominal):
    """Local border width sampled from inner points to the outer contour."""
    return G.min_dist_points_to_polyline(inner, outer)


def validate_frame(frame):
    f = []
    rep = {}
    outer = frame.outer.flatten()
    inner = frame.inner.flatten()
    opening = frame.opening.flatten()
    contours = {"outer": outer, "inner": inner}
    if frame.edge_outer is not None:
        contours["edge_outer"] = frame.edge_outer.flatten()
    if frame.edge_inner is not None:
        contours["edge_inner"] = frame.edge_inner.flatten()

    # --- geometry
    for name, c in contours.items():
        if len(c) < 8 or not np.all(np.isfinite(c)):
            f.append(f"broken path: {name}")
            continue
        if not G.is_simple_polygon(c):
            f.append(f"self-intersection: {name}")
    rough = frame.design.get("edge") in ("torn", "deckle", "handcut")
    lim = RULES["max_turn_rough"] if rough else RULES["max_turn_smooth"]
    if frame.design.get("edge") == "handcut":
        lim = RULES["max_turn_handcut"]
    for name in ("outer", "inner"):
        c = contours[name]
        if rough and len(c) > 400:   # judge macro shape; fibre detail is intentionally jagged
            k = 5
            c = np.stack([np.convolve(np.concatenate([c[-k:, i], c[:, i], c[:k, i]]), np.ones(2 * k + 1) / (2 * k + 1), "valid") for i in (0, 1)], 1)[::3]
        t = G.max_turn_angle(c)
        rep[f"max_turn_{name}"] = round(t, 1)
        if t > lim:
            f.append(f"collapsed/sharp corner on {name} ({t:.0f} deg)")

    A_out = abs(G.polygon_area(outer))
    A_in = abs(G.polygon_area(opening))
    sol_o = A_out / G.convex_hull_area(outer)
    sol_i = abs(G.polygon_area(inner)) / G.convex_hull_area(inner)
    lo, hi = outer.min(0), outer.max(0)
    rect = A_out / float(np.prod(hi - lo))
    rep.update(solidity_outer=round(sol_o, 4), solidity_inner=round(sol_i, 4), rectangularity=round(rect, 4))
    solid_lim = RULES["min_solidity_outer"] - (0.02 if rough else 0)
    if sol_o < solid_lim:
        f.append("extreme distortion: outer dents")
    if sol_i < RULES["min_solidity_inner"] - (0.02 if rough else 0):
        f.append("awkward narrow areas in opening")
    if rect < RULES["min_rectangularity"]:
        f.append("silhouette too blob-like")

    # --- border
    if not np.all(G.points_in_polygon(inner, outer)):
        f.append("opening breaks through border (hole)")
    local = G.min_dist_points_to_polyline(opening, outer)
    min_b = float(local.min())
    nominal = min(frame.design.get("side_borders", [frame.design.get("nominal_border", 90)]))
    rep["min_border"] = round(min_b, 2)
    rep["nominal_min_side"] = round(float(nominal), 2)
    if min_b < max(RULES["min_border_abs"], RULES["min_border_rel"] * nominal):
        f.append(f"border too thin ({min_b:.1f})")

    # --- opening
    ilo, ihi = opening.min(0), opening.max(0)
    rep["open_area_ratio"] = round(A_in / A_out, 3)
    if A_in / A_out < RULES["min_open_area"]:
        f.append("photo opening too small")
    if min(ihi - ilo) < RULES["min_open_dim"] * min(hi - lo):
        f.append("photo opening too narrow")

    # --- composition
    allc = np.vstack(list(contours.values()))
    alo, ahi = allc.min(0), allc.max(0)
    if alo[0] < MARGIN * 0.6 or alo[1] < MARGIN * 0.6 or ahi[0] > frame.width - MARGIN * 0.6 or ahi[1] > frame.height - MARGIN * 0.6:
        f.append("clipping risk: outside safe area")
    cen = G.polygon_centroid(outer)
    off = float(np.hypot(cen[0] - frame.width / 2, cen[1] - frame.height / 2))
    rep["center_offset"] = round(off, 2)
    if off > RULES["max_center_offset"]:
        f.append("frame not centred")
    rep["failures"] = f
    rep["valid"] = not f
    return (not f), rep
