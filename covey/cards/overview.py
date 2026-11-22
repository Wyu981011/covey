"""The 手上的事 card (app/overview.py), pinned in the owner's private chat with the bot and redrawn whole as its
tasks change, in the 看板's 夜航 look (cards/board.py, docs/ui.md 5.2): the conclusion band (要你处理 N 件事, the most
pressing topic, a segment bar of each state's count; 都在掌握中 when nothing asks), then what asks for the owner (the
questions waiting for him, what stopped, what may be stuck), the tasks running and the ones that ended in the last few
minutes, each a topic row (cards/ui.py topic_row: its state's dot and word, its T number and title, one line in words,
grey figures; a question's row opens its card and has 去回答). Times are times of day (``when``), not durations: the card
changes with its content, not with the clock (a row's 等了 18 小时 5 分 would rewrite it every minute). Questions waiting
over STALE seconds are one grey line of topic numbers (such ones can wait for days).

要你处理 is the 看板's number (core/board_read.py Asks, act_count): 等你, 停住了 (a topic's result that stopped however
long ago, a project a guard paused) and 可能卡住, listed in that order (docs/ui.md 5.1). A stop the owner made himself is
已停止, background (core/look.py record_tone).

``view`` is plain data from app/overview.py: ``waiting`` rows (label, title, ask, since, url), newest first, ``stopped``
rows (label, title, status, at, line: why it stopped, url: its task card or its project's card), ``running`` rows (label,
title, harness, workspace, status, started, phase, progress: its estimate as a time of day, ``stuck``: 可能卡住) and
``ended`` rows (label, title, status, at, line: why it stopped or the first line of its result, ``tone``); times are epoch
seconds, ``started`` None while the task waits in the queue.

With the pinned board on (app/pins.py) ``view`` also has ``board``: ``counts`` (state key -> how many: 要你处理 as Asks
counts it, 有结果 the results on it not seen yet, 在做 the rest that run), ``pinned`` (how many of them have their pin),
the rows without a pin under ``waiting``, ``stopped``, ``running`` (``stuck`` marked), ``result`` (as ``ended`` rows,
``seen`` marked 已看) and ``cancelled`` (已停止), and ``stale``, the questions waiting too long to be on it. The card is
then the board's index: the band with the counts and how many are pinned, only the rows without a pin. Its line of old
questions has the button 不管了 (DISMISS, its value the topics listed), and ``dismissed``, the T numbers of the topics
the owner took off the board, is one line at the bottom, with 撤销最近一次 (UNDO) when ``undo`` ({topic: at}) names his
latest 不管了."""
from __future__ import annotations

import datetime
import time

from covey.cards import ui
from covey.cards.elements import CARD_BYTES, CARD_NODES, fits, item, note, notice_card, plain, styled_panel, text_button
from covey.core import board_read, look
from covey.core.text import cut, literal as literal_text

TITLE = "手上的事"
ICON = "waiting_outlined"
SHOWN = 8  # Rows a part shows; the rest is one line under them.
FIT_SHOWN = (SHOWN, 6, 4, 3, 2, 1)  # Rows a part shows, tried in turn until the card fits (``overview_card``).
NODES, BYTES = CARD_NODES - 10, CARD_BYTES - 1500  # Room left under CardKit's limits for what CardKit adds.
TITLE_CHARS, DETAIL_CHARS = 30, 80
STALE = 86400  # A question waiting this long is listed by its topic number only.
LABELS = 10  # Topic numbers that line names.
DISMISS = "bridge_overview_dismiss"  # 不管了 (这些都不用回答了 in older releases) (app/overview.py claim).
DISMISS_MAX = 50  # Topics its value names at most.
UNDO = "bridge_overview_undismiss"  # 撤销 on the line 不管了 leaves (app/overview.py claim): puts back what that click took off.


def when(seconds, now):
    """The local time of ``seconds`` as seen at ``now``: 14:05 the same day, 昨天 22:10 the day before, 11-03 09:30
    before that."""
    then, today = time.localtime(seconds), time.localtime(now)
    days = (datetime.date(*today[:3]) - datetime.date(*then[:3])).days
    if days == 0:
        return time.strftime("%H:%M", then)
    return time.strftime("昨天 %H:%M" if days == 1 else "%m-%d %H:%M", then)


def clock(seconds):
    return time.strftime("%H:%M", time.localtime(seconds))


# How an ended task's row reads by its status when it carries no ``tone`` (core/look.py record_tone): a result not seen,
# one seen, a stop (a cancelled one 已停止: a view without tones came before who stopped it was told).
ENDED_TONES = {"done": "result", "continued": "result", "failed": "stopped", "interrupted": "stopped",
               "cancelled": "cancelled"}
STUCK_WORDS = "可能卡住了"  # core/progress.py board_words: such a running row is drawn 可能卡住.
ACT = board_read.ACT  # 要你处理: what the band counts (core/board_read.py act_count), as the 看板 counts it.
LEAD = 30  # Characters of the most pressing topic's words on the band, as cards/board.py LEAD.
QUIET = "现在没有在做的任务，也没有在等你的事"  # The band's grey line when nothing asks and nothing runs.
CALM = "现在没有在等你的事"  # When nothing asks and something runs (the rows under it say what).


def linked(row, bold=False) -> str:
    """A row's label as a link to the card it is acted on when it has one (``url``: a 等我's, core/board_read.py waits)."""
    label = row.get("label") or ""
    if not row.get("url") or label.startswith("["):
        return label
    return f"[**{label or '话题'}**]({row['url']})" if bold else f"[{label or '话题'}]({row['url']})"


def named_row(row, **fields):
    """A row of the view as the 看板's topic row takes one (cards/board.py block): its T number, its title cut to
    TITLE_CHARS, its line cut to DETAIL_CHARS."""
    line = fields.pop("line", "")
    return {"label": row.get("label") or "", "title": cut(row.get("title") or "", TITLE_CHARS),
            "line": cut(line, DETAIL_CHARS) if line else "", **fields}


def waiting_row(row, now):
    """A question as a 看板 row: what it asks, since when; it opens the card it is answered on."""
    return named_row(row, url=row.get("url") or "", line=row.get("ask") or "",
                     meta=[f"{when(row['since'], now)} 问的"] if row.get("since") else [])


def running_kind(row) -> str:
    """在做, or 可能卡住 (``stuck``, core/board_read.py Asks; a row without it: its estimate says so); one in the queue is
    在做 with 排队中, as on the 看板."""
    if "stuck" in row:
        return "stuck" if row["stuck"] else "running"
    return "stuck" if STUCK_WORDS in (row.get("progress") or ()) else "running"


def running_row(row, now):
    """A running (or queued) task as a 看板 row: its phase, then since when, its estimate, what it runs with."""
    queued = row.get("status") == "queued" or not row.get("started")
    time_part = "排队中" if queued else f"{when(row['started'], now)} 开始"
    line = "正在停止" if row.get("status") == "cancel_requested" else row.get("phase") or ""
    meta = [time_part, *(part for part in row.get("progress") or () if part != STUCK_WORDS), row.get("harness") or "",
            row.get("workspace") or ""]
    return named_row(row, url=row.get("url") or "", line=line, meta=meta)


def ended_kind(row) -> str:
    """The state key of an ended row: its ``tone`` (core/look.py record_tone), else by its status (ENDED_TONES)."""
    kind = row.get("tone") or ENDED_TONES.get(row.get("status"), "result")
    return "done" if kind == "result" and row.get("seen") else kind


def ended_row(row, now):
    """A task that ended a moment ago as a 看板 row: its line (``line``, core/board_read.py ended_line: why it stopped,
    the first line of a result), when, and 已看 for a board result seen within its KEEP_SEEN."""
    return named_row(row, url=row.get("url") or "", line=row.get("line") or "",
                     meta=[when(row["at"], now) if row.get("at") else "", "已看" if row.get("seen") else ""])


def heading(word, count, icon):
    """A group's heading as the 看板 draws one (cards/board.py heading): its word, how many, its icon."""
    return {"tag": "markdown", "content": f"**{word}**  <font color='grey'>{count}</font>", "text_size": "normal_v2",
            "icon": {"tag": "standard_icon", "token": icon, "color": "grey"}}


def head_of(row) -> str:
    return " ".join(part for part in (row.get("label"), row.get("title")) if part) or "话题"


def answer_button(url):
    """去回答 (cards/board.py button's look): the row's one primary button, opening the card the question is on."""
    return {"tag": "button", "text": plain("去回答"), "type": "primary", "size": "small",
            "behaviors": [{"type": "open_url", "default_url": url}]}


def rows_part(rows, draw, now, kind, shown=SHOWN):
    """The rows of a group as topic rows (cards/ui.py topic_row, as cards/board.py block draws them), ``shown`` of
    them, the rest one line; ``kind``: each row's state key."""
    elements = []
    for row in rows[:shown]:
        drawn = draw(row, now)
        url = drawn.get("url") or ""
        elements.append(ui.topic_row(kind(row), head_of(drawn), drawn.get("line") or "", drawn.get("meta") or (),
                                     url=url, buttons=[answer_button(url)] if kind(row) == "waiting" and url else []))
    if len(rows) > shown:
        elements.append(note(f"还有 {len(rows) - shown} 件没列出"))
    return elements


def part(rows, draw, now, key, shown=SHOWN, word=None, kind=None):
    """A heading of state ``key`` (``word`` in place of its word) and its rows (``rows_part``), [] for none."""
    if not rows:
        return []
    return [heading(word or look.group_word(key), len(rows), look.STATES[key].icon),
            *rows_part(rows, draw, now, kind or (lambda row: key), shown)]


def _waiting_part(rows, now, count=None, word=None, shown=SHOWN):
    """等你: the recent questions as rows, the ones waiting over STALE as one line of their topic numbers."""
    recent = [row for row in rows if not row.get("since") or now - row["since"] < STALE]
    old = [row for row in rows if row not in recent]
    elements = [heading(word or look.group_word("waiting"), len(rows) if count is None else count,
                        look.STATES["waiting"].icon)]
    elements += rows_part(recent, waiting_row, now, lambda row: "waiting", shown)
    if old:
        elements.append(stale_line(old))
    return elements


def split(view):
    """The rows of a view without the board, by state: {waiting, stopped, stuck, running, ended} (``ended``: 刚结束, what
    is not 停住了 among them shown there; one that stopped is listed under 停住了 when Asks counts it)."""
    running = list(view.get("running") or ())
    return {"waiting": list(view.get("waiting") or ()), "stopped": list(view.get("stopped") or ()),
            "stuck": [row for row in running if running_kind(row) == "stuck"],
            "running": [row for row in running if running_kind(row) != "stuck"],
            "ended": list(view.get("ended") or ())}


def sizes(found):
    """{state key: how many} in core/look.py PRESSING's order, as the 看板 counts them (cards/board.py state_counts):
    要你处理 from its rows (core/board_read.py Asks names them), 有结果 the results not seen among the ended ones."""
    kinds = [ended_kind(row) for row in found["ended"]]
    return {"waiting": len(found["waiting"]), "stopped": len(found["stopped"]), "stuck": len(found["stuck"]),
            "result": kinds.count("result"), "running": len(found["running"])}


def band(found, now, empty=None):
    """The conclusion band (cards/board.py band): how many things ask for him (core/board_read.py act_count), the most
    pressing topic, every state's count as a bar. When nothing asks, its grey line says so, and that nothing runs only
    when nothing does."""
    lead = {"waiting": [waiting_row(row, now) for row in found["waiting"]],
            "stopped": [ended_row(row, now) for row in found["stopped"]],
            "stuck": [running_row(row, now) for row in found["stuck"]],
            "result": [ended_row(row, now) for row in found["ended"] if ended_kind(row) == "result"],
            "running": [running_row(row, now) for row in found["running"]]}
    counts = sizes(found)
    asked = board_read.act_count(counts)
    first = look.pressing(counts)
    row = (lead.get(first) or [None])[0] if first else None
    line = CALM if found["running"] or found["stuck"] else QUIET
    if row is not None and first in ACT:
        words = f"{look.word(first)} · {head_of(row)}"
        line = literal_text("先看：" + (words if len(words) <= LEAD else words[:LEAD - 1] + "…"))
    headline = ui.number(asked, "件事") if asked else empty[0] if empty else "**都在掌握中**"
    if empty and not asked:
        line = empty[1]
    return ui.conclusion_band("要你处理", headline, line, below=ui.seg_bar(counts),
                              url=(row or {}).get("url") or "" if first in ACT else ""), counts


def tags(counts, empty=None):
    """The title bar's tags: (text, colour) of the states that have someone, most pressing first (cards/board.py counts)."""
    found = [(f"{counts[key]} {look.word(key)}", look.STATES[key].color) for key in ("waiting", "stopped", "stuck", "running")
             if counts.get(key)]
    return found or [(empty[2], "neutral") if empty else ("都在掌握中", "green")]


def head(subtitle, found):
    return {"title": plain(TITLE), "subtitle": plain(subtitle),
            "text_tag_list": [{"tag": "text_tag", "text": plain(text), "color": color} for text, color in found[:3]],
            "template": "default", "icon": {"tag": "standard_icon", "token": ICON, "color": "blue"},
            "padding": "10px 14px 0px 14px"}


def preview(counts, empty=None) -> str:
    """The chat list's preview: how many of the states the title bar counts there are (``tags``), most pressing first;
    else what the title bar says (还没有话题, 都在掌握中)."""
    parts = [f"{look.word(key)} {counts[key]}" for key in (*ACT, "running") if counts.get(key)]
    return " · ".join(parts) or (empty[2] if empty else "都在掌握中")


def counts_words(view, empty=None):
    """The chat list's preview of a card without the board."""
    return preview(sizes(split(view)), empty)


def board_counts(board, empty=None):
    """The chat list's preview of the board's index: its counts (``preview``)."""
    return preview(board["counts"], empty)


def named(labels):
    labels = [label or "?" for label in labels]
    return "、".join(labels[:LABELS]) + ("等" if len(labels) > LABELS else "")


def stale_line(rows, button=False, origin=""):
    """The questions waiting over STALE as one line, here and on the 早晚汇总 card (cards/digest.py); ``button``:
    with 不管了, which names these topics; ``origin``, the card it is on when not this one (its value's
    ``from``: app/overview.py claim hands the click on, app/digest.py redraws that card)."""
    line = note(f"另有 {len(rows)} 个等了一天以上：{named([linked(row) for row in rows])}")
    topics = list(dict.fromkeys(row["topic"] for row in rows if row.get("topic")))[:DISMISS_MAX]
    if not button or not topics:
        return line
    value = {"kind": DISMISS, "topics": topics, **({"from": origin} if origin else {})}
    return item(line, text_button("不管了", value))


def undo_button(taken, label="撤销", origin=""):
    """撤销 for a 不管了: its value ``taken``, {topic: the ``at`` it was taken off at} (app/pins.py undismiss puts back
    those whose entry is still that one), ``origin`` as for stale_line."""
    return text_button(label, {"kind": UNDO, "taken": dict(list(taken.items())[:DISMISS_MAX]), **({"from": origin} if origin else {})})


def dismissed_line(labels, taken=None, origin=""):
    """What the line of ``stale_line`` becomes on a card that is not redrawn from the board (the 早晚汇总's, the 看板's) once
    its button took ``labels``' topics off: grey, with 撤销 (``taken``: what it puts back; a view saved before it has none,
    and then no button)."""
    line = note(f"已撤下 {len(labels)} 个：{named(labels)}")
    return item(line, undo_button(taken, origin=origin)) if taken else line


BOARD_LISTS = ("waiting", "stopped", "running", "result", "cancelled", "stale", "dismissed")  # A board view's row lists.


def lists(view) -> bool:
    """Whether ``view`` lists anything: its own rows, or the board's (rows, pins, old questions, the topics taken off).
    A card that lists nothing tells a first use (还没有话题) from a clear board by it (app/overview.py)."""
    board = view.get("board") or {}
    return bool(any(view.get(key) for key in ("waiting", "stopped", "running", "ended")) or board.get("pinned")
                or any(board.get(key) for key in BOARD_LISTS))


def _board(board, now, shown=SHOWN, empty=None):
    """The index under the pinned board: the band with the counts and how many are pinned, the rest by group, what asks
    for him first (等你 → 停住了 → 可能卡住), then 在做, 有结果 and 已停止."""
    counts = board["counts"]
    sized = {key: int(counts.get(key) or 0) for key in look.PRESSING}
    asked = board_read.act_count(sized)
    # How many are pinned: the title bar says it.
    line = ("在 Pin 页里点话题的卡片，直接打开那个话题" if board["pinned"]
            else "现在没有在等你的事" if not asked else "")
    if empty and not asked:
        line = empty[1]
    elements = [ui.conclusion_band("要你处理", ui.number(asked, "件事") if asked else empty[0] if empty else "**都在掌握中**", line,
                                   below=ui.seg_bar(sized))]
    unpinned = " · 未 Pin"
    if board["waiting"]:
        elements += _waiting_part(board["waiting"], now, word=f"{look.group_word('waiting')}{unpinned}", shown=shown)
    running = board.get("running") or []
    elements += part(board.get("stopped") or [], ended_row, now, "stopped", shown, f"{look.word('stopped')}{unpinned}")
    elements += part([row for row in running if running_kind(row) == "stuck"], running_row, now, "stuck", shown,
                     f"{look.word('stuck')}{unpinned}")
    elements += part([row for row in running if running_kind(row) != "stuck"], running_row, now, "running", shown,
                     f"{look.word('running')}{unpinned}")
    elements += part(board.get("result") or [], ended_row, now, "result", shown, f"{look.word('result')}{unpinned}",
                     ended_kind)
    elements += part(board.get("cancelled") or [], ended_row, now, "cancelled", shown, f"{look.word('cancelled')}{unpinned}")
    if board["stale"]:
        elements.append(stale_line(board["stale"], button=True))
    if board.get("dismissed"):
        line = note(f"你撤下的 {len(board['dismissed'])} 个：{named(board['dismissed'])}")
        # 撤销最近一次: the line lists everything taken off, hand unpins and the butler's too; the button puts back
        # only the owner's latest 不管了 (app/pins.py last_click).
        elements.append(item(line, undo_button(board["undo"], "撤销最近一次")) if board.get("undo") else line)
    return elements, tags(sized, empty)


def overview_card(view, now, stamp="", where="私聊"):
    """The card for ``view`` at ``now``; ``stamp``, the 更新于 time ('' leaves the line out: what app/overview.py
    compares to tell whether the card changed); ``where``, the chat's word (私聊, or 群 for a personal group's, app/group_boards.py).
    A topic row costs more than the line it was: fewer rows a group (FIT_SHOWN) until the card is within what CardKit
    takes (cards/elements.py CARD_NODES, CARD_BYTES), the rest one line each."""
    for shown in FIT_SHOWN:
        card = _drawn(view, now, stamp, where, shown)
        if fits(card, NODES, BYTES):
            break
    return card


def _drawn(view, now, stamp, where, shown):
    # Only 还没有话题: this card is redrawn, never a record; and only when it lists nothing.
    empty = ui.empty_words(first=bool(view.get("first_use")) and not lists(view))
    if "board" in view:
        board = view["board"]
        elements, found = _board(board, now, shown, empty)
        subtitle = f"Pin 着 {board['pinned']} 个话题" if board["pinned"] else f"{where}里在推进的事"
        summary = f"{TITLE} · {board_counts(board, empty)}"
    else:
        rows = split(view)
        top, counts = band(rows, now, empty)
        elements, found = [top], tags(counts, empty)
        if rows["waiting"]:
            elements += _waiting_part(rows["waiting"], now, shown=shown)
        elements += part(rows["stopped"], ended_row, now, "stopped", shown)
        elements += part(rows["stuck"], running_row, now, "stuck", shown)
        elements += part(rows["running"], running_row, now, "running", shown)
        if rows["ended"]:
            elements.append(heading("刚结束", len(rows["ended"]), "yes_outlined"))
            elements += rows_part(rows["ended"], ended_row, now, ended_kind, shown)
        subtitle = f"{where}里在推进的事"
        summary = f"{TITLE} · {counts_words(view, empty)}"
    if stamp:
        elements.append(note(f"更新于 {stamp} · 只列这个{where}里的任务"))
    return ui.styled(styled_panel(head(subtitle, found), elements, summary, spacing="8px"))


def retired_card():
    """What a card that was replaced by a newer one says: it no longer changes."""
    return notice_card(f"这张“{TITLE}”已不再更新，最新的在置顶（Pin）里。",
                       f"{TITLE} · 已不再更新")
