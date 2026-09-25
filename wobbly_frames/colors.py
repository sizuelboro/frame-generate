"""Colour helpers (RGB only)."""


def hex_to_rgb(h):
    h = h.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def rgb_to_hex(rgb):
    return "#%02X%02X%02X" % tuple(int(max(0, min(255, round(c)))) for c in rgb)


def mix(a, b, t):
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def luminance(rgb):
    r, g, b = [c / 255.0 for c in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def shade(rgb, amount):
    """amount>0 lightens toward white, <0 darkens toward a warm black."""
    if amount >= 0:
        return mix(rgb, (255, 255, 255), amount)
    return mix(rgb, (30, 24, 20), -amount)
