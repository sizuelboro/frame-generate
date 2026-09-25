"""Clean product file names derived from the frame style."""
import re

STYLE_NAMES = {
    "Wobbly": "Wobbly_Paper_Frame",
    "Organic": "Organic_Paper_Frame",
    "Hand-Cut": "Hand_Cut_Paper_Frame",
    "Soft Torn": "Soft_Torn_Frame",
    "Deckled": "Deckled_Paper_Frame",
    "Editorial": "Editorial_Wobbly_Frame",
}


def product_name(style):
    return STYLE_NAMES.get(style, "Wobbly_Paper_Frame")


def current_filename(frame, index=1):
    """e.g. Organic_Paper_Frame_002"""
    return f"{product_name(frame.params.style)}_{index:03d}"


def collection_filename(frame, index, scheme="style"):
    """e.g. 001_Organic_Paper_Frame  (scheme='plain' -> 001_Wobbly_Paper_Frame)"""
    base = "Wobbly_Paper_Frame" if scheme == "plain" else product_name(frame.params.style)
    return f"{index:03d}_{base}"


def safe(s):
    return re.sub(r"[^A-Za-z0-9_\-]+", "_", s).strip("_")
