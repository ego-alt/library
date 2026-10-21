"""The download worker: one background thread that follows downloads, imports
new files, refreshes comic series and searches for wanted books and issues.

Gunicorn runs several processes; each starts the thread on its first request,
and a file lock lets only one of them work (another takes over if it dies).
Pages ask for a job to run soon by touching a request file the worker looks
for every few seconds, so a click on "Search all" doesn't wait for a request
to finish.
"""

import fcntl
import json
import logging
import os
import threading
import time
from datetime import datetime, timezone

from flask import current_app

from .. import settings
from ..books import getting as books
from ..comics import downloads as comic_downloads
from ..comics import files as comic_files
from ..comics.series import due_for_refresh, refresh_series
from ..config import DATA_DIR
from ..models import db
from . import pipeline

logger = logging.getLogger(__name__)

TICK = 5  # seconds between looks at the request files
EVERY = {
    "downloads": 60,
    "import": 120,
    "refresh": 30 * 60,
    # "search" comes from settings (search_interval_hours).
}
JOBS = ("downloads", "import", "refresh", "search")

_started = False
_start_lock = threading.Lock()


def _state_dir() -> str:
    return current_app.config.get("WORKER_STATE_DIR") or DATA_DIR


def _state_path() -> str:
    return os.path.join(_state_dir(), "downloads-worker.json")


def _request_path(job: str) -> str:
    return os.path.join(_state_dir(), f"downloads-run-{job}")


def request_run(job: str) -> None:
    """Ask the worker to run a job at its next look (within TICK seconds)."""
    if job not in JOBS:
        raise ValueError(job)
    os.makedirs(_state_dir(), exist_ok=True)
    with open(_request_path(job), "w"):
        pass


def status() -> dict:
    """What the worker last did: {job: {"at", "ok", "message"}, "alive": bool}."""
    try:
        with open(_state_path()) as f:
            state = json.load(f)
    except (OSError, ValueError):
        state = {}
    beat = state.get("heartbeat")
    state["alive"] = bool(beat) and time.time() - beat < 5 * 60
    state["pending"] = [job for job in JOBS if os.path.exists(_request_path(job))]
    return state


def _save_state(state: dict) -> None:
    tmp = _state_path() + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, _state_path())


def import_all() -> dict:
    """Import what's in the import folder: comics to their issues, EPUBs to
    the books. Returns {"imported", "unmatched", "failed"} counts' lists."""
    result = comic_files.scan_import_dir()
    comic_downloads.mark_imported(result["imported"])
    found = books.scan_import_dir(comic_files.import_dir())
    return {"imported": result["imported"] + found["imported"], "unmatched": result["unmatched"], "failed": result["failed"] + found["failed"]}


def describe_import(result: dict) -> str:
    parts = [f"imported {len(result['imported'])}"]
    if result["unmatched"]:
        parts.append(f"{len(result['unmatched'])} to match by hand")
    if result["failed"]:
        parts.append(f"{len(result['failed'])} unreadable")
    return ", ".join(parts).capitalize() + "."


def run_job(job: str) -> str:
    """Run one job now, in this thread. Returns a sentence about what it did."""
    if job == "downloads":
        active = pipeline.check_downloads()
        return f"{active} download{'s' if active != 1 else ''} in progress."
    if job == "import":
        return describe_import(import_all())
    if job == "refresh":
        due = due_for_refresh()
        new, errors = 0, []
        for series in due:
            try:
                new += refresh_series(series)
            except Exception as e:
                db.session.rollback()
                errors.append(f"{series.name}: {e}")
        if errors:
            raise RuntimeError("; ".join(errors[:3]))
        return f"Refreshed {len(due)} series; {new} new issue{'s' if new != 1 else ''}."
    if job == "search":
        if not settings.get("indexers"):
            return "No indexers yet."
        grabbed = pipeline.search_wanted()
        return f"Grabbed {grabbed} release{'s' if grabbed != 1 else ''}."
    raise ValueError(job)


def _loop(app) -> None:
    with app.app_context():
        os.makedirs(_state_dir(), exist_ok=True)
        lock_file = open(os.path.join(_state_dir(), "downloads-worker.lock"), "w")
    while True:
        try:
            fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            time.sleep(60)
    logger.info("Download worker running in process %s", os.getpid())
    with app.app_context():
        state = status()
    state.pop("alive", None)
    state.pop("pending", None)
    while True:
        now = time.time()
        with app.app_context():
            try:
                search_every = float(settings.get("search_interval_hours") or 6) * 3600
            except Exception:
                search_every = 6 * 3600
            for job in JOBS:
                interval = EVERY.get(job, search_every)
                last = state.get(job, {}).get("ts", 0)
                requested = os.path.exists(_request_path(job))
                if not requested and now - last < interval:
                    continue
                if requested:
                    try:
                        os.remove(_request_path(job))
                    except OSError:
                        pass
                try:
                    message, ok = run_job(job), True
                except Exception as e:
                    logger.exception("Download job %s failed", job)
                    message, ok = str(e), False
                    db.session.rollback()
                finally:
                    db.session.remove()
                state[job] = {"ts": time.time(), "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "ok": ok, "message": message}
            state["heartbeat"] = time.time()
            try:
                _save_state(state)
            except OSError:
                pass
        time.sleep(TICK)


def start(app) -> None:
    """Start the worker thread in this process, once."""
    global _started
    if _started or app.config.get("TESTING") or not app.config.get("DOWNLOADS_WORKER"):
        return
    with _start_lock:
        if _started:
            return
        _started = True
        threading.Thread(target=_loop, args=(app,), daemon=True, name="downloads-worker").start()
