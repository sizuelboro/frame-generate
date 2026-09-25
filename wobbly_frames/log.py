import logging
from .settings import APP_DIR


def get_logger():
    log = logging.getLogger("wobbly_frames")
    if log.handlers:
        return log
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(APP_DIR / "generator.log", encoding="utf-8")
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except Exception:
        pass
    return log
