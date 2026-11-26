"""The one review queue of the memory (待审核, ``memory/review.json``): what someone other than the owner proposes waits here.

Everything the owner did not say himself goes here before it counts: the memory's own learning, a lead's proposal, an
import, a conflict, a tidy proposal, the third same-class question (class3) and what the migration could not place
(MASTER-PLAN 2.5; 修订 5: a lead's unconfirmed constraint carried in the last 7 days stays carried as a project rule
and is also put here, until the owner decides). Only the owner's submit moves an item out; a lead answering for him
never writes a rule. A0: the item's shape; the queue is package M2's.
"""
from __future__ import annotations

from dataclasses import dataclass, field

TYPES = ("learn", "candidate", "lead", "import", "conflict", "tidy", "class3", "migrate")


@dataclass(frozen=True)
class ReviewItem:
    key: str
    type: str  # TYPES
    title: str
    text: str
    suggest: dict  # {kind, scope, project_key?}
    created_at: float
    quote: str = ""
    origin: dict = field(default_factory=dict)  # {topic_key?, topic_number?}
    conflict_with: str = ""
    items: tuple = ()  # A tidy proposal's group of refs.
    flags: tuple = ()  # core/memory_gate.py FLAGS


def items(state_dir) -> list[ReviewItem]:
    """The open items, oldest first: M2."""
    raise NotImplementedError("M2")


def add(state_dir, item: ReviewItem) -> str:
    """Put ``item`` in the queue (one per fingerprint of its text); its key: M2."""
    raise NotImplementedError("M2")


def decide(state_dir, keys, action: str, *, by: str, edits: dict | None = None) -> list[str]:
    """``accept``/``reject`` (and their ``_all`` forms when ``keys`` is empty) by the owner (``by``); the refs written: M2."""
    raise NotImplementedError("M2")
