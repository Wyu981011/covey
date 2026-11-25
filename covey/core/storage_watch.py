"""What this process saw of its disk going wrong, kept in memory for the health snapshot, the diagnostics and the alert
(app/storage_alerts.py, service/doctor_words.py):

- ``note_failure``: a write refused for want of space (``full``: EDQUOT "Disk quota exceeded", ENOSPC "No space left on
  device"). Once the state directory's disk is full every record write fails, and the log said only "OSError" (T784);
- ``watched``: a lock waited for or held, a record read, that has not ended SLOW_SECONDS after it began. A watcher thread
  (``start``, the Bridge's) looks every LOOK_EVERY seconds at what is in flight; one past SLOW_SECONDS has its thread's
  stack logged once ("slow <what>: … s so far, at …") and kept, the newest KEPT, with how long it took in the end. A
  process without the watcher (a task runner) only keeps the in-flight table, a dict entry a step.

``snapshot`` is what the last RECENT seconds kept. Standard library only: core/locks.py and core/loops.py use it.
"""
from __future__ import annotations

import collections
import errno
import os
import sys
import threading
import time
import traceback

FULL_ERRNOS = frozenset({errno.ENOSPC, getattr(errno, "EDQUOT", errno.ENOSPC)})
SLOW_SECONDS = 2.0
LOOK_EVERY = 0.5
KEPT = 20
RECENT = 6 * 3600  # What ``snapshot`` says: the last six hours.
FRAMES = 8  # Of a slow step's stack, the innermost frames.
WHAT_CHARS = 80

_full: dict = {}
_slow: collections.deque = collections.deque(maxlen=KEPT)
_inflight: dict = {}  # id(watched) -> [what, thread ident, started (monotonic), its row once logged]
_watcher = None
_log = None


def full(exc) -> bool:
    """Whether ``exc`` is a write refused for want of space (a quota or a full disk)."""
    return isinstance(exc, OSError) and exc.errno in FULL_ERRNOS


def note_failure(exc, where) -> bool:
    """Keep ``exc`` when it is ``full`` (the latest one, with ``where`` it came from); whether it was."""
    if not full(exc):
        return False
    filename = getattr(exc, "filename", None)
    _full.update(at=time.time(), error=exc.strerror or type(exc).__name__, where=str(where)[:WHAT_CHARS],
                 directory=os.path.dirname(str(filename))[-120:] if filename else "",
                 count=int(_full.get("count") or 0) + 1)
    return True


def reason(exc) -> str:
    """An exception for a log line, its words when it is an OSError (no path: "OSError: Disk quota exceeded"), else its
    kind alone, as before."""
    said = getattr(exc, "strerror", None) if isinstance(exc, OSError) else None
    return f"{type(exc).__name__}: {said}" if said else type(exc).__name__


class watched:
    """A step that may hang on the disk (a lock waited for or held, a record read), told to the watcher while it runs:
    ``with watched("读记录 x.json"): ...``, or ``enter``/``leave`` around a hold that spans two calls."""

    __slots__ = ("what",)

    def __init__(self, what):
        self.what = what

    def __enter__(self):
        return self.enter()

    def __exit__(self, *exc):
        self.leave()
        return False

    def enter(self):
        _inflight[id(self)] = [self.what, threading.get_ident(), time.monotonic(), None]
        return self

    def leave(self):
        entry = _inflight.pop(id(self), None)
        if entry is not None and entry[3] is not None:
            entry[3]["seconds"] = round(time.monotonic() - entry[2], 1)  # How long it took in the end.
            entry[3]["ended"] = True


def stack_of(frame) -> str:
    """The innermost FRAMES frames of ``frame``'s stack, innermost first: "core/store.py:466 _read ← app/x.py:12 f"."""
    if frame is None:
        return ""
    found = traceback.extract_stack(frame)[-FRAMES:]
    return " ← ".join(f"{_short(row.filename)}:{row.lineno} {row.name}" for row in reversed(found))


def _short(path) -> str:
    path = str(path)
    mark = path.rfind("/covey/")
    return path[mark + 1:] if mark >= 0 else os.path.basename(path)


def look(now=None) -> list:
    """Log and keep each step in flight past SLOW_SECONDS not told yet; the rows kept (the watcher's tick)."""
    now = time.monotonic() if now is None else now
    try:
        late = [entry for entry in list(_inflight.values()) if entry[3] is None and now - entry[2] >= SLOW_SECONDS]
    except RuntimeError:  # The table changed while it was copied: the next look sees it.
        return []
    if not late:
        return []
    frames = sys._current_frames()
    rows = []
    for entry in late:
        row = {"at": time.time(), "what": str(entry[0])[:WHAT_CHARS], "seconds": round(now - entry[2], 1),
               "ended": False, "stack": stack_of(frames.get(entry[1]))}
        entry[3] = row
        _slow.append(row)
        rows.append(row)
        if _log is not None:
            _log(f"slow {row['what']}: {row['seconds']} s so far, at {row['stack']}")
    return rows


def start(log) -> None:
    """Start this process's watcher thread, once; ``log``: a line to the process's log."""
    global _watcher, _log
    _log = log
    if _watcher is not None and _watcher.is_alive():
        return

    def run():
        while True:
            time.sleep(LOOK_EVERY)
            try:
                look()
            except Exception:  # noqa: BLE001 - a look that failed is the next one's to make
                pass

    _watcher = threading.Thread(target=run, daemon=True, name="storage-watch")
    _watcher.start()


def snapshot(now=None) -> dict:
    """{"full": the latest refused write, "slow": the slow steps, newest first} of the last RECENT seconds; {} when there
    is none."""
    now = time.time() if now is None else now
    found = {}
    if _full and now - _full.get("at", 0) < RECENT:
        found["full"] = dict(_full)
    slow = [dict(row) for row in reversed(_slow) if now - row["at"] < RECENT]
    if slow:
        found["slow"] = slow
    return found


def reset() -> None:
    """Forget what was kept (tests)."""
    _full.clear()
    _slow.clear()
    _inflight.clear()
