"""High-quality transparent PNG rendering of the shared scene (pycairo; Pillow fallback)."""
from __future__ import annotations

import numpy as np

from .scene import scene

try:
    import cairo  # type: ignore
    HAVE_CAIRO = True
except Exception:  # pragma: no cover
    HAVE_CAIRO = False


def output_size(frame, min_side=4000):
    s = min_side / min(frame.width, frame.height)
    return int(round(frame.width * s)), int(round(frame.height * s)), s


def _path(ctx, c):
    A = c.anchors
    ctx.move_to(*A[0])
    n = len(A)
    if c.kind == "poly":
        for i in range(1, n):
            ctx.line_to(*A[i])
    else:
        for i in range(n):
            p3 = A[(i + 1) % n]
            ctx.curve_to(c.c1[i][0], c.c1[i][1], c.c2[i][0], c.c2[i][1], p3[0], p3[1])
    ctx.close_path()


def render_surface(frame, px_w, px_h, checker=False, crop=None):
    """Render the frame at px_w x px_h. `crop` = (x, y, w, h) in those pixel
    coordinates returns only that region at 1:1 (used for the 100% PNG preview)."""
    cx, cy, cw, ch = crop if crop else (0, 0, px_w, px_h)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, int(cw), int(ch))
    ctx = cairo.Context(surf)
    ctx.set_antialias(cairo.ANTIALIAS_BEST)
    if checker:
        _checker(ctx, int(cw), int(ch), offset=(int(cx), int(cy)))
    ctx.translate(-cx, -cy)
    ctx.scale(px_w / frame.width, px_h / frame.height)
    for op in scene(frame):
        k = op["kind"]
        if k == "background":
            ctx.set_source_rgb(*[v / 255 for v in op["rgb"]])
            ctx.paint()
        elif k == "fill":
            ctx.new_path()
            for c in op["contours"]:
                _path(ctx, c)
            ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
            if "gradient" in op:
                x1, y1, x2, y2, ca, cb = op["gradient"]
                g = cairo.LinearGradient(x1, y1, x2, y2)
                g.add_color_stop_rgb(0, *[v / 255 for v in ca])
                g.add_color_stop_rgb(1, *[v / 255 for v in cb])
                ctx.set_source(g)
            else:
                ctx.set_source_rgb(*[v / 255 for v in op["rgb"]])
            ctx.fill()
        elif k == "dots":
            ctx.new_path()
            ctx.set_fill_rule(cairo.FILL_RULE_WINDING)
            for x, y, r in op["dots"]:
                ctx.new_sub_path()
                ctx.arc(x, y, r, 0, 2 * np.pi)
            ctx.set_source_rgba(*[v / 255 for v in op["rgb"]], op["opacity"])
            ctx.fill()
        elif k == "fibers":
            ctx.new_path()
            for x0, y0, cx, cy, x1, y1 in op["fibers"]:
                ctx.move_to(x0, y0)
                # quadratic -> cubic
                ctx.curve_to(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0),
                             x1 + 2 / 3 * (cx - x1), y1 + 2 / 3 * (cy - y1), x1, y1)
            ctx.set_line_width(op["width"])
            ctx.set_line_cap(cairo.LINE_CAP_ROUND)
            ctx.set_source_rgba(*[v / 255 for v in op["rgb"]], op["opacity"])
            ctx.stroke()
    surf.flush()
    return surf


def render_rgba(frame, px_w, px_h, checker=False):
    """Return an RGBA uint8 array (straight alpha), un-premultiplied in row chunks."""
    if not HAVE_CAIRO:
        return _render_pillow(frame, px_w, px_h, checker)
    surf = render_surface(frame, px_w, px_h, checker)
    buf = np.frombuffer(surf.get_data(), np.uint8).reshape(px_h, surf.get_stride() // 4, 4)[:, :px_w]
    out = np.empty((px_h, px_w, 4), np.uint8)
    for y in range(0, px_h, 256):
        b = buf[y:y + 256].astype(np.uint32)
        a = b[..., 3:4]
        rgb = np.where(a > 0, (b[..., :3] * 255 + a // 2) // np.maximum(a, 1), 0)
        out[y:y + 256, :, :3] = np.minimum(rgb[..., ::-1], 255)
        out[y:y + 256, :, 3] = b[..., 3]
    return out


def _checker(ctx, w, h, sq=16, offset=(0, 0)):
    ox, oy = offset
    ctx.set_source_rgb(0.93, 0.93, 0.93)
    ctx.paint()
    ctx.set_source_rgb(0.82, 0.82, 0.82)
    for y in range(-(oy % (sq * 2)), h, sq):
        row = ((y + oy) // sq) % 2
        for x in range(-(ox % (sq * 2)) + row * sq, w, sq * 2):
            ctx.rectangle(x, y, sq, sq)
    ctx.fill()


def render_crop_image(frame, px_w, px_h, crop, checker=False):
    """PIL RGBA image of one region of the full-resolution render (100% zoom)."""
    from PIL import Image
    if not HAVE_CAIRO:
        x, y, w, h = crop
        return _render_pillow(frame, px_w, px_h, checker).crop((x, y, x + w, y + h))
    surf = render_surface(frame, px_w, px_h, checker, crop)
    w, h = surf.get_width(), surf.get_height()
    buf = np.frombuffer(surf.get_data(), np.uint8).reshape(h, surf.get_stride() // 4, 4)[:, :w]
    b = buf.astype(np.uint32)
    a = b[..., 3:4]
    rgb = np.where(a > 0, (b[..., :3] * 255 + a // 2) // np.maximum(a, 1), 0)
    out = np.empty((h, w, 4), np.uint8)
    out[..., :3] = np.minimum(rgb[..., ::-1], 255)
    out[..., 3] = b[..., 3]
    return Image.fromarray(out, "RGBA")


def render_image(frame, px_w, px_h, checker=False):
    from PIL import Image
    return Image.fromarray(render_rgba(frame, px_w, px_h, checker), "RGBA")


def save_png(frame, path, min_side=4000):
    w, h, _ = output_size(frame, min_side)
    if HAVE_CAIRO:
        render_surface(frame, w, h).write_to_png(str(path))  # cairo writes straight-alpha RGBA
    else:
        render_image(frame, w, h).save(path, "PNG")
    return w, h


# ---------------------------------------------------------------- fallback
def _render_pillow(frame, px_w, px_h, checker=False):  # pragma: no cover - used without pycairo
    from PIL import Image, ImageDraw, ImageChops
    ss = 3
    W, H = px_w * ss, px_h * ss
    sx, sy = W / frame.width, H / frame.height
    base = Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def poly(c):
        return [(float(x * sx), float(y * sy)) for x, y in c.flatten()]
    for op in scene(frame):
        if op["kind"] == "background":
            base.paste(tuple(op["rgb"]) + (255,), (0, 0, W, H))
        elif op["kind"] == "fill":
            m = Image.new("L", (W, H), 0)
            dm = ImageDraw.Draw(m)
            dm.polygon(poly(op["contours"][0]), fill=255)
            hole = Image.new("L", (W, H), 0)
            ImageDraw.Draw(hole).polygon(poly(op["contours"][1]), fill=255)
            m = ImageChops.subtract(m, hole)
            layer = Image.new("RGBA", (W, H), tuple(op["rgb"]) + (255,))
            base.paste(layer, (0, 0), m)
        elif op["kind"] == "dots":
            ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            d = ImageDraw.Draw(ov)
            col = tuple(op["rgb"]) + (int(op["opacity"] * 255),)
            for x, y, r in op["dots"]:
                d.ellipse([(x - r) * sx, (y - r) * sy, (x + r) * sx, (y + r) * sy], fill=col)
            base = Image.alpha_composite(base, ov)
    img = base.resize((px_w, px_h), Image.LANCZOS)
    if checker:
        bg = Image.new("RGBA", img.size, (230, 230, 230, 255))
        img = Image.alpha_composite(bg, img)
    return np.array(img)
