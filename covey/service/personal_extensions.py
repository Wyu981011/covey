"""Personal extensions: git checkouts under the data home's ``extensions/`` that every deploy packs into the release.

A person's own extension packages (code only they run, e.g. one that sends Claude Code's commands to other machines) live
in ``<COVEY_DATA_HOME>/extensions/<name>/``, a git checkout laid out as an extension checkout is (scripts/assemble_release.py:
each top-level directory with a ``manifest.py`` is a package, an optional root ``enabled`` file says which are on by
default, else all are). scripts/deploy_bridge.sh finds them here and packs each one's committed HEAD into the release after
the core and the ``--ext-repo`` checkouts, so they survive an upgrade, go back with a rollback, and the release's extension
check (covey_plugins.py deploy-check) imports them before anything is replaced. At run time the Bridge still loads only
from the release; a change in the checkout takes effect with the next upgrade. The data home's ``extensions/enabled`` file
(covey_plugins.py enable|disable) stays this deployment's choice over all of them. Standard library only: the deploy script
runs this from its own checkout before it knows the release.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

DIR = "extensions"  # Under the data home; its ``enabled`` file is covey_plugins.py's, not a checkout.
MANIFEST_LINE = "personal"  # The release's RELEASE_MANIFEST line of each: "personal <commit> <package>..." (assemble_release.py).


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True, timeout=60)


def _unsafe(path: Path) -> str:
    """Why ``path`` may not be packed ('' when it may): its code runs with the Bridge's rights, so only its owner may
    change it (the checkout, and its .git, owned by this user and not writable by the group or others)."""
    for each in (path, path / ".git"):
        try:
            info = each.stat()
        except OSError:
            continue
        if info.st_uid != os.geteuid():
            return f"{each} is owned by uid {info.st_uid}, not this user ({os.geteuid()})"
        if stat.S_IMODE(info.st_mode) & 0o022:
            return f"{each} can be written by its group or others (mode {stat.S_IMODE(info.st_mode):o}): chmod go-w it"
    return ""


def discover(data_home: Path, skip=()) -> dict:
    """What a deploy packs from ``<data_home>/extensions/``: {'repos': [{'path', 'commit', 'packages'}], 'notes': [...],
    'problems': [...]}. A directory there that is a git checkout with at least one package at HEAD is a repo, in name
    order; one in ``skip`` (an ``--ext-repo`` given already, compared resolved) is left out. Notes (nothing stops): a
    directory with packages that is not a git checkout (not packed), a checkout without a package at HEAD, changes not
    committed (only HEAD is packed). Problems (the deploy stops): a checkout someone else could change, one without a
    commit."""
    base = Path(data_home) / DIR
    skipped = {Path(path).resolve() for path in skip}
    found = {"repos": [], "notes": [], "problems": []}
    try:
        children = sorted(child for child in base.iterdir() if child.is_dir() and not child.name.startswith("."))
    except OSError:
        return found
    for child in children:
        if child.resolve() in skipped:
            continue
        if not (child / ".git").exists():
            if any((grand / "manifest.py").is_file() for grand in child.iterdir() if grand.is_dir()):
                found["notes"].append(f"{child}: not a git checkout, not packed (git init and commit it)")
            continue
        unsafe = _unsafe(child)
        if unsafe:
            found["problems"].append(f"{child}: {unsafe}")
            continue
        head = _git(child, "rev-parse", "--verify", "HEAD^{commit}")
        if head.returncode:
            found["problems"].append(f"{child}: a git checkout without a commit (commit it, or move it out of {base})")
            continue
        commit = head.stdout.strip()
        names = _git(child, "ls-tree", "-r", "--name-only", commit).stdout.splitlines()
        packages = sorted({name.split("/")[0] for name in names if re.fullmatch(r"[^/]+/manifest\.py", name)})
        if not packages:
            found["notes"].append(f"{child}: no package (a directory with manifest.py) at {commit[:8]}, not packed")
            continue
        if _git(child, "status", "--porcelain", "--untracked-files=no").stdout.strip():
            found["notes"].append(f"{child}: changes not committed are not packed (the release takes {commit[:8]})")
        found["repos"].append({"path": str(child), "commit": commit, "packages": packages})
    return found


def in_release(release: Path) -> list[dict]:
    """[{'commit', 'packages'}] of the personal checkouts ``release`` was packed with, from its RELEASE_MANIFEST ([] for
    none, or a release without the file)."""
    try:
        lines = (Path(release) / "RELEASE_MANIFEST").read_text().splitlines()
    except OSError:
        return []
    return [{"commit": words[1], "packages": words[2:]} for words in (line.split() for line in lines)
            if words[:1] == [MANIFEST_LINE] and len(words) > 1]


def main(argv=None) -> int:
    """``personal_extensions.py <data home> [<checkout to skip>...]``: discover's JSON on one line (the deploy scripts)."""
    argv = sys.argv[1:] if argv is None else argv
    print(json.dumps(discover(Path(argv[0]), argv[1:]), ensure_ascii=False))
    return 0
