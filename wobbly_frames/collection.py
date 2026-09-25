"""Batch generation with controlled diversity, QA and duplicate rejection."""
from __future__ import annotations

import numpy as np

from .engine import generate_frame, MAX_SEED
from .params import FrameParams, PAPER_COLORS
from .similarity import signature, is_duplicate, DUPLICATE_THRESHOLD

# Curated archetypes: one designer's family of frames. Each fixes the *structure*
# (style, silhouette, corners, opening) while leaving room for seeded variation.
ARCHETYPES = [
    dict(label="Minimal Wobbly Rectangle", style="Wobbly", wobble=16, asymmetry=10, corner_variation=12, border="Medium", silhouette="straight", corner_style="soft", opening="parallel", ratios=["4:5", "3:4", "2:3"]),
    dict(label="Soft Organic Rectangle", style="Organic", wobble=30, asymmetry=18, corner_variation=25, border="Medium", silhouette="pillow", corner_style="soft", opening="soft", ratios=["4:5", "3:4", "4:3"]),
    dict(label="Wobbly Square", style="Wobbly", wobble=26, asymmetry=15, corner_variation=20, border="Medium", silhouette="bowed", ratios=["1:1"]),
    dict(label="Hand-Cut Portrait", style="Hand-Cut", wobble=28, asymmetry=30, corner_variation=30, border="Medium", corner_style="handcut", ratios=["2:3", "3:4", "5:7"]),
    dict(label="Hand-Cut Landscape", style="Hand-Cut", wobble=26, asymmetry=28, corner_variation=30, border="Thick", corner_style="crisp", ratios=["3:2", "4:3", "16:9"]),
    dict(label="Soft Torn Frame", style="Soft Torn", wobble=22, asymmetry=18, corner_variation=20, border="Thick", ratios=["4:5", "1:1", "3:4"]),
    dict(label="Light Deckled Frame", style="Deckled", wobble=14, asymmetry=10, corner_variation=12, border="Thick", opening="parallel", ratios=["5:7", "4:5", "2:3"]),
    dict(label="Rounded Wobbly Frame", style="Wobbly", wobble=24, asymmetry=12, corner_variation=20, border="Thick", corner_style="rounded", opening="rounded", ratios=["4:5", "1:1", "3:2"]),
    dict(label="Asymmetric Editorial Frame", style="Editorial", wobble=18, asymmetry=55, corner_variation=25, border="Thick", opening="asymmetric", ratios=["3:4", "4:5", "4:3"]),
    dict(label="Thick Border Frame", style="Wobbly", wobble=22, asymmetry=15, corner_variation=20, border="Extra-Thick", silhouette="bowed", ratios=["1:1", "4:5", "3:2"]),
    dict(label="Thin Border Frame", style="Wobbly", wobble=18, asymmetry=12, corner_variation=15, border="Thin", corner_style="crisp", ratios=["2:3", "16:9", "3:2"]),
    dict(label="Playful Organic Frame", style="Organic", wobble=52, asymmetry=40, corner_variation=45, border="Thick", silhouette="crooked", corner_style="uneven", opening="irregular", ratios=["1:1", "4:5", "4:3"]),
    dict(label="Crooked Handmade Frame", style="Hand-Cut", wobble=36, asymmetry=55, corner_variation=45, border="Medium", silhouette="crooked", corner_style="uneven", opening="irregular", ratios=["4:5", "3:4", "4:3"]),
    dict(label="Minimal Premium Frame", style="Editorial", wobble=18, asymmetry=10, corner_variation=10, border="Medium", silhouette="straight", corner_style="crisp", opening="parallel", ratios=["4:5", "2:3", "5:7"]),
    dict(label="Organic Square", style="Organic", wobble=36, asymmetry=20, corner_variation=35, border="Thick", corner_style="rounded", ratios=["1:1"]),
    dict(label="Soft Corner Frame", style="Wobbly", wobble=20, asymmetry=12, corner_variation=30, border="Medium", corner_style="soft", opening="soft", ratios=["3:2", "4:3", "4:5"]),
    dict(label="Uneven Edge Frame", style="Soft Torn", wobble=32, asymmetry=30, corner_variation=35, border="Medium", silhouette="crooked", corner_style="uneven", opening="irregular", ratios=["4:3", "3:2", "3:4"]),
    dict(label="Modern Editorial Frame", style="Editorial", wobble=22, asymmetry=25, corner_variation=15, border="Thick", silhouette="bowed", corner_style="soft", opening="offset", ratios=["4:5", "3:4", "1:1"]),
    dict(label="Bold Organic Frame", style="Organic", wobble=45, asymmetry=30, corner_variation=40, border="Extra-Thick", silhouette="pillow", corner_style="rounded", opening="rounded", ratios=["1:1", "4:5", "4:3"]),
    dict(label="Luxury Minimal Frame", style="Editorial", wobble=17, asymmetry=8, corner_variation=8, border="Extra-Thick", silhouette="straight", corner_style="crisp", opening="offset", ratios=["5:7", "4:5", "2:3"]),
]

PALETTE_ORDER = ["Warm White", "Sage", "Blush", "Cream", "Soft Blue", "Terracotta", "Lavender",
                 "Ivory", "Dusty Pink", "Butter Yellow", "Beige", "Charcoal", "Brown", "Black"]


def _jitter(rng, v, rel=0.25, lo=0, hi=100):
    return float(np.clip(round(v * (1 + rng.uniform(-rel, rel))), lo, hi))


def recipe(arch, rng, base: FrameParams, ratio_mode, color, seed, fixed_arch=False):
    a = dict(arch)
    ratios = a.pop("ratios")
    label = a.pop("label")
    p = base.copy(**a, label=label, preset=None, seed=seed, color=color)
    if ratio_mode == "mixed":
        p.ratio = ratios[int(rng.integers(len(ratios)))] if not fixed_arch else ratios[0]
    else:
        p.ratio = base.ratio
    if not fixed_arch:
        p.wobble = _jitter(rng, p.wobble)
        p.asymmetry = _jitter(rng, p.asymmetry)
        p.corner_variation = _jitter(rng, p.corner_variation)
    return p


def generate_collection(count, base: FrameParams, collection_seed=1, ratio_mode="mixed",
                        color_mode="current", archetypes=None, progress=None, log=None,
                        cancel=None, threshold=DUPLICATE_THRESHOLD, fixed_first=False):
    """Return a list of validated, mutually distinct frames."""
    rng = np.random.default_rng(int(collection_seed))
    archetypes = archetypes or ARCHETYPES
    order = []
    while len(order) < count:
        perm = list(rng.permutation(len(archetypes))) if not fixed_first or order else list(range(len(archetypes)))
        if order and perm[0] == order[-1]:
            perm = perm[1:] + perm[:1]
        order += perm
    order = order[:count]
    frames, sigs, stats = [], [], dict(rejected_duplicates=0, qa_retries=0)
    for n, ai in enumerate(order):
        if cancel and cancel():
            break
        color = base.color if color_mode == "current" else PAPER_COLORS[PALETTE_ORDER[n % len(PALETTE_ORDER)]]
        for attempt in range(30):
            seed = int(rng.integers(1, MAX_SEED))
            p = recipe(archetypes[ai], rng, base, ratio_mode, color, seed, fixed_arch=fixed_first and n < len(archetypes) and attempt == 0)
            fr = generate_frame(p, log=log)
            stats["qa_retries"] += fr.attempts - 1
            sig = signature(fr)
            dup, best = is_duplicate(sig, sigs, threshold)
            if not dup:
                break
            stats["rejected_duplicates"] += 1
            if log:
                log.info("frame %d too similar to #%d (d=%.2f) - regenerating", n + 1, best[0] + 1, best[1])
        frames.append(fr)
        sigs.append(sig)
        if progress:
            progress(n + 1, count, fr)
    return frames, stats
