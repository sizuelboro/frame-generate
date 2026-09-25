"""Procedural Wobbly Paper Frame engine.

Pipeline (each stage is deterministic for a given seed):
  1. resolve design  - style defaults + seeded choice of silhouette / corners / opening
  2. base geometry   - native-ratio outer quad, per-corner radii, inset inner quad
  3. wobble engine   - controlled normal displacement (low-freq wobble, side bows,
                       organic mid-freq, hand-cut facets, torn / deckled fibres)
  4. edge detail     - optional light paper-core edge for torn / deckled paper
  5. composition     - centre + fit inside canvas safe area (no clipping)
  6. texture         - subtle vector grain + fibres (paper ring only)
  7. validation      - geometry / border / opening / composition QA
Invalid designs are rejected and regenerated with a deterministic derived seed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geometry as G
from .params import FrameParams, RATIOS, BORDERS
from .colors import hex_to_rgb, mix, luminance, rgb_to_hex

S = 1000.0          # short side of the canvas in SVG user units
MARGIN = 0.035 * S  # transparent safe area around the frame
MAX_SEED = 2 ** 31 - 1

# ------------------------------------------------------------------ style table
STYLE_TABLE = {
    #            edge      low  mid  corner choices                       silhouettes                                  openings
    "Wobbly":   dict(edge="smooth",  low=1.0, mid=0.35, corners=["soft", "crisp", "uneven", "rounded"],
                     sil=["bowed", "straight", "pillow", "crooked", "tapered"],
                     open=["parallel", "soft", "irregular", "rounded"]),
    "Organic":  dict(edge="organic", low=1.25, mid=1.0, corners=["rounded", "soft", "uneven"],
                     sil=["pillow", "bowed", "tapered", "crooked"],
                     open=["rounded", "soft", "irregular", "asymmetric"]),
    "Hand-Cut": dict(edge="handcut", low=0.8, mid=0.0, corners=["handcut", "crisp", "uneven"],
                     sil=["crooked", "straight", "tapered", "bowed"],
                     open=["parallel", "irregular", "asymmetric"]),
    "Soft Torn": dict(edge="torn",   low=0.8, mid=0.4, corners=["soft", "crisp", "uneven"],
                     sil=["straight", "bowed", "crooked"],
                     open=["parallel", "irregular", "soft"]),
    "Deckled":  dict(edge="deckle",  low=0.6, mid=0.2, corners=["crisp", "soft"],
                     sil=["straight", "bowed", "pillow"],
                     open=["parallel", "soft", "offset"]),
    "Editorial": dict(edge="smooth", low=0.9, mid=0.2, corners=["crisp", "soft", "rounded"],
                     sil=["straight", "bowed", "crooked"],
                     open=["offset", "asymmetric", "parallel"]),
}

EDGE_OVERRIDE = {"Smooth": "smooth", "Organic": "organic", "Hand-cut": "handcut"}


@dataclass
class Contour:
    kind: str                 # "bezier" | "poly"
    anchors: np.ndarray       # (n,2) rounded anchor points
    c1: np.ndarray | None = None
    c2: np.ndarray | None = None

    def flatten(self):
        if self.kind == "poly":
            return self.anchors
        p3 = np.roll(self.anchors, -1, axis=0)
        steps = 3 if len(self.anchors) > 600 else 5
        return G.flatten_beziers(self.anchors, self.c1, self.c2, p3, steps=steps)

    def transformed(self, s, t):
        f = lambda a: None if a is None else a * s + t
        return Contour(self.kind, f(self.anchors), f(self.c1), f(self.c2))

    def rounded(self, nd=2):
        r = lambda a: None if a is None else np.round(a, nd)
        return Contour(self.kind, r(self.anchors), r(self.c1), r(self.c2))


@dataclass
class Texture:
    specks_dark: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))   # x,y,r
    specks_light: np.ndarray = field(default_factory=lambda: np.zeros((0, 3)))
    fibers: np.ndarray = field(default_factory=lambda: np.zeros((0, 6)))        # x0,y0,cx,cy,x1,y1
    dark_rgb: tuple = (0, 0, 0)
    light_rgb: tuple = (255, 255, 255)
    fiber_rgb: tuple = (0, 0, 0)
    speck_opacity: float = 0.0
    fiber_opacity: float = 0.0
    fiber_width: float = 0.5
    gradient: tuple | None = None  # (x1,y1,x2,y2,rgb_a,rgb_b)


@dataclass
class Frame:
    params: FrameParams
    seed_used: int
    width: int
    height: int
    outer: Contour
    inner: Contour
    edge_outer: Contour | None
    edge_inner: Contour | None
    paper_rgb: tuple
    edge_rgb: tuple | None
    texture: Texture
    design: dict
    report: dict = field(default_factory=dict)
    attempts: int = 1

    @property
    def opening(self) -> Contour:
        return self.edge_inner if self.edge_inner is not None else self.inner

    @property
    def silhouette(self) -> Contour:
        return self.outer


# ------------------------------------------------------------------ helpers
def canvas_size(ratio):
    rw, rh = RATIOS[ratio]
    if rw >= rh:
        return int(round(S * rw / rh)), int(S)
    return int(S), int(round(S * rh / rw))


def derive_seed(seed, attempt):
    if attempt == 0:
        return int(seed)
    return int((int(seed) * 2654435761 + attempt * 40503 + 97) % MAX_SEED) or 1


def _line_intersect(p1, d1, p2, d2):
    A = np.array([[d1[0], -d2[0]], [d1[1], -d2[1]]])
    t = np.linalg.solve(A, p2 - p1)
    return p1 + d1 * t[0]


def _inset_quad(C, widths):
    """Offset each side of convex clockwise quad inward by widths[i]; return new corners."""
    lines = []
    for i in range(4):
        a, b = C[i], C[(i + 1) % 4]
        d = G._unit(b - a)
        n_in = -np.array([d[1], -d[0]])
        lines.append((a + n_in * widths[i], d))
    out = []
    for j in range(4):
        p1, d1 = lines[j - 1]
        p2, d2 = lines[j]
        out.append(_line_intersect(p1, d1, p2, d2))
    return np.array(out)


def _pick(rng, options, value):
    if value and value != "auto":
        return value
    return options[int(rng.integers(len(options)))]


# ------------------------------------------------------------------ design
def resolve_design(p: FrameParams, rng, atten=1.0):
    st = STYLE_TABLE[p.style]
    edge = EDGE_OVERRIDE.get(p.edge, st["edge"]) if p.edge != "Auto" else st["edge"]
    d = dict(
        style=p.style, edge=edge,
        silhouette=_pick(rng, st["sil"], p.silhouette),
        corner_style=_pick(rng, st["corners"], p.corner_style),
        opening=_pick(rng, st["open"], p.opening),
        w=np.clip(p.wobble / 100.0, 0, 1) * atten,
        a=np.clip(p.asymmetry / 100.0, 0, 1) * atten,
        c=np.clip(p.corner_variation / 100.0, 0, 1) * atten,
        low=st["low"], mid=st["mid"],
    )
    if edge == "organic":
        d["mid"] = max(d["mid"], 0.9)
    if edge == "handcut":
        d["mid"] = 0.0
    return d


def _corner_radii(rng, d):
    cs, c = d["corner_style"], d["c"]
    base = {"soft": (0.022, 0.040), "rounded": (0.060, 0.095), "crisp": (0.006, 0.013),
            "handcut": (0.003, 0.008), "uneven": (0.010, 0.030)}[cs]
    r0 = rng.uniform(*base) * S
    spread = {"uneven": 0.9, "handcut": 0.6}.get(cs, 0.35) * (0.25 + c)
    radii = r0 * np.clip(1 + rng.uniform(-0.6, 1.0, 4) * spread, 0.25, 2.6)
    return radii


def _outer_corners(rng, d, W, H):
    cx, cy = W / 2, H / 2
    hw, hh = W / 2 - MARGIN - 0.02 * S, H / 2 - MARGIN - 0.02 * S
    C = np.array([[cx - hw, cy - hh], [cx + hw, cy - hh], [cx + hw, cy + hh], [cx - hw, cy + hh]])
    a, sil = d["a"], d["silhouette"]
    jit = S * (0.003 + 0.013 * a) * (1.6 if sil == "crooked" else 1.0)
    C = C + rng.normal(0, 1, (4, 2)) * jit
    if sil == "tapered":           # one side slightly shorter -> subtle trapezoid
        side = int(rng.integers(4))
        amt = S * rng.uniform(0.008, 0.02) * (0.6 + a)
        i, j = side, (side + 1) % 4
        mid = (C[i] + C[j]) / 2
        C[i] += G._unit(mid - C[i]) * amt
        C[j] += G._unit(mid - C[j]) * amt
    rot = 0.0
    if sil == "crooked":
        rot = math.radians(rng.uniform(0.5, 1.4) * (0.6 + a) * rng.choice([-1, 1]))
    elif a > 0.3:
        rot = math.radians(rng.uniform(-0.5, 0.5) * a)
    if rot:
        R = np.array([[math.cos(rot), -math.sin(rot)], [math.sin(rot), math.cos(rot)]])
        C = (C - [cx, cy]) @ R.T + [cx, cy]
    return C


def _side_widths(rng, d, border_frac):
    w = BORDERS[border_frac] * S if isinstance(border_frac, str) else border_frac
    op, a = d["opening"], d["a"]
    f = np.ones(4)                       # top, right, bottom, left
    f += rng.uniform(-1, 1, 4) * 0.12 * a
    if op == "offset":                   # gallery / polaroid style heavier bottom
        f[2] *= rng.uniform(1.35, 1.75)
        f[0] *= rng.uniform(0.95, 1.05)
    elif op == "asymmetric":
        k = int(rng.integers(4))
        f[k] *= rng.uniform(1.3, 1.6) + 0.25 * a
        f[(k + 2) % 4] *= rng.uniform(0.85, 0.95)
    return w * f, w


def _bows(rng, d, amp):
    sil = d["silhouette"]
    if sil == "pillow":
        b = rng.uniform(0.55, 1.0, 4) * amp * 1.3
    elif sil == "bowed":
        b = rng.uniform(-0.4, 1.0, 4) * amp
        k = int(rng.integers(2))
        b[k] = rng.uniform(0.8, 1.3) * amp * rng.choice([1, 1, -0.6])
        b[k + 2] = rng.uniform(0.5, 1.1) * amp
    elif sil == "straight":
        b = rng.uniform(-0.25, 0.4, 4) * amp
    else:
        b = rng.uniform(-0.5, 0.8, 4) * amp
    return b


def _displace(rng, base, d, scale, S_, lows=None, inner=False):
    """Return displacement along normals for a sampled base contour."""
    L, P = base["L"], base["perimeter"]
    side, u = base["side"], base["u"]
    w = d["w"]
    edge = d["edge"]
    disp = np.zeros(len(L))
    low_amp = S_ * 0.013 * w * d["low"] * scale
    low = G.PeriodicNoise(rng, P, P / 8, P / 2, low_amp, n_terms=6, beta=1.2)
    own = low(L)
    if lows is not None:                  # correlate inner with outer for even borders
        ref = lows(L / P * lows.P)
        own = 0.55 * ref + 0.6 * own
    disp += own
    bows = _bows(rng, d, S_ * 0.0085 * (0.3 + w) * scale)
    on_side = side >= 0
    disp[on_side] += bows[side[on_side]] * np.sin(math.pi * u[on_side])
    if d["mid"] > 0 and edge in ("smooth", "organic", "torn", "deckle"):
        mid = G.PeriodicNoise(rng, P, 0.08 * S_, 0.22 * S_,
                              S_ * 0.0019 * (0.35 + w) * d["mid"] * scale, n_terms=10, beta=0.8)
        disp += mid(L)
    if edge == "handcut":
        cut = rng.uniform(-1, 1, len(L)) * S_ * 0.0085 * (0.6 + w) * scale
        cut[~on_side] = 0.0
        cut[on_side & (u == 0)] = 0.0      # keep corners crisp, no notches beside them
        disp += cut
    elif edge == "torn":
        t1 = G.PeriodicNoise(rng, P, 0.014 * S_, 0.06 * S_, S_ * 0.0019 * (0.7 + 0.6 * w), n_terms=40, beta=1.1)
        t2 = G.PeriodicNoise(rng, P, 0.0055 * S_, 0.014 * S_, S_ * 0.00045, n_terms=50, beta=0.8)
        disp += t1(L) + t2(L)
    elif edge == "deckle":
        k = 0.55 if inner else 1.0
        t1 = G.PeriodicNoise(rng, P, 0.009 * S_, 0.028 * S_, S_ * 0.0016 * k, n_terms=60, beta=0.7)
        v = t1(L)
        env = 0.75 + 0.25 * G.PeriodicNoise(rng, P, 0.1 * S_, 0.3 * S_, 1.0, n_terms=6)(L)
        sab = np.sqrt(v ** 2 + (0.35 * S_ * 0.0016) ** 2)
        disp += (sab - np.mean(sab)) * 1.5 * env                # soft rounded scallops
        t2 = G.PeriodicNoise(rng, P, 0.005 * S_, 0.01 * S_, S_ * 0.00035 * k, n_terms=50, beta=0.6)
        disp += t2(L)
    # never push a corner arc inward past ~70% of its radius (prevents loops)
    disp = np.maximum(disp, -0.7 * base["r"])
    return disp, low


def _sampling(d):
    e = d["edge"]
    if e in ("torn", "deckle"):
        return dict(ds_side=2.4, arc_step_deg=4.0, arc_ds=2.4)
    if e == "handcut":
        return dict(ds_side=None, arc_step_deg=30.0, arc_ds=None)
    return dict(ds_side=20.0, arc_step_deg=12.0, arc_ds=None)


def _knots(rng, C):
    ks = []
    for i in range(4):
        n = int(rng.integers(3, 7))
        g = rng.uniform(0.5, 1.5, n + 1)
        pos = np.cumsum(g)[:-1] / np.sum(g)
        ks.append(pos)
    return ks


def _build_contour(pts, edge):
    if edge in ("smooth", "organic", "deckle"):
        p0, c1, c2, _ = G.catmull_rom_beziers(pts)
        return Contour("bezier", p0, c1, c2)
    return Contour("poly", pts)


def _fiber_edge(rng, pts, nrm, L, P, sign, strength, r=None):
    f = G.PeriodicNoise(rng, P, 0.005 * S, 0.014 * S, 0.0006 * S * strength, n_terms=50, beta=0.7)
    g = G.PeriodicNoise(rng, P, 0.03 * S, 0.12 * S, 0.0022 * S * strength, n_terms=12, beta=0.9)
    fv = f(L)
    gv = g(L)
    soft_pos = 0.5 * (gv + np.sqrt(gv ** 2 + (0.0008 * S) ** 2))   # smooth max(g, 0)
    off = 0.0012 * S * strength + np.sqrt(fv ** 2 + (0.0003 * S) ** 2) + soft_pos * 1.6
    if sign < 0 and r is not None:
        off = np.minimum(off, 0.6 * r)
    return pts + nrm * (sign * off)[:, None]


def build_frame(p: FrameParams, seed: int, atten=1.0) -> Frame:
    rng = np.random.default_rng(int(seed))
    W, H = canvas_size(p.ratio)
    d = resolve_design(p, rng, atten)
    edge = d["edge"]
    samp = _sampling(d)

    # --- outer
    C_out = _outer_corners(rng, d, W, H)
    r_out = _corner_radii(rng, d)
    knots = _knots(rng, C_out) if edge == "handcut" else None
    base_o = G.sample_rounded_quad(C_out, r_out, samp["ds_side"] or 1e9, samp["arc_step_deg"], knots, samp["arc_ds"])
    disp_o, low_o = _displace(rng, base_o, d, 1.0, S)
    outer_pts = base_o["pts"] + base_o["nrm"] * disp_o[:, None]

    # --- inner opening (native to the ratio: inset per side, not scaled)
    widths, w_nom = _side_widths(rng, d, p.border)
    C_in = _inset_quad(C_out, widths)
    op = d["opening"]
    if op == "irregular":
        C_in = C_in + rng.normal(0, 1, (4, 2)) * S * (0.004 + 0.008 * d["a"])
    if op == "rounded":
        r_in = rng.uniform(0.045, 0.085) * S * np.clip(1 + rng.uniform(-0.3, 0.3, 4) * d["c"], 0.6, 1.4)
    elif op == "soft":
        r_in = rng.uniform(0.018, 0.035) * S * np.ones(4) * np.clip(1 + rng.uniform(-0.4, 0.4, 4) * d["c"], 0.5, 1.5)
    else:
        r_in = np.maximum(r_out * rng.uniform(0.35, 0.7), 0.004 * S)
    knots_i = _knots(rng, C_in) if edge == "handcut" else None
    base_i = G.sample_rounded_quad(C_in, r_in, samp["ds_side"] or 1e9, samp["arc_step_deg"], knots_i, samp["arc_ds"])
    in_scale = {"parallel": 0.5, "offset": 0.45, "soft": 0.7, "rounded": 0.6,
                "irregular": 0.9, "asymmetric": 0.7}[op]
    d_inner = dict(d)
    if edge == "deckle":           # deckled paper keeps a clean, softly wobbled window
        d_inner["edge"] = "smooth"
    disp_i, _ = _displace(rng, base_i, d_inner, in_scale, S, lows=low_o, inner=True)
    inner_pts = base_i["pts"] + base_i["nrm"] * disp_i[:, None]

    # --- optional paper edge detail (light paper core on torn / deckled edges)
    eo = ei = None
    paper = hex_to_rgb(p.color)
    edge_rgb = None
    if edge in ("torn", "deckle"):
        strength = 1.0 if edge == "torn" else 0.6
        eo_pts = _fiber_edge(rng, outer_pts, base_o["nrm"], base_o["L"], base_o["perimeter"], +1, strength)
        eo = _build_contour(eo_pts, edge)
        if edge == "torn":
            ei_pts = _fiber_edge(rng, inner_pts, base_i["nrm"], base_i["L"], base_i["perimeter"], -1, 0.8, base_i["r"])
            ei = Contour("poly", ei_pts)
        core = (244, 240, 232) if luminance(paper) < 0.45 else (255, 253, 249)
        edge_rgb = mix(paper, core, 0.62 if luminance(paper) < 0.45 else 0.7)

    outer = _build_contour(outer_pts, edge)
    inner = _build_contour(inner_pts, d_inner["edge"])

    # --- composition: centre + fit into safe area (uniform scale)
    allpts = np.vstack([c.flatten() for c in (outer, eo) if c is not None])
    lo, hi = allpts.min(0), allpts.max(0)
    s = min((W - 2 * MARGIN) / (hi[0] - lo[0]), (H - 2 * MARGIN) / (hi[1] - lo[1]))
    t = np.array([W / 2, H / 2]) - (lo + hi) / 2 * s
    outer = outer.transformed(s, t).rounded()
    inner = inner.transformed(s, t).rounded()
    eo = eo.transformed(s, t).rounded() if eo is not None else None
    ei = ei.transformed(s, t).rounded() if ei is not None else None

    frame = Frame(params=p.copy(seed=int(seed)), seed_used=int(seed), width=W, height=H,
                  outer=outer, inner=inner, edge_outer=eo, edge_inner=ei,
                  paper_rgb=paper, edge_rgb=edge_rgb, texture=Texture(), design=d)
    frame.design = {k: (round(float(v), 3) if isinstance(v, (float, np.floating)) else v) for k, v in d.items()}
    frame.design["nominal_border"] = round(float(w_nom * s), 2)
    frame.design["side_borders"] = [round(float(x * s), 1) for x in widths]
    frame.design["corner_radii"] = [round(float(x * s), 1) for x in r_out]

    from .texture import make_texture
    frame.texture = make_texture(frame, rng)
    return frame


def generate_frame(p: FrameParams, max_attempts=40, log=None) -> Frame:
    """Generate a *validated* frame. The same params+seed always gives the same frame.
    If the requested seed fails QA, deterministic derived seeds are tried."""
    from .validate import validate_frame
    atten = 1.0
    last = None
    for attempt in range(max_attempts):
        if attempt and attempt % 10 == 0:
            atten *= 0.85                     # safety: soften extreme settings
        sd = derive_seed(p.seed, attempt)
        fr = build_frame(p, sd, atten)
        ok, report = validate_frame(fr)
        fr.report = report
        fr.attempts = attempt + 1
        if ok:
            if log and attempt:
                log.info("seed %s failed QA; accepted derived seed %s after %d attempts",
                         p.seed, sd, attempt + 1)
            return fr
        last = fr
        if log:
            log.debug("rejected seed %s: %s", sd, report.get("failures"))
    raise RuntimeError(f"Could not produce a valid frame (last failures: {last.report.get('failures')})")
