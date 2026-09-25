"""Vector utilities: periodic noise, rounded-quad sampling, bezier fitting,
polygon predicates (self-intersection, containment, distances)."""
from __future__ import annotations

import math
import numpy as np


# --------------------------------------------------------------------------- noise
class PeriodicNoise:
    """Band-limited, seamlessly periodic 1-D noise along a closed contour.

    Frequencies are integer cycles per perimeter so the contour always closes
    smoothly (no seam). Amplitude is the RMS displacement."""

    def __init__(self, rng, perimeter, lam_min, lam_max, amp, n_terms=12, beta=1.0):
        self.P = float(perimeter)
        m_lo = max(1, int(math.ceil(self.P / lam_max)))
        m_hi = max(m_lo, int(math.floor(self.P / lam_min)))
        ms = np.arange(m_lo, m_hi + 1)
        if len(ms) > n_terms:
            ms = np.sort(rng.choice(ms, n_terms, replace=False))
        self.m = ms.astype(float)
        w = self.m ** (-beta) * rng.uniform(0.6, 1.0, len(ms))
        w = w / math.sqrt(0.5 * float(np.sum(w ** 2)) + 1e-12)
        self.a = w * amp
        self.phi = rng.uniform(0, 2 * math.pi, len(ms))

    def __call__(self, L):
        L = np.asarray(L, float)[:, None]
        return np.sum(self.a * np.sin(2 * math.pi * self.m * L / self.P + self.phi), axis=1)


# ------------------------------------------------------------------- base contour
def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def sample_rounded_quad(corners, radii, ds_side, arc_step_deg=12.0, side_knots=None, arc_ds=None):
    """Sample a convex quad (clockwise on screen, y down) with filleted corners.

    Returns dict(pts, nrm, L, side, u, perimeter). `side` is 0..3 on straight
    segments and -1 on corner arcs; `u` is the 0..1 position along a side.
    If side_knots is given (list of 4 arrays of u positions) straight sides are
    sampled exactly at those knots (used for hand-cut facets)."""
    C = [np.asarray(c, float) for c in corners]
    n = len(C)
    tangents = []
    for i in range(n):
        p_prev, p, p_next = C[i - 1], C[i], C[(i + 1) % n]
        u1 = _unit(p - p_prev)
        u2 = _unit(p_next - p)
        cos_t = float(np.clip(np.dot(-u1, u2), -1, 1))
        theta = math.acos(cos_t)  # interior angle
        max_t = 0.42 * min(np.linalg.norm(p - p_prev), np.linalg.norm(p_next - p))
        r = radii[i]
        t = r / math.tan(theta / 2)
        if t > max_t:
            t = max_t
            r = t * math.tan(theta / 2)
        T1 = p - u1 * t
        T2 = p + u2 * t
        bis = _unit(-u1 + u2)
        ctr = p + bis * (r / math.sin(theta / 2))
        tangents.append((T1, T2, ctr, r))

    pts, nrm, side_id, uu, rad = [], [], [], [], []
    for i in range(n):
        # arc at corner i
        T1, T2, ctr, r = tangents[i]
        a1 = math.atan2(T1[1] - ctr[1], T1[0] - ctr[0])
        a2 = math.atan2(T2[1] - ctr[1], T2[0] - ctr[0])
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        k = max(2, int(math.ceil(abs(math.degrees(da)) / arc_step_deg)))
        if arc_ds:
            k = max(2, min(k, int(math.ceil(abs(da) * r / arc_ds)) + 1))
        for j in range(k):
            a = a1 + da * j / k
            d = np.array([math.cos(a), math.sin(a)])
            pts.append(ctr + d * r)
            nrm.append(d)
            side_id.append(-1)
            uu.append(0.0)
            rad.append(r)
        # straight side from corner i to corner i+1
        S0 = tangents[i][1]
        S1 = tangents[(i + 1) % n][0]
        seg = S1 - S0
        length = np.linalg.norm(seg)
        dirv = _unit(seg)
        nr = np.array([dirv[1], -dirv[0]])
        if side_knots is not None:
            us = [0.0] + [float(x) for x in side_knots[i]]
        else:
            m = max(1, int(math.ceil(length / ds_side)))
            us = [j / m for j in range(m)]
        for uj in us:
            pts.append(S0 + seg * uj)
            nrm.append(nr)
            side_id.append(i)
            uu.append(uj)
            rad.append(1e9)
    pts = np.array(pts)
    nrm = np.array(nrm)
    d = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
    L = np.concatenate([[0.0], np.cumsum(d)[:-1]])
    return dict(pts=pts, nrm=nrm, L=L, side=np.array(side_id), u=np.array(uu), r=np.array(rad),
                perimeter=float(np.sum(d)))


# ------------------------------------------------------------- curve fitting
def catmull_rom_beziers(P):
    """Closed chord-length-aware Catmull-Rom -> list of cubic segments (p0,c1,c2,p3)."""
    n = len(P)
    prev = np.roll(P, 1, axis=0)
    nxt = np.roll(P, -1, axis=0)
    d_prev = np.linalg.norm(P - prev, axis=1) + 1e-9
    d_next = np.linalg.norm(nxt - P, axis=1) + 1e-9
    tang = (nxt - prev) / (d_prev + d_next)[:, None]  # unit-ish slope per length
    c1 = P + tang * (d_next / 3.0)[:, None]
    c2 = nxt - np.roll(tang, -1, axis=0) * (d_next / 3.0)[:, None]
    return P, c1, c2, nxt


def flatten_beziers(p0, c1, c2, p3, steps=5):
    t = np.linspace(0, 1, steps, endpoint=False)[None, :, None]
    a = p0[:, None, :]; b = c1[:, None, :]; c = c2[:, None, :]; d = p3[:, None, :]
    mt = 1 - t
    pts = mt ** 3 * a + 3 * mt ** 2 * t * b + 3 * mt * t ** 2 * c + t ** 3 * d
    return pts.reshape(-1, 2)


# ----------------------------------------------------------- polygon predicates
def polygon_area(P):
    x, y = P[:, 0], P[:, 1]
    return 0.5 * float(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def polygon_centroid(P):
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    A = 0.5 * np.sum(cr)
    return np.array([np.sum((x + x1) * cr), np.sum((y + y1) * cr)]) / (6 * A)


def convex_hull_area(P):
    pts = sorted(map(tuple, np.round(P, 6)))
    if len(pts) < 3:
        return 0.0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = np.array(lower[:-1] + upper[:-1])
    return abs(polygon_area(hull))


def points_in_polygon(pts, poly):
    """Vectorised even-odd ray casting."""
    pts = np.asarray(pts, float)
    x = pts[:, 0][:, None]; y = pts[:, 1][:, None]
    x1 = poly[:, 0][None, :]; y1 = poly[:, 1][None, :]
    x2 = np.roll(poly[:, 0], -1)[None, :]; y2 = np.roll(poly[:, 1], -1)[None, :]
    inside = np.zeros(len(pts), bool)
    step = max(1, 2_000_000 // max(1, len(poly)))
    for s in range(0, len(pts), step):
        xs, ys = x[s:s + step], y[s:s + step]
        cond = (y1 > ys) != (y2 > ys)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (ys - y1) / (y2 - y1 + 1e-300) + x1
        crossing = cond & (xs < xint)
        inside[s:s + step] = (np.sum(crossing, axis=1) % 2) == 1
    return inside


def min_dist_points_to_polyline(pts, poly):
    """For each point, min distance to the closed polyline."""
    A = poly
    B = np.roll(poly, -1, axis=0)
    AB = B - A
    ab2 = np.sum(AB ** 2, axis=1) + 1e-12
    out = np.empty(len(pts))
    step = max(1, 1_500_000 // max(1, len(poly)))
    for s in range(0, len(pts), step):
        P = pts[s:s + step][:, None, :]
        t = np.clip(np.sum((P - A[None]) * AB[None], axis=2) / ab2[None], 0, 1)
        proj = A[None] + t[..., None] * AB[None]
        out[s:s + step] = np.sqrt(np.min(np.sum((P - proj) ** 2, axis=2), axis=1))
    return out


def is_simple_polygon(P):
    """True if the closed polyline has no self-intersections (grid-accelerated)."""
    n = len(P)
    A = P
    B = np.roll(P, -1, axis=0)
    lo = np.minimum(A, B); hi = np.maximum(A, B)
    seg_len = np.linalg.norm(B - A, axis=1)
    cell = max(float(np.median(seg_len)) * 4, 1e-6)
    grid = {}
    for i in range(n):
        for gx in range(int(lo[i, 0] // cell), int(hi[i, 0] // cell) + 1):
            for gy in range(int(lo[i, 1] // cell), int(hi[i, 1] // cell) + 1):
                grid.setdefault((gx, gy), []).append(i)
    pairs = set()
    for idx in grid.values():
        if len(idx) < 2:
            continue
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                i, j = idx[a], idx[b]
                if abs(i - j) <= 1 or abs(i - j) == n - 1:
                    continue
                pairs.add((min(i, j), max(i, j)))
    if not pairs:
        return True
    pr = np.array(list(pairs))
    i, j = pr[:, 0], pr[:, 1]
    p, r = A[i], B[i] - A[i]
    q, s = A[j], B[j] - A[j]
    rxs = r[:, 0] * s[:, 1] - r[:, 1] * s[:, 0]
    qp = q - p
    with np.errstate(divide="ignore", invalid="ignore"):
        t = (qp[:, 0] * s[:, 1] - qp[:, 1] * s[:, 0]) / rxs
        u = (qp[:, 0] * r[:, 1] - qp[:, 1] * r[:, 0]) / rxs
    hit = (np.abs(rxs) > 1e-12) & (t > 1e-9) & (t < 1 - 1e-9) & (u > 1e-9) & (u < 1 - 1e-9)
    return not bool(np.any(hit))


def max_turn_angle(P):
    a = P - np.roll(P, 1, axis=0)
    b = np.roll(P, -1, axis=0) - P
    ang = np.arctan2(a[:, 0] * b[:, 1] - a[:, 1] * b[:, 0], np.sum(a * b, axis=1))
    return float(np.degrees(np.max(np.abs(ang))))


def polar_profile(P, center, half_w, half_h, n=180):
    """Radius profile (in aspect-normalised space) sampled at n angles."""
    q = (P - center) / np.array([half_w, half_h])
    ang = np.arctan2(q[:, 1], q[:, 0])
    rad = np.hypot(q[:, 0], q[:, 1])
    o = np.argsort(ang)
    ang, rad = ang[o], rad[o]
    ang = np.concatenate([ang - 2 * math.pi, ang, ang + 2 * math.pi])
    rad = np.concatenate([rad, rad, rad])
    th = np.linspace(-math.pi, math.pi, n, endpoint=False)
    return np.interp(th, ang, rad)
