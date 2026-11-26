"""The memory's one change sentinel, ``<state>/memory/.rev``: every write of any memory store touches it (``touch``), so the
web sync stats one file to know the memory changed (docs/operations.md 状态目录). Here alone, standard library only, so the
older stores (core/principles.py, core/knowledge.py, core/project_memory.py) touch it without importing core/memstore.py,
which reads them."""
from __future__ import annotations

import os
import time
from pathlib import Path

MEMORY_DIR = "memory"
REV_FILE = ".rev"


def rev_path(state_dir) -> Path:
    return Path(state_dir) / MEMORY_DIR / REV_FILE


def touch(state_dir, now: float | None = None, *, create: bool = True) -> None:
    """Mark that some memory changed (the sentinel's mtime ``now``); never raises. ``create`` False (an older store's
    write): only where the memory's folder is there already (core/migrate.py memory_v2 made it), so a deployment that
    never migrated, or has the memory off, gets no new folder."""
    path = rev_path(state_dir)
    if not create and not path.parent.is_dir():
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        stamp = time.time() if now is None else now
        os.utime(path, (stamp, stamp))
    except OSError:
        pass
