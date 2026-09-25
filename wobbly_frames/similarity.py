"""Shape-based duplicate detection (colour is deliberately ignored)."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from . import geometry as G

DUPLICATE_THRESHOLD = 2.4   # combined distance (in % of frame size) below which frames are duplicates


@dataclass
class Signature:
    outer: np.ndarray
    inner: np.ndarray
    aspect: float
    edge: str
    border: float
    roughness: float


def signature(frame) -> Signature:
    c = np.array([frame.width / 2, frame.height / 2])
    hw, hh = frame.width / 2, frame.height / 2
    o = frame.outer.flatten()
    i = frame.opening.flatten()
    per = float(np.sum(np.linalg.norm(np.diff(np.vstack([o, o[:1]]), axis=0), axis=1)))
    lo, hi = o.min(0), o.max(0)
    rough = per / (2 * float(np.sum(hi - lo)))
    return Signature(outer=G.polar_profile(o, c, hw, hh), inner=G.polar_profile(i, c, hw, hh),
                     aspect=math.log(frame.width / frame.height), edge=frame.design.get("edge", ""),
                     border=float(np.mean(frame.design.get("side_borders", [0]))) / 10.0,
                     roughness=rough)


def distance(a: Signature, b: Signature) -> float:
    ro = float(np.sqrt(np.mean((a.outer - b.outer) ** 2))) * 100
    ri = float(np.sqrt(np.mean((a.inner - b.inner) ** 2))) * 100
    asp = abs(a.aspect - b.aspect) * 100
    edge = 0.0 if a.edge == b.edge else 3.0
    bord = abs(a.border - b.border)
    rough = abs(a.roughness - b.roughness) * 100
    return math.sqrt(ro ** 2 + ri ** 2 + asp ** 2 + edge ** 2 + bord ** 2 + rough ** 2)


def similarity_percent(a, b) -> float:
    return round(100 * math.exp(-distance(a, b) / 6.0), 1)


def is_duplicate(sig, others, threshold=DUPLICATE_THRESHOLD):
    best = None
    for k, o in enumerate(others):
        d = distance(sig, o)
        if best is None or d < best[1]:
            best = (k, d)
    return (best is not None and best[1] < threshold), best
