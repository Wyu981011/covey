"""The topic's status card (话题状态卡, app/status_cards.py): what the pinned board pins for a topic with a thread, so
the Pin panel, which shows a card's top alone and lets nothing on it be clicked, says what the topic is, where it is
and what came of it. Three lines and no title bar (sample A): the topic's
number and title in bold, its state as a coloured tag with when and which round, then one small line (this round's
request, the question, the conclusion or why it stopped). No buttons: clicking the pin opens the topic's thread.

Its state is a core/look.py STATES key, the word and colour the table's, as the 看板 and 手上的事 say it (docs/ui.md 2.2,
3): 等你 and 可能卡住 orange, 停住了 red, 有结果 green, 在做 blue, 做完 (a result seen), 已停止 (the owner's own stop) and
排队 grey."""
from __future__ import annotations

from covey.core import look
from covey.core.text import literal
from covey.cards.elements import card, md

# A card's record from an older release keeps the words it showed (app/status_cards.py ``shown``, app/tidy_apply.py draws
# it again until the board's next round writes the key): read as the key each was. 做完 was every result's word there,
# in green: 有结果. A word older still is shown as it is, grey.
LEGACY = {"在做": "running", "排队": "queued", "等你": "waiting", "可能卡住": "stuck", "做完": "result", "停住了": "stopped",
          "已停止": "cancelled"}


def state_key(state) -> str:
    """The core/look.py STATES key of ``state`` (a key, or a word an older card showed: LEGACY); '' for neither."""
    state = str(state or "")
    return state if state in look.STATES else LEGACY.get(state, "")


def status_tag(state):
    """The state as a tag of its colour: its word and colour from core/look.py STATES (one it does not know as it is, grey)."""
    key = state_key(state)
    if not key:
        return f"<text_tag color='neutral'>{_shown(state)}</text_tag>"
    found = look.STATES[key]
    return f"<text_tag color='{found.color}'>{found.word}</text_tag>"


def status_word(state) -> str:
    key = state_key(state)
    return look.word(key) if key else _one_line(state)


def status_card(title, state, facts, line, joined=None):
    """``title`` "T32 · 调研…"; ``state`` a core/look.py STATES key (``state_key``); ``facts`` the rest of its line
    ("13:01 · 2 轮 · 用时 5 分 49 秒"); ``line`` the small last line, '' for none. Plain text in each: no Markdown of
    theirs takes effect. ``joined``: [project name, topic id, project id] of a topic 整理专项 put into a project:
    已归进「X」 · 移出 last (cards/project_proposal.py joined_element; clickable in the thread, not in the Pin panel)."""
    elements = [md(f"**{_shown(title)}**"), md(" ".join(part for part in (status_tag(state), _shown(facts)) if part))]
    if line:
        elements.append(md(_shown(line), size="notation"))
    if joined:
        from covey.cards.project_proposal import joined_element
        elements.append(joined_element(*joined))
    return card(elements, f"{_one_line(title)} · {status_word(state)}", default_width=True, update_multi=True,
                padding="8px 12px 8px 12px", spacing="4px")


def _one_line(text):
    return " ".join(str(text or "").split())


def _shown(text):
    """``text`` on one line, shown as it is: no Markdown or Feishu tag of its takes effect."""
    return literal(_one_line(text))
