"""等主人的账 at the Bridge (docs/architecture.md 等主人的账; core/owner_ledger.py the entries and the record).

``of``: the one read every reader of 要你处理 and 有结果 takes them from (手上的事 app/overview.py, the 看板 and the 早晚汇总
app/digest.py collect, the web page app/web_collect.py asked, the butler's snapshot app/butler.py), from the board's look
the reader took (app/pins.py PinnedTopics.look): 等我 (core/board_read.py waits), 要你处理 (``asks``: with the proposals of
整理专项 waiting in the owner's private chat, a group has none) and 有结果 (``unseen``), each thing one entry with the card
it is opened on; and the entries whose card is not in the chat (``missing``): a question of a topic, pending and the
owner's (not held for a project's lead), asked GRACE seconds ago or more and within MISSING_AGE, whose card never went
(``unshown``: core/board_read.py asks says it is no 等我 then, so no card counted it and nobody saw it; the owner,
2026-11-25: 结论、要我定的、停住了的都要在私聊里有张卡).

``Reconcile``: 对账, a worker thread of the Bridge every COVEY_LEDGER_RECONCILE seconds (RECONCILE_EVERY unset; 0: no
thread): the ledger of the owner's private chat and of each personal group, written to the record (its counts, its
missing keys), and each missing card that is the 对账's (``ours``: not one app/triage.py's sweep sends again, nor one
waiting for its turn's result to go first) sent again as its own Harness sends it (app/triage.py ``show``) when ``due``:
the try counted before the send, its outcome after (AGENTS rules 1 and 2: no record lock across Feishu). The 诊断
(service/doctor.py ``ledger_row``) and ``bin/covey_ledger.py`` read the record: how many tries, how many went out.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

from covey.core import board_read, owner_ledger, triage
from covey.core import env as cenv
from covey.core.jobs import find_job_record
from covey.core.owner_ledger import PROJECT, PROPOSAL, QUESTION, RESULT, START, STOP, STUCK, Entry
from covey.core.store import directory_store

SWITCH = "COVEY_LEDGER_RECONCILE"  # Seconds between two 对账 (unset: RECONCILE_EVERY; 0: none).
RECONCILE_EVERY = 300
START_WAIT = 90  # Seconds after the Bridge starts before the first 对账: the task runners it adopts settle first.
GRACE = 180  # A card younger than this may still be on its way: not missing yet.
MISSING_AGE = 2 * 86400  # A question asked longer ago is the stale closer's (core/stale.py), not sent again.
WAITING = ("waiting_user", "running", "failed")  # A question's task that may still wait on it.


@dataclasses.dataclass(frozen=True)
class Ledger:
    """等主人的账 of one chat now: ``waits`` (core/board_read.py Waits), ``asks`` (Asks), ``unseen`` (topic -> its result's
    job record), ``unshown`` (the question records whose card never went, newest first)."""
    waits: board_read.Waits
    asks: board_read.Asks
    unseen: dict
    unshown: tuple = ()

    def entries(self) -> tuple:
        """Every entry, once: 等你 first, then 停住了, 可能卡住, 有结果 (a topic's result that stopped is 停住了, not 有结果),
        then the missing ones."""
        found, seen = [], set()

        def add(entry):
            if entry.key not in seen:
                seen.add(entry.key)
                found.append(entry)
        for wait in self.waits.all:
            add(Entry(QUESTION if wait.kind == "question" else START,
                      str(wait.record.get("token") if wait.kind == "question" else wait.record.get("key") or ""),
                      wait.topic, wait.since, wait.card))
        for key, record in self.asks.proposals.items():
            add(Entry(PROPOSAL, str(key), "", float(record.get("created_at") or 0), card_of(record)))
        for topic, record in self.asks.stopped.items():
            add(Entry(STOP, job_key(record), topic, board_read.ended_at(record), str(record.get("card_message_id") or "")))
        for key, record in self.asks.projects.items():
            add(Entry(PROJECT, str(key), str(record.get("lead_topic_id") or ""), float(record.get("updated_at") or 0)
                      if isinstance(record.get("updated_at"), (int, float)) else 0.0, card_of(record)))
        for topic, record in self.asks.stuck.items():
            add(Entry(STUCK, job_key(record), topic, board_read.started_at(record) or 0.0,
                      str(record.get("card_message_id") or "")))
        for topic, record in self.unseen.items():
            if topic not in self.asks.stopped:
                add(Entry(RESULT, job_key(record), topic, board_read.ended_at(record),
                          str(record.get("card_message_id") or "")))
        for record in self.unshown:
            add(missing_entry(record))
        return tuple(found)

    def missing(self) -> tuple:
        return tuple(entry for entry in self.entries() if entry.missing)

    def counts(self) -> dict:
        """{waiting, stopped, stuck, result}: the entries not missing, as the cards count them (Asks.counts and 有结果)."""
        return owner_ledger.counts(self.entries())


def missing_entry(record) -> Entry:
    """The entry of a question whose card never went (``unshown``)."""
    return Entry(QUESTION, str(record.get("token") or ""), str(record.get("topic_id") or ""),
                 float(record.get("created_at") or 0), "", True)


def card_of(record) -> str:
    card = record.get("card") if isinstance(record, dict) else None
    return str(card.get("message_id") or "") if isinstance(card, dict) else ""


def job_key(record) -> str:
    return str(record.get("key") or record.get("message_id") or record.get("job_id") or "")


def of(state, chat, now, looked, *, proposals=False, off=None) -> Ledger:
    """The ledger of ``chat`` now from ``looked`` (app/pins.py PinnedTopics after its ``look``; ``off``: the topics taken
    off the board, else the look's ``dismissed``), ``proposals`` in the owner's private chat. What every reader counts."""
    off = dict(looked.dismissed if off is None else off)
    waits = board_read.waits(state, chat, now, off=off)
    asks = looked.asks(state, chat, waits, now, off, proposals=proposals)
    return Ledger(waits, asks, dict(looked.unseen or {}), tuple(unshown(state, chat, now)))


def unshown(state, chat, now) -> list:
    """The questions of ``chat`` whose card never went (newest first): pending, not shown (core/board_read.py ``asks`` is
    false of them) though nothing holds them back — not held for or answered by a project's lead (app/triage.py: a held one
    is the lead's), asked GRACE seconds ago or more and within MISSING_AGE. Index query only; never raises."""
    try:
        rows = directory_store(Path(state) / "questions").query(chat_id=chat, status="pending")
    except (OSError, ValueError):
        return []
    found = []
    for _, row in rows:
        at = row.get("created_at")
        if (board_read.asks(row) or not row.get("topic_id") or not isinstance(at, (int, float))
                or not GRACE <= now - at <= MISSING_AGE or triage.state(row) in (triage.HELD, triage.ANSWERED)):
            continue
        found.append(row)
    return sorted(found, key=lambda row: float(row.get("created_at") or 0), reverse=True)


def ours(state, record) -> str:
    """Why 对账 does not send ``record``'s card itself ('' when it does): one app/triage.py's sweep sends again (handed on
    to the owner, escalated), one whose turn's result must go first (core/board_read.py asks: the outbox sends that), or
    one whose task no longer waits on it."""
    if triage.state(record) == triage.ESCALATED:
        return "triage"
    if record.get("body_delivery_required") and record.get("body_delivery_confirmed") is not True:
        return "result-first"
    job = find_job_record(Path(state), record.get("job_key")) if record.get("job_key") else None
    if job is not None and job.get("status") not in WAITING:
        return "task-ended"
    return ""


def every() -> int:
    """Seconds between two 对账: COVEY_LEDGER_RECONCILE, RECONCILE_EVERY unset; 0 (or below): none."""
    raw = str(cenv.get(SWITCH, "") or "").strip()
    try:
        return int(raw) if raw else RECONCILE_EVERY
    except ValueError:
        return RECONCILE_EVERY


class Reconcile:
    """对账 (the module's ``Reconcile``): its thread, and ``tick`` (one look at every chat)."""

    name = "owner-ledger"

    def __init__(self, runtime, env) -> None:
        self.runtime, self.env = runtime, env

    def threads(self):
        return ((self.name, self.run),) if every() > 0 else ()

    def run(self, ctx) -> None:
        from covey.core.loops import every as loop

        if self.runtime.shutdown.wait(START_WAIT):
            return
        loop(self.runtime, every(), self.tick, args=(ctx,), isolate=self.name)

    def chats(self) -> list:
        access = self.runtime.access
        found = [access.notify_chat() or access.owner_chat(), *sorted(access.agent_groups)]
        return list(dict.fromkeys(chat for chat in found if chat))

    def tick(self, ctx, now=None) -> None:
        import time

        from covey.app.pins import PinnedTopics

        state, now = Path(ctx.state_dir), time.time() if now is None else now
        owner = self.runtime.access.owner_chat()
        for chat in self.chats():
            looked = PinnedTopics(None, None)
            looked.look(state, chat, now)
            ledger = of(state, chat, now, looked, proposals=chat == owner)
            entries = ledger.entries()
            record = owner_ledger.looked(state, chat, entries, now)
            for found in ledger.unshown:
                entry = missing_entry(found)
                why = ours(state, found)
                if why or not owner_ledger.due(record, entry.key, now):
                    continue
                self.resend(state, chat, entry, found, now)

    def resend(self, state, chat, entry, record, now) -> bool:
        """``record``'s card sent again (app/triage.py show), the try counted first; whether it went out. Never raises."""
        from covey.app import triage as triage_flow

        if not owner_ledger.trying(state, chat, entry, now):
            return False
        ok, why = False, ""
        try:
            ok = bool(triage_flow.show(self.env, record))
            why = "" if ok else "卡没发出去"
            if ok:
                triage_flow.mend(self.env, record)  # A task failed for this question's card waits for the answer again.
        except Exception as exc:  # noqa: BLE001 - the next 对账 tries again
            why = f"{type(exc).__name__}: {str(exc)[:80]}"
        owner_ledger.tried(state, entry, ok, why)
        self.runtime.log(f"owner ledger resend key={entry.key[:24]} topic={entry.topic[-8:]} ok={ok}"
                         + (f" why={why[:60]}" if why else ""))
        return ok


WORDS = {"waiting": "等你", "stopped": "停住了", "stuck": "可能卡住", "result": "有结果"}


def now_view(state, chats, now) -> dict:
    """{chat: {counts, entries}} of the ledger of each of ``chats`` now, read only (``of`` over a fresh look)."""
    from covey.app.pins import PinnedTopics

    owner = str((read_owner_chat(state) or {}).get("chat_id") or "")
    found = {}
    for chat in chats:
        looked = PinnedTopics(None, None)
        looked.look(Path(state), chat, now)
        ledger = of(Path(state), chat, now, looked, proposals=chat == owner)
        found[chat] = {"counts": ledger.counts(), "entries": [entry.row() for entry in ledger.entries()]}
    return found


def read_owner_chat(state) -> dict:
    from covey.core.state import read_object

    try:
        return read_object(Path(state) / "owner-chat.json")
    except (OSError, ValueError):
        return {}


def render(state, record, live=None) -> str:
    """The record (and ``live``, ``now_view``'s) as lines for a terminal."""
    import time

    from covey.core.topics import topic_label

    def when(stamp):
        return time.strftime("%m-%d %H:%M", time.localtime(stamp)) if isinstance(stamp, (int, float)) and stamp > 0 else "—"

    def label(topic):
        try:
            return topic_label(Path(state), topic) or (topic[:8] if topic else "")
        except (OSError, ValueError):
            return topic[:8]

    def said(counts):
        return "、".join(f"{WORDS[key]} {counts[key]}" for key in WORDS if (counts or {}).get(key)) or "没有等你的事"
    lines = [f"等主人的账（{state}）"]
    chats = record.get("chats") if isinstance(record.get("chats"), dict) else {}
    if not chats:
        lines.append("还没对过账：Bridge 启动后每 %d 秒对一次（COVEY_LEDGER_RECONCILE）" % RECONCILE_EVERY)
    for chat, row in chats.items():
        if isinstance(row, dict):
            lines.append(f"上次对账 {when(row.get('at'))} · {chat}：{said(row.get('counts'))}")
            for key in row.get("missing") or ():
                lines.append(f"  没到聊天里的卡：{key}")
    for chat, row in (live or {}).items():
        lines.append(f"现在 · {chat}：{said(row['counts'])}")
        for entry in row["entries"]:
            mark = "（卡没到聊天里）" if entry["missing"] else ""
            lines.append(f"  {WORDS.get(entry['state'], entry['state'])} · {label(entry['topic']) or entry['what']} · "
                         f"{entry['key']}{mark}")
    totals = record.get("totals") if isinstance(record.get("totals"), dict) else {}
    lines.append(f"补发：共 {int(totals.get('tries') or 0)} 次，发出 {int(totals.get('ok') or 0)} 次，"
                 f"没发出 {int(totals.get('failed') or 0)} 次")
    for item in owner_ledger.summary(record)["recent"]:
        mark = "✓" if item["ok"] else ("…" if item["ok"] is None else "✗")
        lines.append(f"  {when(item['last_at'])} {mark} {label(item['topic'])} {item['key']} 第 {item['tries']} 次"
                     + (f"：{item['why']}" if item["why"] else ""))
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    import json
    import time

    parser = argparse.ArgumentParser(prog="covey_ledger.py", description="等主人的账：现在数到的、上次对账缺的卡、补发了几次（只读）")
    parser.add_argument("--state-dir", required=True, help="这个部署的状态目录")
    parser.add_argument("--json", action="store_true", help="JSON 输出")
    args = parser.parse_args(argv)
    state = Path(args.state_dir)
    record = owner_ledger.read(state)
    chats = [*(record.get("chats") or {}), str((read_owner_chat(state) or {}).get("chat_id") or "")]
    live = now_view(state, list(dict.fromkeys(chat for chat in chats if chat)), time.time())
    if args.json:
        print(json.dumps({"record": owner_ledger.summary(record), "now": live}, ensure_ascii=False))
    else:
        print(render(state, record, live))
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
