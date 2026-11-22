"""The records of the 派发卡 (docs/butler.md 派发卡): <state>/main-thread/dispatch/<token>.json, one per
card the butler's topic_send put at the chat's top level (app/dispatch_cards.py; ``kind`` send, and start or fork in the
records of the cards topic_start and topic_fork sent before), and the sidecar <token>.relay.json a task runner leaves
when that card's conclusion went out (``mark_relayed``).

The record is written by the Bridge alone: first by the tool that sends the card, then by the refresh thread. The task
runner never writes it (rule 3: one writer for a card); what the runner has to say, the relay's end, goes in the
sidecar, one small file written once, which the refresh thread reads.

``state`` only goes live -> settled (``DISPATCH_TRANSITIONS``, rule 4); a settled card is never refreshed again.
``rounds``, ``upgrade_hint`` and ``project_id`` are for a later phase (a long job becoming a project): written now,
read by nothing yet. Standard library and core only (a task runner imports it)."""
from __future__ import annotations

import time
from pathlib import Path

from covey.core.state import keyed_json_path, read_object, write_json

FOLDER = Path("main-thread") / "dispatch"
LIVE, SETTLED = "live", "settled"
# Rule 4: the only way a record's state moves.
DISPATCH_TRANSITIONS = {LIVE: {SETTLED}, SETTLED: set()}
SCHEMA = 1
RELAY_SUFFIX = ".relay.json"
REQUEST_CHARS = 200  # Of the owner's request kept in the record; the card's header shows the first 30.


def folder(state_dir) -> Path:
    return Path(state_dir) / FOLDER


def record_path(state_dir, token) -> Path:
    return keyed_json_path(state_dir, FOLDER, token)


def relay_note_path(state_dir, token) -> Path:
    return folder(state_dir) / f"{token}{RELAY_SUFFIX}"


def new_record(*, token, chat_id, topic_id, job_key, mid, kind, owner_message, request, starts, rounds=1, now=None, ask_at="", ask_url="",
               in_thread=False) -> dict:
    """A fresh live record. ``job_key`` the butler job that sent the card, ``mid`` the key or message id of the
    topic's job it follows, ``kind`` send (start or fork in older records), ``starts`` whether the topic starts at once
    (else it waits on its launch card: an older start record's). ``ask_at``, ``ask_url``: the owner's message the card's
    "你问" block names (the time he wrote it, the link that opens it). ``in_thread``: the card is a reply in the thread of
    the owner's message (app/dispatch_cards.py), not a message of its own at the chat's top level (an older record's)."""
    request = " ".join(str(request or "").split())
    return {"schema_version": SCHEMA, "token": token, "chat_id": chat_id, "topic_id": topic_id, "job_key": job_key,
            "mid": mid, "kind": kind, "owner_message": owner_message, "request": request[:REQUEST_CHARS],
            "starts": bool(starts), "ask_at": ask_at, "ask_url": ask_url, "in_thread": bool(in_thread),
            "card_id": "", "card_message_id": "", "sequence": 0, "state": LIVE,
            "started_at": time.time() if now is None else now,
            # upgrade_hint: the butler's ``project`` is added by app/dispatch_cards.py. No keyword of the owner's is matched any more
            # (older records may still carry ``long_word``; nothing reads it).
            "rounds": rounds, "upgrade_hint": {}, "project_id": None}


def transition(record, to) -> dict:
    """``record`` moved to state ``to`` when ``DISPATCH_TRANSITIONS`` allows it; ValueError when it does not."""
    state = record.get("state") or LIVE
    if to not in DISPATCH_TRANSITIONS.get(state, ()):
        raise ValueError(f"dispatch card state {state} -> {to} is not allowed")
    record["state"] = to
    return record


def live_paths(state_dir) -> list[Path]:
    """The records' files, those a refresh may still look at (a settled one is told apart by reading it)."""
    try:
        return sorted(path for path in folder(state_dir).glob("*.json") if not path.name.endswith(RELAY_SUFFIX))
    except OSError:
        return []


def rounds_for(state_dir, owner_message, topic_id) -> int:
    """How many times the same question of the owner dispatched to ``topic_id``, this one counted."""
    count = 0
    for path in live_paths(state_dir):
        saved = read_object(path)
        if saved.get("owner_message") == owner_message and saved.get("topic_id") == topic_id:
            count += 1
    return count + 1


def mark_relayed(state_dir, token, *, outcome, state, message_id="", reason="") -> bool:
    """The relay of the topic's turn that ``token`` dispatched has been sent (``state`` "sent", ``message_id`` the
    conclusion) or skipped ("skipped": the owner stopped it himself): the sidecar the refresh thread reads. Only when
    the card has a record, once (a second call keeps the first). Whether it wrote."""
    if not token or "/" in str(token):
        return False
    if not record_path(state_dir, token).exists():
        return False
    path = relay_note_path(state_dir, token)
    if path.exists():
        return False
    write_json(path, {"token": token, "outcome": outcome, "state": state, "message_id": message_id,
                      "reason": str(reason or "")[:200], "at": time.time()}, ensure_ascii=False)
    return True


def relay_note(state_dir, token) -> dict:
    return read_object(relay_note_path(state_dir, token))


def sent(state_dir, token) -> bool:
    """Whether the card of the request ``token`` went out (its record names the card's message)."""
    if not token or "/" in str(token):
        return False
    return bool(read_object(record_path(state_dir, token)).get("card_message_id"))


def threaded(state_dir, chat_id, owner_message) -> bool:
    """Whether a card went out in the thread of the owner's message ``owner_message`` (``in_thread``): that thread holds
    another topic's card, so a topic opened on the same question takes no root there (app/butler_topics.py place)."""
    if not chat_id or not owner_message:
        return False
    for path in live_paths(state_dir):
        saved = read_object(path)
        if (saved.get("in_thread") and saved.get("card_message_id") and saved.get("owner_message") == owner_message
                and saved.get("chat_id") == chat_id):
            return True
    return False
