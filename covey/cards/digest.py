"""The digest card (app/digest.py): sent at the times the deployer set, at the top level of the owner's private chat.
It has the 看板's 夜航 look (cards/board.py, docs/ui.md 5.2) and its parts: the conclusion band (要你处理 N 件事 as of its
time, counted as the 看板 and 手上的事 count it: core/board_read.py Asks; the most pressing topic; each state's count as a
segment bar), then 等你 → 停住了 → 可能卡住 → 有结果没看 → 在做, each topic a topic row (cards/ui.py topic_row: its T
number's badge, its state's dot and word, its title, a line in words, grey figures; the whole row opens it, ``url``),
做完 and 已停止 folded last. A part shows SHOWN rows (fewer while the card would pass what a card takes, as the 看板's
FIT_SHOWN) and says how many more there are. Under 等你, 整理专项's proposals waiting for his 好 (no buttons: this card is
a record of its time) and the questions waiting over a day as one grey line of topic numbers, 手上的事's
(cards/overview.py stale_line), with its button 不管了 when ``dismissable``; once clicked, the line is 已撤下 N 个
(dismissed_line), grey, with 撤销 (``cleared_taken``: what it puts back). A project a guard paused is a row of 停住了.

``view`` is plain data (app/digest.py collect, tick): ``slot`` and ``since`` (epoch seconds), ``waiting``, ``running`` and
``done`` rows as the 看板's (label, title, line, meta, url, card, tone, stuck, seen), ``older`` (results not seen that
ended before ``since``), ``stale`` rows {topic, label, title, url}, ``pending`` (proposals), ``projects`` (the projects a guard
paused), ``knowledge`` and ``wanted`` (rows {what, why, would}: 我本来想找你的事), ``dismissable``, ``cleared`` (the labels
taken off from this card), ``web`` (the web page's address: 打开网页 on the last line). A view saved by an older release
(its link in its label, a ``state`` and ``took`` in place of a line and figures, no ``tone``) is drawn the same way
(``shaped``). ``asked``: the bot menu's 看板 of an older release (随时查看 in the title).

The evening digest's own parts (app/digest.py ``daily``), each left out when the view has none: ``reached`` (本周找你 N 次：问题 a
次、停住 b 次, cards/weekly_usage.py reached_line) and ``proxy`` ({sent, unsent}: 今天代答) as two lines after the topics,
then ``remember`` (你反复说的: rows {id, text, labels, sources (the labels linked), workspace, state, error, carried?,
source?}): each its rule in bold, where it came from and where it would go, and 「记下」 (REMEMBER_KIND, ``op`` save) and
「不用」 (drop) while open; once decided, what came of it in grey instead. With 记忆自己长 (COVEY_MEMORY_LEARN=1) a ``carried`` row
already counts as 它总结的 (its hint says so), and the rows of another ``source`` (what Codex or Claude Code noted on their own,
app/memory_harvest.py) are a part of their own, ``HARVEST_TITLE``. Then ``memory_tidy`` (整理记忆, app/memory_tidy.py view_of:
{run, away {idle, done, superseded}, rules [{project, name, entry, text, state}], expired, undone}): how many lines it put
away and why with 「撤销」 (MEMORY_KIND, ``op`` undo), each new rule with 「确认长期」 (confirm) and 「不对」 (wrong) while open."""
from __future__ import annotations

from covey.cards import board, ui
from covey.cards.project_proposal import board_rows
from covey.cards.elements import callback_button, fits, folded_panel, grey, item, md, menu_item, note, panel_header, styled_panel
from covey.cards.overview import clock, named
from covey.cards.weekly_usage import reached_line
from covey.core import look
from covey.core.text import cut, literal, safe_text

TITLE = "汇总"
SHOWN = 8
FIT_SHOWN = board.FIT_SHOWN  # Rows a part shows, tried in turn until the card fits (``digest_card``).
TITLE_CHARS, STATE_CHARS = 30, 40
PARTS = (("waiting", "等你"), ("running", "在做"), ("done", "做完"))  # The Markdown's parts (``digest_text``).
ASKED = "随时查看"  # 看板's title: the card the owner asked for, not a timed one.
EMPTY = "{} 时没有要你处理的：没有等你的、没有在做的，{} 之后也没有做完的。"  # A record as of its time (the card stays in the chat).
ICON = "waiting_outlined"


ORIGIN = "digest"  # The stale line's button value's ``from`` (app/overview.py claim hands such a click on).
REMEMBER_KIND = "bridge_digest_remember"  # 「记下」 / 「不用」 on one of 你反复说的: ``id`` of the candidate, ``op`` save or drop.
REMEMBER_TITLE = "你反复说的"
REMEMBER_HINT = ("从今天结束的话题里找的、你在不同话题里说过不止一次的话。点「记下」才记进记忆，以后每一轮都带上；"
                 "不点不生效，开了脱敏的话题不看。")
REMEMBER_DONE = {"saved": "已记下", "declined": "不用了，以后不再提", "expired": "很久没用，不再带"}
CARRIED_HINT = ("从今天结束的话题里找的、你在不同话题里说过不止一次的话，已经先照着做（标“它总结的”，你的话和它冲突时以你的为准）。"
                "点「记下」算你说的；点「不用」就撤下，以后不再提。开了脱敏的话题不看。")
LEARN_TITLE = "自动学习想记的"
LEARN_HINT = "从你的话里自动学到、会影响所有话题或整个工作区的规矩，先放在这里，带着你的原话。点「记下」才生效，不点不生效。"
HARVEST_TITLE = "Codex 和 Claude Code 自己记的"
HARVEST_HINT = "它们各自记下、只有自己的话题用得上的关于你的偏好。点「记下」才变成所有话题都带的原则，不点不生效。"
MEMORY_KIND = "bridge_digest_memory"  # 整理记忆's 「撤销」 / 「确认长期」 / 「不对」: ``run``, ``op`` undo, confirm or wrong, ``project``, ``entry``.
MEMORY_TITLE = "整理记忆"
MEMORY_AWAY = {"done": "办完的", "foreign": "别的专项的", "superseded": "被新回答替代的", "idle": "很久没用的"}
MEMORY_HINT = "只收起不删除：收起的不再每轮带，用查记忆还能查到。新约定先照着做（标“它总结的”），点「确认长期」才算你说的。"
MEMORY_RULE_DONE = {"confirmed": "已确认，以后算你说的", "dropped": "已撤下"}
GO_LINE = "在菜单「看板」上点「继续」接着做"  # What a project a guard paused waits for (cards/board.py PROJECT_GO_KIND).
# How an older release's row said a state and a question (``shaped``).
STATE_WORDS = frozenset({look.word(key) for key in look.STATES} | {word for words in look.RETIRED.values() for word in words})
ASKED_STARTS = tuple(f"{word}：" for word in (look.word("waiting"), *look.RETIRED["waiting"]))


def rows_of(view, key):
    """How many ``key`` has: the 等你 part's old questions too, not the ones taken off from this card ("等你 4" over
    已撤下 3 个 reads as four still waiting), so a redraw after the click lowers the header
    and the part's count with the line."""
    extra = len(view.get("stale") or []) if key == "waiting" else 0
    return len(view[key]) + extra


def counts(view):
    return " · ".join(f"{name} {rows_of(view, key)}" for key, name in PARTS if rows_of(view, key))


def tail_text(view):
    if view.get("stale"):
        return [f"另有 {len(view['stale'])} 个等了一天以上：{named([row.get('label') for row in view['stale']])}"]
    return [f"已撤下 {len(view['cleared'])} 个：{named(view['cleared'])}"] if view.get("cleared") else []


def line(row, *, plain=False):
    """A row in one line of Markdown (the card refused: ``digest_text``)."""
    parts = [ui.split_link(row.get("label"))[0] if plain else row.get("label") or "",
             safe_text(row.get("title") or "", TITLE_CHARS), safe_text(row.get("state") or "", STATE_CHARS), row.get("took") or ""]
    text = " · ".join(part for part in parts if part)
    if not row.get("seen"):
        return text
    return f"{text} · 已看" if plain else grey(f"{text} · 已看")


def done_since(view):
    """有结果没看's heading after its count: since when, and how many results not seen ended before (``older``)."""
    older = view.get("older") or 0  # A view saved by an older release has none.
    return f"{clock(view['since'])} 之后结束" + (f"，另有更早没看的 {older} 个" if older else "")


def title_of(view):
    return f"{TITLE} · {ASKED} · {clock(view['slot'])}" if view.get("asked") else f"{TITLE} · {clock(view['slot'])}"


def shaped(row):
    """``row`` as the 看板 draws one, from a view of any release: its link taken out of its label (an older release wrote
    the T number as a Markdown link), its line and figures from the state and time it said before, its tone from its
    status (cards/board.py tone), else from those words."""
    row = dict(row)
    label, url = ui.split_link(row.get("label"))
    row["label"] = label
    if url and not row.get("url"):
        row["url"] = url
    if "line" not in row:  # Its state's words as its line: not the state's word again, a question as the 看板 says it.
        words = str(row.get("state") or "")
        asked = next((words[len(start):] for start in ASKED_STARTS if words.startswith(start)), None)
        row["line"] = f"要你定：{asked}" if asked else "" if words in STATE_WORDS else words
    if "meta" not in row:
        row["meta"] = [row.get("took") or ""]
    if not row.get("tone") and not row.get("status"):
        words = str(row.get("state") or "")
        if words == look.word("stopped") or words in look.RETIRED["stopped"]:
            row["tone"] = "stopped"
        elif words == look.word("cancelled"):
            row["tone"] = "cancelled"
    return row


def project_row(project):
    """A project a guard paused, under 停住了: 专项「名」, why, and where 继续 is; it opens its card's topic."""
    reason = project["halted"] if isinstance(project.get("halted"), str) else ""
    return ui.topic_row("stopped", f"专项「{project.get('name') or ''}」", "；".join(part for part in (reason, GO_LINE) if part),
                        url=project.get("url") or "")


def heading_with(key, count, after=""):
    """A part's heading as the 看板 draws one (cards/board.py heading), ``after`` grey behind its count."""
    element = board.heading(key, count)
    if after:
        element["content"] += "  " + grey(literal(after))
    return element


def part_heading(title, count):
    """The heading of a part that lists no topics (你反复说的, 新记的知识, 我本来想找你的事), as a group's is drawn."""
    return md(f"**{literal(title)}**  {grey(str(count))}", size="normal_v2")


def digest_card(view):
    """The card for ``view``. Many rows would pass what a card takes (cards/elements.py CARD_NODES, CARD_BYTES): fewer a part
    (FIT_SHOWN) until it fits, the band counting them all the same."""
    for shown in FIT_SHOWN:
        built = _drawn(view, shown)
        if fits(built, board.NODES, board.BYTES):
            break
    return built


def _drawn(view, shown):
    view = {**view, **{key: [shaped(row) for row in view.get(key) or ()] for key in ("waiting", "running", "done")},
            "stale": [{**row, "label": ui.split_link(row.get("label"))[0],
                       "url": row.get("url") or ui.split_link(row.get("label"))[1]} for row in view.get("stale") or ()]}
    found = board.groups(view)
    stopped_projects = board.halted(view)
    sizes = board.state_counts(found, stopped_projects)
    at, since = clock(view["slot"]), clock(view["since"])
    listed = any(found[key] for key in found) or stopped_projects or view.get("cleared")
    quiet = f"{at} 时没有在等你的事" if listed else EMPTY.format(at, since)
    elements = [board.band(found, None, sizes, stopped_projects, label=f"要你处理 · {at}", quiet=quiet)]
    elements += board.waiting_part(view, found, shown, origin=ORIGIN, answer=False)
    if found["stopped"] or stopped_projects:
        elements.append(board.heading("stopped", len(found["stopped"]) + len(stopped_projects)))
        elements += board.blocks("stopped", found["stopped"], board.task_card_button, shown)
        elements += [project_row(project) for project in stopped_projects[:shown]]
    if found["stuck"]:
        elements.append(board.heading("stuck", len(found["stuck"])))
        elements += board.blocks("stuck", found["stuck"], board.task_card_button, shown)
    if found["result"]:
        elements.append(heading_with("result", len(found["result"]), done_since(view)))
        elements += board.blocks("result", found["result"], shown=shown)
    if found["running"]:
        elements.append(board.heading("running", len(found["running"])))
        elements += board.blocks("running", found["running"], shown=shown)
    elements += board.done_fold(found, since, shown)
    lines = daily_lines(view)
    if lines:
        elements.append(md("\n".join(lines)))
    review = review_line(view)
    if review:
        elements.append(md(review, size="notation"))
    elements += remember_elements(view)
    elements += memory_elements(view)
    elements += knowledge_elements(view)
    elements += wanted_elements(view)
    if isinstance(view.get("tidy"), dict):  # A view saved when this card had 整理专项 (it is the 看板's alone now).
        elements += board_rows([str(name) for name in view["tidy"].get("projects") or ()])
    last = note(f"只列这个{view.get('where') or '私聊'}里的话题，管家不列")
    elements.append(item(last, ui.link_button(board.WEB, view["web"])) if view.get("web") else last)
    title = title_of(view)
    tags = board.counts(found, None, sizes)
    head = panel_header(ICON, title, f"{view.get('where') or '私聊'}里在推进的事", tags)
    head["text_tag_list"] = [{"tag": "text_tag", "text": {"tag": "plain_text", "content": text}, "color": color}
                             for text, color in tags[:3]]
    return ui.styled(styled_panel(head, elements, " · ".join([title, *(text for text, _ in tags)]), spacing="8px"))


def daily_lines(view):
    """The evening digest's count lines: 本周找你 and 今天代答; none in a view without them."""
    lines = [reached_line(view["reached"])] if isinstance(view.get("reached"), dict) else []
    proxied = view.get("proxy") if isinstance(view.get("proxy"), dict) else None
    if proxied is not None:
        unsent = int(proxied.get("unsent") or 0)
        lines.append(f"今天代答发出 {int(proxied.get('sent') or 0)} 条" + (f"，{unsent} 条没发出，在菜单「代答」里看" if unsent else ""))
    return lines


def review_line(view, *, plain=False) -> str:
    """The memory's 待审核 line (``view["review"]``: {pending, url}, app/digest.py review_view): ``记忆：待审核 N 条`` and, with the web
    page on, the link to the 网页记忆中心's 待审核 tab; '' when nothing waits or the view has none."""
    part = view.get("review")
    waiting = int(part.get("pending") or 0) if isinstance(part, dict) else 0
    if waiting <= 0:
        return ""
    url = str(part.get("url") or "")
    line = f"记忆：待审核 {waiting} 条"
    if not url:
        return line
    return f"{line} · {url}" if plain else f"{line} · [去网页处理]({url})"


def remember_meta(row, *, plain=False):
    """Where a candidate came from and where 「记下」 puts it: ``来源：T12、T15 · 记到工作区 covey`` (``plain``: no Markdown, the
    labels not linked); a row of another source says it: ``来源：Codex 自己记的 · 记到全局``."""
    labels = [str(label) for label in row.get("labels") or ()]
    where = f"工作区 {row['workspace']}" if row.get("workspace") else "全局"
    if plain:
        sources = "、".join(labels)
    else:
        sources, where = row.get("sources") or "、".join(literal(label) for label in labels), literal(where)
    sources = sources or SOURCE_WORDS.get(str(row.get("source") or ""), "")
    quote = cut(row["quote"], 60) if row.get("quote") else ""
    said = f" · 你说过：“{quote if plain else literal(quote)}”" if quote else ""
    return (f"来源：{sources} · " if sources else "") + f"记到{where}{said}"


SOURCE_WORDS = {"codex": "Codex 自己记的", "claude": "Claude Code 自己记的", "learn": "自动学习记的"}  # As app/memory_candidates.py SOURCE_WORDS.


def remember_elements(view):
    rows = view.get("remember") or []
    mine = [row for row in rows if not row.get("source")]
    learned = [row for row in rows if row.get("source") == "learn"]
    theirs = [row for row in rows if row.get("source") and row.get("source") != "learn"]
    hint = CARRIED_HINT if any(row.get("carried") for row in mine) else REMEMBER_HINT
    return [*candidate_part(REMEMBER_TITLE, mine, hint), *candidate_part(LEARN_TITLE, learned, LEARN_HINT),
            *candidate_part(HARVEST_TITLE, theirs, HARVEST_HINT)]


def candidate_part(title, rows, hint):
    if not rows:
        return []
    elements = [part_heading(title, len(rows))]
    for row in rows:
        elements.append(md(f"**{literal(row.get('text') or '')}**"))
        meta = remember_meta(row)
        state = row.get("state") or "open"
        if state in REMEMBER_DONE:
            elements.append(note(f"{meta} · {REMEMBER_DONE[state]}"))
            continue
        if row.get("error"):
            meta += f" · ⚠️ 没记下：{literal(row['error'])}"
        value = {"kind": REMEMBER_KIND, "id": row.get("id") or ""}
        elements += [note(meta), {"tag": "column_set", "flex_mode": "none", "horizontal_spacing": "8px", "columns": [
            {"tag": "column", "width": "auto", "elements": [callback_button("记下", {**value, "op": "save"},
                                                                              style="primary", size="small")]},
            {"tag": "column", "width": "auto", "elements": [callback_button("不用", {**value, "op": "drop"},
                                                                              style="text", size="small")]}]}]
    elements.append(note(hint))
    return elements


def away_line(part) -> str:
    """整理记忆's count of what it put away: ``收起 14 条：办完的 8 条、别的专项的 2 条、被新回答替代的 3 条、很久没用的 1 条``; ''
    with none."""
    away = part.get("away") or {}
    counts = [(MEMORY_AWAY[key], int(away.get(key) or 0)) for key in MEMORY_AWAY]
    total = sum(count for _, count in counts)
    if not total:
        return ""
    return f"收起 {total} 条：" + "、".join(f"{words} {count} 条" for words, count in counts if count)


def memory_elements(view):
    """整理记忆's part of the evening digest (``memory_tidy``); none in a view without it."""
    part = view.get("memory_tidy")
    if not isinstance(part, dict) or not part:
        return []
    rules = part.get("rules") or []
    elements = [part_heading(MEMORY_TITLE, len(rules))]
    value = {"kind": MEMORY_KIND, "run": part.get("run") or ""}
    away = away_line(part)
    if away and part.get("undone"):
        elements.append(note(f"{away} · 已撤销，都放回去了"))
    elif away:
        elements.append(item(md(away), callback_button("撤销", {**value, "op": "undo"}, style="text", size="small")))
    if part.get("expired"):
        elements.append(note(f"{int(part['expired'])} 条候选很久没用，不再带"))
    for rule in rules:
        elements.append(md(f"**{literal(rule.get('text') or '')}**"))
        where = f"专项「{literal(rule.get('name') or '')}」" if rule.get("name") else "专项"
        state = rule.get("state") or "open"
        if state in MEMORY_RULE_DONE:
            elements.append(note(f"{where} · {MEMORY_RULE_DONE[state]}"))
            continue
        chosen = {**value, "project": rule.get("project") or "", "entry": rule.get("entry") or ""}
        elements += [note(f"{where} · 新约定，已先照着做（它总结的）"), {"tag": "column_set", "flex_mode": "none",
                     "horizontal_spacing": "8px", "columns": [
            {"tag": "column", "width": "auto", "elements": [callback_button("确认长期", {**chosen, "op": "confirm"},
                                                                              style="primary", size="small")]},
            {"tag": "column", "width": "auto", "elements": [callback_button("不对", {**chosen, "op": "wrong"},
                                                                              style="text", size="small")]}]}]
    elements.append(note(MEMORY_HINT))
    return elements


def memory_lines(view):
    """整理记忆 in Markdown (``digest_text``); none in a view without it."""
    part = view.get("memory_tidy")
    if not isinstance(part, dict) or not part:
        return []
    lines = [f"**{MEMORY_TITLE}**"]
    if away_line(part):
        lines.append(away_line(part) + ("（已撤销）" if part.get("undone") else ""))
    lines += [f"- {rule.get('text') or ''}（专项「{rule.get('name') or ''}」"
              + (f" · {MEMORY_RULE_DONE[rule['state']]}" if rule.get("state") in MEMORY_RULE_DONE else " · 新约定") + "）"
              for rule in part.get("rules") or ()]
    return lines


def knowledge_lines(view):
    """新记的知识's rows (app/digest.py knowledge_view): op · id · group · text; none when the view has no such part
    (a view saved before it, or nothing new)."""
    part = view.get("knowledge") or {}
    return [f"{row['op']} · {row['id']} · {row['where']} · {row['text']}" for row in part.get("rows") or []]


def knowledge_elements(view):
    lines = knowledge_lines(view)
    if not lines:
        return []
    more = (view.get("knowledge") or {}).get("more") or 0
    return [part_heading("新记的知识", len(lines) + more), *(md(text) for text in lines),
            *([note(f"另有 {more} 条")] if more else [])]


WANTED_TITLE = "我本来想找你的事"
WANTED_HINT = "这类该找你，或这类不用，在私聊里告诉我一句，我会记下。"


def wanted_lines(view):
    """我本来想找你的事's rows (app/digest.py wanted_view): what · why · would; none when the view has no such part."""
    return [" · ".join(part for part in (row.get("what"), row.get("why"), f"本来会：{row.get('would')}" if row.get("would") else "") if part)
            for row in view.get("wanted") or []]


def wanted_elements(view):
    lines = wanted_lines(view)
    return [part_heading(WANTED_TITLE, len(lines)), *(md(text) for text in lines), note(WANTED_HINT)] if lines else []


def folded_board():
    """看板's card folded in place (a second menu click, app/digest.py fold_board)."""
    return folded_panel("bitablekanban_outlined", "看板", menu_item("看板"))


def digest_text(view):
    """The card in Markdown, for when Feishu refuses the card."""
    lines = [f"**{title_of(view)}**"]
    for key, name in PARTS:
        rows, last = view[key], tail_text(view) if key == "waiting" else []
        if rows or last:
            lines.append(f"**{name}（{rows_of(view, key)}）**")
            lines += [line(row, plain=True) for row in rows[:SHOWN]]
            if len(rows) > SHOWN:
                lines.append(f"另有 {len(rows) - SHOWN} 个")
            lines += last
    if len(lines) == 1:
        lines.append(EMPTY.format(clock(view["slot"]), clock(view["since"])))
    lines += daily_lines(view)
    if review_line(view, plain=True):
        lines.append(review_line(view, plain=True))
    rows = view.get("remember") or []
    if rows:
        lines.append(f"**{REMEMBER_TITLE}（{len(rows)}）**")
        lines += [f"- {row.get('text') or ''}（{remember_meta(row, plain=True)}"
                  + (f" · {REMEMBER_DONE[row['state']]}" if row.get("state") in REMEMBER_DONE else "") + "）" for row in rows]
        lines.append("在卡片上点「记下」才记进记忆，不点不生效。" if not any(row.get("carried") for row in rows)
                     else "在卡片上点「记下」算你说的，点「不用」就撤下。")
    lines += memory_lines(view)
    new = knowledge_lines(view)
    if new:
        more = (view.get("knowledge") or {}).get("more") or 0
        lines += [f"**新记的知识（{len(new) + more}）**", *new, *([f"另有 {more} 条"] if more else [])]
    found = wanted_lines(view)
    if found:
        lines += [f"**{WANTED_TITLE}（{len(found)}）**", *found, WANTED_HINT]
    return "\n".join(lines)
