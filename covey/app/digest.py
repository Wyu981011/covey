"""早晚汇总: at the times of day COVEY_DIGEST_TIMES lists (HH:MM, comma separated, Asia/Shanghai), one card
at the top level of the owner's private chat listing what waits for the owner, what runs and what ended since the
digest before (cards/digest.py). Off unless the variable holds a valid time (docs/usage.md 早晚汇总): without
it there is no thread.

What it lists is read from the records, as the pinned board reads them (core/board_read.py read: the indexes of
questions/ and jobs/, no record lock, no Feishu call, the butler's topics left out), never from a model, and drawn as
the 看板 draws it (cards/digest.py: the conclusion band counts 要你处理 as the 看板 and 手上的事 count it, ``asked``, and
each topic is the same topic row, opening its card: ``url``, read before the card is built):
- 等你: 等我 as every reader counts it (core/board_read.py waits): each topic's newest question shown, the butler's
  and the leads' too, else its task waiting for 开始 on a launch card, asked within QUESTION_AGE (one day); those
  waiting longer are not listed one by one but as one line of topic numbers (``stale``), as on 手上的事. Each row
  keeps the card it is acted on (``card``): its T number, and its button on the 看板, open that card;
- 在做: each other topic's running job (board_read.order), the latest started first;
- 做完: each other topic's latest turn (not one cancelled before it ran: board_read.unrun) that ended after the
  digest before (``since``) and by this one's time, and every result the owner has not seen however old (有结果未看,
  pins.board_results: the board's rule, core/board_read.py unseen; ``older`` counts those that ended before
  ``since``), the latest first; one not 有结果未看 is marked 已看. What stopped is listed however long ago it ended, as
  要你处理 counts it (core/board_read.py Asks), and so are the projects a guard paused (``halted``) and, in the owner's
  private chat with 整理专项 on, its proposals waiting for his 好 (``pending``, listed under 等你).
With 手上的事 and the board on (overview.dismissable), the topics the owner took off the board (pins.taken_off: the
board's own reading of its record) are in none of it, and the line of old questions has 手上的事's button
这些都不用回答了 (cards/overview.py stale_line, its value's ``from`` "digest"). Its click is 手上的事's
(app/overview.py claim: the owner's only, the topics taken off, 手上的事 redrawn), which hands it on once
acknowledged (Overview.handed, app/unified.py): ``dismissed`` redraws this card from the view saved when it was
sent, the line turned grey, 已撤下 N 个, with 撤销 (``undismissed``: the line gone and the old questions that still
wait back, Messenger.patch_card, outside the lock; a 看板 card is redrawn from a fresh view instead). A card sent before views
were saved is left as it is. All empty, the line of old questions too, nothing is sent (the time counts as done);
only that line, the card is sent: it is what the owner has to deal with.

<state>/digest.json keeps the last time sent (``last_slot``, epoch seconds), the send under way (``pending``:
the time, its view, card and Markdown, its idempotency key, tries) and the last SENT_KEPT cards sent (``sent``:
message id -> {slot, view}). A time is sent once (``due``): while it is the
latest past, not sent yet and at most CATCH_UP seconds ago, so a Bridge stopped over the time and back within the
hour sends it once, later it is skipped. The card is built and saved before it is sent, outside the lock (rule 1);
a send not confirmed is tried again RETRY seconds later with the same key and card, at most SEND_TRIES times
(Feishu's idempotency window and feishu/transport.py's receipts post nothing twice), then given up.

The day's last digest time (``last_of_day``: with 09:30 and 21:30, the 21:30 one) is the evening digest; in the owner's private
chat it has three parts more (``daily``): 本周找你 N 次 (app/weekly_usage.py ``reached``: the week's questions and stops, counted
only), 今天代答 (``proxy_view``, when there is a 代答 sender: today's replies sent and not sent) and, with COVEY_MEMORY=1, 你反复说的
(app/memory_candidates.py, the hook ``candidates`` app/unified.py sets): the corrections the owner repeated in the day's ended
topics, each with 「记下」「不用」. A click on one (cards/digest.py REMEMBER_KIND, the owner's) decides it (memory_candidates
``decide``) and, once acknowledged, redraws the card from its saved view (``remembered``). The counts never make a card be
sent; an open candidate does, as the line of old questions does.

看板 (the bot menu's BOARD_KEY, in every deployment, the digest off too) is cards/board.py's card at any time, 随时查看 · HH:MM in its title (the view's ``asked``): what waits and runs now, and what ended since the
last digest time (``last_slot``, ``board_since``; without the digest, the last day). It reads digest.json and never writes it: the times and their
sends go on as before. Nothing to list, the card says so (a click wants an answer). Its record is
<state>/BOARD_FOLDER/<token>.json (app/menu_panel.py), the view in ``digest``; the bot menu keeps one such card and a
second click on the newest folds and unfolds it in place (app/bot_menu.py), unfolded with a fresh view. Its
这些都不用回答了 is handed on as the timed card's (``dismissed``), the card redrawn from the record's view. A stopped
topic's own 检查并继续 on it (cards/board.py RECOVER_KIND, ``recover`` on its row: core/failure.py says the record takes
one) is done as its task card's click does it (``recover``: app/task_controls.py retry_topic, in the context an automatic
retry runs in; a saved result or question sent again, never run twice: a task once taken on is not taken on again) and
the card is redrawn in place with one line of what came of it. With the web page's address set (core/web_sync.py
page_url) its last line has 打开网页 (``web``), as the timed card's and 手上的事's do.
"""
from __future__ import annotations

import datetime
import re
import time
from concurrent import futures as concurrent_futures
from pathlib import Path

from covey.app import memory_candidates, weekly_usage
from covey.app.overview import dismissable
from covey.app.pins import board_look, kept, laid, record_path, taken_off as taken_off_now
from covey.app import owner_ledger, project_loop, revisits, topic_links
from covey.app.topic_links import link_for, linkify
from covey.app.form_cards import settle
from covey.app.menu_panel import MenuPanel
from covey.app.card_lanes import after_ack
from covey.cards.board import (KINDS as BOARD_KINDS, OPEN_KIND, PROJECT_GO_KIND, RECOVER_KIND, REVISIT_KIND, SEEN_KIND,
                               SEEN_MAX, board_card)
from covey.cards.digest import MEMORY_KIND, ORIGIN, REMEMBER_KIND, digest_card, digest_text, folded_board
from covey.core import board_read, failure, knowledge, look, memory, patrol, projects, quiet_hours, turn_words, web_sync
from covey.core import project_proposals
from covey.core import progress as turn_progress
from covey.core.board_read import ended_at, order, started_at, unrun
from covey.core.failure import LABELS as FAILURE_LABELS, failure_view
from covey.core.jobs import find_job_record, topic_job_records
from covey.core.locks import resource_lock
from covey.core.loops import every
from covey.core.metrics import run_seconds, took_text
from covey.core.state import read_object, write_json
from covey.core.statuses import RUNNING, TERMINAL
from covey.core.topics import label_title, topic_file, topic_label as number_of

ENV = "COVEY_DIGEST_TIMES"
RECORD = "digest.json"
ZONE = datetime.timezone(datetime.timedelta(hours=8))  # Asia/Shanghai, no summer time; no tz database needed.
TICK = 30
CATCH_UP = 3600
RETRY = 60
SEND_TRIES = 3
SENT_KEPT = 6  # Cards whose view is kept for 这些都不用回答了: three days at two a day.
LOOKBACK = 3 * 86400  # 做完 reaches back this far at most (board_read.read reads jobs written within it).
TIME = re.compile(r"([01]?\d|2[0-3]):([0-5]\d)")
LINK_READS = 6  # The 看板's links read at once (``Digest.urls``), as topic_links reads a text's T numbers.
BOARD_KEY = "digest_board"  # The bot menu's 看板 (docs/usage.md 机器人菜单).
BOARD_KIND = "digest-board"
BOARD_FOLDER = "digest-boards"  # Its cards' records (app/menu_panel.py).
BOARD_FAILED = "看板没能发出去，请稍后再点机器人菜单「看板」。"
BOARD_SCANNED = 20  # The newest board records ``dismissed`` looks a card up in.
RECOVER_ACTIONS = (failure.CONTINUE, failure.RETRY)  # What a stopped row's own button does (cards/board.py RECOVER_KIND).
TOPIC_ID = re.compile(r"[0-9a-f]{16,128}")


def parse_times(raw, log=lambda _: None):
    """The minutes after midnight that ``raw`` lists, sorted and each once; a part that is not HH:MM is logged."""
    minutes = set()
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        match = TIME.fullmatch(part)
        if match is None:
            log(f"digest time ignored: {part!r} is not HH:MM")
            continue
        minutes.add(int(match.group(1)) * 60 + int(match.group(2)))
    return sorted(minutes)


def configured(log=lambda _: None):
    """The digest times COVEY_DIGEST_TIMES lists (``parse_times``; core/quiet_hours.py ``digest_times``: 09:30,21:30
    unset), [] when it is ``off``: the digest is off."""
    raw = quiet_hours.digest_times()
    return parse_times(raw, log) if raw else []


def slots(times, now):
    """The digest times (epoch seconds) at or before ``now``, the latest last, over the last three days."""
    today = datetime.datetime.fromtimestamp(now, ZONE).date()
    found = []
    for back in (3, 2, 1, 0):
        day = today - datetime.timedelta(days=back)
        for minute in times:
            at = datetime.datetime(day.year, day.month, day.day, minute // 60, minute % 60, tzinfo=ZONE).timestamp()
            if at <= now:
                found.append(at)
    return found


def due(times, now, last):
    """The time to send now, or None: the latest past one, if not sent (``last``) and at most CATCH_UP ago."""
    past = slots(times, now)
    if not past:
        return None
    slot = past[-1]
    if isinstance(last, (int, float)) and last >= slot:
        return None
    return slot if now - slot <= CATCH_UP else None


def last_of_day(times, slot) -> bool:
    """Whether ``slot`` is the day's last digest time of ``times``: the evening digest, which has the day's own parts."""
    at = datetime.datetime.fromtimestamp(slot, ZONE)
    return bool(times) and at.hour * 60 + at.minute == max(times)


def proxy_view(state_dir, now) -> dict:
    """今天代答 (Asia/Shanghai's day of ``now``): {sent, unsent}: the batches that went out today, and those whose last move
    today left them not sent (held for the owner, uncertain, failed); {} without a 代答 sender, or with 代答 off and nothing
    of today's."""
    from covey.app.proxy_send import available
    from covey.core import proxy as records
    if not available():
        return {}
    day = datetime.datetime.fromtimestamp(now, ZONE)
    start = datetime.datetime(day.year, day.month, day.day, tzinfo=ZONE).timestamp()
    sent = unsent = 0
    for batch in records.read_batches(state_dir, statuses=None):
        moves = [move for move in batch.get("history") or () if isinstance(move, list) and len(move) >= 2
                 and isinstance(move[1], (int, float))]
        if any(move[0] == "sent" and move[1] >= start for move in moves):
            sent += 1
        elif batch.get("status") in ("held", "uncertain", "failed") and moves and moves[-1][1] >= start:
            unsent += 1
    if not (sent or unsent or records.read_settings(state_dir).get("enabled")):
        return {}
    return {"sent": sent, "unsent": unsent}


def remember_row(row) -> dict:
    """A candidate (app/memory_candidates.py) as the card's view keeps it."""
    return {"id": row["id"], "text": str(row.get("text") or ""), "labels": list(row.get("labels") or ()),
            "workspace": str(row.get("workspace") or ""), "state": row.get("state") or memory_candidates.OPEN,
            **({"error": str(row["error"])} if row.get("error") else {}),
            **({"carried": True} if row.get("carried") else {}),
            **({"quote": str(row["quote"])} if row.get("quote") else {}),
            **({"source": str(row["source"])} if row.get("source") not in (None, "", memory_candidates.REPEAT) else {})}


def since_of(times, slot, last):
    """Where 做完 starts for ``slot``: the digest time before it, or the last one sent when that is earlier (times
    were missed), never more than LOOKBACK back."""
    before = [at for at in slots(times, slot) if at < slot]
    start = before[-1] if before else slot - 86400
    if isinstance(last, (int, float)) and last < start:
        start = last
    return max(start, slot - LOOKBACK)


def clock_words(at, now) -> str:
    """When ``at`` was, as the 看板 says it: "20:31" today, "昨天 02:40", else "11-16 09:05"."""
    then, today = datetime.datetime.fromtimestamp(at, ZONE), datetime.datetime.fromtimestamp(now, ZONE).date()
    if then.date() == today:
        return then.strftime("%H:%M")
    if then.date() == today - datetime.timedelta(days=1):
        return "昨天 " + then.strftime("%H:%M")
    return then.strftime("%m-%d %H:%M")


first_line = board_read.first_line  # As ever, for what imports it here.


def board_since(times, now, last):
    """Where 看板's 做完 starts at ``now``: the last digest time done (``last``, digest.json's last_slot), else the latest
    past time, never more than LOOKBACK back."""
    past = slots(times, now)
    start = last if isinstance(last, (int, float)) else past[-1] if past else now - 86400
    return max(start, now - LOOKBACK)


def review_view(state_dir, log=lambda _: None) -> dict:
    """{"review": {pending, url}} when the memory has items waiting for the owner (app/web_memory.py overview ``counts.pending``,
    ``url`` the 网页记忆中心's 待审核 tab with the web page on, else ''): the line ``记忆：待审核 N 条`` of the 早晚汇总. {} with none
    waiting, or when the memory cannot be read (the digest goes out without the line)."""
    from covey.app import web_memory

    if not web_memory.enabled():
        return {}  # COVEY_MEMORY=0: the digest is as it was without the memory.
    try:
        pending = int(web_memory.overview(state_dir)["counts"]["pending"])
        url = web_memory.center_url("review")
    except Exception as exc:  # noqa: BLE001 - the digest goes out without the line
        log(f"digest review count unreadable: {type(exc).__name__}")
        return {}
    return {"review": {"pending": pending, "url": url}} if pending > 0 else {}


def web_view() -> dict:
    """{"web": the web page's address} with COVEY_WEB=1 and the address set (core/web_sync.py page_url): the 看板's and the
    早晚汇总's last line has 打开网页; {} otherwise, the card as it was."""
    url = web_sync.page_url()
    return {"web": url} if url else {}


def topic_label(state, topic_id):
    """(T number, the topic's title), '' for a topic without a number yet."""
    return label_title(state, topic_id, "（话题未知）")


def collect(state, chat, slot, since, now, *, board=False, asked=False):
    """The three parts' rows for ``chat`` (``view`` of cards/digest.py without links): {label, title, state,
    took, seen, topic}, a 等你 row's ``kind`` and ``card`` too, ``older`` (the 做完 rows of results not seen that ended
    before ``since``), and ``stale``, 等我 waiting over QUESTION_AGE (core/board_read.py waits); ``board``: 手上的事
    and the board are on (overview.dismissable), the topics taken off left out and the stale line's button shown.
    ``asked``: for the 看板, which lists 要你处理 as 手上的事 counts it (core/board_read.py Asks): every topic whose result
    stopped however long ago it ended and no stop besides, and as 可能卡住 the running ones it names, so its band counts
    what 手上的事's says."""
    # One read of the indexes (core/board_read.py): with the board, the one its look judges too; the jobs judged
    # here are those read without the board's ``keep``.
    read = board_read.read(state, chat, now, keep=kept(state, chat) if laid() else ())
    looked = board_look(state, chat, now, read)  # 有结果未看, as the board has it (core/board_read.py), and 要你处理.
    unseen, off = looked.unseen, looked.dismissed
    off = off if board else {}
    jobs = [record for record in read.jobs if board_read.fresh(record, now) and record.get("topic_id") not in off]
    # 等你: 等我 as every reader counts it (core/board_read.py waits): the questions, the butler's and the leads' too,
    # and the tasks waiting for 开始, each with the card it is acted on; those waiting over QUESTION_AGE one line.
    ledger = owner_ledger.of(state, chat, now, looked, off=off)  # 等主人的账 (app/owner_ledger.py), as every reader.
    found = ledger.waits
    asks = ledger.asks if asked else None

    def named(topic):
        """(label, title) of ``topic``: the butler or a lead asking at the top level by its speaker, no T number."""
        if not board_read.listed(topic, chat):
            return board_read.speaker_of(state, topic, chat) or "管家", ""
        return topic_label(state, topic)

    stale = [{"topic": wait.topic, "label": label, "title": title, "card": wait.card}
             for wait in found.stale for label, title in [named(wait.topic)]]

    def row(topic, state_words, took, seen_it=False):
        label, title = named(topic)
        return {"topic": topic, "label": label, "title": title, "state": state_words, "took": took, "seen": seen_it}

    newest = {}
    for record in read.jobs:
        topic = record.get("topic_id") or ""
        if topic and (topic not in newest or order(record) > order(newest[topic])):
            newest[topic] = record

    def phase_of(record) -> str:
        phase = " ".join(str((record or {}).get("phase") or "").split())
        return "" if phase in turn_words.UNSET_PHASES else phase

    waiting = []
    for wait in found.live:
        topic, record = wait.topic, wait.record
        took = f"等了 {took_text(now - wait.since)}"
        waited = f"等了 {turn_words.wait_words(now - wait.since)}"  # The 看板's grey line (docs/ui.md 7).
        if wait.kind == "start":
            waiting.append({**row(topic, turn_words.DIGEST_START, took), "kind": "start", "card": wait.card,
                            "line": turn_words.START_LINE, "meta": [waited]})
            continue
        ask = turn_words.ask_words(record)
        waiting.append({**row(topic, f"{turn_words.BOARD['waiting']}：{ask}" if ask else turn_words.BOARD["waiting"], took),
                        "kind": "question", "card": wait.card,
                        # The 看板's words (cards/board.py): what he is asked to decide, then how long it waited.
                        "line": f"要你定：{phase_of(newest.get(topic))}" if phase_of(newest.get(topic)) else
                        (f"要你定：{ask}" if ask else "有问题要你定"), "meta": [waited]})
    busy = {wait.topic for wait in found.live}

    running = {}
    for record in jobs:
        topic = record.get("topic_id") or ""
        if topic and topic not in busy and record.get("status") in RUNNING and (
                topic not in running or order(record) > order(running[topic])):
            running[topic] = record
    running_rows = []
    for topic, record in sorted(running.items(), key=lambda item: started_at(item[1]), reverse=True):
        phase = str(record.get("phase") or "")
        status = record.get("status")
        if status == "cancel_requested":
            words = "正在停止"
        elif phase and phase not in turn_words.UNSET_PHASES:
            words = phase
        else:
            words = turn_words.BOARD["queued" if status == "queued" else "running"]
        # The estimate or 可能卡住了 after the phase (core/progress.py board_words), the topic's earlier turns as read.
        found = turn_progress.progress(record, now=now, history=turn_progress.turn_seconds(
            [job for job in jobs if job.get("topic_id") == topic], exclude=record.get("job_id")))
        figures = turn_progress.board_words(found, now)
        words = " · ".join([words, *figures])
        ran = run_seconds(record.get("timings"), now=now) if status != "queued" else None
        # Steps as words, not a bar (docs/ui.md 4 progress: 话题行里不放，用“5/8 步”的文字代替).
        plan = (f"{found['plan_done']}/{found['plan_total']} 步"
                if found.get("plan_total") and found.get("plan_done") is not None else "")
        moved = found.get("last_activity_at")
        running_rows.append({**row(topic, words, f"已运行 {took_text(ran)}" if ran is not None else ""),
                             "line": f"现在：{phase_of(record)}" if phase_of(record) else
                             ("正在停止" if status == "cancel_requested" else turn_words.BOARD["queued" if status == "queued" else "running"]),
                             "meta": [plan, *(figure for figure in figures if "卡住" not in figure),
                                      f"{turn_progress.ago_words(now - moved)}有动静" if moved else "",
                                      f"已跑 {turn_words.wait_words(ran)}" if ran is not None else ""],
                             # Its task card: the 看板's row of one that may be stuck opens it (看看 is there).
                             "card": str(record.get("card_message_id") or ""),
                             "stuck": topic in asks.stuck if asks is not None else bool(found.get("maybe_stuck"))})
    busy |= set(running)

    ended = {}
    for record in jobs:
        topic = record.get("topic_id") or ""
        at = ended_at(record)
        if (topic and topic not in busy and record.get("status") in TERMINAL and not unrun(record)
                and since < at <= slot and int(record.get("job_id") or 0) > int(ended.get(topic, {}).get("job_id") or 0)):
            ended[topic] = record
    # Every result the owner has not seen is listed, however long ago it ended (the board's 有结果未看: its own
    # record, the one ``unseen`` has); the others only when they ended since the digest before. 已看: not unseen.
    unseen = {topic: record for topic, record in unseen.items() if ended_at(record) <= slot}  # As of its time.
    older = sum(ended_at(record) <= since for record in unseen.values())
    ended.update(unseen)
    if asks is not None:
        # 停住了 on the 看板 is what 要你处理 counts (core/board_read.py Asks): each topic whose result on the board stopped,
        # however long ago it ended; a stop it does not count (seen long ago, before the board, no task card) is not one.
        ended = {topic: record for topic, record in ended.items()
                 if look.record_tone(record) != "stopped" or topic in asks.stopped}
        ended.update({topic: record for topic, record in asks.stopped.items() if topic not in busy})
    done = []
    for topic, record in sorted(ended.items(), key=lambda item: ended_at(item[1]), reverse=True):
        took = run_seconds(record.get("timings"), now=ended_at(record))
        status = record["status"]
        line, meta, card = "", [f"用时 {turn_words.wait_words(took)}" if took is not None else ""], ""
        recover = {}
        if status in ("failed", "cancelled", "interrupted"):  # 停住了 on the 看板: why, where it stopped, what next.
            failed = failure_view(record, now)
            line = board_read.ended_line(record, now)  # The same line 手上的事's 刚结束 row says.
            acts = (failed or {}).get("actions") or []
            recover = recovery(state, record, acts) if asks is not None and topic in asks.stopped else {}
            step = FAILURE_LABELS.get(acts[0], "") if acts else ""
            # Its own button says what next when it has one (``recover``); else where to click it.
            meta = [f"{clock_words(ended_at(record), now)} 停", f"下一步：在任务卡上点「{step}」" if step and not recover else ""]
            card = str(record.get("card_message_id") or "")  # The 看板's row opens its task card (its buttons are there).
        elif status == "done":
            line = board_read.ended_line(record, now)
        done.append({**row(topic, turn_words.STATES.get(status, status), f"用时 {took_text(took)}" if took is not None else "",
                           topic not in unseen), "status": status, "line": line, "meta": meta, "card": card,
                     # 停住了, 已停止 (the owner's own stop), 有结果 or 做完 (core/look.py; cards/board.py groups by it).
                     "tone": look.record_tone(record, seen=topic not in unseen), **({"recover": recover} if recover else {})})
    view = {"slot": slot, "since": since, "waiting": waiting, "stale": stale, "running": running_rows, "done": done,
            "older": older, "dismissable": bool(board and stale)}
    new, wanted = knowledge_view(state, since, slot), wanted_view(state, chat, since, slot)
    return {**view, **({"knowledge": new} if new else {}), **({"wanted": wanted} if wanted else {})}


def recovery(state, record, actions) -> dict:
    """What a stopped row's own button does (cards/board.py RECOVER_KIND): {action, label, job} of the first of
    RECOVER_ACTIONS that core/failure.py offers for ``record`` (``actions``: 检查并继续, 现在重试, or 重新投递结果 for a result
    that did not go out), {} when there is none (a pending automatic retry, a refusal that wants another model), the task
    went on already (``retried_by``) or its topic was switched since (app/binding.py stale_job_card: its card's click
    starts nothing then): such a row keeps 去任务卡."""
    from covey.app.binding import stale_job_card

    name = next((name for name in RECOVER_ACTIONS if name in (actions or ())), "")
    if not name or record.get("retried_by") or not isinstance(record.get("job_id"), int):
        return {}
    try:
        if stale_job_card(read_object(topic_file(Path(state), str(record.get("topic_id") or ""))), record):
            return {}
    except (OSError, TypeError, ValueError):
        return {}
    return {"action": name, "label": failure.label(record, name), "job": record["job_id"]}


KNOWLEDGE_SHOWN = 10  # Rows of 新记的知识; the rest is one line.
KNOWLEDGE_TEXT = 40  # Characters of an entry's text on its row.
KNOWLEDGE_OPS = {"add": "新增", "update": "改写", "drop": "作废"}


def knowledge_view(state, since, slot):
    """The 新记的知识 part (core/knowledge.py changes, COVEY_KNOWLEDGE=1): {"rows": [{op, id, where, text}],
    "more"} of the entries added, rewritten or dropped after ``since`` up to ``slot``, the newest first; {} when
    there are none (or the entries are off): the card then has no such part. It never makes a card be sent."""
    if not knowledge.enabled():
        return {}
    found = knowledge.changes(state, since, slot)
    rows = [{"op": KNOWLEDGE_OPS[change["op"]], "id": change["id"],
             "where": "通用" if change["scope"] == knowledge.OWNER else change["workspace"],
             "text": change["text"][:KNOWLEDGE_TEXT] + ("…" if len(change["text"]) > KNOWLEDGE_TEXT else "")}
            for change in found[:KNOWLEDGE_SHOWN]]
    return {"rows": rows, "more": len(found) - len(rows)} if rows else {}


WANTED_SHOWN = 5  # Rows of 我本来想找你的事; the rest is left out.


def wanted_view(state, chat, since, slot):
    """The 我本来想找你的事 part (core/patrol.py decisions, COVEY_PATROL=shadow): rows {what, why, would} of what the butler
    would have acted on in ``chat`` (verdict ``handle``) decided after ``since`` up to ``slot``, the newest first, an
    object once, at most WANTED_SHOWN; [] when there are none (or the patrol is off): the card then has no such part. It
    never makes a card be sent."""
    if not patrol.enabled():
        return []
    rows, seen = [], set()
    for row in reversed(patrol.rows(state, "decisions", since, slot)):
        if row.get("verdict") != "handle" or row.get("chat") != chat or row.get("key") in seen:
            continue
        seen.add(row.get("key"))
        would = patrol.ACTION_WORDS.get(row.get("action"), patrol.ACTION_WORDS["none"])
        name = str(projects.read_record(state, row["project"]).get("name") or "") if row.get("action") == "join" and row.get("project") else ""
        rows.append({"what": str(row.get("what") or ""), "why": str(row.get("why") or ""),
                     "would": f"{would}「{name}」" if name else would})
    return rows[:WANTED_SHOWN]


def cleared(view, topics, at=None):
    """``view`` once 这些都不用回答了 took ``topics`` off (as of ``at``): their stale rows gone, their labels under
    ``cleared``, the rows themselves under ``cleared_rows`` and ``{topic: at}`` under ``cleared_taken`` (what 撤销 puts
    back: ``undone``); None when none of its stale rows is theirs (the card says so already)."""
    taken = [row for row in view.get("stale") or [] if row.get("topic") in topics]
    if not taken:
        return None
    out = {**view, "stale": [row for row in view.get("stale") or [] if row not in taken],
           "cleared": [*(view.get("cleared") or []), *(row.get("label") or "" for row in taken)]}
    if at is not None:
        out["cleared_rows"] = [*(view.get("cleared_rows") or []), *taken]
        out["cleared_taken"] = {**(view.get("cleared_taken") or {}), **{row["topic"]: at for row in taken}}
    return out


def undone(view, back, found):
    """``view`` once 撤销 put the topics ``back`` (a list) on the board: their lines gone from ``cleared``, and the ones
    still waiting (``found``: their topics, from core/board_read.py waits) among the stale rows again; one answered or
    retired since is not listed. None when the card has none of them under ``cleared_taken``."""
    taken = dict(view.get("cleared_taken") or {})
    if not any(topic in taken for topic in back):
        return None
    rows = [row for row in view.get("cleared_rows") or [] if row.get("topic") in back]
    labels = list(view.get("cleared") or [])
    for row in rows:
        if row.get("label") in labels:
            labels.remove(row.get("label"))
    out = {**view, "cleared": labels, "stale": [*(view.get("stale") or []), *(row for row in rows if row.get("topic") in found)],
           "cleared_rows": [row for row in view.get("cleared_rows") or [] if row.get("topic") not in back],
           "cleared_taken": {topic: at for topic, at in taken.items() if topic not in back}}
    for key in ("cleared", "cleared_rows", "cleared_taken"):
        if not out[key]:
            out.pop(key)
    return out


def taken_off(view, topics, at=None):
    """A 看板's ``view`` once ``topics`` were taken off (这些都不用回答了, or a stopped topic's 不管了): their stale rows
    under ``cleared`` and their blocks gone; None when none of them is on it."""
    on = any(row.get("topic") in topics for key in ("stale", "waiting", "running", "done") for row in view.get(key) or ())
    if not on:
        return None
    view = cleared(view, topics, at) or dict(view)
    return {**view, **{key: [row for row in view.get(key) or () if row.get("topic") not in topics]
                       for key in ("waiting", "running", "done")}}


class Digest:
    """``chat``: the chat it is sent to, '' the owner's private chat (Access.owner_chat); a personal group has one of
    its own (app/group_boards.py), its record its own (app/pins.py record_path) and
    ``name`` its thread's."""
    origin = ORIGIN  # What its card's 这些都不用回答了 says it is from (Overview.handed's key).

    def __init__(self, runtime, messenger, voice, *, chat="", name="digest") -> None:
        self.runtime, self.messenger, self.voice = runtime, messenger, voice
        self.fixed, self.name = chat, name
        self.others = {}  # chat_id -> a personal group's Digest (app/group_boards.py): its 看板's clicks are its own.
        self.link = lambda ctx, chat, text, cards=None: linkify(text, ctx.state_dir, chat, profile=ctx.profile, cards=cards)
        self.menu = MenuPanel(self, BOARD_KIND, BOARD_FOLDER, BOARD_KIND)
        self.candidates = None  # 你反复说的 (app/memory_candidates.py Candidates): the private chat's digest only (app/unified.py).
        self.memory_tidy = None  # 整理记忆 (app/memory_tidy.py MemoryTidy, COVEY_MEMORY_LEARN=1): the private chat's digest only.
        self.harvest = None  # What Codex and Claude Code noted on their own (app/memory_harvest.py Harvest), the same.
        # The Bridge's Topics (app/unified.py, app/group_boards.py): their apps take a stopped row's 检查并继续 (``recover``);
        # None: the 看板's stopped rows keep 去任务卡.
        self.topics = None

    def menu_items(self):
        """The bot menu's 看板, always (app/unified.py menu)."""
        return {BOARD_KEY: self.board}

    def menu_folds(self):
        """A second 看板 on its card, the newest in the chat (app/bot_menu.py)."""
        return {BOARD_KEY: self.fold_board}

    def board_view(self, ctx, chat, now=None):
        """看板's view now (``asked``): ``chat``'s digest.json only read. Feishu calls (the T links), so outside any
        lock."""
        now = time.time() if now is None else now
        last = read_object(record_path(ctx.state_dir, chat, RECORD)).get("last_slot")
        view = collect(ctx.state_dir, chat, now, board_since(self.times(), now, last), now, board=dismissable(), asked=True)
        view.pop("wanted", None)  # 我本来想找你的事 is the 早晚汇总's, not the 看板's.
        # Each block of the 看板 opens its topic (cards/board.py): the topic's applink, read outside any lock.
        # A 等你 row's opens the card it is acted on (core/board_read.py waits): the question card, the launch card.
        # The old ones' labels link through their ``url`` (cards/overview.py stale_line), plain for the band to lead with.
        # All of them read at once (``urls``): one by one, eight topics whose cards were not kept took four seconds.
        self.link_rows(ctx, view)
        if self.topics is None:  # Nothing here to take a 检查并继续 on: the row's task card does.
            for row in view["done"]:
                row.pop("recover", None)
        # ``at``: when it was read (a redraw from this view later says so, cards/board.py empty_state); ``first_use``: it
        # lists nothing and the chat never had a topic (还没有话题), told from a clear board.
        first = not any(view[key] for key in ("waiting", "stale", "running", "done")) and not board_read.has_topics(ctx.state_dir, chat)
        return {**view, "asked": True, "stamp": clock_words(now, now), "at": now, "can_dismiss": dismissable(),
                **({"first_use": True} if first else {}),
                "done_since": clock_words(view["since"], now) if view.get("since") else "",
                **self.where(chat), **self.tidy(ctx, chat), **web_view(),
                **self.projects_view(ctx, chat, view), **self.revisit_view(ctx, chat, now)}

    def link_rows(self, ctx, view):
        """Each row of ``view``'s 等你, 在做, 做完 and old questions with the link that opens it (``url``): a 等我's the card it
        is acted on (core/board_read.py waits), a stopped one's and a running one's its task card (``card``), any other its
        topic at its newest card; all read at once (``urls``: one by one, eight topics whose cards were not kept took four
        seconds). A task waiting for 开始 says so on its button (``act``). Feishu reads: outside any lock."""
        rows = [row for key in ("waiting", "running", "done", "stale") for row in view.get(key) or ()]
        urls = self.urls(ctx, [(row.get("topic") or "", row.get("card") or "") for row in rows])
        for row in rows:
            row["url"] = urls.get((row.get("topic") or "", row.get("card") or ""), "")
            if row.get("kind") == "start":
                row["act"] = turn_words.START_ACT

    def revisit_view(self, ctx, chat, now):
        """到点回来看's rows on the 看板 (app/revisits.py board_rows), each with its topic's link; {} without any (the switch
        off: the view is as before)."""
        rows = revisits.board_rows(ctx.state_dir, chat, lambda at: clock_words(at, now))
        if not rows:
            return {}
        urls = self.urls(ctx, [(row["topic"], "") for row in rows])
        for row in rows:
            row["url"] = urls.get((row["topic"], ""), "")
        return {"revisits": rows}

    def urls(self, ctx, pairs) -> dict:
        """{(topic, card): ``url``} for each pair with a topic, read in parallel (a Feishu read each when the link is
        not kept, app/topic_links.py) within topic_links.BUDGET seconds; one not read by then has ''. Outside any lock."""
        wanted = list(dict.fromkeys((topic, card) for topic, card in pairs if topic))
        if len(wanted) < 2:
            return {pair: self.url(ctx, *pair) for pair in wanted}
        pool = concurrent_futures.ThreadPoolExecutor(max_workers=min(LINK_READS, len(wanted)),
                                                     thread_name_prefix="board-link")
        try:
            reads = {pool.submit(self.url, ctx, *pair): pair for pair in wanted}
            done, _ = concurrent_futures.wait(reads, timeout=topic_links.BUDGET)
            return {reads[read]: read.result() for read in done if not read.exception()}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

    def url(self, ctx, topic, card="") -> str:
        try:
            return link_for(ctx.state_dir, topic, card=card, profile=getattr(ctx, "profile", None))
        except Exception:  # noqa: BLE001 - a block that opens nothing, as a topic without a link
            return ""

    def projects_view(self, ctx, chat, view):
        """The 看板's 专项 part (cards/board.py): each live project of ``chat`` with how its topics stand in ``view``,
        and how many proposal cards wait (整理专项 on); nothing in a group's 看板 or with 专项 off."""
        if self.where(chat) or not projects.enabled():
            return {}
        rows = {"waiting": {row.get("topic") for row in view.get("waiting") or ()},
                "running": {row.get("topic") for row in view.get("running") or () if not row.get("stuck")},
                "stuck": {row.get("topic") for row in view.get("running") or () if row.get("stuck")},
                "stopped": {row.get("topic") for row in view.get("done") or () if row.get("tone") == "stopped"}}
        found = []
        for record in projects.records(ctx.state_dir, chat):
            if record.get("state") not in (projects.ACTIVE, projects.PAUSED):
                continue
            topics = [topic for topic in (record.get("lead_topic_id"), *(record.get("threads") or ())) if topic]
            # Its own state when it is not at work (core/projects.py pause_tone): 停住了 and why for a guard's pause (继续 on
            # its block), 已停止 for the owner's stop, 收起 for one folded away.
            paused = projects.pause_tone(record)
            found.append({"id": str(record.get("id") or ""), "name": record.get("name") or "",
                          "goal": record.get("goal") or "", "topics": topics,
                          **{key: len(rows[key] & set(topics)) for key in ("waiting", "stopped", "stuck", "running")},
                          "lead": record.get("lead_topic_id") or "",
                          **({"folded": True} if paused == "idle" else
                             {"halted": projects.stop_reason(record) or True} if paused == "stopped" else
                             {"cancelled": True} if paused == "cancelled" else {}),
                          "_at": float(record.get("updated_at") or 0)})
        # What asks for him first (等你, the project's own 停住了, its topics' 停住了 and 可能卡住), then the ones at work, then
        # the rest, each the most recently changed first; folded away last (cards/board.py puts those and what is past its
        # SHOWN blocks in one fold).
        found.sort(key=lambda entry: (bool(entry.get("folded")), not entry["waiting"], not entry.get("halted"),
                                      not entry["stopped"], not entry["stuck"], not entry["running"], -entry["_at"]))
        for entry in found:
            entry.pop("_at")
        # The proposals waiting for him, each with its topics, to decide right on the 看板 (under 等你), not by scrolling up
        # the chat.
        pending = self.pending(ctx, chat)
        urls = self.urls(ctx, [(entry["lead"], "") for entry in found]
                         + [(row["topic"], "") for entry in pending for row in entry["rows"]])
        for entry in found:
            entry["url"] = urls.get((entry.pop("lead"), ""), "")
        for entry in pending:
            for row in entry["rows"]:
                row["url"] = urls.get((row["topic"], ""), "")
        return {"projects": found, "proposals": len(pending), "pending": pending}

    def pending(self, ctx, chat) -> list:
        """The proposals of 整理专项 waiting for the owner's 好 (core/board_read.py waiting_proposals: 要你处理 counts them, as
        projects_list and 整理专项's 还在等你定 list them), each {id, name, goal, why, rows: its topics {topic, label, title}};
        [] in a group (整理专项 sorts the private chat's topics) and with 整理专项 off."""
        if self.where(chat):
            return []
        found = []
        for record in board_read.waiting_proposals(ctx.state_dir).values():
            rows = []
            for topic in dict.fromkeys(record.get("topics") or ()):
                label, title = label_title(ctx.state_dir, topic)
                rows.append({"topic": topic, "label": label, "title": title})
            found.append({"id": record["id"], "name": record.get("name") or "", "goal": record.get("goal") or "",
                          "why": record.get("why") or "", "rows": rows})
        return found

    def asks_view(self, ctx, chat):
        """What 要你处理 counts beyond the topics, for the 早晚汇总 (the 看板 has them in its 专项 part): the projects a guard
        paused (``projects``, each {id, name, halted, url}: cards/board.py halted) and the proposals waiting (``pending``,
        each topic with its link); {} for none. A project here names no topics: the 早晚汇总 lists its topics as any others."""
        halted = [] if self.where(chat) else [
            {"id": key, "name": record.get("name") or "", "goal": "", "topics": [], "lead": record.get("lead_topic_id") or "",
             "halted": projects.stop_reason(record) or True}
            for key, record in board_read.halted_projects(ctx.state_dir, chat).items()]
        pending = self.pending(ctx, chat)
        urls = self.urls(ctx, [(entry["lead"], "") for entry in halted if entry["lead"]]
                         + [(row["topic"], "") for entry in pending for row in entry["rows"]])
        for entry in halted:
            entry["url"] = urls.get((entry.pop("lead"), ""), "")
        for entry in pending:
            for row in entry["rows"]:
                row["url"] = urls.get((row["topic"], ""), "")
        return {**({"projects": halted} if halted else {}), **({"pending": pending} if pending else {})}

    def tidy(self, ctx, chat):
        """The 专项 part (cards/project_proposal.py board_rows): with 整理专项 on, in the owner's private chat (a group's
        看板 has none: 整理专项 sorts the private chat's topics)."""
        if not project_proposals.enabled() or self.where(chat):
            return {}
        return {"tidy": {}}

    def where(self, chat):
        """The card's word for ``chat`` when it is a group with a butler (cards/digest.py), else nothing."""
        return {"where": "群"} if chat in getattr(self.runtime.access, "agent_groups", ()) else {}

    def path(self, ctx):
        return record_path(ctx.state_dir, self.fixed, RECORD)

    def board(self, ctx, chat_id, source, shown=None):
        """The bot menu's 看板: a new card in ``chat_id`` (the owner's private chat) for the click ``source``."""
        self.menu.open(ctx, chat_id, source, lambda token, record: board_card(record["digest"]), BOARD_FAILED,
                       fields=lambda: {"digest": self.board_view(ctx, chat_id)}, shown=shown)
        self.runtime.log(f"digest board sent event={source[-10:]}")

    def fold_board(self, ctx, chat_id, source, message_id):
        """看板 again on its card, the newest in the chat: folded, or unfolded with a fresh view (MenuPanel toggle)."""
        return self.menu.toggle(ctx, chat_id, source, message_id, lambda token, record: board_card(record["digest"]),
                                lambda token, record: folded_board(),
                                fields=lambda: {"digest": self.board_view(ctx, chat_id)})

    @staticmethod
    def matches(raw):
        return isinstance(raw, dict) and (raw.get("kind") in BOARD_KINDS or raw.get("kind") in (REMEMBER_KIND, MEMORY_KIND))

    def claim(self, ctx, event, raw, owner):
        """刷新, 记为看过 or a project's 继续 on a 看板 card, or 去看板 under an answered question (cards/board.py KINDS;
        app/unified.py PANELS), else None: the owner's only; the card redrawn from a fresh view once the click is
        acknowledged, or the 看板 sent."""
        if not self.matches(raw):
            return None
        kind = raw["kind"]
        other = self.others.get(str(event.get("chat_id") or ""))
        if other is not None:
            return other.claim(ctx, event, raw, owner)
        if not owner:
            return "owner_only"
        if kind == REMEMBER_KIND:
            return self.remember(ctx, event, raw)
        if kind == MEMORY_KIND:
            return self.memory_click(ctx, event, raw)
        message = str(event.get("message_id") or "")
        if kind == OPEN_KIND:
            # 去看板 under an answered question: the bot menu's 看板, a new card for this click (its event id keys it).
            chat, source = str(event.get("chat_id") or ""), str(event.get("event_id") or "")
            if not source or not chat or chat != (self.fixed or self.runtime.access.notify_chat()):
                return "board_open_ignored"
            after_ack(lambda: self.board(ctx, chat, source))
            return "board_open"
        if kind == REVISIT_KIND:
            # 取消 on a row of 到点回来看: that revisit (its ``set_at``: a newer one the topic asked for since stays).
            topic, set_at = raw.get("topic"), raw.get("set_at")
            if not isinstance(topic, str) or not topic or isinstance(set_at, bool) or not isinstance(set_at, (int, float)):
                return "board_revisit_ignored"
            gone = revisits.records.cancel(ctx.state_dir, topic, set_at)
            self.runtime.log(f"revisit cancelled topic={topic[-8:]} gone={gone}")
        elif kind == RECOVER_KIND:
            # 检查并继续 on a stopped row (cards/board.py ``recover``): its task card's click, done after the acknowledgement
            # in the topic's lane (its value names the topic), then the card redrawn in place saying what came of it.
            topic, job, action = raw.get("topic_id"), raw.get("job_id"), raw.get("action")
            if not (isinstance(topic, str) and TOPIC_ID.fullmatch(topic) and isinstance(job, int) and not isinstance(job, bool)
                    and action in RECOVER_ACTIONS):
                return "board_recover_ignored"
            source = str(event.get("event_id") or message)
            after_ack(lambda: self.recover(ctx, topic, job, action, source, message))
            return "board_recover"
        elif kind == PROJECT_GO_KIND:
            # 继续 on the block of a project a guard paused: what the pause card's 继续 does (app/project_loop.py resume).
            chat, project = self.fixed or self.runtime.access.notify_chat(), raw.get("project")
            if not chat or not isinstance(project, str) or not projects.valid_id(project):
                return "board_project_go_ignored"
            outcome = project_loop.resume(ctx.state_dir, project, chat)
            self.runtime.log(f"digest board project go project={project[:8]} outcome={outcome}")
        elif kind == SEEN_KIND:
            # One row's 记为看过 names its ``topic``; 全部记为看过 names them all (``topics``, cards/board.py SEEN_MAX).
            chat = self.fixed or self.runtime.access.notify_chat()
            topics = raw.get("topics") if isinstance(raw.get("topics"), list) else [raw.get("topic")]
            topics = [topic for topic in topics[:SEEN_MAX] if isinstance(topic, str) and topic]
            if not topics or not chat:
                return "board_seen_ignored"
            now = time.time()
            for topic in topics:
                fresh = board_read.mark_seen(ctx.state_dir, chat, topic, now)
                self.runtime.log(f"digest board seen topic={topic[-8:]} fresh={fresh}")
        if message:
            after_ack(lambda: self.board_refresh(ctx, message))
        return {SEEN_KIND: "board_seen", REVISIT_KIND: "board_revisit_cancel",
                PROJECT_GO_KIND: "board_project_go"}.get(kind, "board_refresh")

    def recover(self, ctx, topic, job_id, action, source, message):
        """A stopped row's 检查并继续 (``claim``), after the acknowledgement: done (``recovered``), then the 看板 card ``message``
        redrawn from a fresh view, with what came of it under the band."""
        chat = self.fixed or self.runtime.access.notify_chat()
        notice = self.recovered(ctx, chat, topic, job_id, action, source) if chat else ""
        self.runtime.log(f"digest board recover topic={topic[-8:]} job={job_id} action={action} said={notice[:40]!r}")
        if message:
            self.board_refresh(ctx, message, notice=notice)

    def recovered(self, ctx, chat, topic, job_id, action, source) -> str:
        """The task card's 检查并继续 of task #``job_id`` of ``topic`` (``action``: core/failure.py continue or retry; 重新投递结果
        for a result that did not go out), as the web page's ``recover`` does it (app/web_ops.py): app/task_controls.py
        retry_topic in the context an automatic retry runs in (app/auto_retry.py retry_context), ``source`` (the click's
        event id) the new turn's message id. What the 看板 then says of it: ↪ 已接着做 · 任务 #N, or why nothing was done
        (it went on already: a second click or a repeated event starts nothing, the record says ``retried_by``; the topic
        has a task at work; it was switched since; the record takes it on no more). Never raises."""
        state = Path(ctx.state_dir)
        label = number_of(state, topic) or "话题"
        try:
            record = next((each for each in topic_job_records(state, topic, chat_id=chat) if each.get("job_id") == job_id), None)
            if record is None:
                return f"⚠️ {label} 找不到任务 #{job_id}，没有接着做"
            if record.get("retried_by"):
                moved = find_job_record(state, str(record["retried_by"])) or {}
                return f"↪ {label} 已经接着做了 · 任务 #{moved.get('job_id') or '?'}，没有再开一次"
            app = getattr(self.topics, "apps", {}).get(record.get("backend")) if self.topics is not None else None
            if app is None:
                return f"⚠️ {label} 这个任务的 Harness 现在不可用，去任务卡上看"
            offered = (failure_view(record) or {}).get("actions") or ()
            if action not in offered or not recovery(state, record, (action,)):  # Its record takes it on no more.
                return f"⚠️ {label} 现在不能在这里接着做了，去任务卡上看"
            from covey.app import auto_retry

            target = auto_retry.retry_context(app, record, auto_retry.record_topic(app, record))
            if target.topic_id != topic:
                return f"⚠️ {label} 现在读不到，没有接着做"
            said = app.controls.retry_topic(target, chat, source, job_id=job_id)
            after = find_job_record(state, record["key"]) or {}
            if after.get("retried_by") and after.get("retried_by") != record.get("retried_by"):
                moved = find_job_record(state, str(after["retried_by"])) or {}
                return f"↪ {label} 已接着做 · 任务 #{moved.get('job_id') or '?'}"
            if any(after.get(name) is True and record.get(name) is not True for name in ("delivery_ok", "question_delivery_ok")):
                return f"↪ {label} 的结果已重新发出"
            return f"⚠️ {label} {said}" if said else f"⚠️ {label} 没有接着做，去任务卡上看"
        except Exception as exc:  # noqa: BLE001 - the card says so; the task card's button is still there
            self.runtime.log(f"digest board recover failed topic={topic[-8:]} job={job_id}: {type(exc).__name__}")
            return f"⚠️ {label} 没能接着做（{type(exc).__name__}），去任务卡上点「{failure.LABELS.get(action, failure.LABELS[failure.CONTINUE])}」"

    def remember(self, ctx, event, raw):
        """「记下」 or 「不用」 on one of 你反复说的 (the owner's): decided and the card redrawn once acknowledged."""
        candidate, op, message = raw.get("id"), raw.get("op"), str(event.get("message_id") or "")
        if not (isinstance(candidate, str) and re.fullmatch(r"c[0-9a-f]{8}", candidate)) or op not in ("save", "drop") \
                or not message:
            return "digest_remember_ignored"
        after_ack(lambda: self.remembered(ctx, message, candidate, op))
        return "digest_remember"

    def remembered(self, ctx, message_id, candidate, op):
        """After a click on 你反复说的: the candidate decided (app/memory_candidates.py ``decide``: the principle written, or it
        set aside), then the card ``message_id`` redrawn from its saved view with every candidate as it stands now (the view
        saved once Feishu took it). A card whose view is no longer kept is left as it is."""
        row = memory_candidates.decide(ctx.state_dir, candidate, op)
        self.runtime.log(f"digest candidate {op} id={candidate} state={(row or {}).get('state', 'gone')}")
        path = self.path(ctx)
        with resource_lock("digest", str(path)):
            sent = read_object(path).get("sent")
        entry = sent.get(message_id) if isinstance(sent, dict) else None
        view = entry.get("view") if isinstance(entry, dict) else None
        if not isinstance(view, dict) or not view.get("remember"):
            self.runtime.log(f"digest card not redrawn message={message_id[-8:]}: no view of its candidates kept")
            return
        stored = {item["id"]: item for item in memory_candidates.load(ctx.state_dir)["rows"]}
        rows = []
        for shown in view["remember"]:
            fresh = stored.get(shown.get("id"))
            if fresh is not None:
                shown = {**shown, "state": fresh.get("state") or memory_candidates.OPEN, "error": str(fresh.get("error") or "")}
            rows.append(shown)
        view = {**view, "remember": rows}
        if not self.messenger.patch_card(ctx.profile, message_id, digest_card(view)):
            self.runtime.log(f"digest card redraw failed message={message_id[-8:]}")
            return
        with resource_lock("digest", str(path)):
            record = read_object(path)
            sent = record.get("sent") if isinstance(record.get("sent"), dict) else {}
            if isinstance(sent.get(message_id), dict):
                write_json(path, {**record, "sent": {**sent, message_id: {**sent[message_id], "view": view}}},
                           ensure_ascii=False)

    def memory_click(self, ctx, event, raw):
        """确认长期, 不对 or 撤销 on the evening digest's 整理记忆 (the owner's): decided (app/memory_tidy.py ``decide``) and the
        card redrawn once acknowledged."""
        run, op, message = raw.get("run"), raw.get("op"), str(event.get("message_id") or "")
        if (self.memory_tidy is None or not (isinstance(run, str) and re.fullmatch(r"t[0-9a-f]{8}", run))
                or op not in ("confirm", "wrong", "undo") or not message):
            return "digest_memory_ignored"
        project, entry = str(raw.get("project") or ""), str(raw.get("entry") or "")
        after_ack(lambda: self.memory_decided(ctx, message, run, op, project, entry))
        return "digest_memory"

    def memory_decided(self, ctx, message_id, run_id, op, project, entry):
        """After a click on 整理记忆: the run decided, then the card ``message_id`` redrawn from its saved view with the run as it
        stands now. A card whose view is no longer kept is left as it is."""
        from covey.app.memory_tidy import view_of
        run = self.memory_tidy.decide(ctx, run_id, op, project=project, entry=entry, message_id=message_id)
        if run is None:
            self.runtime.log(f"digest memory {op} run={run_id}: no such run")
            return
        path = self.path(ctx)
        with resource_lock("digest", str(path)):
            sent = read_object(path).get("sent")
        entry_view = sent.get(message_id) if isinstance(sent, dict) else None
        view = entry_view.get("view") if isinstance(entry_view, dict) else None
        if not isinstance(view, dict) or not view.get("memory_tidy"):
            self.runtime.log(f"digest card not redrawn message={message_id[-8:]}: no view of its 整理记忆 kept")
            return
        view = {**view, "memory_tidy": view_of(run) or view["memory_tidy"]}
        if not self.messenger.patch_card(ctx.profile, message_id, digest_card(view)):
            self.runtime.log(f"digest card redraw failed message={message_id[-8:]}")
            return
        with resource_lock("digest", str(path)):
            record = read_object(path)
            sent = record.get("sent") if isinstance(record.get("sent"), dict) else {}
            if isinstance(sent.get(message_id), dict):
                write_json(path, {**record, "sent": {**sent, message_id: {**sent[message_id], "view": view}}},
                           ensure_ascii=False)

    def daily(self, ctx, chat, slot, now) -> dict:
        """The evening digest's own parts (the private chat's, the day's last time): 本周找你, 今天代答 and 你反复说的; each
        one that cannot be read is left out (a log line)."""
        found = {}
        try:
            found["reached"] = weekly_usage.reached(ctx.state_dir, now, log=self.runtime.log)
        except Exception as exc:  # noqa: BLE001 - the digest goes out without it
            self.runtime.log(f"digest reached unreadable: {type(exc).__name__}")
        try:
            proxied = proxy_view(ctx.state_dir, now)
        except Exception as exc:  # noqa: BLE001
            self.runtime.log(f"digest proxy count unreadable: {type(exc).__name__}")
            proxied = {}
        if proxied:
            found["proxy"] = proxied
        if self.candidates is not None and memory.enabled():
            try:
                found_rows = self.candidates.offer(ctx, chat, slot)
                if self.harvest is not None and memory.learning() and self.harvest.offer(ctx, slot):  # Never raises.
                    found_rows = memory_candidates.rows_of(ctx.state_dir, slot)
                rows = [remember_row(row) for row in found_rows]
                for row in rows:
                    row["sources"] = self.link(ctx, chat, "、".join(row["labels"])) if row["labels"] else ""
            except Exception as exc:  # noqa: BLE001 - the digest goes out without them
                self.runtime.log(f"digest candidates unreadable: {type(exc).__name__}")
                rows = []
            if rows:
                found["remember"] = rows
        if self.memory_tidy is not None and memory.learning():
            tidied = self.memory_tidy.view(ctx, chat, slot, now)  # 整理记忆: never raises.
            if tidied:
                found["memory_tidy"] = tidied
        return found

    def board_refresh(self, ctx, message_id, notice=""):
        """A 看板 card redrawn from a fresh view, after a proposal on it was decided (app/project_tidy.py ``handed``),
        its 刷新 or 记为看过 was clicked (``claim``) or a stopped row's 检查并继续 was done (``recover``: ``notice``, what came
        of it, under the band of this redraw alone). Whether ``message_id`` is a 看板 card."""
        chat = self.fixed or self.runtime.access.notify_chat()
        folder = self.menu.directory(ctx)
        try:
            paths = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)[-BOARD_SCANNED:]
        except OSError:
            return False
        for path in reversed(paths):
            if read_object(path).get("message_id") != message_id or not chat:
                continue
            view = self.board_view(ctx, chat)  # Feishu reads for the links: outside the lock.
            with self.menu.lock(path):
                record = read_object(path)
                if record.get("message_id") != message_id or not isinstance((record.get("view") or {}).get("revision"), int):
                    return True
                changed = {**record, "digest": view, "view": {**record["view"], "revision": record["view"]["revision"] + 1}}
                confirmed = settle(ctx, path, record, changed, board_card(view, notice=notice), self.messenger, BOARD_KIND)
            self.runtime.log(f"digest board refreshed message={message_id[-8:]} confirmed={bool(confirmed)}")
            return True
        return False

    def board_dismissed(self, ctx, message_id, topics, at=None):
        """``dismissed`` on a 看板 card: its record's view redrawn with those topics taken off; whether it was one."""
        folder = self.menu.directory(ctx)
        try:
            paths = sorted(folder.glob("*.json"), key=lambda path: path.stat().st_mtime)[-BOARD_SCANNED:]
        except OSError:
            return False
        for path in reversed(paths):
            if read_object(path).get("message_id") != message_id:
                continue
            with self.menu.lock(path):
                record = read_object(path)
                view = taken_off(record.get("digest"), set(topics), at) if isinstance(record.get("digest"), dict) else None
                if view is None or record.get("message_id") != message_id or not isinstance(
                        (record.get("view") or {}).get("revision"), int):
                    return True
                changed = {**record, "digest": view, "view": {**record["view"], "revision": record["view"]["revision"] + 1}}
                confirmed = settle(ctx, path, record, changed, board_card(view, time.time()), self.messenger, BOARD_KIND)
            self.runtime.log(f"digest board redrawn message={message_id[-8:]} confirmed={confirmed}")
            return True
        return False

    def times(self):
        return configured(self.runtime.log)

    def threads(self):
        """Its worker, only when COVEY_DIGEST_TIMES lists a time (app/unified.py worker_targets)."""
        times = self.times()
        return ((self.name, lambda ctx: every(self.runtime, TICK, self.tick, args=(ctx, times), isolate="digest")),
                ) if times else ()

    def save(self, ctx, **fields):
        path = self.path(ctx)
        with resource_lock("digest", str(path)):
            saved = read_object(path)
            write_json(path, {**saved, "schema_version": 1, **fields}, ensure_ascii=False)

    def tick(self, ctx, times, now=None):
        now = time.time() if now is None else now
        record = read_object(self.path(ctx))
        last = record.get("last_slot")
        slot = due(times, now, last)
        if slot is None:
            return
        pending = record.get("pending") if isinstance(record.get("pending"), dict) else {}
        if pending.get("slot") == slot:
            if now - float(pending.get("tried_at") or 0) >= RETRY:
                self.send(ctx, slot, pending, now)
            return
        chat = self.fixed or self.runtime.access.notify_chat()
        if not chat:
            return  # No private chat with the owner known yet: tried again until the time is CATCH_UP old.
        # 要你处理 as the 看板 and 手上的事 count it (``asked``: what stopped however long ago, what may be stuck, the projects a
        # guard paused, the proposals waiting); 整理专项's button is the 看板's alone.
        view = {**collect(ctx.state_dir, chat, slot, since_of(times, slot, last), now, board=dismissable(), asked=True),
                **self.where(chat), **web_view()}
        view.update(self.asks_view(ctx, chat))
        if not self.fixed:
            view.update(review_view(ctx.state_dir, self.runtime.log))
        if not self.fixed and last_of_day(times, slot):
            view.update(self.daily(ctx, chat, slot, now))
        waits = (any(row.get("state") == memory_candidates.OPEN for row in view.get("remember") or ())
                 or bool(view.get("memory_tidy")))  # 整理记忆 put something away or wrote a rule: it says so, with 撤销.
        if not (view["waiting"] or view["stale"] or view["running"] or view["done"] or view.get("pending")
                or view.get("projects") or waits):
            self.save(ctx, last_slot=slot, pending=None)
            self.runtime.log("digest not sent: nothing to list")
            return
        for row in view["done"]:
            row.pop("recover", None)  # The 看板's button: this card is a record of its time.
        self.link_rows(ctx, view)
        named = f"{self.fixed}-{int(slot)}" if self.fixed else str(int(slot))  # A group's send is its own.
        pending = {"slot": slot, "chat_id": chat, "key": self.voice.safe_key(self.voice.key("digest", named)),
                   "view": view, "card": digest_card(view), "text": digest_text(view), "tries": 0, "tried_at": 0}
        self.save(ctx, pending=pending)
        self.send(ctx, slot, pending, now)

    def send(self, ctx, slot, pending, now):
        pending = {**pending, "tries": int(pending.get("tries") or 0) + 1, "tried_at": now}
        self.save(ctx, pending=pending)  # The try counts even if the process ends during it.
        cards = []
        if self.messenger.send_message(ctx.profile, pending["chat_id"], pending["text"], pending["key"],
                                       voice=self.voice, card=pending["card"], on_card=cards.append):
            message = cards[0] if cards else ""
            self.save(ctx, last_slot=slot, sent_at=time.time(), message_id=message, pending=None,
                      sent=self.kept(ctx, message, slot, pending.get("view")))
            self.runtime.log(f"digest sent slot={time.strftime('%H:%M', time.localtime(slot))} "
                             f"card={'yes' if cards else 'no'}")
        elif pending["tries"] >= SEND_TRIES:
            self.save(ctx, last_slot=slot, pending=None)
            self.runtime.log(f"digest not sent after {pending['tries']} tries; given up")
        else:
            self.runtime.log(f"digest not sent try={pending['tries']}; tried again in {RETRY} s")

    def kept(self, ctx, message, slot, view):
        """The record's ``sent`` with this card's view, the last SENT_KEPT cards' (no view: an older pending's)."""
        sent = read_object(self.path(ctx)).get("sent")
        sent = {key: value for key, value in sent.items() if isinstance(value, dict)} if isinstance(sent, dict) else {}
        if message and isinstance(view, dict):
            sent[message] = {"slot": slot, "view": view}
        return dict(sorted(sent.items(), key=lambda item: float(item[1].get("slot") or 0))[-SENT_KEPT:])

    def dismissed(self, ctx, message_id, topics, at=None):
        """After a click on this card's 这些都不用回答了 (Overview.handed, once acknowledged): the card redrawn
        from its saved view with that line grey, 已撤下 N 个, no button; the view saved once Feishu took it. A card
        without a saved view (sent before they were, or no longer kept) is left as it is."""
        path = self.path(ctx)
        with resource_lock("digest", str(path)):
            sent = read_object(path).get("sent")
        entry = sent.get(message_id) if isinstance(sent, dict) else None
        view = entry.get("view") if isinstance(entry, dict) else None
        if entry is None and self.board_dismissed(ctx, message_id, topics, at):
            return
        view = cleared(view, set(topics), at) if isinstance(view, dict) else None
        if view is None:
            self.runtime.log(f"digest card not redrawn message={message_id[-8:]}: no view of those topics kept")
            return
        if not self.messenger.patch_card(ctx.profile, message_id, digest_card(view)):
            self.runtime.log(f"digest card redraw failed message={message_id[-8:]}")
            return
        with resource_lock("digest", str(path)):
            record = read_object(path)
            sent = record.get("sent") if isinstance(record.get("sent"), dict) else {}
            if isinstance(sent.get(message_id), dict):
                write_json(path, {**record, "sent": {**sent, message_id: {**sent[message_id], "view": view}}},
                           ensure_ascii=False)
        self.runtime.log(f"digest card redrawn message={message_id[-8:]} cleared={len(view['cleared'])}")

    def undismissed(self, ctx, message_id, back):
        """After a click on 撤销 under this card's 已撤下 line (Overview.unhanded, once acknowledged; ``back``: the
        topics put back): a 看板 card is redrawn from a fresh view, which lists what waits now; the timed card from its
        saved view with the topics that still wait among the old questions again (one answered or retired since is
        not listed, and the line goes), and that view saved once Feishu took it."""
        if self.board_refresh(ctx, message_id):
            return
        path = self.path(ctx)
        with resource_lock("digest", str(path)):
            sent = read_object(path).get("sent")
        entry = sent.get(message_id) if isinstance(sent, dict) else None
        view = entry.get("view") if isinstance(entry, dict) else None
        chat = self.fixed or self.runtime.access.notify_chat()
        if not isinstance(view, dict) or not chat:
            self.runtime.log(f"digest card not redrawn message={message_id[-8:]}: no view kept")
            return
        now = time.time()
        waiting = {wait.topic for wait in board_read.waits(ctx.state_dir, chat, now, off=taken_off_now(ctx.state_dir, chat, now)).all}
        view = undone(view, set(back), waiting)
        if view is None:
            self.runtime.log(f"digest card not redrawn message={message_id[-8:]}: none of those topics on it")
            return
        if not self.messenger.patch_card(ctx.profile, message_id, digest_card(view)):
            self.runtime.log(f"digest card redraw failed message={message_id[-8:]}")
            return
        with resource_lock("digest", str(path)):
            record = read_object(path)
            sent = record.get("sent") if isinstance(record.get("sent"), dict) else {}
            if isinstance(sent.get(message_id), dict):
                write_json(path, {**record, "sent": {**sent, message_id: {**sent[message_id], "view": view}}},
                           ensure_ascii=False)
        self.runtime.log(f"digest card redrawn message={message_id[-8:]} put back={len(back)}")
