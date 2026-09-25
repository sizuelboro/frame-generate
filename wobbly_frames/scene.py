"""Shared draw list. Both the SVG writer and the PNG rasteriser consume the same
scene, so the exported PNG always corresponds exactly to the SVG / preview."""
from __future__ import annotations


def scene(frame):
    ops = []
    if frame.params.background:
        from .colors import hex_to_rgb
        ops.append(dict(kind="background", rgb=hex_to_rgb(frame.params.background)))
    if frame.edge_outer is not None:
        ops.append(dict(kind="fill", id="paper-edge", rgb=frame.edge_rgb,
                        contours=[frame.edge_outer, frame.opening]))
    t = frame.texture
    paper = dict(kind="fill", id="paper", rgb=frame.paper_rgb,
                 contours=[frame.outer, frame.inner])
    if t.gradient is not None:
        paper["gradient"] = t.gradient
    ops.append(paper)
    if len(t.specks_dark):
        ops.append(dict(kind="dots", id="grain-dark", rgb=t.dark_rgb, opacity=t.speck_opacity, dots=t.specks_dark))
    if len(t.specks_light):
        ops.append(dict(kind="dots", id="grain-light", rgb=t.light_rgb, opacity=t.speck_opacity, dots=t.specks_light))
    if len(t.fibers):
        ops.append(dict(kind="fibers", id="fibers", rgb=t.fiber_rgb, opacity=t.fiber_opacity,
                        width=t.fiber_width, fibers=t.fibers))
    return ops
