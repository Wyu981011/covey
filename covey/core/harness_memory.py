"""What the Harnesses remember on their own (Claude Code, Codex, Antigravity), offered for import into the memory one entry at a time.

Replaces app/memory_harvest.py's directory hash: each candidate has a fingerprint of its Harness, file and text
(``fingerprint``), ``memory/imports.json`` keeps each one's state (new, imported, ignored), and the web's 导入 lists the
new ones a page at a time (contract v43 ``memory:import:<page>``). Nothing is imported without the owner ticking it.
A0: the shape and the fingerprint; the adapters are package M1's.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

HARNESSES = ("claude_code", "codex", "antigravity")
STATES = ("new", "imported", "ignored")
PAGE = 200


@dataclass(frozen=True)
class ImportItem:
    fingerprint: str
    harness: str  # HARNESSES
    bucket: str  # Where it was found: the project or repository its Harness keeps it under.
    file: str
    title: str
    text: str
    type: str  # What the Harness calls it (a memory file's section, a rule…).
    repo: str = ""


def fingerprint(harness: str, file: str, text: str) -> str:
    """Stable across scans: the same text in the same file of the same Harness is the same candidate."""
    body = "\0".join((harness, str(file), " ".join(str(text).split())))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def scan(state_dir, home) -> list[ImportItem]:
    """Every candidate the Harnesses hold for this deployment's home: M1."""
    raise NotImplementedError("M1")
