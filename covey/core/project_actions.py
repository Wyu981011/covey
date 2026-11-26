"""动作 (项目简报, docs/projects.md 负责人对照目标跟进, COVEY_COLLAB=1): the few things a project's goal is split into, each with
its items of the 目标检查表 and the topics that work on it, as plain functions of the project record. Standard library and core only.

- An action (``items``) is {id, title, note, items, topics, state, at, job}: what is being done (``title``), the lead's line on
  how it stands (``note``), the items it is met by (``items``, ids of the checklist, core/project_checklist.py), the member topics
  that work on it (``topics``, topic ids; one topic may be on several actions), and its state (``STATES``): ``open``, or
  ``dropped`` (not done any more: it stays in the record, out of the way, and its id is never given again). Ids are ``a1``,
  ``a2`` … in the order written. At most MAX_OPEN actions are not dropped.
- The record keeps them in ``actions``: {items, next, at, job}. Only the lead's tools write it (app/project_tools.py:
  project_checklist's ``actions``, ``apply``; project_topic_start and project_topic_send's ``action`` and ``item``, ``attach``),
  under the record's lock (core/projects.py update). ``apply`` checks everything before it edits, so a refusal writes nothing.
- ``state`` is kept nowhere: it is read off the checklist's items and the topics' own states every time (``OWNER`` the owner's
  turn, ``DOING``, ``DONE``, ``CHECK``, ``NEXT``: see ``state``), the same rule as the web page's briefData.ts. So a topic that
  ends or asks changes it at once, and the lead writes the line and the items, not the state.
- ``unmapped``: the member topics no item names (``topics_of``), what the lead is asked to hang on an item.

Not a task tracker: no dates, no owners but the owner himself, no history but what the record keeps."""
from __future__ import annotations

import re
import time

from covey.core import project_checklist as checklist

FIELD = "actions"
OPEN, DROPPED = "open", "dropped"
STATES = (OPEN, DROPPED)
MAX_OPEN = 10  # Actions not dropped.
TITLE = 30  # Characters of an action's title.
NOTE = 80  # Characters of the lead's line on how it stands.
TOPICS = 30  # Topics one action may have.
BACKGROUND = 300  # Characters of the project's background (the record's ``lead_background``, app/project_tools.py project_goal).
ACTION_ID = re.compile(r"a([1-9][0-9]{0,3})")
# What an action reads as (``state``) and the words for it; the topics' states ``state`` is given.
OWNER, DOING, DONE, CHECK, NEXT = "owner", "doing", "done", "check", "next"
STATE_WORDS = {OWNER: "等你", DOING: "在做", DONE: "做完", CHECK: "待核对", NEXT: "将要做"}
RUNNING, WAITING, ENDED = "running", "waiting", "ended"  # What a topic is: a turn runs or is queued, it waits for the owner, neither.


def _field(record) -> dict:
    found = record.get(FIELD) if isinstance(record, dict) else None
    return found if isinstance(found, dict) else {}


def _action(row) -> dict | None:
    """``row`` as an action, None for one that is not (no id of ours, no title)."""
    if not isinstance(row, dict) or not ACTION_ID.fullmatch(str(row.get("id") or "")) or not checklist.clean(row.get("title"), TITLE):
        return None
    at = row.get("at")
    return {"id": row["id"], "title": checklist.clean(row.get("title"), TITLE), "note": checklist.clean(row.get("note"), NOTE),
            "items": list(dict.fromkeys(each for each in row.get("items") or () if isinstance(each, str) and checklist.ITEM_ID.fullmatch(each))),
            "topics": list(dict.fromkeys(topic for topic in (checklist.clean(each, 64) for each in row.get("topics") or ()
                                                             if isinstance(each, str)) if topic))[:TOPICS],
            "state": row.get("state") if row.get("state") in STATES else OPEN,
            "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else 0, "job": checklist.clean(row.get("job"), 120)}


def items(record) -> list:
    """The record's actions, each well formed, in the order they were written (the dropped ones too); [] before the lead wrote any."""
    rows = _field(record).get("items")
    return [action for action in map(_action, rows if isinstance(rows, list) else ()) if action is not None]


def kept(record) -> bool:
    """Whether the lead has written an action for ``record``'s project."""
    return bool(items(record))


def _number(action_id) -> int:
    found = ACTION_ID.fullmatch(str(action_id or ""))
    return int(found.group(1)) if found else 0


def _list(value) -> list:
    return value if isinstance(value, list) else [value] if value else []


def apply(record, rows=(), *, job="", now=None) -> list:
    """Edit ``record`` in place (core/projects.py update's ``change``, after core/project_checklist.py ``apply`` when the same
    call changed items): ``rows`` are actions to add (no ``id``: a ``title`` at least) or to change (an ``id`` of one there: the
    keys given replace those it has; ``items`` and ``topics`` as a whole). ``items`` are ids of the checklist; ``topics`` are topic
    ids of the project's members (the tool turns T numbers into them). Everything is checked first: ValueError says what does
    not fit and nothing is changed. The ids of the actions added or changed, in order."""
    stamp = time.time() if now is None else now
    current = items(record)
    by_id = {action["id"]: dict(action) for action in current}
    order = [action["id"] for action in current]
    known = {item["id"] for item in checklist.items(record)}
    members = {topic for topic in record.get("threads") or () if isinstance(topic, str)}
    field = _field(record)
    number = max(0, _number(field.get("next")) - 1, *(_number(action_id) for action_id in order))
    touched, problems = [], []
    for row in rows:
        if not isinstance(row, dict):
            problems.append("每一个动作要是一个对象")
            continue
        action_id = checklist.clean(row.get("id"), 8)
        if action_id:
            if action_id not in by_id:
                problems.append(f"没有动作 {action_id}（状态包“简报”里每行开头的是 id）")
                continue
            action = by_id[action_id]
        else:
            if not checklist.clean(row.get("title"), TITLE):
                problems.append("新加的动作要写 title（动作名）")
                continue
            number += 1
            action_id = f"a{number}"
            action = by_id[action_id] = {"id": action_id, "title": "", "note": "", "items": [], "topics": [], "state": OPEN,
                                         "at": stamp, "job": checklist.clean(job, 120)}
            order.append(action_id)
        if "title" in row:
            action["title"] = checklist.clean(row.get("title"), TITLE)
        if "note" in row:
            action["note"] = checklist.clean(row.get("note"), NOTE)
        if "items" in row:
            given = list(dict.fromkeys(checklist.clean(each, 8) for each in _list(row.get("items")) if checklist.clean(each, 8)))
            for item_id in given:
                if item_id not in known:
                    problems.append(f"{action_id} 的条目 {item_id} 不在目标检查表里")
            action["items"] = given
        if "topics" in row:
            given = list(dict.fromkeys(checklist.clean(each, 64) for each in _list(row.get("topics")) if checklist.clean(each, 64)))
            for topic in given:
                if topic not in members:
                    problems.append(f"{action_id} 的话题 {topic[:8]} 不是这个专项的话题")
            if len(given) > TOPICS:
                problems.append(f"{action_id} 最多 {TOPICS} 个话题")
            action["topics"] = given
        if "state" in row:
            if row.get("state") not in STATES:
                problems.append(f"{action_id} 的 state 要是 " + "、".join(STATES) + " 之一")
                continue
            action["state"] = row["state"]
        action["at"], action["job"] = stamp, checklist.clean(job, 120) or action.get("job", "")
        touched.append(action_id)
    for action_id in dict.fromkeys(touched):
        if not by_id[action_id]["title"]:
            problems.append(f"{action_id} 的 title 不能为空")
    if sum(1 for action in by_id.values() if action["state"] != DROPPED) > MAX_OPEN:
        problems.append(f"没标 dropped 的动作最多 {MAX_OPEN} 个：把做完不再要的并起来，不做的标 dropped")
    if problems:
        raise ValueError("；".join(dict.fromkeys(problems)))
    record[FIELD] = {"items": [by_id[action_id] for action_id in order], "next": f"a{number + 1}", "at": stamp,
                     "job": checklist.clean(job, 120)}
    return list(dict.fromkeys(touched))


def check(record, action="", item="") -> None:
    """ValueError when ``action`` (an action id) or ``item`` (a checklist item id), either may be '', is not one of ``record``'s,
    or the action is dropped: what project_topic_start and project_topic_send look at before they open or feed a topic."""
    if action:
        found = next((each for each in items(record) if each["id"] == action), None)
        if found is None:
            raise ValueError(f"没有动作 {action}（状态包“简报”里每行开头的是 id）；先用 project_checklist 的 actions 加上它")
        if found["state"] == DROPPED:
            raise ValueError(f"动作 {action} 已经不做了（dropped）")
    if item and all(each["id"] != item for each in checklist.items(record)):
        raise ValueError(f"没有条目 {item}（状态包“目标检查表”里每行开头的是 id）")


def attach(record, topic, action="", item="", *, job="", now=None) -> tuple:
    """Hang ``topic`` (a member topic's id) on the action ``action`` and the item ``item`` (``check`` has seen them), in place
    (core/projects.py update's ``change``); with ``item`` and no ``action``, on every action not dropped that has the item. A
    place already there is left as it is; one that is full (TOPICS of an action, checklist.TOPICS of an item beside its main
    topic) is not hung on. (The ids hung on, in order; the words of what could not be.)"""
    stamp = time.time() if now is None else now
    done, full = [], []
    rows = items(record)
    targets = [each for each in rows if each["id"] == action] if action else \
        [each for each in rows if item and item in each["items"] and each["state"] != DROPPED]
    changed = {}
    for each in targets:
        if topic in each["topics"]:
            continue
        if len(each["topics"]) >= TOPICS:
            full.append(f"{each['id']} 的话题已满 {TOPICS} 个")
            continue
        changed[each["id"]] = {**each, "topics": [*each["topics"], topic], "at": stamp, "job": checklist.clean(job, 120) or each["job"]}
        done.append(each["id"])
    if changed:
        record[FIELD] = {**_field(record), "items": [changed.get(each["id"], each) for each in rows], "at": stamp,
                         "job": checklist.clean(job, 120)}
    entries = checklist.items(record)
    mine = next((each for each in entries if each["id"] == item), None) if item else None
    if mine is not None and topic != mine["topic"] and topic not in mine["topics"]:
        if len(mine["topics"]) >= checklist.TOPICS:
            full.append(f"{item} 已有 {checklist.TOPICS} 个参与的话题")
        else:
            mine = {**mine, "topics": [*mine["topics"], topic], "at": stamp, "job": checklist.clean(job, 120) or mine["job"]}
            record[checklist.FIELD] = {**record[checklist.FIELD], "at": stamp, "job": checklist.clean(job, 120),
                                       "items": [checklist.stored(mine if each["id"] == item else each) for each in entries]}
            done.append(item)
    return done, full


def state(action, entries, topic_states) -> str:
    """What ``action`` reads as, from the checklist's items (``entries``: ``checklist.items``) and its topics' states
    (``topic_states``: topic id -> RUNNING, WAITING or ENDED; a topic that is not in it is not counted), in this order:
    the owner's turn (``OWNER``: an item of it whose next step is the owner's, ``checklist.owners``, or a topic waiting for him),
    ``DOING`` (a topic runs), ``DONE`` (it has items, all met), ``CHECK`` (not met, its topics all ended: what a topic says is
    its own claim, the lead checks and writes the item), ``NEXT`` (no topic yet). An action with no item is never ``DONE``."""
    by_id = {item["id"]: item for item in entries}
    mine = [by_id[item_id] for item_id in action["items"] if item_id in by_id]
    seen = [topic_states[topic] for topic in action["topics"] if topic in topic_states]
    if any(checklist.owners(item)[0] for item in mine) or WAITING in seen:
        return OWNER
    if RUNNING in seen:
        return DOING
    if mine and all(item["state"] in checklist.MET for item in mine):
        return DONE
    return CHECK if seen else NEXT


def unmapped(record) -> list:
    """The member topics (ids, in the order they came in) that no item of the checklist names, ``topic`` or ``topics``."""
    named = {topic for item in checklist.items(record) for topic in checklist.topics_of(item)}
    return [topic for topic in record.get("threads") or () if isinstance(topic, str) and topic and topic not in named]
