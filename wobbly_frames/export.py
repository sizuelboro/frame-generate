"""Export system: current frame and whole collections (SVG + transparent PNG)."""
from __future__ import annotations

import json
from pathlib import Path

from .naming import current_filename, collection_filename
from .raster import save_png, render_image
from .svg_export import to_svg


def export_frame(frame, out_dir, stem=None, png_min_side=4000, svg=True, png=True):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = stem or current_filename(frame)
    files = []
    if svg:
        p = out / f"{stem}.svg"
        p.write_text(to_svg(frame), encoding="utf-8")
        files.append(p)
    if png:
        p = out / f"{stem}.png"
        save_png(frame, p, png_min_side)
        files.append(p)
    return files


def export_collection(frames, out_dir, png_min_side=4000, scheme="style", manifest=True,
                      contact_sheet=True, progress=None):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for i, fr in enumerate(frames, 1):
        stem = collection_filename(fr, i, scheme)
        export_frame(fr, out, stem, png_min_side)
        rows.append(dict(file=stem, label=fr.params.label, seed=fr.seed_used, params=fr.params.to_dict(),
                         design={k: v for k, v in fr.design.items()}, qa=fr.report))
        if progress:
            progress(i, len(frames))
    if manifest:
        (out / "collection_manifest.json").write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    if contact_sheet:
        make_contact_sheet(frames, out / "_collection_preview.png")
    return out


def make_contact_sheet(frames, path, cols=5, cell=420, bg=(216, 210, 202, 255), labels=False):
    from PIL import Image
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cell, rows * cell), bg)
    for k, fr in enumerate(frames):
        s = (cell - 40) / max(fr.width, fr.height)
        im = render_image(fr, max(1, int(fr.width * s)), max(1, int(fr.height * s)))
        x = (k % cols) * cell + (cell - im.width) // 2
        y = (k // cols) * cell + (cell - im.height) // 2
        sheet.alpha_composite(im, (x, y))
    sheet.convert("RGB").save(path)
    return path
