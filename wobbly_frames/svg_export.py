"""Clean, editable SVG writer (no rasters, fonts, text or filters)."""
from __future__ import annotations

from .colors import rgb_to_hex
from .scene import scene


def _n(v):
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def contour_d(c):
    """Relative-command path data computed from rounded absolute coordinates."""
    A = c.anchors
    out = [f"M{_n(A[0,0])} {_n(A[0,1])}"]
    n = len(A)
    if c.kind == "poly":
        parts = []
        for i in range(1, n):
            dx, dy = A[i] - A[i - 1]
            parts.append(f"{_n(dx)} {_n(dy)}")
        out.append("l" + " ".join(parts))
    else:
        parts = []
        for i in range(n):
            p0 = A[i]
            p3 = A[(i + 1) % n]
            c1, c2 = c.c1[i] - p0, c.c2[i] - p0
            d3 = p3 - p0
            parts.append(" ".join(_n(v) for v in (c1[0], c1[1], c2[0], c2[1], d3[0], d3[1])))
        out.append("c" + " ".join(parts))
    out.append("z")
    return "".join(out)


def _dots_d(dots):
    parts = []
    for x, y, r in dots:
        parts.append(f"M{_n(x - r)} {_n(y)}a{_n(r)} {_n(r)} 0 1 0 {_n(2*r)} 0a{_n(r)} {_n(r)} 0 1 0 {_n(-2*r)} 0z")
    return "".join(parts)


def _fibers_d(fibers):
    return "".join(f"M{_n(a)} {_n(b)}Q{_n(c)} {_n(d)} {_n(e)} {_n(f)}" for a, b, c, d, e, f in fibers)


def to_svg(frame, title=None) -> str:
    W, H = frame.width, frame.height
    uid = f"wpf{frame.seed_used:x}"
    defs, body = [], []
    for op in scene(frame):
        k = op["kind"]
        if k == "background":
            body.append(f'<rect id="{uid}-background" width="{W}" height="{H}" fill="{rgb_to_hex(op["rgb"])}"/>')
        elif k == "fill":
            d = "".join(contour_d(c) for c in op["contours"])
            if "gradient" in op:
                x1, y1, x2, y2, ca, cb = op["gradient"]
                gid = f"{uid}-grad"
                defs.append(f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{_n(x1)}" y1="{_n(y1)}" '
                            f'x2="{_n(x2)}" y2="{_n(y2)}"><stop offset="0" stop-color="{rgb_to_hex(ca)}"/>'
                            f'<stop offset="1" stop-color="{rgb_to_hex(cb)}"/></linearGradient>')
                fill = f"url(#{gid})"
            else:
                fill = rgb_to_hex(op["rgb"])
            body.append(f'<path id="{uid}-{op['id']}" fill="{fill}" fill-rule="evenodd" d="{d}"/>')
        elif k == "dots":
            body.append(f'<path id="{uid}-{op['id']}" fill="{rgb_to_hex(op["rgb"])}" fill-opacity="{_n(op["opacity"])}" d="{_dots_d(op["dots"])}"/>')
        elif k == "fibers":
            body.append(f'<path id="{uid}-{op['id']}" fill="none" stroke="{rgb_to_hex(op["rgb"])}" stroke-opacity="{_n(op["opacity"])}" '
                        f'stroke-width="{_n(op["width"])}" stroke-linecap="round" d="{_fibers_d(op["fibers"])}"/>')
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">']
    if defs:
        parts.append("<defs>" + "".join(defs) + "</defs>")
    tex = [b for b in body if '-grain' in b or '-fibers"' in b]
    main = [b for b in body if b not in tex]
    parts.append(f'<g id="{uid}-frame">' + "".join(main))
    if tex:
        parts.append(f'<g id="{uid}-paper-texture">' + "".join(tex) + "</g>")
    parts.append("</g></svg>")
    return "\n".join(parts) + "\n"
