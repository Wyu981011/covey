"""The card a topic turn's outcome takes back to the butler's top level (app/butler_relay.py, docs/butler.md
结论回到顶层): ``relay_card``, pure, and what it shares with the question card's copy there
(cards/question_cards.py mirror_card): a topic's reply as card Markdown (``reply_body``). ``merged_card``: 做完了 relays that
came close together, as one card (app/relay_send.py send_merged)."""
from __future__ import annotations

import re

from covey.cards.answer_card import JOINER, SEPARATOR, change_rows, check_element, part_label, tail as answer_tail, unbroken
from covey.cards.elements import card, collapsible, grey, json_size, md, note
from covey.cards.review import (ANSWER_CARD_BYTES, after_lead, answer_lead, bold_minor_headings,
                                inline_one_line_code)
from covey.cards.ui import (back_link, band_label, banded, conclusion_band, container, speaker_header, split_ask,
                            styled)
from covey.core.checkpoint import change_summary
from covey.core import look
from covey.core.failure import HEADLINE_CHARS, split_title
from covey.core.text import literal, redact

CARD_TEXT_BYTES = 24000  # A card is at most 30 KB (CardKit); a longer reply goes as Markdown messages.
QUESTION_CHARS = 300
SUMMARY_CHARS = 40
DONE, WAITING, STOPPED = "done", "waiting", "stopped"
# A reply longer than this (lines, characters) or with a table goes into a fold under the conclusion (``long_reply``).
FOLD_LINES, FOLD_CHARS = 6, 180
FOLD_ID = "relay_reply"
FOOT_ID = "relay_foot"
FOOT_PARTS = ("用时", "token")  # The figures of 输出 the footnote keeps.
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
    """Whether a reply goes into a fold on the relay: more than FOLD_LINES lines or FOLD_CHARS characters, or a table."""
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


def reply_fold(text, rows=()):
    """The reply in a fold closed under the conclusion: ``text`` (Markdown), then ``rows`` (the 改动's, as an open
    fold has them) under a small grey 改动."""
    inner = [md(text)]
    if rows:
        inner += [md(grey("改动"), size="notation"), *rows]
    return collapsible(FOLD_ID, fold_title(text), inner, quiet=True, spacing="6px")


def foot_line(inputs, outputs, *, change=None, links=()):
    """The 输入/输出 box as one small line (a relay's, FOOT_ID): 用时 and token of ``outputs`` (the parts
    cards/answer_card.py output_parts writes), the model of ``inputs`` (its parts, input_parts: the third), ``change`` (a
    dict's one-line summary, when the 改动 is in the reply's fold), then ``links`` (Markdown: 看你那句 ›, 进话题 ›) after a
    gap. None without anything."""
    parts = [unbroken(part) for part in outputs or () if part_label(str(part).replace(JOINER, "")) in FOOT_PARTS]
    model = [str(part).strip() for part in list(inputs or ())[2:3]]
    parts += [grey(unbroken(part)) for part in model if part not in ("", "—")]
    if isinstance(change, dict) and change:
        parts.append(grey(f"改动 · {literal(change_summary(change))}"))
    line = SEPARATOR.join(parts) + ("　" if parts and links else "") + "　".join(links)
    return md(line, size="notation", element_id=FOOT_ID) if line.strip() else None


def summary(label, words, text):
    """The card's summary (the chat list's preview): "T41 · 有结果：…"."""
    return f"{label} · {words}：{redact(text)}" if text else f"{label} · {words}"


def relay_card(label, outcome, *, text="", question="", reason="", inputs=None, outputs=(), files=None,
               files_status=None, ask=None, at=None, took=None, artifacts=0, change=None, delivery="", notes=(),
               buttons=(), url=""):
    """(card, text): the relay's card (None for a reply over CARD_TEXT_BYTES: the Markdown alone), and
    the same as Markdown when the card is refused. The title bar says whose it is (cards/ui.py speaker_header: the topic's
    T number and title, its state as a tag, what it did with the owner's words under it), so the card has no "你问" block.
    ``outcome`` DONE (``text`` the saved reply; ``inputs`` and ``outputs``, the answer card's 输入/输出 lines, of which a
    small line (``foot_line``) keeps 用时, token and the model; ``files``, its 产物 panel, cards/answer_card.py;
    ``change``, its 改动 fold: a dict, or ``delivery``, the 交付
    line an older release kept as a string; ``notes`` and ``buttons``, its other parts, as the answer card's tail
    takes them), WAITING (``question``) or STOPPED (``reason``, one line). A DONE reply that is long (``long_reply``) is
    in a fold under the conclusion and takes a dict ``change``'s rows with it.
    ``ask``: the "你问" block (cards/answer_card.py ask_block; a relay at the top level quoting no card, threaded):
    its words go to the title bar, its way back is "看你那句 ›" on the small line, with ``url``, which opens the topic,
    "进话题 ›". ``at``, ``took``,
    ``artifacts``: what a relay held (inline_pending) by an older release had besides, for a grey line no
    card has now, not shown; without ``inputs`` its box has no 输入 line."""
    meta, _ = split_ask([ask] if ask else [])
    links = [link for link in (back_link(meta), f"[进话题 ›]({url})" if url else "") if link]
    key = {DONE: "result", WAITING: "waiting"}.get(outcome, "stopped")
    header = speaker_header(meta, outcome=key, label=label)
    if outcome == DONE:
        body = reply_body(text)
        lead = summary(label, look.word("result"), answer_lead(text, SUMMARY_CHARS))
        if len(body.encode("utf-8")) > CARD_TEXT_BYTES:
            return None, body
        # The conclusion band (docs/ui.md 5.2 聊天结果卡): the reply's lead as its conclusion.
        conclusion = answer_lead(text, HEADLINE_CHARS)
        band = [conclusion_band("结论", literal(conclusion))] if conclusion else []
        # The band says the reply's first line: the reply under it starts after that line (cards/review.py after_lead).
        rest = after_lead(body, conclusion) if band else body
        folded = bool(rest.strip()) and long_reply(rest)
        shown_change = change or delivery
        rows = change_rows(shown_change) if folded else []
        reply = [reply_fold(rest, rows)] if folded else [md(rest)] if rest.strip() else []
        # A fold that took the 改动 leaves its one line to the small line below; a commit not found stays outside.
        foot = foot_line(inputs, outputs, change=shown_change if rows else None, links=links)
        tail = [*answer_tail(files, (), (), change=None if rows else shown_change, notes=notes),
                *([check_element(shown_change)] if rows and check_element(shown_change) else []),
                *([foot] if foot else []), *(buttons or ())]
        built = banded(card([*band, *reply, *tail], lead, update_multi=True, header=header))
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
    foot = foot_line(None, (), links=links)
    elements = [band] + ([md(body)] if shown else []) + [note(tail)] + ([foot] if foot else [])
    markdown = "\n\n".join(part for part in (first, body, tail) if part)
    return styled(card(elements, lead, header=header)), markdown


MERGED_SUBTITLE = "点一行进那个话题"
ROW_ID = "merged_row"


def merged_card(items):
    """(card, text): 做完了 relays that came close together (app/relay_send.py send_merged) as one card, the Markdown when
    the card is refused. ``items``: each relay's {label (T41), title, lead (its reply's first line), url (that opens
    its topic, when known)}, in the order they came. The title bar says how many (有结果 tag); one block each, its T number
    and title bold, its lead grey under it, the whole block opening ``url``."""
    count = len(items)
    rows = []
    for item in items:
        head = " ".join(part for part in (literal(item.get("label") or ""), literal(item.get("title") or "")) if part)
        lead = literal(item.get("lead") or "")
        words = f"**{head or '话题'}**" + (f"\n{grey(lead)}" if lead else "")
        row = container([md(words, size="normal_v2")], background="grey-50", radius="6px", padding="6px 10px 6px 10px",
                        url=str(item.get("url") or ""))
        rows.append(row)
    found = look.STATES["result"]
    header = {"title": {"tag": "plain_text", "content": f"{count} 个话题做完了"},
              "subtitle": {"tag": "plain_text", "content": MERGED_SUBTITLE},
              "text_tag_list": [{"tag": "text_tag", "text": {"tag": "plain_text", "content": found.word},
                                 "color": found.color}],
              "template": "default", "icon": {"tag": "standard_icon", "token": found.icon, "color": found.color}}
    labels = "、".join(str(item.get("label") or "话题") for item in items)
    built = card(rows, summary(f"{count} 个话题", look.word("result"), labels), update_multi=True, header=header)
    lines = [f"**{count} 个话题做完了**"] + [
        "- " + " ".join(part for part in (str(item.get("label") or ""), str(item.get("title") or "")) if part)
        + (f"：{item['lead']}" if item.get("lead") else "") for item in items]
    return built, "\n".join(lines)
