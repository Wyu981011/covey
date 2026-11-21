"""The avatars of the private chat's cards (docs/ui.md 5.3): which picture a speaker has, and the image keys Feishu gave them.

The pictures are in covey/assets/avatars/: ``butler.png`` for the butler (replace the file to change it), ``topic.png``
for every topic, and ``POOL`` for the project leads. A lead's picture is picked once from its project id and kept in
``<state>/avatars.json`` (``leads``: {chat: {project id: name}}): the id's stable hash picks one of the 20, a name another
project of the same chat has is passed over for the next free one, a project that no longer exists frees its name. The
same file holds the image keys (``keys``: {profile: {sha256 of the file: image_key}}), so a picture uploaded once is
used again, and one whose file changed is uploaded again (feishu/avatars.py). Nothing here does network."""
from __future__ import annotations

import hashlib
from pathlib import Path

from covey.core import projects
from covey.core.locks import shared_file_lock
from covey.core.state import read_object, write_json

BUTLER, TOPIC = "butler", "topic"
# DiceBear Moods (G), DiceBear Clay (M), the sea set: the names of the files without ".png".
POOL = ("G-1", "G-2", "G-3", "G-6", "G-7", "G-9",
        "M-2", "M-3", "M-5", "M-9", "M-11", "M-12",
        "sea-crab", "sea-jellyfish", "sea-octopus", "sea-puffer", "sea-sponge", "sea-starfish", "sea-turtle", "sea-whale")
ASSETS = Path(__file__).resolve().parents[1] / "assets" / "avatars"
FILE = "avatars.json"


def asset(name) -> Path | None:
    """The picture file of ``name`` (BUTLER, TOPIC or one of POOL); None for any other name or a missing file."""
    if name not in (BUTLER, TOPIC, *POOL):
        return None
    path = ASSETS / f"{name}.png"
    return path if path.is_file() else None


def digest(name) -> str:
    """The SHA-256 of ``name``'s picture file; '' without one."""
    path = asset(name)
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path else ""
    except OSError:
        return ""


def pick(project_id, taken=()) -> str:
    """The name of POOL for ``project_id``: its hash's place, else the next one not in ``taken``, else that place."""
    start = int(hashlib.sha256(str(project_id).encode()).hexdigest(), 16) % len(POOL)
    free = (POOL[(start + step) % len(POOL)] for step in range(len(POOL)))
    return next((name for name in free if name not in taken), POOL[start])


def lead_name(state_dir, chat_id, project_id) -> str:
    """The name of the picture the lead of ``project_id`` has in ``chat_id`` (``pick`` the first time, then the one
    kept in <state>/avatars.json); '' when it cannot be kept (no state directory, a file that cannot be written)."""
    if not state_dir or not chat_id or not project_id:
        return ""
    path = Path(state_dir) / FILE
    try:
        with shared_file_lock(path):
            data = read_object(path)
            chats = data["leads"] if isinstance(data.get("leads"), dict) else {}
            leads = chats.get(chat_id) if isinstance(chats.get(chat_id), dict) else {}
            if leads.get(project_id) in POOL:
                return leads[project_id]
            # A project that is gone (no record) lets go of its picture.
            leads = {pid: name for pid, name in leads.items() if name in POOL and pid != project_id
                     and projects.read_record(state_dir, pid)}
            name = pick(project_id, set(leads.values()))
            write_json(path, {**data, "leads": {**chats, chat_id: {**leads, project_id: name}}},
                       ensure_ascii=False, indent=1)
            return name
    except OSError:
        return ""


def cached_key(state_dir, profile, name) -> str:
    """The image key Feishu gave ``profile`` for the current file of ``name``; '' when there is none."""
    found = digest(name)
    keys = read_object(Path(state_dir) / FILE).get("keys") if state_dir else None
    per = keys.get(str(profile or "")) if isinstance(keys, dict) else None
    key = per.get(found) if found and isinstance(per, dict) else ""
    return key if isinstance(key, str) else ""


def remember_key(state_dir, profile, name, key) -> None:
    """Keep ``key`` as the image key of the current file of ``name`` for ``profile``. Never raises."""
    found = digest(name)
    if not state_dir or not found or not key:
        return
    path = Path(state_dir) / FILE
    try:
        with shared_file_lock(path):
            data = read_object(path)
            keys = data["keys"] if isinstance(data.get("keys"), dict) else {}
            per = keys.get(str(profile or "")) if isinstance(keys.get(str(profile or "")), dict) else {}
            write_json(path, {**data, "keys": {**keys, str(profile or ""): {**per, found: key}}},
                       ensure_ascii=False, indent=1)
    except OSError:
        pass
