"""Core test suite:  python -m pytest -q   (or: python tests/test_core.py)"""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wobbly_frames.collection import generate_collection
from wobbly_frames.engine import generate_frame
from wobbly_frames.export import export_frame
from wobbly_frames.params import BORDERS, PRESETS, RATIOS, STYLES, TEXTURES, FrameParams, apply_preset
from wobbly_frames.raster import output_size, render_rgba
from wobbly_frames.similarity import distance, signature
from wobbly_frames.svg_export import to_svg
from wobbly_frames.validate import validate_frame


def frame(**kw):
    return generate_frame(FrameParams(**kw))


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_geometry(self):
        for seed in (1, 7, 12345):
            a, b = frame(seed=seed, style="Organic"), frame(seed=seed, style="Organic")
            self.assertEqual(a.seed_used, b.seed_used)
            self.assertEqual(to_svg(a), to_svg(b))

    def test_different_seed_different_geometry(self):
        a, b = frame(seed=1), frame(seed=2)
        self.assertNotEqual(to_svg(a), to_svg(b))

    def test_colour_does_not_change_geometry(self):
        a = frame(seed=99, color="#F6F1E9")
        b = frame(seed=99, color="#3E3C3A")
        self.assertLess(distance(signature(a), signature(b)), 1e-6)


class TestValidity(unittest.TestCase):
    def test_all_styles_and_ratios_pass_qa(self):
        for style in STYLES:
            for ratio in RATIOS:
                fr = frame(style=style, ratio=ratio, seed=hash((style, ratio)) % 10 ** 6 + 1)
                ok, rep = validate_frame(fr)
                self.assertTrue(ok, f"{style} {ratio}: {rep.get('failures')}")

    def test_all_presets_pass_qa(self):
        for name in PRESETS:
            fr = generate_frame(apply_preset(FrameParams(seed=4242), name))
            self.assertTrue(validate_frame(fr)[0], name)

    def test_native_ratio(self):
        for ratio, (rw, rh) in RATIOS.items():
            fr = frame(ratio=ratio)
            self.assertAlmostEqual(fr.width / fr.height, rw / rh, places=2)

    def test_borders_and_textures(self):
        for b in BORDERS:
            for t in TEXTURES:
                self.assertTrue(validate_frame(frame(border=b, texture=t, seed=11))[0], (b, t))

    def test_extreme_settings_still_valid(self):
        for w, a, c in ((100, 100, 100), (0, 0, 0), (100, 0, 100), (0, 100, 0)):
            fr = frame(wobble=w, asymmetry=a, corner_variation=c, seed=8, style="Hand-Cut")
            self.assertTrue(validate_frame(fr)[0], (w, a, c))


class TestSvg(unittest.TestCase):
    def setUp(self):
        self.svg = to_svg(frame(seed=5, texture="Medium", style="Deckled"))

    def test_header(self):
        self.assertTrue(self.svg.startswith("<svg"))
        for attr in ("width=", "height=", "viewBox="):
            self.assertIn(attr, self.svg)

    def test_no_raster_or_text(self):
        for bad in ("<text", "<image", "<filter", "feTurbulence", "base64", "<foreignObject"):
            self.assertNotIn(bad, self.svg)

    def test_transparent_and_evenodd(self):
        self.assertIn("evenodd", self.svg)
        self.assertNotIn('<rect width="100%" height="100%"', self.svg)

    def test_unique_gradient_ids(self):
        a, b = to_svg(frame(seed=1)), to_svg(frame(seed=2))
        ida = set(re.findall(r'id="([^"]+)"', a))
        idb = set(re.findall(r'id="([^"]+)"', b))
        self.assertFalse(ida & idb, "gradient ids must be unique across files")


class TestPng(unittest.TestCase):
    def test_transparent_corners_and_opening(self):
        fr = frame(seed=3)
        w, h = 400, int(400 * fr.height / fr.width)
        px = render_rgba(fr, w, h)
        self.assertEqual(px[2, 2, 3], 0, "corner must be transparent")
        self.assertEqual(px[h // 2, w // 2, 3], 0, "opening must be transparent")
        self.assertGreater(px[int(h * 0.02) + 2:int(h * 0.2), w // 2, 3].max(), 200, "paper must be opaque")

    def test_export_size(self):
        fr = frame(seed=3)
        with tempfile.TemporaryDirectory() as d:
            files = export_frame(fr, d, png_min_side=1000)
            self.assertEqual({f.suffix for f in files}, {".svg", ".png"})
            from PIL import Image
            im = Image.open(files[1])
            self.assertEqual(min(im.size), 1000)
            self.assertEqual(im.mode, "RGBA")
            self.assertEqual(im.size, output_size(fr, 1000)[:2])

    def test_baked_background_is_opaque(self):
        fr = frame(seed=3, background="#EDE8DF")
        px = render_rgba(fr, 200, 250)
        self.assertEqual(px[2, 2, 3], 255)


class TestCollection(unittest.TestCase):
    def test_distinct_frames(self):
        frames, stats = generate_collection(10, FrameParams(), collection_seed=7, color_mode="palette")
        self.assertEqual(len(frames), 10)
        sigs = [signature(f) for f in frames]
        for i in range(len(sigs)):
            for j in range(i + 1, len(sigs)):
                self.assertGreater(distance(sigs[i], sigs[j]), 2.4, f"frames {i} and {j} are duplicates")
        for f in frames:
            self.assertTrue(validate_frame(f)[0])

    def test_reproducible(self):
        a, _ = generate_collection(4, FrameParams(), collection_seed=3)
        b, _ = generate_collection(4, FrameParams(), collection_seed=3)
        self.assertEqual([f.seed_used for f in a], [f.seed_used for f in b])

    def test_duplicate_detection_flags_identical(self):
        f1 = frame(seed=21)
        self.assertLess(distance(signature(f1), signature(frame(seed=21))), 2.4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
