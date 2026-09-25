"""Subtle, clean vector paper texture: tonal gradient, fine grain and a few fibres.
Everything is vector (no raster images, no SVG filters) so it stays editable."""
from __future__ import annotations

import math
import numpy as np

from . import geometry as G
from .colors import shade, luminance

LEVELS = {
    # grain density (units^2 per speck), fibre density, gradient span, opacity multiplier
    "Light":  dict(speck_area=600.0, fiber_area=7000.0, grad=0.022, op=1.0),
    "Medium": dict(speck_area=260.0, fiber_area=3200.0, grad=0.038, op=1.4),
}


def _inside_ring(pts, outer, inner, pad):
    ok = G.points_in_polygon(pts, outer) & ~G.points_in_polygon(pts, inner)
    for dx, dy in ((pad, 0), (-pad, 0), (0, pad), (0, -pad)):
        q = pts + np.array([dx, dy])
        ok &= G.points_in_polygon(q, outer) & ~G.points_in_polygon(q, inner)
    return ok


def make_texture(frame, rng):
    from .engine import Texture
    tex = Texture()
    level = frame.params.texture
    if level not in LEVELS:
        return tex
    cfg = LEVELS[level]
    paper = frame.paper_rgb
    lum = luminance(paper)
    dark = lum < 0.35

    # tonal variation: very soft linear gradient across the sheet
    ang = rng.uniform(0, 2 * math.pi)
    cx, cy = frame.width / 2, frame.height / 2
    R = 0.5 * math.hypot(frame.width, frame.height)
    x1, y1 = cx - math.cos(ang) * R, cy - math.sin(ang) * R
    x2, y2 = cx + math.cos(ang) * R, cy + math.sin(ang) * R
    g = cfg["grad"]
    tex.gradient = (round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1),
                    shade(paper, g * (1.6 if dark else 1.0)), shade(paper, -g))

    outer = frame.outer.flatten()
    inner = frame.inner.flatten()
    ring_area = abs(G.polygon_area(outer)) - abs(G.polygon_area(inner))
    lo, hi = outer.min(0), outer.max(0)

    def sample(n, pad):
        pts = rng.uniform(lo, hi, (int(n * 2.2) + 8, 2))
        pts = pts[_inside_ring(pts, outer, inner, pad)]
        return pts[:n]

    n_specks = int(ring_area / cfg["speck_area"])
    pts = sample(n_specks, 3.0)
    r = rng.uniform(0.22, 0.6, len(pts))
    tone = rng.random(len(pts)) < (0.6 if dark else 0.35)   # light vs dark grain
    tex.specks_light = np.round(np.column_stack([pts[tone], r[tone]]), 2)
    tex.specks_dark = np.round(np.column_stack([pts[~tone], r[~tone]]), 2)
    tex.dark_rgb = shade(paper, -0.35)
    tex.light_rgb = shade(paper, 0.6 if dark else 0.75)
    tex.speck_opacity = round(min(0.25, (0.13 if dark else 0.09) * cfg["op"]), 3)

    n_f = int(ring_area / cfg["fiber_area"])
    fp = sample(n_f, 14.0)
    fib = []
    for (x, y) in fp:
        L = rng.uniform(5, 16)
        a = rng.uniform(0, math.pi)
        dx, dy = math.cos(a) * L / 2, math.sin(a) * L / 2
        bend = rng.uniform(-0.35, 0.35) * L
        nx, ny = -math.sin(a) * bend, math.cos(a) * bend
        fib.append((x - dx, y - dy, x + nx, y + ny, x + dx, y + dy))
    tex.fibers = np.round(np.array(fib).reshape(-1, 6), 2)
    tex.fiber_rgb = shade(paper, 0.5) if dark else shade(paper, -0.22)
    tex.fiber_opacity = round(min(0.3, (0.1 if dark else 0.14) * cfg["op"]), 3)
    tex.fiber_width = 0.45
    return tex
