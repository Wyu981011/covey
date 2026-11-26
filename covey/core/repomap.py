"""The repo map (仓库地图, ``<state>/repos.json``): the git repositories this deployment works in, and the ``covey repo`` command.

Each repository has a name, a path, what it is for (``note``), a status (``frozen`` ones are never written to) and how a
topic writes to it (FINAL-SPEC 修订 9 ``write_mode``: ``worktree`` makes the topic's own worktree under
``<数据根>/worktrees/T<号>-<id8>/<仓库>/``, ``inplace`` edits the checkout; a new light install's default is
``inplace``). Read without ``LOCK`` (rule 2). ``main`` is bin/covey_repo.py: a task finds its context in
``COVEY_STATE``, ``COVEY_HOME`` and ``COVEY_TOPIC``. A0: the shape, the read and ``list``; ``use``, ``status`` and
``prune-plan`` say they are not on yet (package W1).
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from covey.core import env as cenv

REPOS_FILE = "repos.json"
RENDERED_FILE = "repos.md"  # The map as the Harness reads it; rendered, never edited, never backed up.
STATUSES = ("active", "readonly", "frozen")
WRITE_MODES = ("worktree", "inplace")
ADDED_BY = ("migrate", "discover", "touched", "owner")
NOT_YET = "这个命令在这一版还没有启用（仓库地图开发中）。"


@dataclass(frozen=True)
class Repo:
    name: str
    path: str
    note: str = ""
    status: str = "active"  # STATUSES
    write_mode: str = "worktree"  # WRITE_MODES
    branch: str = ""
    device: str = ""
    rules: tuple = ("AGENTS.md",)
    added_by: str = "owner"  # ADDED_BY
    last_used: float = 0.0
    extra: dict = field(default_factory=dict)  # Keys a newer release wrote, kept as they are.


def path(state_dir) -> Path:
    return Path(state_dir) / REPOS_FILE


def read(state_dir) -> list[Repo]:
    """The repositories of ``repos.json``; [] when it is missing or unreadable."""
    try:
        data = json.loads(path(state_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    found = []
    for item in (data.get("repos") if isinstance(data, dict) else None) or []:
        if not isinstance(item, dict) or not str(item.get("name") or "").strip() or not str(item.get("path") or "").startswith("/"):
            continue
        known = {key: item[key] for key in Repo.__dataclass_fields__ if key in item and key != "extra"}
        known["rules"] = tuple(str(rule) for rule in known.get("rules") or ()) or ("AGENTS.md",)
        if known.get("status") not in STATUSES:
            known.pop("status", None)
        if known.get("write_mode") not in WRITE_MODES:
            known.pop("write_mode", None)
        try:
            found.append(Repo(**known, extra={k: v for k, v in item.items() if k not in Repo.__dataclass_fields__}))
        except TypeError:
            continue
    return found


def find(repos, key: str) -> Repo | None:
    """The repository named ``key``, or whose path is ``key``."""
    key = str(key or "").rstrip("/")
    return next((repo for repo in repos if repo.name == key or repo.path.rstrip("/") == key), None)


def _context() -> dict:
    return {"state": cenv.get("COVEY_STATE", ""), "home": cenv.get("COVEY_HOME", ""), "topic": cenv.get("COVEY_TOPIC", "")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="covey_repo.py", description="仓库地图：列出、声明和查看本话题用到的仓库")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="仓库地图")
    use = sub.add_parser("use", help="声明本话题用到一个仓库")
    use.add_argument("repo")
    use.add_argument("--write", action="store_true", help="要改：建或复用本话题的 worktree")
    sub.add_parser("status", help="本话题用到的仓库")
    prune = sub.add_parser("prune-plan", help="只读：列出可以清理的 worktree")
    prune.add_argument("--legacy", default="", help="另看这个目录下的旧 worktree")
    args = parser.parse_args(argv)
    context = _context()
    if args.action != "list":
        print(NOT_YET, file=sys.stderr)
        return 2
    repos = read(context["state"]) if context["state"] else []
    if args.json:
        print(json.dumps([asdict(repo) for repo in repos], ensure_ascii=False))
    elif not repos:
        print("仓库地图是空的。")
    else:
        for repo in repos:
            print(f"{repo.name}\t{repo.status}\t{repo.path}\t{repo.note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
