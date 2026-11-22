"""The card a topic turn's outcome takes back to the butler's top level (app/butler_relay.py, docs/butler.md
结论回到顶层): ``relay_card``, pure, and what it shares with the question card's copy there
(cards/question_cards.py mirror_card): a topic's reply as card Markdown (``reply_body``), a long one with its opening in
view and the rest folded under it (``reply_peek``). ``merged_card``: 做完了 relays that came close together, as one card
(app/relay_send.py send_merged)."""
from __future__ import annotations

import re

from covey.cards.answer_card import ARTIFACTS_ID, check_element, facts_element, tail as answer_tail
from covey.cards.elements import card, collapsible, grey, json_size, md, note
from covey.cards.review import (ANSWER_CARD_BYTES, answer_lead, bold_minor_headings, drop_part_heading, fits,
                                inline_one_line_code, opening)
from covey.cards.ui import (BODY_PADDING, BODY_SPACING, band_label, banded, conclusion_band, container, labelled, read_more,
                            speaker_row, split_ask, styled, topic_badge)
from covey.core import look
from covey.core.failure import HEADLINE_CHARS, split_title
from covey.core.text import literal, redact

CARD_TEXT_BYTES = 24000  # A card is at most 30 KB (CardKit); a longer reply goes as Markdown messages.
QUESTION_CHARS = 300
SUMMARY_CHARS = 40
DONE, WAITING, STOPPED = "done", "waiting", "stopped"
# A reply longer than this (lines, characters) or with a table shows its opening, the rest folded (``long_reply``).
FOLD_LINES, FOLD_CHARS = 6, 180
FOLD_ID = "relay_reply"
FOOT_ID = "relay_foot"
TABLE_RULE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def reply_body(text) -> str:
    """A turn's reply as a card shows it: its line ends as \\n, one-line code inline, its small headings bold."""
    return bold_minor_headings(inline_one_line_code(str(text or "").replace("\r\n", "\n").strip()))


def reply_size(text):
    """(lines, characters, tables) of a reply's Markdown: its non-blank lines, its characters without spaces, and its
    tables (a line of dashes under a header row)."""
    body = str(text or "")
    lines = [line for line in body.splitlines() if line.strip()]
    tables = sum(1 for line in lines if "|" in line and "-" in line and TABLE_RULE.match(line))
    return len(lines), len("".join(body.split())), tables


def long_reply(text) -> bool:
    """Whether a reply is folded on the relay, its opening in view (``reply_peek``): more than FOLD_LINES lines or
    FOLD_CHARS characters, or a table."""
    lines, chars, tables = reply_size(text)
    return lines > FOLD_LINES or chars > FOLD_CHARS or tables > 0


def size_words(text) -> str:
    """How much a reply is: "约 1800 字 · 含 1 张表"."""
    _, chars, tables = reply_size(text)
    step = 100 if chars >= 1000 else 10
    size = max(step, round(chars / step) * step)
    return f"约 {size} 字" + (f" · 含 {tables} 张表" if tables else "")


def fold_title(text) -> str:
    """The fold's title says how much is in it: "完整回答 · 约 1800 字 · 含 1 张表（点开看）"."""
    return f"完整回答 · {size_words(text)}（点开看）"


def reply_fold(text):
    """The reply in a closed fold titled with its size: ``text`` (Markdown) that does not start with words."""
    return collapsible(FOLD_ID, fold_title(text), [md(text)], quiet=True, spacing="6px")


def whole_words(text) -> str:
    """The title of the fold under a long text's opening, ``text`` what it holds: "展开全文 · 还有约 1800 字 · 含 1 张表"."""
    return "展开全文 · 还有" + size_words(text)


def reply_peek(text, element_id=FOLD_ID, *, label="", icon_key="") -> list:
    """A reply (Markdown) as 犹抱琵琶半遮面 (docs/ui.md 4 露一截, cards/ui.py read_more): its first few hundred
    characters in view as card text (cards/review.py opening, ``label`` grey before them), then a fold that says how
    much there is in all and goes on from there; a reply that fits, as it is; one that does not start with words (a
    table, code), the fold titled with its size (``reply_fold``). Elements, one or two."""
    if fits(text):  # Short: all of it (the owner: 短回复直接完整展示).
        return [md(labelled(text, label), element_id=element_id)]
    head, rest = opening(text)
    if not head:
        return [reply_fold(text) if element_id == FOLD_ID else collapsible(
            element_id, " · ".join(part for part in (label, size_words(text)) if part) + "（点开看）", [md(text)],
            quiet=True, spacing="6px")]
    if not rest.strip():
        return [md(labelled(head, label), element_id=element_id)]
    return read_more(element_id, head, rest, label=label, icon_key=icon_key)


DETAILS_ID = "relay_details"
# What a part under the answer is called in the 详情 fold's title (cards/answer_card.py element ids).
DETAIL_WORDS = {"answer_acceptance": "验收说明", "answer_change_check": "提交号对不上", "answer_change": "改动",
                "answer_criteria": "完成标准", "answer_review": "独立复核", "answer_memory": "记下的事"}


def details(parts) -> list:
    """The parts under a relay's answer (产物, 验收说明, a commit not found, 独立复核…) in one closed fold whose title
    names them, so the answer stays what the card is for (the owner, 2026-11-22: 底下的东西占了太高); one part alone stays
    as it is. The 输入/输出 lines stay outside, under it."""
    parts = [part for part in parts if part]
    if len(parts) < 2:
        return parts
    words = []
    for part in parts:
        title = ((part.get("header") or {}).get("title") or {}).get("content", "") if part.get("element_id") == ARTIFACTS_ID else ""
        word = title or DETAIL_WORDS.get(str(part.get("element_id") or ""), "")
        if word and word not in words:
            words.append(word)
    return [collapsible(DETAILS_ID, " · ".join(words or ["更多"]) + "（点开看）", parts, quiet=True, spacing="6px")]


def foot(inputs, outputs, *, change=None, links=()):
    """What ends a relay (FACTS_ID, cards/answer_card.py facts_element): its 输入 and 输出 lines, the 改动 line of a
    turn that changed code (a dict) and ``links`` (Markdown: 进话题 ›) ending the 输出 line; with neither 输入 nor 输出,
    the links alone on a small line (FOOT_ID). None without anything."""
    if inputs or outputs or change:
        return facts_element(inputs, outputs, links=links, change=change)
    line = "　".join(links)
    return md(line, size="notation", element_id=FOOT_ID) if line.strip() else None


INTO_LABEL = "进话题 ›"


def into(url, meta) -> list:
    """The relay's one link into its topic, ["[进话题 ›](…)"]: ``url`` (app/relay_send.py topic_url), else the "你问" block's
    (``meta``, cards/ui.py split_ask): a topic's turn's block opens that topic's thread too, at the same card. [] without
    either."""
    link = str(url or "") or str((meta or {}).get("url") or "")
    return [f"[{INTO_LABEL}]({link})"] if link else []


def summary(label, words, text):
    """The card's summary (the chat list's preview): "T41 · 有结果：…"."""
    return f"{label} · {words}：{redact(text)}" if text else f"{label} · {words}"


def relay_card(label, outcome, *, text="", question="", reason="", inputs=None, outputs=(), files=None,
               files_status=None, ask=None, at=None, took=None, artifacts=0, change=None, delivery="", notes=(),
               buttons=(), url="", avatar="", expand_icon=""):
    """(card, text): the relay's card (None for a reply over CARD_TEXT_BYTES: the Markdown alone), and
    the same as Markdown when the card is refused. Its first element says whose it is (cards/ui.py speaker_row: the
    topic's T number as its badge, its title, its state as a tag, what it did with the owner's words after it), so the
    card has no "你问" block. ``avatar``: the speaker's picture (an image key) when ``ask`` has none and no T number
    makes a badge.
    ``outcome`` DONE (``text`` the saved reply; ``inputs`` and ``outputs``, the answer card's 输入/输出 lines, which the
    foot (``foot``) keeps whole, with the 改动 line of ``change``, a dict; ``files``, its 产物 panel,
    cards/answer_card.py; ``delivery``, the 交付
    line an older release kept as a string, ``change`` of those, its fold; ``notes`` and ``buttons``, its other parts, as
    the answer card's tail takes them), WAITING (``question``) or STOPPED (``reason``, one line). A DONE reply is the
    card's body as it is, no conclusion band over it (its first words are its conclusion); a long one
    (``long_reply``) shows its opening, the rest folded under it (``reply_peek``).
    ``ask``: the "你问" block (cards/answer_card.py ask_block; a relay at the top level quoting no card, threaded):
    its words go to the speaker's row. One link ends the 输出 line, "进话题 ›" (``into``): ``url``, which opens the topic
    at this turn's card, else the block's own link, which opens the same thread (app/answer_cards.py ask_url) and was a
    second link, "看你那句 ›", to the same place. ``at``, ``took``,
    ``artifacts``: what a relay held (inline_pending) by an older release had besides, for a grey line no
    card has now, not shown; without ``inputs`` the foot has no 输入 line."""
    meta, _ = split_ask([ask] if ask else [])
    links = into(url, meta)
    key = {DONE: "result", WAITING: "waiting"}.get(outcome, "stopped")
    row = speaker_row(meta, outcome=key, label=label, avatar=avatar)
    style = dict(padding=BODY_PADDING, spacing=BODY_SPACING)
    if outcome == DONE:
        body = reply_body(text)
        lead = summary(label, look.word("result"), answer_lead(text, SUMMARY_CHARS))
        if len(body.encode("utf-8")) > CARD_TEXT_BYTES:
            return None, body
        # No conclusion band (T638): the band said the reply's first line again, large, over two rows. The reply's
        # first lines are in view as they are; a long reply folds the rest under them (docs/ui.md 5.2 聊天结果卡).
        shown_change = change or delivery
        line = shown_change if isinstance(shown_change, dict) and shown_change else None  # Its 改动 is a line of the foot.
        shown = drop_part_heading(body)  # Its first words say it: no "## 结论" row over them.
        reply = reply_peek(shown, icon_key=expand_icon) if shown.strip() else []  # A reply that fits is all of it, a longer one its opening.
        ending = foot(inputs, outputs, change=line, links=links)
        extra = [*answer_tail(files, (), (), change=None if line else shown_change, notes=notes),
                 *([check_element(shown_change)] if line and check_element(shown_change) else []), *(buttons or ())]
        tail = [*details(extra), *([ending] if ending else [])]
        built = banded(card([row, *reply, *tail], lead, update_multi=True, **style))
        # A long 改动 fold may take a card past its limit (as cards/review.py answer_card): the reply goes as
        # Markdown, its parts after it (app/relay_send.py send_once).
        return (built if json_size(built) <= ANSWER_CARD_BYTES else None), body
    elif outcome == WAITING:
        words = " ".join(str(question or "").split())
        body = words[:QUESTION_CHARS] + ("…" if len(words) > QUESTION_CHARS else "")
        # A short question is the band's 要你定 alone; a longer one goes under it whole, never said twice.
        short = len(words) <= HEADLINE_CHARS - 4
        key, headline, line = "waiting", "要你定：" + (words if short else "下面这个问题"), ""
        first = f"**{label} {look.word(key)}**"
        tail = f"在 {label} 的问题卡里答，或在这里回「{label} …」"
        lead = summary(label, look.word(key), words[:SUMMARY_CHARS])
    else:
        why = " ".join(str(reason or "").split())[:80]
        short = False
        key, body, tail = "stopped", "", f"详情在 {label}"
        headline, line = split_title(why) if why else ("没有说原因", "")
        first = f"**{label} {look.word(key)}**" + (f"：{why}" if why else "")
        lead = summary(label, look.word(key), why[:SUMMARY_CHARS])
    band = conclusion_band(band_label(key), literal(headline), literal(line))
    shown = body and not (key == "waiting" and short)
    ending = foot(None, (), links=links)
    elements = [row, band] + ([md(body)] if shown else []) + [note(tail)] + ([ending] if ending else [])
    markdown = "\n\n".join(part for part in (first, body, tail) if part)
    return styled(card(elements, lead, **style)), markdown


MERGED_SUBTITLE = "点一行进那个话题"
ROW_ID = "merged_row"


def merged_card(items, avatar=""):
    """(card, text): 做完了 relays that came close together (app/relay_send.py send_merged) as one card, the Markdown when
    the card is refused. ``items``: each relay's {label (T41), title, lead (its reply's first line), url (that opens
    its topic, when known)}, in the order they came. The speaker's row (``avatar``, a picture when given) says how many
    (有结果 tag); one block each, the topic's T number as its badge (cards/ui.py topic_badge), its title bold and its
    lead grey beside it, the whole block opening ``url``."""
    count = len(items)
    rows = []
    for item in items:
        label, title, url = str(item.get("label") or ""), literal(item.get("title") or ""), str(item.get("url") or "")
        badge = topic_badge(label, url=url)  # Its own link too: a click on it would not reach the block's.
        head = title if badge else " ".join(part for part in (literal(label), title) if part)
        lead = literal(item.get("lead") or "")
        words = "\n".join(part for part in (f"**{head}**" if head else "", grey(lead) if lead else "") if part)
        text = md(words or f"**{literal(label) or '话题'}**", size="normal_v2")
        inner = [{"tag": "column_set", "horizontal_spacing": "8px", "columns": [
            {"tag": "column", "width": "auto", "vertical_align": "top", "elements": [badge]},
            {"tag": "column", "width": "weighted", "weight": 1, "vertical_align": "center", "elements": [text]}]}] if badge else [text]
        row = container(inner, background="grey-50", radius="6px", padding="6px 10px 6px 10px", url=url)
        rows.append(row)
    head = speaker_row({"who": f"{count} 个话题做完了", "says": MERGED_SUBTITLE}, outcome="result", avatar=avatar)
    labels = "、".join(str(item.get("label") or "话题") for item in items)
    built = banded(card([head, *rows], summary(f"{count} 个话题", look.word("result"), labels), update_multi=True,
                        padding=BODY_PADDING, spacing=BODY_SPACING))
    lines = [f"**{count} 个话题做完了**"] + [
        "- " + " ".join(part for part in (str(item.get("label") or ""), str(item.get("title") or "")) if part)
        + (f"：{item['lead']}" if item.get("lead") else "") for item in items]
    return built, "\n".join(lines)
