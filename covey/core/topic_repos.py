"""The repositories a topic uses (``topic.json`` ``repos``), the repository of a path, and a task's requests to use one.

``repo_of`` (moved here from app/repo_peers.py, which keeps the name) finds the repository of a path: the nearest
ancestor holding ``.git``, a linked worktree counting as the repository its ``.git`` file names; cached for ``TTL``
seconds, at most ``DEPTH`` levels up. A task asks for a repository through ``covey repo use`` (bin/covey_repo.py), which
writes only the task's own ``runs/<任务键>/repos.json`` (core/run_dir.py ``REPOS``) with the worktree's ``base_oid``;
the Bridge folds it into the topic when the turn settles, and core/diff.py makes the diff of a worktree made in the
middle of a turn from that base (FINAL-SPEC 修订 9). A0: ``repo_of`` and the shapes; the rest is package W1's.
"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from covey.core.run_dir import REPOS

TTL = 10 * 60
DEPTH = 12
MODES = ("read", "write")
SOURCES = ("declared", "cli", "touched", "checkpoint")

cache: dict[str, tuple[float, str]] = {}  # repo_of's: path -> (when, repository); app/repo_peers.py names it too.
_lock = threading.Lock()


@dataclass(frozen=True)
class TopicRepo:
    name: str
    path: str
    mode: str = "read"  # MODES
    worktree: str = ""
    branch: str = ""
    base: str = ""  # "<remote branch>@<short oid>" as shown.
    base_oid: str = ""  # The full commit the worktree started from: the diff's base when no snapshot was taken.
    source: str = "touched"  # SOURCES
    first_at: float = 0.0
    rules_read_at: float = 0.0
    rules_miss: int = 0


def repo_of(workdir, now=None) -> str:
    """The repository of ``workdir`` as a path ('' for none): its ``.git`` directory's, or for a linked worktree the
    main one's, which its ``.git`` file names."""
    key = str(workdir or "")
    if not key.startswith("/"):
        return ""
    now = time.time() if now is None else now
    with _lock:
        hit = cache.get(key)
        if hit and now - hit[0] < TTL:
            return hit[1]
    found = _find(Path(key))
    with _lock:
        if len(cache) > 256:
            cache.clear()
        cache[key] = (now, found)
    return found


def _find(path: Path) -> str:
    try:
        for level, directory in enumerate([path, *path.parents]):
            if level > DEPTH or str(directory) == "/":
                return ""
            git = directory / ".git"
            if git.is_dir():
                return str(git.resolve())
            if git.is_file():
                return _linked(git)
    except (OSError, ValueError):
        return ""
    return ""


def _linked(git: Path) -> str:
    """The main repository's ``.git`` of a worktree's ``.git`` file ("gitdir: <main>/.git/worktrees/<name>"), else its own path."""
    try:
        text = git.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if not text.startswith("gitdir:"):
        return ""
    target = Path(text[len("gitdir:"):].strip())
    if not target.is_absolute():
        target = git.parent / target
    parts = target.resolve().parts
    return str(Path(*parts[:parts.index("worktrees")])) if "worktrees" in parts else str(target.resolve())


def requests_path(task_dir) -> Path:
    return Path(task_dir) / REPOS


def requests(task_dir) -> list[dict]:
    """The ``covey repo use`` requests a task wrote (``{at, name, mode, worktree, branch, base_oid}`` each); [] for none."""
    try:
        data = json.loads(requests_path(task_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = data.get("requests") if isinstance(data, dict) else None
    return [item for item in found if isinstance(item, dict)] if isinstance(found, list) else []


def touched(trace, repos) -> list[TopicRepo]:
    """The repositories a turn's tool calls (``trace``) touched, by the repo map ``repos``: W1."""
    raise NotImplementedError("W1")
