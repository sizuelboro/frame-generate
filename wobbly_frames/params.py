"""Parameter model, presets, palettes and option lists (the settings vocabulary)."""
from __future__ import annotations

from dataclasses import dataclass, asdict, field, replace
from typing import Optional

RATIOS = {
    "1:1": (1, 1), "4:5": (4, 5), "3:4": (3, 4), "5:7": (5, 7),
    "2:3": (2, 3), "3:2": (3, 2), "4:3": (4, 3), "16:9": (16, 9),
}

STYLES = ["Wobbly", "Organic", "Hand-Cut", "Soft Torn", "Deckled", "Editorial"]

# Border thickness as a fraction of the frame's short side.
BORDERS = {"Thin": 0.062, "Medium": 0.092, "Thick": 0.125, "Extra-Thick": 0.155}

EDGE_MODES = ["Auto", "Smooth", "Organic", "Hand-cut"]
TEXTURES = ["None", "Light", "Medium"]

# Muted, premium paper palette (RGB hex).
PAPER_COLORS = {
    "Warm White": "#F6F1E9",
    "Ivory": "#F3ECDA",
    "Cream": "#EEE2C8",
    "Beige": "#E0CFB4",
    "Blush": "#EFD8CF",
    "Dusty Pink": "#D8ABA3",
    "Lavender": "#D4CADF",
    "Sage": "#BCC7AC",
    "Soft Blue": "#C3D1DC",
    "Butter Yellow": "#F1E1A6",
    "Terracotta": "#C27857",
    "Brown": "#876750",
    "Charcoal": "#3E3C3A",
    "Black": "#1D1C1B",
}

# Quick mappings for the named levels in the brief.
WOBBLE_LEVELS = {"Subtle": 20, "Medium": 45, "Strong": 70}
ASYMMETRY_LEVELS = {"Low": 15, "Medium": 40, "High": 70}
CORNER_LEVELS = {"Minimal": 10, "Medium": 35, "Organic": 65}

# Internal design vocabulary (chosen per seed when "auto").
CORNER_STYLES = ["soft", "rounded", "crisp", "handcut", "uneven"]
SILHOUETTES = ["straight", "bowed", "pillow", "crooked", "tapered"]
OPENINGS = ["parallel", "soft", "rounded", "irregular", "asymmetric", "offset"]


@dataclass
class FrameParams:
    style: str = "Wobbly"
    ratio: str = "4:5"
    border: str = "Medium"
    wobble: float = 20
    asymmetry: float = 15
    corner_variation: float = 20
    color: str = PAPER_COLORS["Warm White"]
    texture: str = "Light"
    seed: int = 1
    edge: str = "Auto"
    silhouette: str = "auto"
    opening: str = "auto"
    corner_style: str = "auto"
    preset: Optional[str] = None
    background: Optional[str] = None  # None = transparent (default)
    label: Optional[str] = None       # product/archetype label for naming

    def to_dict(self):
        return asdict(self)

    @staticmethod
    def from_dict(d):
        known = {k: v for k, v in d.items() if k in FrameParams.__dataclass_fields__}
        return FrameParams(**known)

    def copy(self, **kw):
        return replace(self, **kw)


# 16 frame presets from the brief. They change *generation parameters*, not colours.
PRESETS = {
    # Basic
    "Wobbly Rectangle":   dict(style="Wobbly", ratio="4:5", wobble=22, asymmetry=12, corner_variation=18, border="Medium"),
    "Wobbly Square":      dict(style="Wobbly", ratio="1:1", wobble=24, asymmetry=14, corner_variation=20, border="Medium"),
    "Wobbly Portrait":    dict(style="Wobbly", ratio="2:3", wobble=22, asymmetry=15, corner_variation=20, border="Medium"),
    "Wobbly Landscape":   dict(style="Wobbly", ratio="3:2", wobble=22, asymmetry=15, corner_variation=20, border="Medium"),
    # Organic
    "Organic Rectangle":  dict(style="Organic", ratio="4:5", wobble=35, asymmetry=20, corner_variation=35, border="Medium", silhouette="pillow"),
    "Organic Square":     dict(style="Organic", ratio="1:1", wobble=38, asymmetry=22, corner_variation=35, border="Thick"),
    "Organic Rounded":    dict(style="Organic", ratio="4:5", wobble=30, asymmetry=15, corner_variation=25, border="Medium", corner_style="rounded", opening="rounded"),
    "Organic Asymmetric": dict(style="Organic", ratio="3:4", wobble=36, asymmetry=65, corner_variation=45, border="Thick", opening="asymmetric"),
    # Handmade
    "Hand-Cut Paper":     dict(style="Hand-Cut", ratio="4:5", wobble=30, asymmetry=35, corner_variation=35, border="Medium", corner_style="handcut"),
    "Soft Torn Paper":    dict(style="Soft Torn", ratio="4:5", wobble=22, asymmetry=20, corner_variation=25, border="Thick"),
    "Light Deckled Paper":dict(style="Deckled", ratio="5:7", wobble=15, asymmetry=12, corner_variation=15, border="Thick"),
    "Uneven Paper Edge":  dict(style="Hand-Cut", ratio="3:4", wobble=40, asymmetry=40, corner_variation=50, border="Medium", corner_style="uneven", silhouette="crooked"),
    # Editorial
    "Minimal Editorial":  dict(style="Editorial", ratio="4:5", wobble=16, asymmetry=10, corner_variation=10, border="Thin", corner_style="crisp", opening="parallel"),
    "Luxury Minimal":     dict(style="Editorial", ratio="5:7", wobble=14, asymmetry=8, corner_variation=8, border="Extra-Thick", corner_style="crisp", opening="offset"),
    "Playful Editorial":  dict(style="Editorial", ratio="1:1", wobble=38, asymmetry=45, corner_variation=40, border="Thick", silhouette="crooked", opening="asymmetric"),
    "Modern Organic":     dict(style="Organic", ratio="4:3", wobble=28, asymmetry=30, corner_variation=30, border="Medium", corner_style="soft", opening="soft"),
}

PRESET_GROUPS = {
    "Basic": ["Wobbly Rectangle", "Wobbly Square", "Wobbly Portrait", "Wobbly Landscape"],
    "Organic": ["Organic Rectangle", "Organic Square", "Organic Rounded", "Organic Asymmetric"],
    "Handmade": ["Hand-Cut Paper", "Soft Torn Paper", "Light Deckled Paper", "Uneven Paper Edge"],
    "Editorial": ["Minimal Editorial", "Luxury Minimal", "Playful Editorial", "Modern Organic"],
}


def apply_preset(params: FrameParams, preset_name: str) -> FrameParams:
    base = FrameParams(color=params.color, texture=params.texture, seed=params.seed,
                       background=params.background)
    p = base.copy(**PRESETS[preset_name])
    p.preset = preset_name
    return p
