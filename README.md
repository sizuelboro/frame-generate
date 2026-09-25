# Wobbly Paper Frames Generator

A desktop app that generates **commercially sellable, handmade-looking wobbly paper frames** as clean
SVG and transparent high-resolution PNG, ready for Canva, Etsy, Creative Market and print-on-demand.

Every frame is a single closed paper shape with a transparent photo opening: no text, no raster
images, no SVG filters — just fills and paths that import cleanly and stay editable.

## Install & run

```bash
pip install -r requirements.txt
python web.py                  # browser UI  ->  http://127.0.0.1:8765  (recommended)
python main.py                 # desktop Tkinter GUI
```

The browser version runs a small local server (standard library only — no Flask, nothing leaves your
machine) and gives you the same controls as the desktop app, plus direct SVG/PNG downloads. Use
`python web.py --port 9000 --no-browser` to change the port or stop it opening a tab.

Headless:

```bash
python -m wobbly_frames.cli frame      --style Organic --ratio 4:5 --seed 42 --out out/
python -m wobbly_frames.cli collection --count 50 --colors palette --out bundle/
python -m wobbly_frames.cli sample     --out sample20/        # the 20-frame review set
python tests/test_core.py               # test suite
```

Requires Python 3.10+, `numpy`, `pycairo` (Pillow-only fallback included) and `Pillow`.
Only the desktop GUI needs Tkinter (`python3-tk` on Debian/Ubuntu); the browser UI does not.

## What it produces

| | |
|---|---|
| **SVG** | explicit `width`, `height`, `viewBox`; relative path commands; `fill-rule="evenodd"`; per-file unique ids; transparent background and opening |
| **PNG** | transparent RGBA, short side 4000 px by default (up to 8000) |
| **Naming** | `001_Organic_Paper_Frame.svg` for collections, `Organic_Paper_Frame_002` for single exports |
| **Manifest** | `collection_manifest.json` with seed, parameters, design choices and QA report per frame, plus `_collection_preview.png` contact sheet |

## Controls

- **Wobble intensity** (default 20), **Asymmetry** (15), **Corner irregularity** (20), each 0–100 with
  Subtle / Medium / Strong shortcuts.
- **Edge smoothness**: Auto, Smooth, Organic, Hand-cut.
- **Styles**: Wobbly, Organic, Hand-Cut, Soft Torn, Deckled, Editorial.
- **16 presets** in four groups — Basic, Organic, Handmade, Editorial.
- **8 aspect ratios** — 1:1, 4:5, 3:4, 5:7, 2:3, 3:2, 4:3, 16:9 — each generated natively, never
  stretched from a square.
- **Border thickness**: Thin, Medium, Thick (plus Extra-Thick), as a fraction of the short side.
- **14 muted paper colours** plus a custom picker; **texture** None / Light (default) / Medium.
- **Seed** field: the same seed and settings always rebuild the identical frame.
- **GENERATE NEW FRAME** searches seeds until the geometry is meaningfully different from the frame
  on screen; **RANDOMIZE** simply picks a new valid seed.

## Collections

Generate 10 / 20 / 30 / 50 / 100 frames from 20 curated archetypes, with optional mixed ratios and a
cycling palette. Each frame is validated, and shape-based duplicate detection (colour is deliberately
ignored) rejects and regenerates anything too close to a frame already in the set.

## Quality control

Validation runs on the **exact rounded geometry that gets exported**, so the preview, the SVG and the
PNG are the same shape. A frame is rejected and regenerated from a derived seed if any of these fail:

- self-intersecting outer or inner contour, or spiky turn angles for the chosen edge type
- solidity or rectangularity outside the rectangle family (no blobs or dents)
- border thinner than 3.2% of the short side, or uneven beyond tolerance on any side
- opening not fully inside the outer edge, smaller than 30% of the frame area, or under 45% of the
  frame's dimensions
- silhouette off-centre on the canvas

## Architecture

```
wobbly_frames/
  params.py      FrameParams, ratios, styles, borders, 14 colours, 16 presets
  engine.py      seeded design choices, geometry construction, generate_frame() with QA retries
  geometry.py    band-limited noise, Catmull-Rom → Bézier, flattening, intersection tests
  texture.py     vector gradient, grain specks and fibres (paper ring only)
  validate.py    the QA rules above
  scene.py       one shared draw list consumed by both writers
  svg_export.py  clean SVG
  raster.py      cairo render, transparent PNG, 100%-crop preview
  similarity.py  polar-profile shape signature and duplicate detection
  collection.py  20 archetypes, controlled diversity, batch generation
  export.py      file writing, manifest, contact sheet
  naming.py      product file names
  gui.py         Tkinter desktop GUI (controls · preview tabs · frame info)
  webapp.py      local HTTP server + JSON API for the browser UI
  web/index.html browser UI (controls · live SVG preview · collection grid · frame info)
  cli.py         headless interface
```

## Notes

- The PNG is rasterised from the same scene the SVG describes, so they never drift apart. An
  independent headless-Chromium render of the SVG matched the PNG to an alpha mean difference of 0.04.
- "Bake background" is off by default; leave it off for marketplace-ready transparent assets.
