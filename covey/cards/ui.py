"""The shared parts of the 夜航 look (docs/ui.md) as schema 2.0 card elements: the conclusion band, the 要你做 bar, the segment bar, a state's dot and pill, a topic row. Words and colours come from core/look.py;
no card here is sent by itself, the cards that move to this look use these parts (docs/ui.md 怎么开工).

- ``conclusion_band``: the visual centre of a card. A small label, the headline, a grey line, then ``below`` (a
  ``todo_bar`` or a ``seg_bar``), each a row of its own on a background a step lighter than the row above (core/look.py
  BAND: a gradient in steps too fine to see), inside one thin line. Its colours are the card's own: a card with a band
  goes through ``styled``, which puts them in its ``config.style.color``.
- ``seg_bar``: how many of each state, as one line of coloured bars as long as their counts, and a legend under it.
- ``speaker_header``: the title bar of a card at the private chat's top level, which says who speaks (docs/ui.md 5.3):
  the butler indigo, a project's lead violet, a topic's default with its state as a coloured tag. It takes what the
  "你问" block (cards/answer_card.py ask_block, ``ASK_META``) carried, so the card does not have the block as well
  (``split_ask``); the block's link back to the owner's message stays as a line ``ask_footnote``.
- ``topic_row``: a state's dot and word, ``T31 title ›``, a line in words, grey figures; buttons at the right; the
  whole opens ``url``.
"""
from __future__ import annotations

from covey.cards.elements import grey, md
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


def styled(card) -> dict:
    """``card`` (cards/elements.py card) with the colours of the band in its ``config.style.color``, beside any it has."""
    config = card.setdefault("config", {})
    style = config.setdefault("style", {})
    style["color"] = {**style.get("color", {}), **look.band_colors()}
    return card


def has_band(elements) -> bool:
    """Whether ``elements`` (a card body's) have a conclusion band among them."""
    return any(isinstance(e, dict) and e.get("border_color") == "band-line" for e in elements or ())


def banded(card) -> dict:
    """``card`` ``styled`` when its body has a conclusion band (``has_band``), else as it is: for the cards that
    take a band from their caller (an answer card's head, a question card's copy)."""
    return styled(card) if has_band(card.get("body", {}).get("elements")) else card


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
BACK_LABEL = "看你那句 ›"
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


def _tag(text, color) -> dict:
    return {"tag": "text_tag", "text": {"tag": "plain_text", "content": text}, "color": color}


def _icon(token, color) -> dict:
    return {"tag": "standard_icon", "token": token, "color": INK.get(color, color)}


def speaker_header(meta, *, outcome="", label="", tag=None) -> dict:
    """The title bar for the block ``meta`` came from. The butler: indigo, 管家, "回你 20:41「原话前 18 字…」" and a 答复
    tag. A lead: violet, its name 负责人, what it did with the owner's words, a 专项 tag. A topic: default, its T number
    and title, the same sentence, its state as a tag. ``outcome``: a look.STATES key that sets the topic's tag (a relay
    knows its own); a state that asks for the owner (等你, 停住了) is the tag of the other two as well. Without a block
    (``meta`` None) the title is ``label`` (the T number) and there is no subtitle. ``tag``: (text, colour) in place of
    the state's, for a card that is settled."""
    meta = meta or {"who": label}
    who, doing = str(meta.get("who") or ""), str(meta.get("doing") or "")
    role, key = role_of(who), outcome or TOPIC_TAGS.get(doing, "")
    says, words = str(meta.get("says") or ""), " ".join(str(meta.get("words") or "").split())
    at = str(meta.get("at") or "")
    if role == "butler" and doing == "answer" and meta.get("verb", "你问") == "你问" and (at or words):
        quote = words if len(words) <= SUBTITLE_WORDS else words[:SUBTITLE_WORDS - 1] + "…"
        says = f"回你{' ' + at if at else ''}" + (f"「{quote}」" if quote else "")
    asks = key in ("waiting", "stopped", "stuck")
    if role == "butler":
        template, icon, color = "indigo", "robot_outlined", "indigo"
        tags = [_tag(look.STATES[key].word, look.STATES[key].color) if asks else _tag("答复", "indigo")]
    elif role == "lead":
        template, icon, color = "violet", "group_outlined", "violet"
        tags = [_tag("专项", "violet"), *([_tag(look.STATES[key].word, look.STATES[key].color)] if asks else [])]
    else:
        found = look.STATES.get(key)
        template, icon, color = "default", (found.icon if found and found.icon else "chat_outlined"), \
            (found.color if found else "grey")
        tags = [_tag(found.word, found.color)] if found else []
    if tag:
        tags = [_tag(*tag)]
    head = {"title": {"tag": "plain_text", "content": " ".join((who or look.SPEAKERS["butler"]).split())}}
    if says:
        head["subtitle"] = {"tag": "plain_text", "content": says}
    head["text_tag_list"] = tags
    head["template"] = template
    head["icon"] = _icon(icon, color)
    return head


def back_link(meta) -> str:
    """The link back to the owner's message the block opened, "[看你那句 ›](url)"; '' without a place to open."""
    url = str((meta or {}).get("url") or "")
    return f"[{BACK_LABEL}]({url})" if url else ""


def ask_footnote(meta):
    """The line that keeps the block's way back to the owner's message once the title bar says the rest: one small
    Markdown element; None without a link."""
    link = back_link(meta)
    return md(link, size="notation", element_id=ASK_ID) if link else None
