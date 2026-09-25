"""Local web UI for the Wobbly Paper Frames Generator.

    python web.py            ->  http://127.0.0.1:8765

Pure standard-library HTTP server in front of the same tested generation engine,
so the browser UI and the CLI always produce identical files.
"""
from __future__ import annotations

import io
import json
import mimetypes
import threading
import time
import traceback
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .collection import ARCHETYPES, generate_collection
from .engine import MAX_SEED, generate_frame
from .export import export_collection, export_frame
from .log import get_logger
from .naming import current_filename
from .params import (ASYMMETRY_LEVELS, BORDERS, CORNER_LEVELS, EDGE_MODES, PAPER_COLORS,
                     PRESET_GROUPS, PRESETS, RATIOS, STYLES, TEXTURES, WOBBLE_LEVELS,
                     FrameParams, apply_preset)
from .raster import output_size, save_png
from .similarity import distance, signature, similarity_percent
from .svg_export import to_svg

LOG = get_logger()
WEB = Path(__file__).parent / "web"
NEW_FRAME_MIN_DISTANCE = 3.0

# ------------------------------------------------------------------ app state
class State:
    def __init__(self):
        self.lock = threading.Lock()
        self.current = None
        self.previous = None
        self.collection = []
        self.stats = {}
        self.jobs = {}

    def job(self, fn):
        jid = uuid.uuid4().hex[:12]
        self.jobs[jid] = dict(status="running", done=0, total=0, message="", result=None, error=None)

        def run():
            try:
                fn(self.jobs[jid])
                self.jobs[jid]["status"] = "done"
            except Exception as exc:
                LOG.error("job failed: %s", traceback.format_exc())
                self.jobs[jid].update(status="error", error=str(exc))
        threading.Thread(target=run, daemon=True).start()
        return jid


ST = State()


def frame_info(fr, ref=None):
    d, rep = fr.design, fr.report or {}
    w, h, _ = output_size(fr, 4000)
    info = dict(
        name=current_filename(fr), style=fr.params.style, preset=fr.params.preset,
        label=fr.params.label, ratio=fr.params.ratio, units=f"{fr.width}x{fr.height}",
        border=fr.params.border, edge=d.get("edge"), silhouette=d.get("silhouette"),
        corner_style=d.get("corner_style"), opening=d.get("opening"),
        wobble=round(fr.params.wobble), asymmetry=round(fr.params.asymmetry),
        corner_variation=round(fr.params.corner_variation), texture=fr.params.texture,
        color=fr.params.color, background=fr.params.background or "transparent",
        seed=fr.seed_used, attempts=fr.attempts, png=f"{w} x {h} px",
        qa_border=round(100 * rep.get("min_border", 0) / max(rep.get("nominal_min_side", 1), 1)),
        qa_open=round(100 * rep.get("open_area_ratio", 0)),
        qa_solidity=round(rep.get("solidity_outer", 0), 3),
        qa_turn=round(rep.get("max_turn_outer", 0)),
        qa_pass=not rep.get("failures"), qa_failures=rep.get("failures") or [],
        width=fr.width, height=fr.height,
    )
    if ref is not None:
        info["similarity"] = similarity_percent(signature(fr), signature(ref))
    return info


def params_from(body) -> FrameParams:
    p = FrameParams.from_dict({**FrameParams().to_dict(), **body.get("params", {})})
    if body.get("preset"):
        p = apply_preset(p, body["preset"])
        for k in ("wobble", "asymmetry", "corner_variation", "ratio", "border", "style", "edge"):
            if k in body.get("overrides", {}):
                setattr(p, k, body["overrides"][k])
    p.seed = max(1, min(MAX_SEED, int(p.seed or 1)))
    return p


# ------------------------------------------------------------------ handlers
def api_options():
    return dict(styles=STYLES, ratios=list(RATIOS), borders=list(BORDERS), edges=EDGE_MODES,
                textures=TEXTURES, colors=PAPER_COLORS, presets=PRESETS, preset_groups=PRESET_GROUPS,
                levels=dict(wobble=WOBBLE_LEVELS, asymmetry=ASYMMETRY_LEVELS, corner=CORNER_LEVELS),
                archetypes=[a["label"] for a in ARCHETYPES], defaults=FrameParams().to_dict(),
                max_seed=MAX_SEED)


def api_frame(body):
    p = params_from(body)
    mode = body.get("mode", "set")
    t0 = time.time()
    with ST.lock:
        ref = ST.current
    if mode == "new" and ref is not None:
        import random
        rsig = signature(ref)
        best, best_d = None, -1.0
        for _ in range(24):
            fr = generate_frame(p.copy(seed=random.randint(1, MAX_SEED)), log=LOG)
            d = distance(signature(fr), rsig)
            if d > best_d:
                best, best_d = fr, d
            if d >= NEW_FRAME_MIN_DISTANCE:
                break
        fr = best
    else:
        fr = generate_frame(p, log=LOG)
    with ST.lock:
        if ST.current is not None and ST.current is not fr:
            ST.previous = ST.current
        ST.current = fr
        prev = ST.previous
    return dict(svg=to_svg(fr), info=frame_info(fr, prev), secs=round(time.time() - t0, 2),
                previous_svg=to_svg(prev) if prev is not None else None)


def api_collection(body):
    p = params_from(body)
    count = int(body.get("count", 20))

    def work(job):
        job["total"] = count
        frames, stats = generate_collection(
            count, p, collection_seed=p.seed, ratio_mode=body.get("ratio_mode", "mixed"),
            color_mode=body.get("color_mode", "palette"), log=LOG,
            cancel=lambda: job.get("cancel"),
            progress=lambda i, n, fr: job.update(done=i, total=n, message=fr.params.label or ""))
        with ST.lock:
            ST.collection, ST.stats = frames, stats
        job["result"] = dict(
            stats=stats,
            frames=[dict(index=i + 1, label=f.params.label, style=f.params.style, ratio=f.params.ratio,
                         seed=f.seed_used, color=f.params.color, svg=to_svg(f), info=frame_info(f))
                    for i, f in enumerate(frames)])
    return dict(job=ST.job(work))


def api_export(body):
    scope = body.get("scope", "current")
    out = Path(body.get("dir") or (Path.home() / "Wobbly Paper Frames")).expanduser()
    size = int(body.get("png_min_side", 4000))
    scheme = body.get("scheme", "style")

    def work(job):
        if scope == "current":
            with ST.lock:
                fr = ST.current
            if fr is None:
                raise RuntimeError("No current frame")
            job["total"] = 1
            files = export_frame(fr, out, png_min_side=size)
            job["result"] = dict(dir=str(out), files=[f.name for f in files])
            job["done"] = 1
        else:
            with ST.lock:
                frames = list(ST.collection)
            if not frames:
                raise RuntimeError("Generate a collection first")
            sub = out / time.strftime("Collection_%Y%m%d_%H%M%S")
            job["total"] = len(frames)
            export_collection(frames, sub, png_min_side=size, scheme=scheme,
                              progress=lambda i, n: job.update(done=i, total=n))
            job["result"] = dict(dir=str(sub), files=[f"{len(frames)} frames + manifest + preview"])
    return dict(job=ST.job(work))


def png_bytes(fr, size):
    buf = io.BytesIO()
    tmp = Path(f"/tmp/wpf_{uuid.uuid4().hex}.png")
    try:
        save_png(fr, tmp, size)
        buf.write(tmp.read_bytes())
    finally:
        tmp.unlink(missing_ok=True)
    return buf.getvalue()


ROUTES = {"/api/frame": api_frame, "/api/collection": api_collection, "/api/export": api_export}


class Handler(BaseHTTPRequestHandler):
    server_version = "WobblyFrames"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json", headers=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path in ("/", "/index.html"):
            return self._send(200, (WEB / "index.html").read_bytes(), "text/html; charset=utf-8")
        if u.path.startswith("/static/"):
            f = WEB / u.path[len("/static/"):]
            if f.is_file():
                return self._send(200, f.read_bytes(), mimetypes.guess_type(f.name)[0] or "text/plain")
            return self._send(404, b"not found", "text/plain")
        if u.path == "/api/options":
            return self._send(200, json.dumps(api_options()))
        if u.path == "/api/job":
            job = ST.jobs.get(q.get("id", [""])[0])
            if not job:
                return self._send(404, json.dumps(dict(error="unknown job")))
            return self._send(200, json.dumps(job))
        if u.path == "/api/cancel":
            job = ST.jobs.get(q.get("id", [""])[0])
            if job:
                job["cancel"] = True
            return self._send(200, json.dumps(dict(ok=True)))
        if u.path == "/api/png":
            size = int(q.get("size", ["4000"])[0])
            idx = q.get("index", ["current"])[0]
            with ST.lock:
                fr = ST.current if idx == "current" else ST.collection[int(idx) - 1]
            if fr is None:
                return self._send(404, b"no frame", "text/plain")
            name = current_filename(fr) + ".png"
            return self._send(200, png_bytes(fr, size), "image/png",
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        if u.path == "/api/svg":
            idx = q.get("index", ["current"])[0]
            with ST.lock:
                fr = ST.current if idx == "current" else ST.collection[int(idx) - 1]
            if fr is None:
                return self._send(404, b"no frame", "text/plain")
            return self._send(200, to_svg(fr), "image/svg+xml",
                              {"Content-Disposition": f'attachment; filename="{current_filename(fr)}.svg"'})
        return self._send(404, json.dumps(dict(error="not found")))

    def do_POST(self):
        u = urlparse(self.path)
        fn = ROUTES.get(u.path)
        if not fn:
            return self._send(404, json.dumps(dict(error="not found")))
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        try:
            return self._send(200, json.dumps(fn(body)))
        except Exception as exc:
            LOG.error("%s failed: %s", u.path, traceback.format_exc())
            return self._send(500, json.dumps(dict(error=str(exc))))


def run(host="127.0.0.1", port=8765, open_browser=True):
    srv = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}"
    LOG.info("Wobbly Paper Frames Generator running at %s  (Ctrl+C to stop)", url)
    if open_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopped")
    finally:
        srv.server_close()


if __name__ == "__main__":
    run()
