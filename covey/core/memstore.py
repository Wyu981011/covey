"""The one memory store of the overhaul (FINAL-SPEC 修订 3): an entry's frozen shape, its short code and where each part lies.

A0 freezes the contract only; nothing reads or writes through this module yet, and the memory works as before
(core/memory.py, core/principles.py, core/knowledge.py, core/project_memory.py, core/topic_memory.py). Package M1 fills
the functions that raise ``NotImplementedError`` without changing their signatures.

Rollback never destroys (修订 3): the new fields never go into the files an older release rewrites with its own keys
(``memory-meta.json``, ``memory-usage.json``); they lie beside them in ``projects/<id>/memory-v2.json``,
``topics/<id>/memory-v2.json`` and ``memory/usage.json`` (which reads the old usage file and adds to it). The
migration is incremental (what an older release wrote after a rollback is taken again) and never walks every topic
directory at start: a topic's short codes are given the first time its entries are read (lazy).

Every memory write touches the one sentinel ``memory/.rev`` (``touch_rev``), so the web sync stats a single file.
"""
from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

KINDS = ("rule", "decision", "note")
SCOPES = ("global", "project", "topic")
STATUSES = ("active", "pending", "done", "archived", "void")
SAID = ("owner", "summary")  # 你定的 (the owner's words or confirmed by him) / 别人总结的.
BY = ("owner", "lead", "butler", "learn", "import", "bridge", "web")

TITLE_CHARS = 40
TEXT_CHARS = 200  # A rule's and a note's.
DECISION_CHARS = 600  # A decision's: the question and the answer as given.

CODE_LETTERS = {"rule": "R", "decision": "D", "note": "N"}
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32: no I, L, O, U.
CODE_RE = re.compile(r"^[RDN][0-9A-HJKMNP-TV-Z]{4,6}$")
# What the turns and the tools wrote before: a principle's p + 6 hex, a knowledge entry's k + 6 hex, a memory number M12.
LEGACY_RE = re.compile(r"^(?:p[0-9a-f]{6}|k[0-9a-f]{6}|M\d{2,3})$")

MEMORY_DIR = "memory"
GLOBAL_FILE = "global.json"
REVIEW_FILE = "review.json"
IMPORTS_FILE = "imports.json"
LOG_FILE = "log.jsonl"
USAGE_FILE = "usage.json"
SYNONYMS_FILE = "synonyms.json"
REV_FILE = ".rev"
SIDECAR_FILE = "memory-v2.json"  # Beside a project's or a topic's memory.json.
DECISIONS_FILE = "decisions.jsonl"


@dataclass(frozen=True)
class Entry:
    """One memory entry, whatever store it came from (MASTER-PLAN 2.2.1 with the final fixes)."""

    ref: str  # global:<id> / project:<pid>:<id> / topic:<tid>:<id> / decision:<pid|tid>:<id>
    code: str  # CODE_RE; given once, kept.
    kind: str  # KINDS
    scope: str  # SCOPES
    owner_key: str  # The project's id, the topic's id, '' for global.
    title: str  # ≤ TITLE_CHARS
    text: str  # ≤ TEXT_CHARS, a decision's ≤ DECISION_CHARS
    status: str  # STATUSES
    said: str  # SAID
    by: str  # BY
    origin: dict = field(default_factory=dict)  # {at, topic_key?, topic_number?, job?, message_id?, question?, quote?, file?, harness?}
    why: str = ""
    repos: tuple = ()  # A note's: the repo map names it is about.
    device: str = ""
    verified_at: float = 0.0  # A fact's; 0 not verified.
    superseded_by: str = ""
    aliases: tuple = ()  # The refs it had before (principle:p…, knowledge:k…, candidate:c…).
    redacted: bool = False
    at: float = 0.0
    edited_at: float = 0.0


def memory_dir(state_dir) -> Path:
    return Path(state_dir) / MEMORY_DIR


def global_path(state_dir) -> Path:
    return memory_dir(state_dir) / GLOBAL_FILE


def review_path(state_dir) -> Path:
    return memory_dir(state_dir) / REVIEW_FILE


def imports_path(state_dir) -> Path:
    return memory_dir(state_dir) / IMPORTS_FILE


def log_path(state_dir) -> Path:
    return memory_dir(state_dir) / LOG_FILE


def usage_path(state_dir) -> Path:
    return memory_dir(state_dir) / USAGE_FILE


def rev_path(state_dir) -> Path:
    return memory_dir(state_dir) / REV_FILE


def sidecar_path(state_dir, scope: str, owner_key: str) -> Path:
    """``projects/<id>/memory-v2.json`` or ``topics/<id>/memory-v2.json``: the new fields an older release does not know."""
    if scope not in ("project", "topic"):
        raise ValueError(f"no sidecar for scope {scope!r}")
    return Path(state_dir) / ("projects" if scope == "project" else "topics") / owner_key / SIDECAR_FILE


def decisions_path(state_dir, scope: str, owner_key: str) -> Path:
    """A project's or a topic's ``decisions.jsonl`` (append only): the owner's answers, out of memory.json's 120 lines."""
    if scope not in ("project", "topic"):
        raise ValueError(f"no decisions for scope {scope!r}")
    return Path(state_dir) / ("projects" if scope == "project" else "topics") / owner_key / DECISIONS_FILE


def is_code(text) -> bool:
    return bool(CODE_RE.match(str(text or "")))


def is_legacy(text) -> bool:
    return bool(LEGACY_RE.match(str(text or "")))


def touch_rev(state_dir, now: float | None = None) -> None:
    """Mark that some memory changed (``memory/.rev``'s mtime); never raises."""
    path = rev_path(state_dir)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
        stamp = time.time() if now is None else now
        os.utime(path, (stamp, stamp))
    except OSError:
        pass


def kind3_of(entry: dict, meta: dict | None = None, *, source: str = "") -> tuple[str, str, str]:
    """(kind, said, status) of an old entry (MASTER-PLAN 2.2.3 table; 修订 5: a lead's unconfirmed constraint carried in the
    last 7 days stays a rule until the owner decides). Pure: M1."""
    raise NotImplementedError("M1")


def entries(state_dir, *, scope: str = "", owner_key: str = "", kinds=KINDS, statuses=("active",)) -> list[Entry]:
    """The entries of ``scope``/``owner_key`` (all scopes when ''), of ``kinds`` and ``statuses``: M1."""
    raise NotImplementedError("M1")


def find(state_dir, key: str) -> Entry | None:
    """The entry a ref, a short code or an old id (``LEGACY_RE``, an alias) names; None when none does: M1."""
    raise NotImplementedError("M1")


def code_for(state_dir, kind: str) -> str:
    """A new short code of ``kind`` not given before: M1."""
    raise NotImplementedError("M1")
