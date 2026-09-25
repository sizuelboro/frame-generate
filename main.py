#!/usr/bin/env python3
"""Wobbly Paper Frames Generator — desktop launcher.

    python main.py            # GUI
    python -m wobbly_frames.cli sample --out sample20    # headless
"""
import sys


def main():
    try:
        import tkinter  # noqa: F401
    except ImportError:
        sys.exit("Tkinter is required for the GUI. Use `python -m wobbly_frames.cli --help` "
                 "for the headless command line instead.")
    from wobbly_frames.gui import run
    run()


if __name__ == "__main__":
    main()
