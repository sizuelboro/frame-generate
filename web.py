#!/usr/bin/env python3
"""Wobbly Paper Frames Generator — browser version.

    python web.py                 # opens http://127.0.0.1:8765
    python web.py --port 9000 --no-browser
"""
import argparse

from wobbly_frames.webapp import run

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    run(a.host, a.port, not a.no_browser)
