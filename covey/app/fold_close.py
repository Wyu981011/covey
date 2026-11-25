"""A fold closed by a click on its text: 这一轮中途的汇报 under a relay (cards/review.py stages_fold).

A fold's own title closes it, but after a long read the title is where the owner scrolled past (the owner, 2026-11-25:
随便点一下这个过程项的文字，它自己就能折起来). Its text is one button (FOLD_CLOSE_KIND) whose click lands here, before topic
routing (app/unified.py PANELS). The card as it went out is kept by its message (``remember``, <state>/fold-cards/, gone
after maintenance's TEMPORARY_DAYS untouched); a relay whose 产物 are kept up to date (app/answer_cards.py) is read from
there instead, so neither write takes back the other's. The card is written again with the fold closed under the next ID
(<element_id>_s<n>): the client keeps a fold open or closed by its ID, so only a new one closes it. The text names the new
ID, so it opens and closes again. The owner's click alone; nothing here holds a lock across a Feishu call (rule 1).
"""
from __future__ import annotations

import copy
import functools
import hashlib
import re
from pathlib import Path

from covey.app import answer_cards
from covey.app.card_lanes import after_ack
from covey.cards.review import FOLD_CLOSE_KIND
from covey.core.state import read_object, write_json

FOLDER = "fold-cards"
NUMBERED = re.compile(r"^(.+_s)(\d+)$")
ID_CHARS = 20  # CardKit's limit on an element ID.


def path_of(state_dir, message_id) -> Path:
    return Path(state_dir) / FOLDER / (hashlib.sha256(str(message_id).encode()).hexdigest()[:32] + ".json")


def has_fold(card) -> bool:
    """Whether ``card`` holds a fold that closes on its text."""
    return bool(_folds(card))


def remember(state_dir, message_id, card, key="") -> None:
    """Keep ``card``, sent as ``message_id`` for the job ``key``, when it has a fold that closes on its text. Never
    raises: without it the fold closes at its title alone."""
    try:
        if message_id and isinstance(card, dict) and has_fold(card):
            write_json(path_of(state_dir, message_id), {"message_id": message_id, "key": key, "card": card},
                       ensure_ascii=False)
    except Exception:  # noqa: BLE001 - the card is out
        pass


def _folds(node, found=None) -> list:
    """The collapsible panels under ``node`` whose text is a button of FOLD_CLOSE_KIND."""
    found = [] if found is None else found
    if isinstance(node, dict):
        if node.get("tag") == "collapsible_panel" and any(_value(e) for e in node.get("elements") or ()):
            found.append(node)
        for value in node.values():
            _folds(value, found)
    elif isinstance(node, list):
        for value in node:
            _folds(value, found)
    return found


def _value(element) -> dict | None:
    for behavior in (element.get("behaviors") or []) if isinstance(element, dict) else ():
        if isinstance(behavior, dict) and (behavior.get("value") or {}).get("kind") == FOLD_CLOSE_KIND:
            return behavior["value"]
    return None


def closed(card, fold_id) -> dict | None:
    """``card`` with the fold ``fold_id`` closed under the next ID, its text naming that ID; None when it has no such
    fold. A fold of the same name under another number (a second click before the card changed, or the card as the
    other record had it) is the same fold: it is closed under a number past both, never one the client has seen."""
    found = NUMBERED.match(str(fold_id or ""))
    if found is None:
        return None
    base, clicked = found.group(1), int(found.group(2))
    card = copy.deepcopy(card)
    for panel in _folds(card):
        mine = NUMBERED.match(str(panel.get("element_id") or ""))
        if mine is None or mine.group(1) != base:
            continue
        new_id = f"{base}{max(clicked, int(mine.group(2))) + 1}"
        if len(new_id) > ID_CHARS:
            return None
        panel["element_id"], panel["expanded"] = new_id, False
        for element in panel.get("elements") or ():
            value = _value(element)
            if value is not None:
                value["fold"] = new_id
        return card
    return None


class FoldClose:
    def __init__(self, runtime, messenger) -> None:
        self.runtime, self.messenger = runtime, messenger

    @staticmethod
    def matches(raw) -> bool:
        return isinstance(raw, dict) and raw.get("kind") == FOLD_CLOSE_KIND

    def claim(self, ctx, event, raw, owner):
        """A click on the text of a fold (app/unified.py PANELS), else None."""
        if not self.matches(raw):
            return None
        if not owner:
            return "owner_only"
        message_id = str(event.get("message_id") or "")
        if not message_id:
            return "fold_close_stale"
        after_ack(functools.partial(self.close, ctx, message_id, str(raw.get("fold") or "")))
        return "fold_close"

    def close(self, ctx, message_id, fold_id) -> None:
        """Write the card ``message_id`` again with its fold ``fold_id`` closed. Never raises: the fold stays open and
        its title still closes it."""
        try:
            path = path_of(ctx.state_dir, message_id)
            saved = read_object(path)
            if not saved:
                return  # Not kept (sent before this release, or past maintenance's days).
            key = str(saved.get("key") or "")
            kept = answer_cards.kept_card(ctx.state_dir, key, message_id) if key else None
            card = closed(kept if kept is not None else saved.get("card"), fold_id)
            if card is None:
                return
            if not self.messenger.patch_card(ctx.profile, message_id, card):
                self.runtime.log(f"fold not closed message={message_id[-10:]}")
                return
            write_json(path, {**saved, "card": card}, ensure_ascii=False)
            if kept is not None:
                answer_cards.keep_card(ctx.state_dir, key, message_id, card)
        except Exception as exc:  # noqa: BLE001
            self.runtime.log(f"fold close failed: {type(exc).__name__}")
