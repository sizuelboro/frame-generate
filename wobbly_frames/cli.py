"""Headless command line interface.

  python -m wobbly_frames.cli frame --style Organic --ratio 4:5 --seed 42 --out out/
  python -m wobbly_frames.cli collection --count 50 --out bundle/
  python -m wobbly_frames.cli sample --out sample20/
"""
import argparse
import time

from .collection import generate_collection, ARCHETYPES
from .engine import generate_frame
from .export import export_frame, export_collection
from .log import get_logger
from .params import FrameParams, PAPER_COLORS, STYLES, RATIOS, BORDERS, TEXTURES, PRESETS, apply_preset


def _color(v):
    return PAPER_COLORS.get(v, v)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="wobbly-frames")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("frame", "collection", "sample"):
        s = sub.add_parser(name)
        s.add_argument("--out", default="output")
        s.add_argument("--style", choices=STYLES, default="Wobbly")
        s.add_argument("--preset", choices=list(PRESETS))
        s.add_argument("--ratio", choices=list(RATIOS), default="4:5")
        s.add_argument("--border", choices=list(BORDERS), default="Medium")
        s.add_argument("--wobble", type=float, default=20)
        s.add_argument("--asymmetry", type=float, default=15)
        s.add_argument("--corners", type=float, default=20)
        s.add_argument("--color", default="Warm White", help="preset name or #RRGGBB")
        s.add_argument("--texture", choices=TEXTURES, default="Light")
        s.add_argument("--seed", type=int, default=1)
        s.add_argument("--png-size", type=int, default=4000, help="PNG short side in px")
        if name == "collection":
            s.add_argument("--count", type=int, default=20)
            s.add_argument("--ratios", choices=["mixed", "current"], default="mixed")
            s.add_argument("--colors", choices=["current", "palette"], default="current")
        if name == "sample":
            s.add_argument("--colors", choices=["current", "palette"], default="palette")
    a = ap.parse_args(argv)
    log = get_logger()
    p = FrameParams(style=a.style, ratio=a.ratio, border=a.border, wobble=a.wobble, asymmetry=a.asymmetry,
                    corner_variation=a.corners, color=_color(a.color), texture=a.texture, seed=a.seed)
    if a.preset:
        p = apply_preset(p, a.preset)
    t = time.time()
    if a.cmd == "frame":
        fr = generate_frame(p, log=log)
        files = export_frame(fr, a.out, png_min_side=a.png_size)
        log.info("exported %s (seed %s)", [str(f) for f in files], fr.seed_used)
    else:
        count = a.count if a.cmd == "collection" else len(ARCHETYPES)
        frames, stats = generate_collection(
            count, p, collection_seed=a.seed, ratio_mode=getattr(a, "ratios", "mixed"),
            color_mode=a.colors, log=log, fixed_first=(a.cmd == "sample"),
            progress=lambda i, n, fr: log.info("generated %d/%d  %s  seed=%s", i, n, fr.params.label, fr.seed_used))
        log.info("QA stats: %s", stats)
        export_collection(frames, a.out, png_min_side=a.png_size)
        log.info("collection exported to %s", a.out)
    log.info("done in %.1fs", time.time() - t)


if __name__ == "__main__":
    main()
