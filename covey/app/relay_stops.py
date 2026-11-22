"""停住了 at the private chat's top level (app/butler_relay.py relays a topic turn the butler started or handed on that stopped
with no automatic retry planned; docs/butler.md 结论回到顶层): what its card says and what its buttons do.

- Its words are core/failure.py ``failure_view``'s, the reason and the next step, as the task card, the recovery card and the web
  page say them (``facts``), never the record's status line (it went to 技术详情 on the task card).
- Its buttons (``area``, under the reason) are the task card's for that record: its 检查并继续 (现在重试, 重新投递结果: the record's
  own, core/failure.py label), 看原因, 拆小再试 and 换个模型 (a record with a binding, cards/recovery.py switch_route), none for a
  stop whose retry is already scheduled (failure_view offers none then).
- Each button is the task card's own kind (bridge_job_retry, bridge_job_diagnose, bridge_job_split, bridge_switch_open) with
  ``RELAY`` in its value: the same handler (app/task_controls.py task_action, app/submission.py follow_up, app/harness_switch.py)
  and the same checks (one on a card from before the topic's latest 换配置 starts nothing, app/card_routing.py job_route,
  app/binding.py current_binding_card). A click on the first three then redraws the relay's card in place (``clicked``): the area
  becomes one line of what was started (↪ 已接着做 · 任务 #12, ↪ 已开一轮只读排查 · 任务 #13) or of why it stands for nothing any
  more (the topic moved on to a newer turn, 换配置); a click refused for now (the topic has a task at work) keeps the buttons and
  says why on the card's last line (cards/relay_card.py stop_note). Nothing is replied in the topic's thread unless the card
  cannot be written.
- 换个模型 (T669) opens the 换配置 card at the top level, under the relay (cards/topic_actions.py RELAY), a model of another
  Harness usable now preselected when there is one (PREFER_OTHER); once the owner confirms a switch there, the relay's card is
  redrawn (``switched``): the area is one line, ↪ 已换配置：<the new model>, and a reply to the card goes on with it.
- The relay record (main-thread/relays/<job key>.json, app/relay_send.py) keeps the card as it was sent (``card``) and what was
  started from it (``clicked``), so the area is drawn from the records as they are now (``area``): a second click, a repeated event
  or a card clicked after the task went on by another way says what became of it and starts nothing new."""
from __future__ import annotations

import copy
import time
from pathlib import Path

from covey.app import relay_send
from covey.app.binding import stale_job_card
from covey.cards.elements import button_row, grey, md, replace_element, topic_button
from covey.cards.recovery import DIAGNOSE_KIND, RETRY_KIND, SPLIT_KIND, switch_route
from covey.cards.relay_card import NOTE_ID, STOPPED, stop_note
from covey.cards.topic_actions import PREFER_OTHER, RELAY, SWITCH_OPEN, switch_value
from covey.core import failure
from covey.core.jobs import find_job_record, job_field, job_key, topic_job_records
from covey.core.state import read_object, write_json
from covey.core.store import directory_store
from covey.core.topics import topic_file, topic_label

# RELAY (cards/topic_actions.py): the mark in a stopped relay's button value: its click redraws the relay's card.
AREA_ID = "relay_actions"  # The element under the reason: the buttons, then the line of what came of a click.
# The next steps the card offers, in failure_view's order; the button kind of each (cards/recovery.py, app/card_actions.py;
# 换个模型 the 换配置 card's own, app/harness_switch.py).
KINDS = {failure.CONTINUE: RETRY_KIND, failure.RETRY: RETRY_KIND, failure.DIAGNOSE: DIAGNOSE_KIND, failure.SPLIT: SPLIT_KIND,
         failure.SWITCH_MODEL: SWITCH_OPEN}
# A stop failure_view has no words for (its record could not be read, or a stop no one named).
FALLBACK = "这一轮停了；进话题看看停在哪里"
STARTED = {failure.DIAGNOSE: "已开一轮只读排查", failure.SPLIT: "已开始拆小再试"}
MOVED_ON = "↪ 话题后来又有了新的一轮，这里的按钮不再用；进话题看最新的"
STALE = "↪ 话题之后换过配置，这一轮不再接着做；进话题说一句，就按新配置开下一轮"
# Switched from this card's 换个模型 (``switched``): a reply to the relay goes to its topic (app/relay_send.py remember_sent).
SWITCHED = "↪ 已换配置{}；回复这张卡说一句，就按新配置接着做"


def facts(state_dir, job, now=None) -> dict:
    """{reason, buttons} of ``job``'s 停住了 relay (cards/relay_card.py relay_card STOPPED): failure_view's title of its record (the
    turn's delivery wrote it just before) and ``area``'s buttons; FALLBACK and none when the record says no reason or cannot be
    read (the stop is relayed all the same)."""
    try:
        key = job_key(str(job_field(job, "message_id")), job_field(job, "job_id"))
        record = find_job_record(Path(state_dir), key) or {}
        view = failure.failure_view(record, time.time() if now is None else now) if record else None
        element = area(state_dir, record, {}, view=view) if view else None
    except (OSError, ValueError, TypeError, KeyError):
        view, element = None, None
    return {"reason": view["title"] if view else FALLBACK, "buttons": [element] if element else []}


def buttons(record, view):
    """The row of the card's buttons for ``record`` whose failure_view is ``view`` (AREA_ID): the first one offered the primary
    (docs/ui.md 第 6 节: one a block), each the task card's kind with RELAY; 换个模型 only for a record with a binding
    (switch_route), its 换配置 card preselecting another Harness usable now (PREFER_OTHER); None when it offers none."""
    route = switch_route(record)
    offered = [name for name in view.get("actions") or () if name in KINDS and (name != failure.SWITCH_MODEL or route)]
    if failure.CONTINUE in offered and failure.RETRY in offered:
        offered.remove(failure.RETRY)  # The same click under two names.
    if not offered:
        return None

    def value(name):
        if name == failure.SWITCH_MODEL:
            return switch_value(record.get("topic_id"), record.get("job_id"), *route, **{RELAY: True, PREFER_OTHER: True})
        return {"kind": KINDS[name], "topic_id": record.get("topic_id"), "job_id": record.get("job_id"), RELAY: True}
    return button_row([topic_button(failure.label(record, name), tone="primary" if not index else "", value=value(name))
                       for index, name in enumerate(offered)], AREA_ID)


def line(words):
    """The area as one grey line (AREA_ID), once the buttons have done what they could."""
    return md(grey(words), element_id=AREA_ID, size="notation")


def area(state_dir, record, relay, *, view=None):
    """What stands under the relay's reason for the job ``record`` as the records are now (``relay``: its relay record, {} before it
    is sent): the line of the task that went on from it (retried_by: 检查并继续 here or on its task card, or an automatic retry), of
    the follow-up a click here started (``relay`` clicked), of a topic that moved on to a newer turn or was switched (SWITCHED
    when this card's 换个模型 did it, ``switched``); else the buttons its failure_view offers (``view``, read when None), None
    when there are none."""
    moved = str(record.get("retried_by") or "")
    if moved:
        found = find_job_record(Path(state_dir), moved) or {}
        return line(f"↪ 已接着做 · 任务 #{found.get('job_id') or '?'}")
    started = relay.get("clicked") if isinstance(relay.get("clicked"), dict) else {}
    if started.get("action") in STARTED:
        return line(f"↪ {STARTED[started['action']]} · 任务 #{started.get('job_id') or '?'}")
    view = failure.failure_view(record) if view is None else view
    if not view:
        return line("↪ 这一轮已经处理过了，进话题看看")
    if newer_turn(state_dir, record):
        return line(MOVED_ON)
    if stale(state_dir, record):
        to = " ".join(str(started.get("to") or "").split())
        return line(SWITCHED.format(f"：{to}" if to else "") if started.get("action") == failure.SWITCH_MODEL else STALE)
    return buttons(record, view)


def newer_turn(state_dir, record) -> bool:
    """Whether ``record``'s topic has a task of a later job than it (the owner's next message, a 看原因 started on its task card):
    the relay's buttons then no longer stand for what the topic is doing. Its own retries are told by ``retried_by`` before."""
    try:
        mine = int(record.get("job_id") or 0)
        return any(int(other.get("job_id") or 0) > mine for other in topic_job_records(
            Path(state_dir), str(record.get("topic_id") or ""), chat_id=record.get("chat_id")))
    except (OSError, TypeError, ValueError):
        return False


def stale(state_dir, record) -> bool:
    """Whether ``record``'s task is from before its topic's latest 换配置 (app/binding.py stale_job_card): its card's 检查并继续 starts
    nothing then (app/card_routing.py job_route), so the relay offers none."""
    try:
        return stale_job_card(read_object(topic_file(Path(state_dir), str(record.get("topic_id") or ""))), record)
    except (OSError, TypeError, ValueError):
        return False


def clicked(part, ctx, event, raw, run) -> None:
    """A click on a stopped relay's button (``raw`` with RELAY), after it is acknowledged, in the place of the task card's reply:
    ``run()`` does what the task card's button does and returns (what the owner would be told, the job it started or None), unless
    the topic moved on to a newer turn (then nothing runs); then the relay's card is redrawn from the records (``settle``). The reply
    goes to the topic's thread only when the card could not be written. ``part``: the TaskControls or Submission that took the
    click (its harness, messenger, voice and runtime). ``run`` raising is the click's failure, reported as the task card's is
    (app/card_lanes.py reporting); the redraw never raises."""
    chat = str(event.get("chat_id") or "")
    event_id = str(event.get("event_id") or event.get("message_id") or "")
    try:
        job_id = int(raw.get("job_id") or 0)
    except (TypeError, ValueError):
        return
    record = next((r for r in part.harness.topic_records(ctx, chat) if r.get("job_id") == job_id), None)
    if record is None:  # Its record is gone (maintenance): the task card's click says why, under the topic's thread.
        said = run()[0]
        if said:
            part.messenger.reply(ctx, chat, said, part.voice.key("relay-action", event_id), voice=part.voice)
        return
    said, started = "", None
    if not record.get("retried_by") and not newer_turn(ctx.state_dir, record):
        said, started = run()  # Else it went on, or the topic did: the card says so and nothing starts.
    action = {DIAGNOSE_KIND: failure.DIAGNOSE, SPLIT_KIND: failure.SPLIT}.get(raw.get("kind"), failure.CONTINUE)
    try:
        current = find_job_record(Path(ctx.state_dir), record["key"]) or record
        note = "" if started is not None or current.get("retried_by") else said
        if settle(ctx.state_dir, part.messenger, ctx.profile, record["key"], current, note=note,
                  clicked={"action": action, "job_id": started, "at": time.time()} if started is not None else None):
            return
    except Exception as exc:  # noqa: BLE001 - the click did what it did; the owner is told below
        part.runtime.log(f"stopped relay card of job #{job_id} not redrawn: {type(exc).__name__}")
    if said:  # The card was not written: the owner is told the old way, under the topic's thread.
        part.messenger.reply(ctx, chat, said, part.voice.key("relay-action", event_id), voice=part.voice)


def settle(state_dir, messenger, profile, key, record, *, note="", clicked=None) -> bool:
    """The relay card of the job ``key`` redrawn with ``area`` (``record`` its job record now; ``clicked``, the follow-up this
    click started, kept in the relay record first) and its last line (``note``: why the click started nothing, said while the
    buttons stay): read and written under the relay records' lock, the card replaced whole outside it (rule 1;
    Messenger.patch_card, last write wins). Whether the card was written; False without a card sent."""
    path = relay_send.relay_path(state_dir, key)
    with relay_send.lock(state_dir):
        saved = read_object(path)
        if clicked is not None and saved:
            saved["clicked"] = clicked
            write_json(path, saved, ensure_ascii=False, indent=1)
    built = copy.deepcopy(saved.get("card")) if isinstance(saved.get("card"), dict) else None
    message = str(saved.get("message_id") or "")
    element = area(state_dir, record, saved)
    if built is None or not message.startswith("om_") or element is None or not replace_element(built, AREA_ID, element):
        return False
    label = topic_label(Path(state_dir), str(record.get("topic_id") or "")) or "话题"
    replace_element(built, NOTE_ID, stop_note(label, note if element.get("tag") == "column_set" else ""))
    if not messenger.patch_card(profile, message, built):
        return False
    with relay_send.lock(state_dir):
        saved = read_object(path)
        if saved.get("message_id") == message:
            saved["card"] = built
            write_json(path, saved, ensure_ascii=False, indent=1)
    return True


def job_record(state_dir, topic_id, chat_id, job_id) -> dict:
    """The record of the job ``job_id`` of ``topic_id`` in ``chat_id`` (what a relay's button names); {} when it is gone or
    cannot be read."""
    try:
        return next((r for _, r in directory_store(Path(state_dir) / "jobs").query(
            topic_id=str(topic_id or ""), chat_id=str(chat_id or ""), job_id=int(job_id))), None) or {}
    except (OSError, TypeError, ValueError):
        return {}


def redraw(state_dir, messenger, profile, topic_id, chat_id, job_id, *, clicked=None) -> bool:
    """``settle`` for the 停住了 relay of the job a click names (``topic_id``, ``chat_id``, ``job_id``): app/harness_switch.py
    when its 换个模型 meets a card from before the topic's latest 换配置 (the card says so, STALE) or has switched the topic
    (``switched``). Whether its card was written; False for a job with no 停住了 relay card (a 做完了 relay keeps none)."""
    record = job_record(state_dir, topic_id, chat_id, job_id)
    key = str(record.get("key") or "")
    if not key:
        return False
    with relay_send.lock(state_dir):
        saved = read_object(relay_send.relay_path(state_dir, key))
    if saved.get("outcome") != STOPPED or not isinstance(saved.get("card"), dict):
        return False
    return settle(state_dir, messenger, profile, key, record, clicked=clicked)


def switched(state_dir, messenger, profile, form, to="") -> bool:
    """After the owner confirmed a 换配置 the 停住了 relay's 换个模型 opened (``form``: its switch record, app/harness_switch.py
    finish, ``to`` the new model's name): the relay's card redrawn, its buttons a line (SWITCHED), as a click here keeps it
    (``clicked``); nothing while its task is not from before the topic's latest switch (``stale``: the binding did not
    change). Whether it was written; never raises: the switch is done whatever becomes of the card."""
    try:
        topic, chat, number = form.get("topic_id"), form.get("chat_id"), form.get("job_id")
        if not stale(state_dir, job_record(state_dir, topic, chat, number)):
            return False
        return redraw(state_dir, messenger, profile, topic, chat, number,
                      clicked={"action": failure.SWITCH_MODEL, "to": str(to or ""), "at": time.time()})
    except Exception:  # noqa: BLE001 - the card keeps its buttons; a click on them says the topic was switched (STALE)
        return False
