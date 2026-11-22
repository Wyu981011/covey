"""协作记录 (docs/architecture.md 多参与者协作 · 协作记录与状态机, COVEY_COLLAB): one file a collaboration,
<state>/collab/<id>.json, written by the Bridge alone (app/collab_flow.py), under its lock and never across a network call
(rule 1). A state changes only by core/collab.py's tables (``move_ask``, ``move_collab``: ``collab.moved``), so an ended
ask or collaboration never runs again, and a late answer is kept without waking anybody.

The record: ``id``, ``chat_id``, ``root`` (the owner's message that started it: its message id, job key and number, the
topic, his words), ``goal_rev`` (the integrator topic's latest owner turn then: a later one is a new goal), ``integrator``
and ``helpers`` (participants: key, role, project, label; a helper ``named`` when the owner named it himself), ``asks``,
``replies`` (the integrator's continuation turns), ``state``, ``stopped_by``, ``deadline`` (the window's end:
``window_seconds``, an ask's queue ``queue_seconds``; both configurable),
``created_at``, ``updated_at``. An ask: ``id`` (core/collab.py ask_id), ``to``, ``from``, ``number`` (1 the ask, 2 its
clarification), ``text``, ``state``, ``reason`` (why not taken, failed, expired, cancelled), ``channel``, ``message_id``
and ``job_key`` of its turn, ``attempt``, ``deadline`` (the queue's), ``evidence`` (what the answer stands on: a fork of
the helper's session or its record, the helper's last ended task then), ``reply`` (the answer's words as the turn's
authorized reply had them, when, the goal it answered, how many turns of the helper ended since).

Standard library and core only.
"""
from __future__ import annotations

import time
from pathlib import Path

from covey.core import collab
from covey.core import env as cenv
from covey.core.locks import resource_lock
from covey.core.state import read_object, write_json

FOLDER = "collab"
SCHEMA = 1
TEXT_CHARS = 2000  # Of an ask's words kept in its record.
REPLY_CHARS = 12000  # Of an answer's words kept and handed to the integrator.
WORDS_CHARS = 600  # Of the owner's words of the root kept.


def _seconds(raw, default) -> int:
    try:
        value = int(str(raw or "").strip() or default)
    except ValueError:
        return default
    return value if value > 0 else default


def queue_seconds() -> int:
    """How long an ask waits for its helper's turn to end: COVEY_COLLAB_QUEUE_SECONDS, else core/collab.py QUEUE_SECONDS."""
    return _seconds(cenv.get("COVEY_COLLAB_QUEUE_SECONDS", ""), collab.QUEUE_SECONDS)


def window_seconds() -> int:
    """A whole collaboration's window: COVEY_COLLAB_WINDOW_SECONDS, else core/collab.py WINDOW_SECONDS."""
    return _seconds(cenv.get("COVEY_COLLAB_WINDOW_SECONDS", ""), collab.WINDOW_SECONDS)


def path(state_dir, collab_id) -> Path:
    return Path(state_dir) / FOLDER / f"{collab_id}.json"


def read(state_dir, collab_id) -> dict:
    """The record of ``collab_id``, {} when there is none (or it is not one)."""
    if not isinstance(collab_id, str) or not collab_id or "/" in collab_id or collab_id.startswith("."):
        return {}
    record = read_object(path(state_dir, collab_id))
    return record if record.get("id") == collab_id else {}


def records(state_dir, *, chat=None, open_only=False) -> list:
    """Every record (of ``chat`` when given; only those ``open`` with ``open_only``), the oldest first."""
    folder = Path(state_dir) / FOLDER
    try:
        names = sorted(p.stem for p in folder.glob("*.json"))
    except OSError:
        return []
    found = []
    for name in names:
        record = read(state_dir, name)
        if not record or (chat is not None and record.get("chat_id") != chat):
            continue
        if open_only and record.get("state") != collab.OPEN:
            continue
        found.append(record)
    return sorted(found, key=lambda record: float(record.get("created_at") or 0))


def change(state_dir, collab_id, edit):
    """``edit(record)`` under the record's lock (the Bridge's own: it alone writes these): the record it returns is
    written, None leaves the file as it was. What was written, else None. ``edit`` gets {} when there is no record."""
    target = path(state_dir, collab_id)
    with resource_lock("collab", collab_id):
        current = read(state_dir, collab_id)
        new = edit(dict(current))
        if new is None:
            return None
        new = {**new, "schema_version": SCHEMA, "updated_at": time.time()}
        target.parent.mkdir(parents=True, exist_ok=True)
        write_json(target, new, ensure_ascii=False, indent=1)
        return new


def ask_of(record, ask_id) -> dict:
    """The ask ``ask_id`` of ``record`` (the dict in it, so a change in an ``edit`` goes in the record), {} without."""
    return next((ask for ask in record.get("asks") or () if ask.get("id") == ask_id), {})


def asks_to(record, helper) -> list:
    """The asks of ``record`` to ``helper``, the first first."""
    return sorted((ask for ask in record.get("asks") or () if ask.get("to") == helper),
                  key=lambda ask: int(ask.get("number") or 0))


def move_ask(ask, new, now=None, **fields) -> dict:
    """``ask`` moved to ``new`` with ``fields`` (core/collab.py ASK_TRANSITIONS, ValueError when it may not)."""
    ask["state"] = collab.moved(collab.ASK_TRANSITIONS, ask.get("state"), new)
    ask.update(fields, updated_at=time.time() if now is None else now)
    return ask


def move_collab(record, new, now=None, **fields) -> dict:
    """``record`` moved to ``new`` with ``fields`` (core/collab.py COLLAB_TRANSITIONS)."""
    record["state"] = collab.moved(collab.COLLAB_TRANSITIONS, record.get("state"), new)
    record.update(fields, updated_at=time.time() if now is None else now)
    return record


def ended(ask) -> bool:
    """Whether ``ask`` can change no more (core/collab.py ASK_ENDED)."""
    return ask.get("state") in collab.ASK_ENDED


def settled(ask) -> bool:
    """Whether the integrator has what ``ask`` will give: an answer (replied or read) or an end without one."""
    return ask.get("state") in (collab.REPLIED, collab.READ) or ended(ask)


def participant(key, role, project="", label="", named=False) -> dict:
    return {"key": str(key), "role": str(role), "project": str(project or ""), "label": str(label or ""),
            "named": bool(named)}


def new_record(collab_id, chat, *, root, integrator, helpers, goal_rev, source, now=None) -> dict:
    """A collaboration's first record, open, with no ask yet. ``root``: {message_id, job_key, job_id, topic, words};
    ``integrator``/``helpers``: ``participant``s; ``source``: who started it (core/turn_source.py provenance)."""
    now = time.time() if now is None else now
    root = {**root, "words": str(root.get("words") or "")[:WORDS_CHARS]}
    return {"id": collab_id, "chat_id": str(chat), "root": root, "goal_rev": int(goal_rev or 0),
            "integrator": integrator, "helpers": list(helpers), "asks": [], "replies": [], "state": collab.OPEN,
            "stopped_by": "", "source": dict(source or {}), "deadline": now + window_seconds(),
            "created_at": now}


def new_ask(collab_id, *, to, frm, number, text, channel, now=None) -> dict:
    """An ask in CHECKING (core/collab.py ask_id)."""
    now = time.time() if now is None else now
    return {"id": collab.ask_id(collab_id, to, number), "to": str(to), "from": str(frm), "number": int(number),
            "text": str(text or "")[:TEXT_CHARS], "state": collab.CHECKING, "reason": "", "channel": channel,
            "message_id": "", "job_key": "", "attempt": 0, "deadline": now + queue_seconds(),
            "evidence": {}, "reply": {}, "created_at": now, "updated_at": now}


def view(record) -> dict:
    """What a reader shows of ``record`` (the web page, a card): its state and each ask's, with the words; nothing a
    reader must not write back."""
    if not record:
        return {}
    return {"id": record.get("id"), "chat_id": record.get("chat_id"), "state": record.get("state"),
            "integrator": record.get("integrator"), "helpers": record.get("helpers") or [],
            "goal_rev": record.get("goal_rev"), "root": {key: (record.get("root") or {}).get(key)
                                                         for key in ("message_id", "job_id", "topic")},
            "stopped_by": record.get("stopped_by") or "", "deadline": record.get("deadline"),
            "asks": [{"id": ask.get("id"), "from": ask.get("from"), "to": ask.get("to"), "number": ask.get("number"),
                      "text": ask.get("text"), "state": ask.get("state"), "words": collab.ASK_WORDS.get(ask.get("state"), ""),
                      "reason": ask.get("reason") or "", "evidence": ask.get("evidence") or {},
                      "reply": {key: (ask.get("reply") or {}).get(key)
                                for key in ("text", "at", "goal_rev", "owner_since", "evidence", "job_id")},
                      "late": bool(ask.get("late"))}
                     for ask in record.get("asks") or ()],
            "replies": [{key: reply.get(key) for key in ("number", "state", "message_id")}
                        for reply in record.get("replies") or ()],
            "created_at": record.get("created_at"), "updated_at": record.get("updated_at")}
