"""The card a topic turn's outcome takes back to the butler's top level (app/butler_relay.py, docs/butler.md
结论回到顶层): ``relay_card``, pure, and what it shares with the question card's copy there
(cards/question_cards.py mirror_card): a topic's reply as card Markdown, whole (``reply_body``, ``reply_shown``; both in
cards/review.py, where the answer card in a topic's thread takes them too). ``merged_card``: 做完了 relays that came close together, as one card
(app/relay_send.py send_merged)."""
from __future__ import annotations

from covey.cards.answer_card import check_element, details, facts_element, words_fold
from covey.cards.answer_card import tail as answer_tail
from covey.cards.elements import card, grey, json_size, md, note
from covey.cards.review import ANSWER_CARD_BYTES, answer_lead, drop_part_heading, reply_body, reply_shown
from covey.cards.ui import (BODY_PADDING, BODY_SPACING, band_label, banded, conclusion_band, container, speaker_row,
                            split_ask, styled, topic_badge)
from covey.core import look
from covey.core.failure import HEADLINE_CHARS, split_title
from covey.core.text import literal, redact

CARD_TEXT_BYTES = 24000  # A card is at most 30 KB (CardKit); a longer reply goes as Markdown messages.
QUESTION_CHARS = 300
SUMMARY_CHARS = 40
REASON_CHARS = 200  # A stop's reason and next step (core/failure.py failure_view's title), before the band splits them.
DONE, WAITING, STOPPED = "done", "waiting", "stopped"
NOTE_ID = "relay_note"  # A 停住了 card's last line (``stop_note``), redrawn after a click on its buttons (app/relay_stops.py).


def stop_note(label, why=""):
    """The last line of a 停住了 relay (NOTE_ID): "详情在 T439"; after a click that started nothing (the topic had a task at work,
    a result still could not be sent), why, its buttons kept: "没有开始：… · 详情在 T439"."""
    words = f"详情在 {label}"
    why = " ".join(str(why or "").split()).rstrip("。")
    return md(grey(literal(f"没有开始：{why} · {words}" if why else words)), element_id=NOTE_ID, size="notation")


def foot(inputs, outputs, *, change=None):
    """What ends a relay (FACTS_ID, cards/answer_card.py facts_element): its 输入 and 输出 lines and the 改动 line of a
    turn that changed code (a dict); None without them. No link ends it: the row opens the topic."""
    return facts_element(inputs, outputs, change=change) if inputs or outputs or change else None


def into(url, meta) -> str:
    """Where a click on the relay's row goes, into its topic: ``url`` (app/relay_send.py topic_url), else the "你问"
    block's (``meta``, cards/ui.py split_ask): a topic's turn's block opens that topic's thread too, at the same card.
    '' without either."""
    return str(url or "") or str((meta or {}).get("url") or "")


def summary(label, words, text):
    """The card's summary (the chat list's preview): "T41 · 有结果：…"."""
    return f"{label} · {words}：{redact(text)}" if text else f"{label} · {words}"


def relay_card(label, outcome, *, text="", question="", reason="", inputs=None, outputs=(), files=None,
               files_status=None, ask=None, at=None, took=None, artifacts=0, change=None, delivery="", notes=(),
               buttons=(), url="", avatar=""):
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
    card's body as it is, whole, no conclusion band over it (its first words are its conclusion). A STOPPED ``reason`` is
    core/failure.py failure_view's title: the band says the reason and, on its second line, the next step; its ``buttons``
    go under it (app/relay_stops.py area: 检查并继续 and 看原因, redrawn in place once clicked: a shared card, ``update_multi``).
    ``ask``: the "你问" block (cards/answer_card.py ask_block; a relay at the top level quoting no card, threaded):
    who and what it did go to the speaker's row, the owner's words to one line under it that opens (``words_fold``).
    The row is the way into the topic (``into``: ``url``, which opens it at this turn's card, else the block's own
    link, the same thread): a click anywhere on it, no "进话题 ›" at the end (the owner, 2026-11-22). ``at``, ``took``,
    ``artifacts``: what a relay held (inline_pending) by an older release had besides, for a grey line no
    card has now, not shown; without ``inputs`` the foot has no 输入 line."""
    meta, _ = split_ask([ask] if ask else [])
    link = into(url, meta)
    key = {DONE: "result", WAITING: "waiting"}.get(outcome, "stopped")
    row = speaker_row(meta, outcome=key, label=label, avatar=avatar, url=link)
    said = [part for part in (words_fold(meta),) if part]  # What the owner said, one line that opens.
    style = dict(padding=BODY_PADDING, spacing=BODY_SPACING)
    if outcome == DONE:
        body = reply_body(text)
        lead = summary(label, look.word("result"), answer_lead(text, SUMMARY_CHARS))
        if len(body.encode("utf-8")) > CARD_TEXT_BYTES:
            return None, body
        # No conclusion band (T638): the band said the reply's first line again, large, over two rows. The reply as it
        # is, whole (docs/ui.md 5.2 聊天结果卡).
        shown_change = change or delivery
        line = shown_change if isinstance(shown_change, dict) and shown_change else None  # Its 改动 is a line of the foot.
        shown = drop_part_heading(body)  # Its first words say it: no "## 结论" row over them.
        reply = reply_shown(shown) if shown.strip() else []  # Whole (the owner, 2026-11-22: 不折叠，直接展示全文).
        ending = foot(inputs, outputs, change=line)
        extra = [*answer_tail(files, (), (), change=None if line else shown_change, notes=notes),
                 *([check_element(shown_change)] if line and check_element(shown_change) else []), *(buttons or ())]
        tail = [*details(extra), *([ending] if ending else [])]
        built = banded(card([row, *said, *reply, *tail], lead, update_multi=True, **style))
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
        why = " ".join(str(reason or "").split())[:REASON_CHARS]
        short = False
        key, body, tail = "stopped", "", f"详情在 {label}"
        headline, line = split_title(why) if why else ("没有说原因", "")
        first = f"**{label} {look.word(key)}**" + (f"：{why}" if why else "")
        lead = summary(label, look.word(key), headline[:SUMMARY_CHARS])
    band = conclusion_band(band_label(key), literal(headline), literal(line))
    shown = body and not (key == "waiting" and short)
    acts = list(buttons or ()) if outcome == STOPPED else []  # Its next steps, under the reason (app/relay_stops.py).
    elements = [row, *said, band] + ([md(body)] if shown else []) + acts + [
        stop_note(label) if outcome == STOPPED else note(tail)]
    markdown = "\n\n".join(part for part in (first, body, tail) if part)
    return styled(card(elements, lead, update_multi=outcome == STOPPED, **style)), markdown


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
