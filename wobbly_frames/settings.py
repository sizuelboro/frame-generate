"""Persistent user settings (JSON in the user's home folder)."""
import json
from pathlib import Path

from .params import FrameParams

APP_DIR = Path.home() / ".wobbly_frame_generator"
SETTINGS_FILE = APP_DIR / "settings.json"

DEFAULTS = dict(params=FrameParams().to_dict(), png_min_side=4000, export_dir=str(Path.home() / "Wobbly Paper Frames"),
                collection_count=20, collection_ratio_mode="mixed", collection_color_mode="current",
                naming_scheme="style")


def load():
    s = json.loads(json.dumps(DEFAULTS))
    try:
        s.update(json.loads(SETTINGS_FILE.read_text()))
    except Exception:
        pass
    return s


def save(s):
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(s, indent=2))
    except Exception:
        pass
