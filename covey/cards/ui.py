"""The shared parts of the 夜航 look (docs/ui.md) as schema 2.0 card elements: the conclusion band, the 要你做 bar, the segment bar, a state's dot and pill, a topic row, the speaker's row. Words and colours come from core/look.py;
no card here is sent by itself, the cards that move to this look use these parts (docs/ui.md 怎么开工).

- ``conclusion_band``: the visual centre of a card. A small label, the headline, a grey line, then ``below`` (a
  ``todo_bar`` or a ``seg_bar``), each a row of its own on a background a step lighter than the row above (core/look.py
  BAND: a gradient in steps too fine to see), inside one thin line. Its colours are the card's own: a card with a band
  goes through ``styled``, which puts them in its ``config.style.color``.
- ``seg_bar``: how many of each state, as one line of coloured bars as long as their counts, and a legend under it.
- ``speaker_row``: the first element of a card at the private chat's top level, which says who speaks (docs/ui.md 5.3):
  the speaker's picture, its name bold and what it did with the owner's words grey, a topic's state as a coloured tag.
  It takes what the "你问" block (cards/answer_card.py ask_block, ``ASK_META``) carried, so the card does not have the
  block as well (``split_ask``); the block's link (back to the owner's message, or into a topic's thread) is the row
  itself: a click anywhere on it opens it, and no "看你那句 ›" or "进话题 ›" ends the card. The picture is an image key the caller made
  (app/answer_cards.py ``avatar``): cards make no network calls. A topic has no picture: its T number is its
  badge (``topic_badge``), white on the topic's own colour, and its title follows alone.
- ``peek``: a settled question's opening in view and the rest one click away, a fold whose title is that opening
  (cards/review.py ``opening`` cuts it) and whose body goes on from there. Answers and a turn's output are not folded:
  they are shown whole (the owner, 2026-11-22).
- ``topic_row``: a state's dot and word, ``T31 title ›``, a line in words, grey figures; buttons at the right; the
  whole opens ``url``.

Colours a card defines itself (``config.style.color``: the band's, a badge's) are put there by ``styled`` or
``banded``, the last thing a card with them goes through.
"""
from __future__ import annotations

import re

from covey.cards.elements import chevron, grey, md
from covey.core import look
from covey.core.text import literal

EDGE, GAP = "10px", "3px"  # A band row's padding at the band's top and bottom edge, and between two rows.
SIDE = "14px"
SEG_WIDTH = 24  # Characters of the segment bar: wide enough to read the parts, narrow enough for a topic's side panel.
SEG_CHAR = "━"


def font(text, color) -> str:
    return f"<font color='{color}'>{text}</font>"


def speaker(who) -> str:
    """说话人 (docs/ui.md 第 4 节 ``speaker``): who speaks, bold in the brand colour; '' for no one. What follows it
    on the line (what it does, when, ›) is grey, as the caller writes it."""
    return font("**" + literal(" ".join(str(who or "").split())) + "**", look.BRAND["color"]) if who else ""


# Feishu's ``neutral`` is a grey tag but near-black text: a background state's words, dot and bar part are ``grey``
# (docs/ui.md 2.2: neutral 或 grey; else 做完 reads as a black bar).
INK = {"neutral": "grey"}


def ink(key) -> str:
    """A state's colour for text, a dot or a bar part (``<font>``)."""
    color = look.STATES[key].color
    return INK.get(color, color)


def dot(key) -> str:
    """A state's dot, in its colour."""
    return font("●", ink(key))


def state_word(key, *, heading=False) -> str:
    """A state's dot and its word in bold, both in its colour: how a row says its state."""
    found = look.STATES[key]
    return f"{dot(key)} {font('**' + (look.group_word(key) if heading else found.word) + '**', ink(key))}"


def state_pill(key) -> str:
    """A state's word as a coloured tag (cards/board.py pill's look)."""
    found = look.STATES[key]
    return f"<text_tag color='{found.color}'>{found.word}</text_tag>"


def empty_words(*, first=False, when=""):
    """What a card with nothing asking for the owner says when "都在掌握中" would mislead (docs/ui.md 7 空状态):
    (headline in Markdown, grey line, the title bar's tag) for ``first`` (he has had no topic yet: say what to do) or
    a record as of ``when`` (a time as the 看板 says it: what it lists is not now); None for a clear board, which
    keeps its own words (都在掌握中, 现在没有在等你的事)."""
    if first:
        return "**还没有话题**", "在私聊里发一句要做的事，第一个话题从这里开始", "还没有话题"
    if when:
        return (f"**{literal(when)} 时没有等你的事**", f"这是 {literal(when)} 的记录，不是现在的；点刷新看现在的",
                f"{literal(when)} 的记录")
    return None


def container(elements, *, background="", border="", radius="10px", padding="0px", spacing="2px", url="") -> dict:
    box = {"tag": "interactive_container", "width": "fill", "padding": padding, "corner_radius": radius,
           "vertical_spacing": spacing}
    if background:
        box["background_style"] = background
    if border:
        box["has_border"] = True
        box["border_color"] = border
    else:
        box["has_border"] = False
    box["elements"] = elements
    if url:
        box["behaviors"] = [{"type": "open_url", "default_url": url}]
    return box


def side_by_side(left, right, *, align="top") -> dict:
    """``left`` (elements) filling the width, ``right`` (elements) as wide as it needs, side by side."""
    columns = [{"tag": "column", "width": "weighted", "weight": 1, "vertical_align": align, "vertical_spacing": "2px",
                "elements": left}]
    if right:
        columns.append({"tag": "column", "width": "auto", "vertical_align": align, "elements": right})
    return {"tag": "column_set", "flex_mode": "none", "horizontal_spacing": "8px", "columns": columns}


def conclusion_band(label, headline, line="", *, below=(), url="") -> dict:
    """The conclusion band: ``label`` (small, the brand's colour), ``headline`` (Markdown, large), ``line`` (grey),
    then ``below`` (elements, one row together), each row a step lighter than the one above, inside one thin line.
    The card it is on goes through ``styled``."""
    rows = [[md(font(label, look.BRAND["color"]), size="notation")], [md(headline, size="heading")]]
    if line:
        rows.append([md(grey(line), size="notation")])
    if below:
        rows.append(list(below))
    rows = rows[:look.BAND["rows"]]
    last = len(rows) - 1
    boxes = [container(row, background=f"band-{n}", radius="0px", spacing="4px",
                       padding=f"{EDGE if n == 0 else GAP} {SIDE} {EDGE if n == last else GAP} {SIDE}")
             for n, row in enumerate(rows)]
    return container(boxes, border="band-line", radius="10px", spacing="0px", url=url)


def _colored(card, colors) -> dict:
    config = card.setdefault("config", {})
    style = config.setdefault("style", {})
    style["color"] = {**style.get("color", {}), **colors}
    return card


def styled(card) -> dict:
    """``card`` (cards/elements.py card) with the colours of the band in its ``config.style.color``, and those of the
    topic badges on it (``badge_colors``), beside any it has."""
    return _colored(card, {**look.band_colors(), **badge_colors(card.get("body"))})


def has_band(elements) -> bool:
    """Whether ``elements`` (a card body's) have a conclusion band among them."""
    return any(isinstance(e, dict) and e.get("border_color") == "band-line" for e in elements or ())


def banded(card) -> dict:
    """``card`` ``styled`` when its body has a conclusion band (``has_band``), else with the colours of its topic
    badges alone, else as it is: the last step of a card that may have either (an answer card's head, a question
    card's copy, a relay, the merged relay, a tail card)."""
    if has_band(card.get("body", {}).get("elements")):
        return styled(card)
    colors = badge_colors(card.get("body"))
    return _colored(card, colors) if colors else card


# 话题头像 (docs/ui.md 4): the badge a topic has where a speaker has a picture.
BADGE_COLOR = "topic-{}"  # The config.style.color name of core/look.py TOPIC_COLORS[n].
BADGE_HEIGHT = "28px"  # As tall as a speaker's picture (AVATAR_SIZE).
_BADGE = re.compile(r"topic-(\d+)")


def topic_badge(label, url=""):
    """A topic's badge: its T number ``label`` ("T12") bold and white on the topic's own colour (core/look.py
    topic_color), a rounded block as tall as a speaker's picture and as wide as the number, so T7, T1234 and T12345
    all read at the same size. ``url``: what a click on it opens (inside a block that opens it: the click stops at
    the badge). None for a label without a number. The card it is on ends with ``banded`` or ``styled``: they put
    its colour in the card's config."""
    place = look.topic_color(label)
    if place < 0:
        return None
    words = md(font("**" + literal(" ".join(str(label).split())) + "**", "white"), size="notation")
    badge = {"tag": "interactive_container", "width": "auto", "height": BADGE_HEIGHT, "padding": "0px 8px 0px 8px",
             "corner_radius": "8px", "background_style": BADGE_COLOR.format(place), "has_border": False,
             "horizontal_align": "center", "vertical_align": "center", "elements": [words]}
    if url:
        badge["behaviors"] = [{"type": "open_url", "default_url": url}]
    return badge


def badge_colors(node) -> dict:
    """The ``config.style.color`` entries of the topic badges in ``node`` (a card's body, any element), at any depth:
    each badge's colour, the same in light and dark mode (white words on it either way)."""
    found = set()

    def walk(value):
        if isinstance(value, dict):
            style = value.get("background_style")
            matched = _BADGE.fullmatch(style) if isinstance(style, str) else None
            if matched and value.get("tag") == "interactive_container":
                found.add(int(matched.group(1)))
            for each in value.values():
                walk(each)
        elif isinstance(value, list):
            for each in value:
                walk(each)
    walk(node)
    colors = {}
    for place in sorted(found):
        if place < len(look.TOPIC_COLORS):
            rgba = _hex_rgba(look.TOPIC_COLORS[place])
            colors[BADGE_COLOR.format(place)] = {"light_mode": rgba, "dark_mode": rgba}
    return colors


def _hex_rgba(color) -> str:
    color = color.lstrip("#")
    return f"rgba({int(color[0:2], 16)},{int(color[2:4], 16)},{int(color[4:6], 16)},1)"


_NUMBER = re.compile(r"(T\d+)(?:\s+(.*))?", re.S)


def split_number(who):
    """(T number, title) of a topic's speaker words, "T12 标题" -> ("T12", "标题"); ('', ``who``) when they do not
    start with a T number."""
    found = _NUMBER.fullmatch(" ".join(str(who or "").split()))
    return (found.group(1), found.group(2) or "") if found else ("", str(who or ""))


# A text with a grey label before it ("这一轮输出"): answers and outputs are shown whole (docs/ui.md 5.2).
def labelled(text, label, raw=None) -> str:
    """``text`` with ``label`` grey before it, on a line of its own when ``raw`` (``text`` as written) starts a block."""
    if not label:
        return text
    return grey(label) + ("\n" if _BLOCK_START.match(str(text if raw is None else raw)) else " ") + text


_BLOCK_START = re.compile(r" {0,3}(?:[-*+]\s|\d{1,9}[.)]\s|>|#{1,6}\s|\|)")


# 露一截 for a short text in a fold's title (a settled question): its opening in view, the rest a click away.
def peek(element_id, head, rest, *, hint="", label="", spacing="4px") -> dict:
    """犹抱琵琶半遮面: a fold whose title is ``head`` (Markdown, the text's opening as cards/review.py opening cut it),
    ``label`` grey before it and ``hint`` grey after it (how much there is in all), and whose body is ``rest``
    (Markdown going on from where ``head`` stopped, or elements). No frame: the opening reads as the text it is, the
    chevron at the right says there is more; opened, the rest follows it as if never cut."""
    title = " ".join(part for part in (grey(label) if label else "", head, grey(hint) if hint else "") if part)
    body = [md(rest)] if isinstance(rest, str) else list(rest)
    return {"tag": "collapsible_panel", "element_id": element_id, "expanded": False,
            "header": {"title": {"tag": "markdown", "content": title}, "vertical_align": "center",
                       "icon": chevron(), "icon_position": "right", "icon_expanded_angle": -180},
            "padding": "0px 0px 0px 0px", "vertical_spacing": spacing, "elements": body}


TITLE_CHARS = 24  # Characters of a topic's title a band's label shows (as core/look.py SPEAKER_TITLE).


def band_label(key, *parts) -> str:
    """A band's label: ``key``'s word (core/look.py STATES), then ``parts`` (a T number, a title, a task's number)
    that say something, "有结果 · T12 改看板"; a part over TITLE_CHARS ends with "…"."""
    shown = [" ".join(str(part or "").split()) for part in parts]
    shown = [part if len(part) <= TITLE_CHARS else part[:TITLE_CHARS - 1] + "…" for part in shown if part]
    return literal(" · ".join([look.word(key), " ".join(shown)] if shown else [look.word(key)]))


def number(value, unit) -> str:
    """A headline figure: the number in the brand's colour, its unit after it (``2 件事``)."""
    return f"{font('**' + str(value) + '**', look.BRAND['color'])} **{unit}**"


def todo_bar(text, *, label="要你做") -> dict:
    """The one thing asked of the owner, on white inside the band: ``label`` in the waiting colour, then ``text``."""
    return container([md(f"{font('**' + label + '**', look.STATES['waiting'].color)}　{literal(text)}", size="notation")],
                     background="bg-white", radius="8px", padding="6px 8px 6px 8px")


def seg_bar(counts) -> list:
    """``counts`` ({state key: how many}, in the order given) as a bar of coloured parts and a legend line; [] when
    nothing counts. Each part is at least one character long."""
    parts = [(key, int(n)) for key, n in counts.items() if int(n or 0) > 0]
    if not parts:
        return []
    total = sum(n for _, n in parts)
    widths = [max(1, round(SEG_WIDTH * n / total)) for _, n in parts]
    widths[widths.index(max(widths))] += SEG_WIDTH - sum(widths)  # The longest part takes the rounding.
    bar = "".join(font(SEG_CHAR * width, ink(key)) for (key, _), width in zip(parts, widths))
    legend = "　".join(f"{dot(key)} {grey(f'{n} {look.STATES[key].word}')}" for key, n in parts)
    return [md(bar, size="notation"), md(legend, size="notation")]


def topic_row(key, head, line="", figures=(), *, url="", buttons=()) -> dict:
    """One topic: ``key``'s dot and word, ``head`` (``T31 title``) and › when it opens ``url``, ``line`` in words,
    ``figures`` grey; ``buttons`` (elements) at the right."""
    left = [md(f"{state_word(key)} **{literal(head)}**" + (f"　{grey('›')}" if url else ""), size="normal_v2")]
    if line:
        left.append(md(literal(line), size="normal_v2"))
    shown = " ｜ ".join(literal(part) for part in figures if part)
    if shown:
        left.append(md(grey(shown), size="notation"))
    return container([side_by_side(left, list(buttons), align="center")], padding="6px 4px 6px 4px", radius="8px",
                     url=url)


DONE_MARK = "✓"  # The mark the setting cards' notices started with before docs/ui.md 5.2.
PROBLEM_MARK = "⚠️"  # A notice of a change that did not happen, or of something to fix first.


def receipt(text) -> dict:
    """What a setting card says after a change (docs/ui.md 5.2: 保存后用一句灰字回执): one grey line in small print, the
    ✓ it used to start with left off. One that starts with ⚠️ (the change did not happen, or something comes first)
    says so in the body's size and colour."""
    text = str(text or "").strip()
    if text.startswith(PROBLEM_MARK):
        return md(text)
    if text.startswith(DONE_MARK):
        text = text[len(DONE_MARK):].lstrip()
    return md(grey(text), size="notation")


ASK_META = "_ask"  # The key of the "你问" block (cards/answer_card.py ask_block) that holds what a title bar says; never sent.
ASK_ID = "answer_ask"
SUBTITLE_WORDS = 18  # Characters of the owner's words a butler card's subtitle quotes.
# What the topic did with the owner's words (cards/answer_card.py SAYS ``doing``) -> the look.STATES key of its tag.
TOPIC_TAGS = {"done": "result", "waiting": "waiting", "member": "waiting", "stopped": "stopped", "running": "running"}


def split_ask(elements):
    """(what the "你问" block among ``elements`` carried (``ASK_META``), ``elements`` without it); None and the same
    list when there is none: a block saved before the title bar kept its own look."""
    rest, meta = [], None
    for element in elements or ():
        found = element.get(ASK_META) if isinstance(element, dict) else None
        if meta is None and isinstance(found, dict):
            meta = found
        else:
            rest.append(element)
    return meta, rest


def role_of(who) -> str:
    """"butler", "lead" or "topic": whose words ``who`` (core/look.py speaker) is."""
    if who == look.SPEAKERS["butler"]:
        return "butler"
    return "lead" if str(who or "").startswith("专项「") else "topic"


def _tag(text, color) -> str:
    return f"<text_tag color='{color}'>{literal(text)}</text_tag>"


AVATAR_SIZE = "28px 28px"
ROW_ID = "speaker_row"


def speaker_row(meta, *, outcome="", label="", tag=None, avatar="", url=None) -> dict:
    """The first element of a card at the private chat's top level, which says who speaks (docs/ui.md 5.3): the speaker's
    picture (``avatar``, its image key, else the ``avatar`` of ``meta``; none: the line alone) and one line, the name
    bold and what it did with the owner's words grey, "**管家** 回你 20:41「原话前 18 字…」"; a lead "**<专项名> ·
    负责人** 汇报你 …", a topic "[T439] **标题** [有结果] 做完了你 12:31 交代的事": a topic's T number is its badge
    (``topic_badge``) in the picture's place, whatever picture was given, and its title alone is the name. A topic's
    state is a tag (``outcome``: a look.STATES key a relay knows itself, else the ``outcome`` of ``meta``); a state
    that asks for the owner (等你, 停住了) is the tag of the other two as well. Without a block (``meta`` None) the name
    is ``label`` (the T number) and nothing follows it. ``tag``: (text, colour) in place of the state's, for a card
    that is settled.

    ``url`` (else the ``url`` of ``meta``: the owner's message for the butler and a lead, the topic's thread for a
    topic): what a click anywhere on the row opens (the owner, 2026-11-22: 点卡头就能进话题、跳回原话), the line ending
    with a grey ›; a card with such a row has no "看你那句 ›" or "进话题 ›" at its end. ``url=""``: no link whatever the
    block says (a topic's card in its own thread)."""
    meta = meta or {"who": label}
    link = str(meta.get("url") or "") if url is None else str(url or "")
    who, doing = str(meta.get("who") or ""), str(meta.get("doing") or "")
    role, key = role_of(who), outcome or str(meta.get("outcome") or "") or TOPIC_TAGS.get(doing, "")
    says, words = str(meta.get("says") or ""), " ".join(str(meta.get("words") or "").split())
    at = str(meta.get("at") or "")
    if role != "topic" and doing == "answer" and meta.get("verb", "你问") == "你问" and (at or words):
        quote = words if len(words) <= SUBTITLE_WORDS else words[:SUBTITLE_WORDS - 1] + "…"
        says = f"回你{' ' + at if at else ''}" + (f"「{quote}」" if quote else "")
    if role == "lead":
        says = says.replace("做完了你", "汇报你", 1)
    asks = key in ("waiting", "stopped", "stuck")
    found = look.STATES.get(key)
    tags = [_tag(*tag)] if tag else [_tag(found.word, found.color)] if found and (asks or role == "topic") else []
    name = " ".join((who or look.SPEAKERS["butler"]).split())
    if role == "lead":
        name = name.removeprefix("专项「").replace("」· 负责人", " · 负责人")
    number, title = split_number(name) if role == "topic" else ("", name)
    badge = topic_badge(number, url=link) if number else None  # Its own link too: a click on it stops there.
    if badge:
        name = title
    line = " ".join(part for part in (f"**{literal(name)}**" if name else "", *tags,
                                      grey(literal(says)) if says else "", grey("›") if link else "") if part)
    text = md(line, size="normal_v2")
    picture = avatar or str(meta.get("avatar") or "")
    if badge:
        first = badge
    elif picture:
        # No preview: a click on the picture opens what the row opens, not the picture.
        first = {"tag": "img", "img_key": picture, "size": AVATAR_SIZE, "scale_type": "crop_center",
                 "alt": {"tag": "plain_text", "content": ""}, **({"preview": False} if link else {})}
    else:
        first = None
    row = {"tag": "column_set", "horizontal_spacing": "8px", "columns": [
        {"tag": "column", "width": "auto", "vertical_align": "center", "elements": [first]},
        {"tag": "column", "width": "weighted", "weight": 1, "vertical_align": "center", "elements": [text]}]} if first else text
    if not link:
        return {**row, "element_id": ROW_ID}
    return {"tag": "interactive_container", "element_id": ROW_ID, "width": "fill", "padding": "0px",
            "corner_radius": "6px", "has_border": False, "elements": [row],
            "behaviors": [{"type": "open_url", "default_url": link}]}


BODY_SPACING, BODY_PADDING = "6px", "10px 12px 10px 12px"  # The body of a card that opens with a speaker's row.
