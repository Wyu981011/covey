"""目标检查表 (docs/projects.md 目标检查表, COVEY_COLLAB=1): a project's done-when as a few items its lead keeps, and the
协作 gaps it has not dealt with yet, as plain functions of the project record and its inbox. Standard library and core only.

- An item (``items``) is {id, criterion, topic, needs, evidence, gap, state, at, job}: what is to be true (``criterion``),
  the member topic that delivers it (``topic``, a topic id; '' before one is named), the items it waits on (``needs``, their
  ids), where the proof is (``evidence``: a commit, a path, the check a topic's checkpoint said), what is still missing and who
  does it next (``gap``), and its state (``STATES``): ``open`` not met yet, ``done`` met, with its evidence, ``blocked`` held
  up (by ``needs`` or what ``gap`` says), ``dropped`` the owner let it go (``gap`` says why). Ids are ``c1``, ``c2`` … in
  the order written and never given again.
- The record keeps them in ``checklist``: {items, closed, next, at, job}. ``closed`` is the 协作 gaps the lead dealt with
  (gap id -> {how, at, job}). Only the lead's tool writes it (app/project_tools.py project_checklist), under the record's
  lock (core/projects.py update), and ``apply`` is that change: it checks everything before it edits, so a refusal writes
  nothing.
- A gap is a ``collab_gap`` receipt of the project's inbox (core/collab.py RECEIPT_GAP: what an integrator's continuation
  could not close). It stays open until the lead closes it with how (``gaps``), read or not: its id comes from the
  receipt's (``gap_id``).
- ``unmet``: the items not met (open, blocked) and the gaps not closed, what project_finish refuses on; ``conflicts``: an
  item marked met while one it waits on is not.

Not a project manager: no dates, no people but topics, no history but what the record keeps."""
from __future__ import annotations

import hashlib
import re
import time

from covey.core import collab

FIELD = "checklist"
OPEN, DONE, BLOCKED, DROPPED = "open", "done", "blocked", "dropped"
STATES = (OPEN, DONE, BLOCKED, DROPPED)
MET = frozenset({DONE, DROPPED})  # What project_finish lets through; ``dropped`` only because the owner let it go.
STATE_WORDS = {OPEN: "没满足", DONE: "满足", BLOCKED: "卡住", DROPPED: "不做了"}
MAX_ITEMS = 20
TEXT = 200  # Characters of a criterion, an evidence, a gap.
HOW = 120  # Characters of how a gap was dealt with.
NEEDS = 6  # Items one item may wait on.
CLOSED_KEPT = 100  # Closed gaps the record remembers.
ITEM_ID = re.compile(r"c([1-9][0-9]{0,3})")
GAP_ID = re.compile(r"g[0-9a-f]{6}")
GAP_KIND = collab.RECEIPT_GAP


def clean(text, limit=TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _field(record) -> dict:
    found = record.get(FIELD) if isinstance(record, dict) else None
    return found if isinstance(found, dict) else {}


def _item(row) -> dict | None:
    """``row`` as an item, None for one that is not (no id of ours, no criterion)."""
    if not isinstance(row, dict) or not ITEM_ID.fullmatch(str(row.get("id") or "")) or not clean(row.get("criterion")):
        return None
    needs = [need for need in row.get("needs") or () if isinstance(need, str) and ITEM_ID.fullmatch(need)]
    at = row.get("at")
    return {"id": row["id"], "criterion": clean(row.get("criterion")), "topic": clean(row.get("topic"), 64),
            "needs": needs[:NEEDS], "evidence": clean(row.get("evidence")), "gap": clean(row.get("gap")),
            "state": row.get("state") if row.get("state") in STATES else OPEN,
            "at": at if isinstance(at, (int, float)) and not isinstance(at, bool) else 0, "job": clean(row.get("job"), 120)}


def items(record) -> list:
    """The record's items, each well formed, in the order they were written; [] when the lead has written none."""
    rows = _field(record).get("items")
    return [item for item in map(_item, rows if isinstance(rows, list) else ()) if item is not None]


def kept(record) -> bool:
    """Whether the lead keeps a checklist for ``record``'s project (one item at least)."""
    return bool(items(record))


def closed(record) -> dict:
    """Gap id -> {how, at, job} of the 协作 gaps the lead dealt with."""
    found = _field(record).get("closed")
    return {key: value for key, value in found.items() if GAP_ID.fullmatch(str(key)) and isinstance(value, dict)} \
        if isinstance(found, dict) else {}


def gap_id(receipt_id) -> str:
    """The id a ``collab_gap`` receipt goes by: 'g' and six hex digits of its receipt id."""
    return "g" + hashlib.sha1(str(receipt_id).encode()).hexdigest()[:6]


def gaps(record, receipts) -> list:
    """The 协作 gaps not dealt with: of ``receipts`` (every receipt of the inbox, read or not, oldest first) the
    ``collab_gap`` ones the lead has not closed, as {id, receipt, thread, text, at}."""
    done = closed(record)
    found = []
    for item in receipts:
        if not isinstance(item, dict) or item.get("kind") != GAP_KIND or not item.get("id"):
            continue
        gap = gap_id(item["id"])
        if gap not in done and all(row["id"] != gap for row in found):
            found.append({"id": gap, "receipt": str(item["id"]), "thread": str(item.get("thread") or ""),
                          "text": clean(item.get("text"), 500), "at": float(item.get("at") or 0)})
    return found


def unmet(record, receipts) -> tuple:
    """(the items not met, the gaps not closed): what keeps ``record``'s project from being finished."""
    return [item for item in items(record) if item["state"] not in MET], gaps(record, receipts)


def conflicts(record) -> list:
    """(item, the ids of what it waits on that is not met) for each item marked met while something it needs is not."""
    by_id = {item["id"]: item for item in items(record)}
    found = []
    for item in by_id.values():
        if item["state"] not in MET:
            continue
        waiting = [need for need in item["needs"] if need in by_id and by_id[need]["state"] not in MET]
        if waiting:
            found.append((item, waiting))
    return found


def _number(item_id) -> int:
    found = ITEM_ID.fullmatch(str(item_id or ""))
    return int(found.group(1)) if found else 0


def apply(record, rows=(), close=(), *, receipts=(), job="", now=None) -> list:
    """Edit ``record`` in place (core/projects.py update's ``change``): ``rows`` are items to add (no ``id``: a
    ``criterion`` at least) or to change (an ``id`` of one there: the keys given replace those it has; ``topic`` already a
    topic id or ''), ``close`` the gaps dealt with ({gap, how}; ``receipts`` the inbox, to know the open ones). Everything is
    checked first: ValueError says what does not fit and nothing is changed. The ids of the items added or changed and of the
    gaps closed, in order."""
    stamp = time.time() if now is None else now
    current = items(record)
    by_id = {item["id"]: dict(item) for item in current}
    order = [item["id"] for item in current]
    field = _field(record)
    number = max(0, _number(field.get("next")) - 1, *(_number(item_id) for item_id in order))
    touched, problems = [], []
    for row in rows:
        if not isinstance(row, dict):
            problems.append("每一条要是一个对象")
            continue
        item_id = clean(row.get("id"), 8)
        if item_id:
            if item_id not in by_id:
                problems.append(f"没有条目 {item_id}（状态包“目标检查表”里每行开头的是 id）")
                continue
            item = by_id[item_id]
        else:
            if not clean(row.get("criterion")):
                problems.append("新加的条目要写 criterion（完成标准）")
                continue
            number += 1
            item_id = f"c{number}"
            item = by_id[item_id] = {"id": item_id, "criterion": "", "topic": "", "needs": [], "evidence": "", "gap": "",
                                     "state": OPEN, "at": stamp, "job": clean(job, 120)}
            order.append(item_id)
        for key in ("criterion", "evidence", "gap"):
            if key in row:
                item[key] = clean(row.get(key))
        if "topic" in row:
            item["topic"] = clean(row.get("topic"), 64)
        if "needs" in row:
            given = row.get("needs") if isinstance(row.get("needs"), list) else [row.get("needs")] if row.get("needs") else []
            item["needs"] = list(dict.fromkeys(clean(need, 8) for need in given if clean(need, 8)))
        if "state" in row:
            if row.get("state") not in STATES:
                problems.append(f"{item_id} 的 state 要是 " + "、".join(STATES) + " 之一")
                continue
            item["state"] = row["state"]
        item["at"], item["job"] = stamp, clean(job, 120) or item.get("job", "")
        touched.append(item_id)
    for item_id in dict.fromkeys(touched):
        item = by_id[item_id]
        if not item["criterion"]:
            problems.append(f"{item_id} 的 criterion 不能为空")
        if len(item["needs"]) > NEEDS:
            problems.append(f"{item_id} 最多依赖 {NEEDS} 条")
        for need in item["needs"]:
            if need == item_id:
                problems.append(f"{item_id} 不能依赖自己")
            elif need not in by_id:
                problems.append(f"{item_id} 依赖的 {need} 不在检查表里")
        if item["state"] == DONE and not item["evidence"]:
            problems.append(f"{item_id} 标 done 要写 evidence（证据在哪：提交号、产物路径、检查点里的自检）")
        if item["state"] == BLOCKED and not (item["needs"] or item["gap"]):
            problems.append(f"{item_id} 标 blocked 要写卡在哪（needs 或 gap）")
        if item["state"] == DROPPED and not item["gap"]:
            problems.append(f"{item_id} 标 dropped 要在 gap 里写为什么不做了（主人怎么说的）")
    if len(order) > MAX_ITEMS:
        problems.append(f"目标检查表最多 {MAX_ITEMS} 条，这次会有 {len(order)} 条：合并几条再加")
    open_gaps = {gap["id"] for gap in gaps(record, receipts)}
    shut = []
    for row in close:
        row = row if isinstance(row, dict) else {"gap": row}
        gap, how = clean(row.get("gap"), 8), clean(row.get("how"), HOW)
        if gap not in open_gaps:
            problems.append(f"没有没处理的缺口 {gap or '（空）'}（状态包“没处理的协作缺口”里每行开头的是 id）")
        elif not how:
            problems.append(f"关掉缺口 {gap} 要写 how（怎么处理的：谁补了、证据在哪，或主人说不用补）")
        else:
            shut.append((gap, how))
    if problems:
        raise ValueError("；".join(dict.fromkeys(problems)))
    done = closed(record)
    for gap, how in shut:
        done[gap] = {"how": how, "at": stamp, "job": clean(job, 120)}
    record[FIELD] = {"items": [by_id[item_id] for item_id in order],
                     "closed": dict(sorted(done.items(), key=lambda pair: pair[1].get("at") or 0)[-CLOSED_KEPT:]),
                     "next": f"c{number + 1}", "at": stamp, "job": clean(job, 120)}
    return [*dict.fromkeys(touched), *(gap for gap, _ in shut)]
