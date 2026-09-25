"""Tkinter desktop GUI for the Wobbly Paper Frames Generator.

Layout:  [ controls ] [ preview tabs ] [ frame info ]
All generation happens on a worker thread; results come back through a queue.
"""
from __future__ import annotations

import queue
import random
import threading
import time
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

from PIL import Image, ImageTk

from . import settings as settings_mod
from .collection import generate_collection, PALETTE_ORDER
from .engine import MAX_SEED, generate_frame
from .export import export_collection, export_frame
from .log import get_logger
from .naming import current_filename
from .params import (ASYMMETRY_LEVELS, BORDERS, CORNER_LEVELS, EDGE_MODES, PAPER_COLORS,
                     PRESET_GROUPS, PRESETS, RATIOS, STYLES, TEXTURES, WOBBLE_LEVELS,
                     FrameParams, apply_preset)
from .raster import output_size, render_crop_image, render_image
from .similarity import distance, signature, similarity_percent
from .svg_export import to_svg

LOG = get_logger()

BG = "#f4f2ee"
PANEL = "#ffffff"
ACCENT = "#2f6f61"
NEW_FRAME_MIN_DISTANCE = 3.0      # geometry must differ by at least this much
PREVIEW_MAX = 1400                # px of the largest preview render


# --------------------------------------------------------------------------- jobs
class Job:
    """A unit of background work."""

    def __init__(self, kind, **kw):
        self.kind = kind
        self.__dict__.update(kw)


class App(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=0)
        self.master.title("Wobbly Paper Frames Generator")
        self.master.geometry("1500x940")
        self.master.minsize(1180, 760)
        self.pack(fill="both", expand=True)

        self.settings = settings_mod.load()
        self.params = FrameParams.from_dict(self.settings["params"])
        self.frame = None            # current Frame
        self.previous = None         # previous Frame (before/after)
        self.collection = []
        self.collection_stats = {}
        self._photo = {}             # keep PhotoImage references alive
        self._thumbs = []
        self.zoom = 1.0
        self.fit = True
        self.showing_previous = False
        self.busy = False
        self.cancel_flag = False

        self.q = queue.Queue()
        self.jobs = queue.Queue()
        self.worker = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker.start()

        self._style()
        self._build()
        self._sync_widgets_from_params()
        self.after(60, self._pump)
        self.submit(Job("frame", params=self.params.copy()))

    # ------------------------------------------------------------------ chrome
    def _style(self):
        s = ttk.Style()
        try:
            s.theme_use("clam")
        except tk.TclError:
            pass
        s.configure(".", background=BG, font=("Helvetica", 10))
        s.configure("TFrame", background=BG)
        s.configure("Card.TFrame", background=PANEL, relief="flat")
        s.configure("TLabel", background=BG)
        s.configure("Card.TLabel", background=PANEL)
        s.configure("Head.TLabel", font=("Helvetica", 11, "bold"))
        s.configure("Muted.TLabel", foreground="#7b7669")
        s.configure("TButton", padding=5)
        s.configure("Primary.TButton", background=ACCENT, foreground="white",
                    font=("Helvetica", 10, "bold"), padding=8)
        s.map("Primary.TButton", background=[("active", "#26584d")])
        s.configure("TNotebook", background=BG)
        s.configure("Horizontal.TProgressbar", background=ACCENT)
        self.master.configure(bg=BG)

    def _build(self):
        left = ttk.Frame(self, padding=(12, 10))
        left.pack(side="left", fill="y")
        right = ttk.Frame(self, padding=(0, 10, 12, 10))
        right.pack(side="right", fill="y")
        center = ttk.Frame(self, padding=(6, 10))
        center.pack(side="left", fill="both", expand=True)
        self._build_controls(left)
        self._build_preview(center)
        self._build_info(right)
        self._build_status()

    # ------------------------------------------------------------------ controls
    def _build_controls(self, root):
        canvas = tk.Canvas(root, width=306, bg=BG, highlightthickness=0)
        bar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        box = ttk.Frame(canvas)
        box.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=box, anchor="nw")
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="y", expand=False)
        bar.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-e.delta / 60), "units"))
        canvas.bind_all("<Button-4>", lambda e: canvas.yview_scroll(-2, "units"))
        canvas.bind_all("<Button-5>", lambda e: canvas.yview_scroll(2, "units"))

        ttk.Label(box, text="FRAME SETTINGS", style="Head.TLabel").pack(anchor="w", pady=(0, 8))

        # -- preset
        self.v_preset = tk.StringVar(value="— none —")
        preset_values = ["— none —"] + [f"{g}: {n}" for g, names in PRESET_GROUPS.items() for n in names]
        self._combo(box, "Preset", self.v_preset, preset_values, self._on_preset)

        # -- style / ratio / border / edge
        self.v_style = tk.StringVar()
        self._combo(box, "Style", self.v_style, STYLES, self._on_change)
        self.v_ratio = tk.StringVar()
        self._combo(box, "Aspect ratio", self.v_ratio, list(RATIOS), self._on_change)
        self.v_border = tk.StringVar()
        self._combo(box, "Border thickness", self.v_border, list(BORDERS), self._on_change)
        self.v_edge = tk.StringVar()
        self._combo(box, "Edge smoothness", self.v_edge, EDGE_MODES, self._on_change)

        # -- sliders
        self.v_wobble = tk.DoubleVar()
        self.v_asym = tk.DoubleVar()
        self.v_corner = tk.DoubleVar()
        self._slider(box, "Wobble intensity", self.v_wobble, WOBBLE_LEVELS)
        self._slider(box, "Asymmetry", self.v_asym, ASYMMETRY_LEVELS)
        self._slider(box, "Corner irregularity", self.v_corner, CORNER_LEVELS)

        # -- colour
        ttk.Label(box, text="Paper colour").pack(anchor="w", pady=(10, 4))
        grid = ttk.Frame(box)
        grid.pack(anchor="w")
        self.swatches = {}
        for i, (name, hexv) in enumerate(PAPER_COLORS.items()):
            b = tk.Button(grid, bg=hexv, width=2, height=1, relief="flat", bd=2,
                          highlightthickness=2, highlightbackground=BG,
                          command=lambda h=hexv: self._set_color(h))
            b.grid(row=i // 7, column=i % 7, padx=2, pady=2)
            self._tip(b, name)
            self.swatches[hexv] = b
        row = ttk.Frame(box)
        row.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Button(row, text="Custom…", command=self._pick_color).pack(side="left")
        self.l_color = ttk.Label(row, text="", style="Muted.TLabel")
        self.l_color.pack(side="left", padx=6)

        # -- texture / background
        self.v_texture = tk.StringVar()
        self._combo(box, "Paper texture", self.v_texture, TEXTURES, self._on_change)
        self.v_bake_bg = tk.BooleanVar(value=bool(self.params.background))
        self.v_bg_hex = tk.StringVar(value=self.params.background or "#EDE8DF")
        bgrow = ttk.Frame(box)
        bgrow.pack(anchor="w", fill="x", pady=(8, 0))
        ttk.Checkbutton(bgrow, text="Bake background", variable=self.v_bake_bg,
                        command=self._on_change).pack(side="left")
        ttk.Button(bgrow, text="…", width=3, command=self._pick_bg).pack(side="left", padx=4)
        ttk.Label(box, text="Off = transparent background and transparent opening.",
                  style="Muted.TLabel", wraplength=280).pack(anchor="w", pady=(2, 0))

        # -- seed
        ttk.Label(box, text="Seed", style="Head.TLabel").pack(anchor="w", pady=(14, 4))
        srow = ttk.Frame(box)
        srow.pack(anchor="w", fill="x")
        self.v_seed = tk.StringVar(value=str(self.params.seed))
        e = ttk.Entry(srow, textvariable=self.v_seed, width=14)
        e.pack(side="left")
        e.bind("<Return>", lambda _e: self._apply_seed())
        ttk.Button(srow, text="Apply", width=7, command=self._apply_seed).pack(side="left", padx=4)
        ttk.Label(box, text="The same seed + settings always rebuilds the identical frame.",
                  style="Muted.TLabel", wraplength=280).pack(anchor="w", pady=(2, 0))

        # -- actions
        ttk.Separator(box).pack(fill="x", pady=12)
        ttk.Button(box, text="GENERATE NEW FRAME", style="Primary.TButton",
                   command=self.generate_new).pack(fill="x")
        ttk.Button(box, text="RANDOMIZE", command=self.randomize).pack(fill="x", pady=(6, 0))

        # -- collection
        ttk.Label(box, text="COLLECTION", style="Head.TLabel").pack(anchor="w", pady=(16, 6))
        crow = ttk.Frame(box)
        crow.pack(anchor="w", fill="x")
        self.v_count = tk.IntVar(value=int(self.settings.get("collection_count", 20)))
        for n in (10, 20, 30, 50, 100):
            ttk.Radiobutton(crow, text=str(n), value=n, variable=self.v_count).pack(side="left")
        self.v_ratio_mode = tk.StringVar(value=self.settings.get("collection_ratio_mode", "mixed"))
        self.v_color_mode = tk.StringVar(value=self.settings.get("collection_color_mode", "current"))
        opts = ttk.Frame(box)
        opts.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Checkbutton(opts, text="Mixed ratios", onvalue="mixed", offvalue="current",
                        variable=self.v_ratio_mode).pack(anchor="w")
        ttk.Checkbutton(opts, text="Cycle palette colours", onvalue="palette", offvalue="current",
                        variable=self.v_color_mode).pack(anchor="w")
        ttk.Button(box, text="GENERATE COLLECTION", style="Primary.TButton",
                   command=self.generate_collection_).pack(fill="x", pady=(8, 0))
        self.progress = ttk.Progressbar(box, mode="determinate")
        self.progress.pack(fill="x", pady=(6, 0))
        self.b_cancel = ttk.Button(box, text="Cancel", command=self._cancel, state="disabled")
        self.b_cancel.pack(fill="x", pady=(4, 0))

        # -- export
        ttk.Label(box, text="EXPORT", style="Head.TLabel").pack(anchor="w", pady=(16, 6))
        prow = ttk.Frame(box)
        prow.pack(anchor="w", fill="x")
        ttk.Label(prow, text="PNG short side").pack(side="left")
        self.v_png = tk.IntVar(value=int(self.settings.get("png_min_side", 4000)))
        ttk.Combobox(prow, textvariable=self.v_png, width=7, state="readonly",
                     values=[2000, 3000, 4000, 5000, 6000, 8000]).pack(side="left", padx=6)
        nrow = ttk.Frame(box)
        nrow.pack(anchor="w", fill="x", pady=(4, 0))
        ttk.Label(nrow, text="Naming").pack(side="left")
        self.v_scheme = tk.StringVar(value=self.settings.get("naming_scheme", "style"))
        ttk.Combobox(nrow, textvariable=self.v_scheme, width=10, state="readonly",
                     values=["style", "plain"]).pack(side="left", padx=6)
        drow = ttk.Frame(box)
        drow.pack(anchor="w", fill="x", pady=(6, 0))
        self.v_dir = tk.StringVar(value=self.settings.get("export_dir"))
        ttk.Button(drow, text="Folder…", command=self._pick_dir).pack(side="left")
        self.l_dir = ttk.Label(drow, textvariable=self.v_dir, style="Muted.TLabel", wraplength=200)
        self.l_dir.pack(side="left", padx=6)
        ttk.Button(box, text="EXPORT CURRENT (SVG + PNG)", command=self.export_current).pack(fill="x", pady=(8, 0))
        ttk.Button(box, text="EXPORT COLLECTION", command=self.export_collection_).pack(fill="x", pady=(6, 12))

    def _combo(self, parent, label, var, values, cmd):
        ttk.Label(parent, text=label).pack(anchor="w", pady=(10, 2))
        c = ttk.Combobox(parent, textvariable=var, values=list(values), state="readonly", width=30)
        c.pack(anchor="w", fill="x")
        c.bind("<<ComboboxSelected>>", lambda _e: cmd())
        return c

    def _slider(self, parent, label, var, levels):
        head = ttk.Frame(parent)
        head.pack(anchor="w", fill="x", pady=(12, 0))
        ttk.Label(head, text=label).pack(side="left")
        val = ttk.Label(head, text="0", style="Muted.TLabel")
        val.pack(side="right")
        sc = ttk.Scale(parent, from_=0, to=100, variable=var, orient="horizontal")
        sc.pack(fill="x")
        sc.bind("<ButtonRelease-1>", lambda _e: self._on_change())
        var.trace_add("write", lambda *_: val.configure(text=f"{var.get():.0f}"))
        row = ttk.Frame(parent)
        row.pack(anchor="w", pady=(2, 0))
        for name, v in levels.items():
            ttk.Button(row, text=name, width=8,
                       command=lambda vv=v, vr=var: (vr.set(vv), self._on_change())).pack(side="left", padx=1)

    def _tip(self, widget, text):
        def enter(_e):
            self.status.configure(text=text)
        widget.bind("<Enter>", enter)

    # ------------------------------------------------------------------ preview
    def _build_preview(self, root):
        bar = ttk.Frame(root)
        bar.pack(fill="x")
        self.v_checker = tk.BooleanVar(value=True)
        ttk.Checkbutton(bar, text="Checkerboard", variable=self.v_checker,
                        command=self._redraw).pack(side="left")
        ttk.Button(bar, text="－", width=3, command=lambda: self._zoom(1 / 1.25)).pack(side="left", padx=(12, 2))
        ttk.Button(bar, text="＋", width=3, command=lambda: self._zoom(1.25)).pack(side="left", padx=2)
        ttk.Button(bar, text="Fit", width=5, command=self._fit).pack(side="left", padx=2)
        ttk.Button(bar, text="100%", width=6, command=lambda: self._set_zoom(1.0)).pack(side="left", padx=2)
        self.v_side = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Side-by-side before/after", variable=self.v_side,
                        command=self._redraw).pack(side="left", padx=12)
        b = ttk.Button(bar, text="Hold to see previous")
        b.pack(side="left")
        b.bind("<ButtonPress-1>", lambda _e: self._show_prev(True))
        b.bind("<ButtonRelease-1>", lambda _e: self._show_prev(False))

        self.tabs = ttk.Notebook(root)
        self.tabs.pack(fill="both", expand=True, pady=(8, 0))

        self.tab_current = ttk.Frame(self.tabs)
        self.canvas = tk.Canvas(self.tab_current, bg="#e9e6e0", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", lambda _e: self._redraw())
        self.tabs.add(self.tab_current, text="Current frame")

        self.tab_svg = ttk.Frame(self.tabs)
        self.svg_text = tk.Text(self.tab_svg, wrap="none", font=("Menlo", 9), bg="#fbfaf7")
        sb = ttk.Scrollbar(self.tab_svg, command=self.svg_text.yview)
        self.svg_text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.svg_text.pack(fill="both", expand=True)
        self.tabs.add(self.tab_svg, text="SVG")

        self.tab_png = ttk.Frame(self.tabs)
        prow = ttk.Frame(self.tab_png)
        prow.pack(fill="x")
        self.l_png = ttk.Label(prow, text="", style="Muted.TLabel")
        self.l_png.pack(side="left", padx=6, pady=4)
        ttk.Button(prow, text="Refresh 100% crop", command=self._png_crop).pack(side="right", padx=6)
        self.png_canvas = tk.Canvas(self.tab_png, bg="#e9e6e0", highlightthickness=0)
        self.png_canvas.pack(fill="both", expand=True)
        self.tabs.add(self.tab_png, text="PNG (100%)")

        self.tab_coll = ttk.Frame(self.tabs)
        self.coll_canvas = tk.Canvas(self.tab_coll, bg="#e9e6e0", highlightthickness=0)
        csb = ttk.Scrollbar(self.tab_coll, orient="vertical", command=self.coll_canvas.yview)
        self.coll_inner = ttk.Frame(self.coll_canvas)
        self.coll_inner.bind("<Configure>",
                             lambda e: self.coll_canvas.configure(scrollregion=self.coll_canvas.bbox("all")))
        self.coll_canvas.create_window((0, 0), window=self.coll_inner, anchor="nw")
        self.coll_canvas.configure(yscrollcommand=csb.set)
        csb.pack(side="right", fill="y")
        self.coll_canvas.pack(fill="both", expand=True)
        self.tabs.add(self.tab_coll, text="Collection")
        self.tabs.bind("<<NotebookTabChanged>>", self._on_tab)

    def _build_info(self, root):
        card = ttk.Frame(root, style="Card.TFrame", padding=12, width=250)
        card.pack(fill="y")
        card.pack_propagate(False)
        ttk.Label(card, text="FRAME INFO", style="Head.TLabel", background=PANEL).pack(anchor="w")
        self.info = tk.Text(card, width=28, height=34, relief="flat", bg=PANEL,
                            font=("Menlo", 9), wrap="word")
        self.info.pack(fill="both", expand=True, pady=(8, 0))
        self.info.configure(state="disabled")

    def _build_status(self):
        bar = ttk.Frame(self.master, padding=(12, 4))
        bar.pack(side="bottom", fill="x")
        self.status = ttk.Label(bar, text="Ready", style="Muted.TLabel")
        self.status.pack(side="left")
        self.spin = ttk.Label(bar, text="", style="Muted.TLabel")
        self.spin.pack(side="right")

    # ------------------------------------------------------------------ params <-> widgets
    def _sync_widgets_from_params(self):
        p = self.params
        self.v_style.set(p.style)
        self.v_ratio.set(p.ratio)
        self.v_border.set(p.border)
        self.v_edge.set(p.edge)
        self.v_texture.set(p.texture)
        self.v_wobble.set(p.wobble)
        self.v_asym.set(p.asymmetry)
        self.v_corner.set(p.corner_variation)
        self.v_seed.set(str(p.seed))
        self._mark_color(p.color)

    def _params_from_widgets(self) -> FrameParams:
        p = self.params.copy(
            style=self.v_style.get(), ratio=self.v_ratio.get(), border=self.v_border.get(),
            edge=self.v_edge.get(), texture=self.v_texture.get(),
            wobble=round(self.v_wobble.get()), asymmetry=round(self.v_asym.get()),
            corner_variation=round(self.v_corner.get()),
            background=self.v_bg_hex.get() if self.v_bake_bg.get() else None,
        )
        try:
            p.seed = max(1, min(MAX_SEED, int(self.v_seed.get())))
        except ValueError:
            pass
        return p

    def _mark_color(self, hexv):
        for h, b in self.swatches.items():
            b.configure(highlightbackground=ACCENT if h.lower() == hexv.lower() else BG,
                        relief="solid" if h.lower() == hexv.lower() else "flat")
        self.l_color.configure(text=hexv.upper())

    # ------------------------------------------------------------------ actions
    def _on_change(self):
        if self.busy:
            return
        self.params = self._params_from_widgets()
        self.params.preset = None if self.v_preset.get() == "— none —" else self.params.preset
        self.submit(Job("frame", params=self.params.copy()))

    def _on_preset(self):
        sel = self.v_preset.get()
        if sel == "— none —":
            return
        name = sel.split(": ", 1)[1]
        self.params = apply_preset(self._params_from_widgets(), name)
        # keep the free-form design fields the preset did not set
        self._sync_widgets_from_params()
        self.submit(Job("frame", params=self.params.copy()))

    def _set_color(self, hexv):
        self.params = self._params_from_widgets().copy(color=hexv)
        self._mark_color(hexv)
        self.submit(Job("frame", params=self.params.copy()))

    def _pick_color(self):
        c = colorchooser.askcolor(color=self.params.color, title="Paper colour")[1]
        if c:
            self._set_color(c)

    def _pick_bg(self):
        c = colorchooser.askcolor(color=self.v_bg_hex.get(), title="Baked background")[1]
        if c:
            self.v_bg_hex.set(c)
            self.v_bake_bg.set(True)
            self._on_change()

    def _apply_seed(self):
        self._on_change()

    def randomize(self):
        """A brand new valid seed (settings untouched)."""
        self.v_seed.set(str(random.randint(1, MAX_SEED)))
        self.params = self._params_from_widgets()
        self.submit(Job("frame", params=self.params.copy()))

    def generate_new(self):
        """A meaningfully different frame: retries seeds until the geometry differs."""
        self.params = self._params_from_widgets()
        self.submit(Job("new_frame", params=self.params.copy(), ref=self.frame))

    def generate_collection_(self):
        self.params = self._params_from_widgets()
        self.cancel_flag = False
        self.b_cancel.configure(state="normal")
        self.submit(Job("collection", params=self.params.copy(), count=int(self.v_count.get()),
                        ratio_mode=self.v_ratio_mode.get(), color_mode=self.v_color_mode.get(),
                        seed=self.params.seed))

    def _cancel(self):
        self.cancel_flag = True
        self.status.configure(text="Cancelling…")

    def _pick_dir(self):
        d = filedialog.askdirectory(initialdir=self.v_dir.get() or str(Path.home()))
        if d:
            self.v_dir.set(d)

    def export_current(self):
        if not self.frame:
            return
        d = self.v_dir.get() or str(Path.home())
        self.submit(Job("export_frame", frame=self.frame, out=d, png=int(self.v_png.get())))

    def export_collection_(self):
        if not self.collection:
            messagebox.showinfo("Nothing to export", "Generate a collection first.")
            return
        d = self.v_dir.get() or str(Path.home())
        sub = Path(d) / time.strftime("Collection_%Y%m%d_%H%M%S")
        self.cancel_flag = False
        self.b_cancel.configure(state="normal")
        self.submit(Job("export_collection", frames=list(self.collection), out=str(sub),
                        png=int(self.v_png.get()), scheme=self.v_scheme.get()))

    # ------------------------------------------------------------------ worker
    def submit(self, job):
        self.busy = True
        self.spin.configure(text="working…")
        self.jobs.put(job)

    def _worker_loop(self):
        while True:
            job = self.jobs.get()
            try:
                self._run_job(job)
            except Exception as exc:  # pragma: no cover - surfaced in the UI
                LOG.error("job %s failed: %s", job.kind, traceback.format_exc())
                self.q.put(("error", f"{job.kind}: {exc}"))

    def _run_job(self, job):
        t0 = time.time()
        if job.kind == "frame":
            fr = generate_frame(job.params, log=LOG)
            self.q.put(("frame", fr, time.time() - t0))
        elif job.kind == "new_frame":
            rsig = signature(job.ref) if job.ref is not None else None
            best_fr, best_d = None, -1.0
            for _ in range(24):
                p = job.params.copy(seed=random.randint(1, MAX_SEED))
                fr = generate_frame(p, log=LOG)
                if rsig is None:
                    best_fr = fr
                    break
                d = distance(signature(fr), rsig)
                if d > best_d:
                    best_fr, best_d = fr, d
                if d >= NEW_FRAME_MIN_DISTANCE:
                    break
            self.q.put(("frame", best_fr, time.time() - t0))
        elif job.kind == "collection":
            frames, stats = generate_collection(
                job.count, job.params, collection_seed=job.seed, ratio_mode=job.ratio_mode,
                color_mode=job.color_mode, log=LOG, cancel=lambda: self.cancel_flag,
                progress=lambda i, n, fr: self.q.put(("progress", i, n, fr.params.label)))
            self.q.put(("collection", frames, stats, time.time() - t0))
        elif job.kind == "export_frame":
            files = export_frame(job.frame, job.out, png_min_side=job.png)
            self.q.put(("exported", [str(f) for f in files], time.time() - t0))
        elif job.kind == "export_collection":
            export_collection(job.frames, job.out, png_min_side=job.png, scheme=job.scheme,
                              progress=lambda i, n: self.q.put(("progress", i, n, "exporting")))
            self.q.put(("exported", [job.out], time.time() - t0))

    def _pump(self):
        try:
            while True:
                msg = self.q.get_nowait()
                self._handle(msg)
        except queue.Empty:
            pass
        self.after(60, self._pump)

    def _handle(self, msg):
        kind = msg[0]
        if kind == "frame":
            _, fr, secs = msg
            if self.frame is not None and self.frame is not fr:
                self.previous = self.frame
            self.frame = fr
            self.params = fr.params
            self.v_seed.set(str(fr.seed_used))
            self.busy = False
            self.spin.configure(text="")
            self.status.configure(text=f"Frame ready in {secs:.2f}s"
                                       f"{' · ' + str(fr.attempts) + ' QA attempts' if fr.attempts > 1 else ''}")
            self._redraw()
            self._update_info()
            self._update_svg()
        elif kind == "progress":
            _, i, n, label = msg
            self.progress.configure(maximum=n, value=i)
            self.status.configure(text=f"{i}/{n} · {label}")
        elif kind == "collection":
            _, frames, stats, secs = msg
            self.collection, self.collection_stats = frames, stats
            self.busy = False
            self.spin.configure(text="")
            self.b_cancel.configure(state="disabled")
            self.progress.configure(value=0)
            self.status.configure(
                text=f"{len(frames)} frames in {secs:.1f}s · {stats['rejected_duplicates']} duplicates rejected"
                     f" · {stats['qa_retries']} QA retries")
            self._build_thumbs()
            self.tabs.select(self.tab_coll)
        elif kind == "exported":
            _, files, secs = msg
            self.busy = False
            self.spin.configure(text="")
            self.b_cancel.configure(state="disabled")
            self.progress.configure(value=0)
            self.status.configure(text=f"Exported in {secs:.1f}s → {files[-1]}")
            self._save_settings()
        elif kind == "error":
            self.busy = False
            self.spin.configure(text="")
            self.b_cancel.configure(state="disabled")
            self.status.configure(text="Error")
            messagebox.showerror("Wobbly Paper Frames", msg[1])

    # ------------------------------------------------------------------ drawing
    def _zoom(self, f):
        self.fit = False
        self.zoom = max(0.1, min(8.0, self.zoom * f))
        self._redraw()

    def _set_zoom(self, z):
        self.fit = False
        self.zoom = z
        self._redraw()

    def _fit(self):
        self.fit = True
        self._redraw()

    def _show_prev(self, on):
        self.showing_previous = on and self.previous is not None
        self._redraw()

    def _render(self, fr, w, h):
        w, h = max(1, int(w)), max(1, int(h))
        return ImageTk.PhotoImage(render_image(fr, w, h, checker=self.v_checker.get()))

    def _redraw(self):
        if not self.frame:
            return
        c = self.canvas
        c.delete("all")
        cw, ch = max(c.winfo_width(), 50), max(c.winfo_height(), 50)
        frames = [self.frame]
        if self.v_side.get() and self.previous is not None:
            frames = [self.previous, self.frame]
        elif self.showing_previous and self.previous is not None:
            frames = [self.previous]
        pad = 24
        slot_w = (cw - pad * (len(frames) + 1)) / len(frames)
        self._photo.clear()
        for i, fr in enumerate(frames):
            base = min(slot_w / fr.width, (ch - pad * 2) / fr.height)
            s = base if self.fit else self.zoom * base if len(frames) > 1 else self.zoom
            w, h = min(fr.width * s, PREVIEW_MAX), min(fr.height * s, PREVIEW_MAX)
            img = self._render(fr, w, h)
            self._photo[i] = img
            x = pad + i * (slot_w + pad) + slot_w / 2
            c.create_image(x, ch / 2, image=img)
            if len(frames) > 1:
                c.create_text(x, ch - 10, text="before" if i == 0 else "after", fill="#7b7669")
        if self.showing_previous and self.previous is not None and len(frames) == 1:
            c.create_text(cw / 2, 16, text="previous frame", fill="#7b7669")
        if self.fit:
            self.zoom = 1.0

    def _update_svg(self):
        svg = to_svg(self.frame)
        self.svg_text.configure(state="normal")
        self.svg_text.delete("1.0", "end")
        self.svg_text.insert("1.0", svg)
        self.svg_text.configure(state="disabled")

    def _png_crop(self):
        if not self.frame:
            return
        w, h, _ = output_size(self.frame, int(self.v_png.get()))
        cw = max(self.png_canvas.winfo_width(), 200)
        chh = max(self.png_canvas.winfo_height(), 200)
        cw, chh = min(cw, w), min(chh, h)
        x, y = (w - cw) // 2, (h - chh) // 8      # top-left corner region of the frame
        img = render_crop_image(self.frame, w, h, (x, y, cw, chh), checker=self.v_checker.get())
        self._photo["png"] = ImageTk.PhotoImage(img)
        self.png_canvas.delete("all")
        self.png_canvas.create_image(cw / 2, chh / 2, image=self._photo["png"])
        self.l_png.configure(text=f"Export size {w} × {h} px · showing a {cw} × {chh} px crop at 100%")

    def _on_tab(self, _e=None):
        if self.tabs.select() == str(self.tab_png):
            self._png_crop()

    def _build_thumbs(self):
        for w in self.coll_inner.winfo_children():
            w.destroy()
        self._thumbs = []
        cols = 6
        for i, fr in enumerate(self.collection):
            s = 150 / max(fr.width, fr.height)
            img = ImageTk.PhotoImage(render_image(fr, max(1, int(fr.width * s)),
                                                  max(1, int(fr.height * s)), checker=True))
            self._thumbs.append(img)
            cell = ttk.Frame(self.coll_inner, padding=4)
            cell.grid(row=i // cols, column=i % cols)
            b = tk.Button(cell, image=img, relief="flat", bd=0, bg="#e9e6e0",
                          command=lambda f=fr: self._select_from_collection(f))
            b.pack()
            ttk.Label(cell, text=f"{i + 1:03d} · {fr.params.label or fr.params.style}",
                      style="Muted.TLabel", wraplength=150).pack()

    def _select_from_collection(self, fr):
        self.previous = self.frame
        self.frame = fr
        self.params = fr.params
        self._sync_widgets_from_params()
        self.v_seed.set(str(fr.seed_used))
        self._redraw()
        self._update_info()
        self._update_svg()
        self.tabs.select(self.tab_current)

    def _update_info(self):
        fr = self.frame
        d = fr.design
        rep = fr.report or {}
        w, h, _ = output_size(fr, int(self.v_png.get()))
        sim = ""
        if self.previous is not None:
            sim = f"vs previous   {similarity_percent(signature(fr), signature(self.previous))}% similar\n"
        lines = [
            f"Name        {current_filename(fr)}",
            f"Style       {fr.params.style}",
            f"Preset      {fr.params.preset or '—'}",
            f"Label       {fr.params.label or '—'}",
            f"Ratio       {fr.params.ratio}  ({fr.width}×{fr.height} units)",
            f"Border      {fr.params.border}",
            f"Edge        {d.get('edge', '—')}",
            f"Silhouette  {d.get('silhouette', '—')}",
            f"Corners     {d.get('corner_style', '—')}",
            f"Opening     {d.get('opening', '—')}",
            "",
            f"Wobble      {fr.params.wobble:.0f}",
            f"Asymmetry   {fr.params.asymmetry:.0f}",
            f"Corner var. {fr.params.corner_variation:.0f}",
            f"Texture     {fr.params.texture}",
            f"Colour      {fr.params.color}",
            f"Background  {fr.params.background or 'transparent'}",
            "",
            f"Seed        {fr.seed_used}",
            f"QA attempts {fr.attempts}",
            f"PNG export  {w} × {h} px",
            "",
            "QA",
            f"  min border   {100 * rep.get('min_border', 0) / rep.get('nominal_min_side', 1):.0f}% of nominal",
            f"  opening area {100 * rep.get('open_area_ratio', 0):.0f}% of frame",
            f"  solidity     {rep.get('solidity_outer', 0):.3f} / {rep.get('solidity_inner', 0):.3f}",
            f"  max turn     {rep.get('max_turn_outer', 0):.0f}deg",
            f"  result       {'PASS' if not rep.get('failures') else 'FAIL: ' + ', '.join(rep['failures'])}",
            "",
            sim,
        ]
        self.info.configure(state="normal")
        self.info.delete("1.0", "end")
        self.info.insert("1.0", "\n".join(x for x in lines if x is not None))
        self.info.configure(state="disabled")

    # ------------------------------------------------------------------ settings
    def _save_settings(self):
        self.settings.update(params=self.params.to_dict(), png_min_side=int(self.v_png.get()),
                             export_dir=self.v_dir.get(), collection_count=int(self.v_count.get()),
                             collection_ratio_mode=self.v_ratio_mode.get(),
                             collection_color_mode=self.v_color_mode.get(),
                             naming_scheme=self.v_scheme.get())
        settings_mod.save(self.settings)

    def on_close(self):
        self._save_settings()
        self.master.destroy()


def run():
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    run()
