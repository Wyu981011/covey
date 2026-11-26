"""The one review queue of the memory (待审核, ``memory/review.json``): what someone other than the owner proposes waits here.

Everything the owner did not say himself goes here before it counts: the memory's own learning, a lead's proposal, an
import, a conflict, a tidy proposal, the third same-class question (class3) and what the migration could not place
(a lead's unconfirmed constraint carried in the last 7 days stays carried as a project rule
and is also put here, until the owner decides). Only the owner's submit moves an item out; a lead answering for him
never writes a rule (docs/butler.md 记忆, docs/operations.md 记忆的存储与迁移). The queue itself is core/memstore.py's
(memory/review.json); this module is what an item means when decided.
"""
from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

from covey.core import harness_memory, memory_gate, memory_rank, memory_search, memory_usage, memstore

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


EXPIRE_DAYS = 14  # An open item older than this is ``expired`` (kept, never deleted).
IDLE_SHOWN = 10  # A note carried this often with no sign of use is idle.
DUP_MUTUAL = 0.5  # Two entries of one scope and kind this alike (``mutual_similarity``, and covered) are a duplicate.
DUP_PER_SCOPE = 200  # Entries of one scope compared for duplicates (the pairs grow with the square).
# A scope's rules past either number are over the cap: (entries, characters).
RULE_CAPS = {"global": (15, 1200), "project": (10, 1000), "topic": (5, 400)}
ACTIONS = ("accept", "reject", "keep_left", "keep_right", "keep_both")
_BY = {"learn": "learn", "lead": "lead", "candidate": "bridge", "class3": "bridge", "migrate": "bridge"}
_FIELDS = ("key", "type", "title", "text", "suggest", "created_at", "quote", "origin", "conflict_with", "items", "flags")


def _item(row: dict) -> ReviewItem:
    return ReviewItem(**{name: (tuple(row[name]) if name in ("items", "flags") else row[name]) for name in _FIELDS if name in row})


def items(state_dir) -> list[ReviewItem]:
    """The open items, oldest first."""
    return [_item(row) for row in memstore.review_items(state_dir)]


def add(state_dir, item: ReviewItem) -> str:
    """Put ``item`` in the queue (one per proposal, ``memstore.review_fp``); its key, the existing one's for a proposal that is
    there already (open or decided)."""
    row = {name: getattr(item, name) for name in _FIELDS if name != "key" or item.key}
    return memstore.review_put(state_dir, row)[0]


def _need(state_dir, key: str) -> dict:
    row = next((row for row in memstore.review_items(state_dir, states=None) if row.get("key") == key), None)
    if row is None:
        raise ValueError("待审核里没有这一项")
    if row.get("state", "open") != "open":
        raise ValueError("这一项已经处理过了")
    return row


def _where(row: dict) -> tuple[str, str]:
    """(scope, owner key) an item's ``suggest`` says, a topic's key from its origin."""
    suggest = row.get("suggest") if isinstance(row.get("suggest"), dict) else {}
    scope = str(suggest.get("scope") or "global")
    owner = str(suggest.get("project_key") or suggest.get("owner_key") or "")
    if scope == "topic" and not owner:
        owner = str((row.get("origin") or {}).get("topic_key") or "")
    return scope, ("" if scope == "global" else owner)


def _add(state_dir, row: dict, who, token, now, *, by: str, text: str = "") -> list[str]:
    suggest = row.get("suggest") if isinstance(row.get("suggest"), dict) else {}
    scope, owner = _where(row)
    entry = memstore.add(state_dir, kind=str(suggest.get("kind") or "rule"), scope=scope, owner_key=owner,
                         text=text or row.get("text") or "", title=row.get("title") or "", said="owner", by=by,
                         origin=dict(row.get("origin") or {}), who=who, token=token, now=now)
    return [entry.ref]


def _conflict(state_dir, row: dict, action: str, who, token, now) -> list[str]:
    old = memstore.find(state_dir, row.get("conflict_with") or "")
    if action == "keep_left":
        return [old.ref] if old else []
    if old is None:
        return _add(state_dir, row, who, token, now, by="bridge") if action in ("keep_right", "keep_both") else []
    if action == "keep_right":  # The old entry takes the new words: one edit, one undo.
        return [memstore.edit(state_dir, old.ref, text=row.get("text") or "", who=who, token=token, now=now).ref]
    suggest = {"kind": old.kind, "scope": old.scope, "owner_key": old.owner_key}  # keep_both: the new words an entry of their own.
    return _add(state_dir, {**row, "suggest": suggest}, who, token, now, by="bridge")


def _written(state_dir, row: dict, action: str, who, token, now) -> list[str]:
    """What the owner's ``action`` on item ``row`` writes; the refs written."""
    kind, refs = row["type"], [str(ref) for ref in row.get("items") or ()]
    suggest = row.get("suggest") if isinstance(row.get("suggest"), dict) else {}
    if kind == "conflict":
        return _conflict(state_dir, row, {"accept": "keep_right", "reject": "keep_left"}.get(action, action), who, token, now)
    if action not in ("accept", "reject"):
        raise ValueError("这一项只能采纳或不要")
    if kind == "migrate" and suggest.get("scope") == "project":  # The guardrail's: a lead's line carried as a rule.
        written = []
        for ref in refs:
            if action == "accept":
                written.append(memstore.confirm(state_dir, ref, who=who, token=token, now=now).ref)
            else:
                written.append(memstore.set_kind(state_dir, ref, "note", who=who, token=token, now=now).ref)
        return written
    if kind == "tidy":
        written = []
        if action == "reject":
            for ref in refs:
                written.append(memstore.restore(state_dir, ref, who=who, token=token, now=now).ref)
        return written
    if kind == "import":
        scope, owner = _where(row)
        if action == "accept":
            made = harness_memory.take(state_dir, Path.home(), refs, kind=str(suggest.get("kind") or ""), scope=scope,
                                       owner_key=owner, who=who, token=token, now=now)
            return [entry.ref for entry in made]
        harness_memory.ignore(state_dir, refs, now=now)
        return []
    if action == "reject":
        return []
    return _add(state_dir, row, who, token, now, by=_BY.get(kind, "bridge"))


def decide(state_dir, key: str, action: str, *, who: str = "owner", token: str = "", now: float | None = None) -> dict:
    """The owner's ``action`` (``ACTIONS``) on item ``key``, one memstore token over every write so one ``memstore.undo`` takes
    it all back: {ok, key, state (accepted/rejected), refs written, undo_token}. ValueError (a Chinese reason) for a key that
    is not there or was decided already. Only the owner's submit gets here; a lead answering for him never writes a rule.
    Each entry written counts as a strong sign of use (``memory_usage.signal`` confirm)."""
    if action not in ACTIONS:
        raise ValueError("不认识这个操作")
    row = _need(state_dir, key)
    token = token or "u-" + secrets.token_hex(6)
    stamp = time.time() if now is None else now
    refs = _written(state_dir, row, action, who, token, stamp)
    if refs:
        memory_usage.signal(state_dir, refs, "confirm")
    state = "rejected" if action in ("reject", "keep_left") else "accepted"
    memstore.review_set(state_dir, key, state, by=who, now=stamp, refs=refs)
    return {"ok": True, "key": key, "state": state, "refs": refs, "undo_token": token}


def decide_all(state_dir, action: str, *, keys: list[str] | None = None, who: str = "owner", token: str = "",
               now: float | None = None) -> dict:
    """``accept_all`` / ``reject_all`` on ``keys`` (every open item when empty), under one token: {ok, decided, failed [{key,
    error}], refs, undo_token}."""
    if action not in ("accept_all", "reject_all"):
        raise ValueError("不认识这个操作")
    token = token or "u-" + secrets.token_hex(6)
    wanted = list(keys) if keys else [item.key for item in items(state_dir)]
    out = {"ok": True, "decided": [], "failed": [], "refs": [], "undo_token": token}
    for key in wanted:
        try:
            done = decide(state_dir, key, action.split("_")[0], who=who, token=token, now=now)
        except (ValueError, OSError) as exc:
            out["failed"].append({"key": key, "error": str(exc)})
            continue
        out["decided"].append(key)
        out["refs"] += done["refs"]
    return out


def expire(state_dir, *, now: float | None = None) -> int:
    """Open items older than ``EXPIRE_DAYS`` marked ``expired`` (kept, never deleted); how many."""
    stamp = time.time() if now is None else now
    count = 0
    for row in memstore.review_items(state_dir):
        if stamp - float(row.get("created_at") or 0) > EXPIRE_DAYS * 86400:
            memstore.review_set(state_dir, row["key"], "expired", by="bridge", now=stamp)
            count += 1
    return count


def _over_cap(entries) -> list[str]:
    rules: dict = {}
    for entry in entries:
        if entry.kind == "rule":
            rules.setdefault((entry.scope, entry.owner_key), []).append(entry)
    over = []
    for (scope, owner), rows in rules.items():
        most, chars = RULE_CAPS[scope]
        if len(rows) > most or sum(len(row.text) for row in rows) > chars:
            over.append(scope if scope == "global" else f"{scope}:{owner}")
    return sorted(over)


def _duplicates(state_dir, entries) -> list[str]:
    groups: dict = {}
    for entry in entries:
        groups.setdefault((entry.scope, entry.owner_key, entry.kind), []).append(entry)
    if not any(len(rows) > 1 for rows in groups.values()):
        return []
    corpus = memory_search.index(state_dir)
    idf = corpus.idfs()
    docs = {entry.ref: memory_search.text_doc(entry.text) for entry in entries}
    dup: list = []
    for rows in groups.values():
        rows = rows[:DUP_PER_SCOPE]
        for i, one in enumerate(rows):
            mine = docs[one.ref]
            for other in rows[i + 1:]:
                theirs = docs[other.ref]
                if not memory_rank.covered(mine[0].keys() & theirs[0].keys(), idf):
                    continue  # Too few words in common to be alike: not worth the four scores.
                sim, covered = memory_search.mutual_docs(corpus, mine, theirs)
                if covered and sim >= DUP_MUTUAL:
                    dup += [ref for ref in (one.ref, other.ref) if ref not in dup]
    return dup


def health(state_dir, *, now: float | None = None) -> dict:
    """What looks unwell in the memory, as web contract MemoryHealth: only the non-empty lists; ``{}`` when all is well.
    ``dup``: active entries of one scope and kind whose texts are alike (``memory_search.mutual_similarity``, the words
    weighed by the whole memory's index, covered and at or over ``DUP_MUTUAL``; at most ``DUP_PER_SCOPE`` entries of a scope
    compared). ``conflict``: [old ref, item key] of each open
    conflict item. ``vague``: active rules and notes the gate flags vague. ``stale``: notes verified more than
    ``memory_rank.STALE_DAYS`` ago. ``idle``: notes carried ``IDLE_SHOWN`` times or more and never used. ``over_cap``: scope
    keys (global, project:<id>, topic:<id>) whose rules are over ``RULE_CAPS``. ``repo_rule`` and ``skill`` are not worked out."""
    stamp = time.time() if now is None else now
    entries = memstore.entries(state_dir, kinds=("rule", "note"))
    used = memory_usage.counts(state_dir)
    found = {
        "dup": _duplicates(state_dir, entries),
        "conflict": [[row["conflict_with"], row["key"]] for row in memstore.review_items(state_dir)
                     if row.get("type") == "conflict" and row.get("conflict_with")],
        "vague": [entry.ref for entry in entries if "vague" in memory_gate.check(entry.text, kind=entry.kind, title=entry.title).flags],
        "stale": [entry.ref for entry in entries if entry.kind == "note" and entry.verified_at
                  and stamp - entry.verified_at > memory_rank.STALE_DAYS * 86400],
        "idle": [entry.ref for entry in entries if entry.kind == "note"
                 and used.get(entry.ref, {}).get("e", 0) >= IDLE_SHOWN and not used.get(entry.ref, {}).get("h", 0)],
        "over_cap": _over_cap(entries),
    }
    return {name: value for name, value in found.items() if value}
