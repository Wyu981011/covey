"""The 派发卡 (app/dispatch_cards.py; docs/butler.md 派发卡): the card the butler's hand-on of a job to a topic leaves, a
reply in the thread of the owner's question (``Dispatch.threaded``) or, an older card's or a long job's, a message of its
own at the chat's top level naming his question. It is drawn whole from ``Dispatch`` (what the job records say), again
each time that changes, and once more as a single line when the conclusion went out.

In the question's thread the question is the thread's root, right above the card: no "你问" block, and the header names
the topic doing the work ("T53 查登录页的报错"), the chat list's preview of the thread too (``summary``).

Top to bottom, element IDs (CardKit takes at most 20 characters, rule 9) in the order drawn:

- ``answer_ask``, at the top level only: the grey "你问 · 12:31 ›" block (cards/answer_card.py ``ask_block``) with the
  owner's words, opening his message at its place in the chat (a card at the top level is no reply to his message);
- the header: the owner's request (in the thread: the topic's T number and title), its first ``HEAD_CHARS`` characters,
  and the state as a tag (在做, 等你, 做完, 失败, 已停);
- ``dp_meta``: one grey line, "T53 · 12:41 起 · 用时 2分05秒" (in the thread without the T number, which heads the card);
- ``dp_thread``: the fold 话题 (open while the job works or waits on the owner, closed once it ended), its title line the
  topic's T number, title and workspace (in the thread: 进度 and the workspace); inside it ``dp_body`` (the stage or step
  the job is at) and ``dp_notes``;
- ``dp_io``: the grey 输入/输出 box (cards/answer_card.py ``box``);
- ``dp_btns``: 补充 (``dp_steer``), 停止 (``dp_stop``) and 打开话题 (``dp_open``), those that can be used now.

No input field: a card that is redrawn must not hold one (docs/cards.md 卡片的客户端限制); 补充 sends a card of its own.
The single line a settled card becomes: ``dp_line``, one grey block that opens the conclusion (``settled_card``): "结论在
下方" at the top level, where the conclusion comes after it, "看结论" in the thread, where it does not."""
from __future__ import annotations

from dataclasses import dataclass

from covey.cards import answer_card
from covey.cards.answer_card import literal_text
from covey.cards.elements import (button_row, card, collapsible, grey, md, note, panel_header, styled_panel,
                                  topic_button)

HEAD_CHARS = 30
TOPIC_TITLE = 40  # Of the topic's title on the fold's title line.
STEER_KIND, STOP_KIND = "bridge_dispatch_steer", "bridge_dispatch_stop"
RUNNING, WAITING, DONE, FAILED, STOPPED = "在做", "等你", "做完", "失败", "已停"
# status -> (tag colour, header icon: one the other cards use, '' for none, whether the 话题 fold is open).
LOOKS = {RUNNING: ("blue", "waiting_outlined", True), WAITING: ("orange", "chat_outlined", True),
         DONE: ("green", "yes_outlined", False), FAILED: ("red", "", False), STOPPED: ("neutral", "", False)}
LINE_MARKS = {DONE: "✅", FAILED: "⚠️", STOPPED: "⏹"}


@dataclass(frozen=True)
class Dispatch:
    """What one card says. ``job_id`` the topic's job the buttons act on ('' while it has none); ``url`` opens the
    topic's thread ('' while it is not known)."""
    token: str
    topic_id: str
    request: str
    status: str
    label: str = ""
    title: str = ""
    workspace: str = ""
    started: str = ""
    took: str = ""
    body: str = ""
    notes: tuple = ()
    inputs: tuple = ()
    outputs: tuple = ()
    job_id: str = ""
    url: str = ""
    ask_at: str = ""
    ask_url: str = ""
    who: str = ""  # Its topic as the speaker of the "你问" line (core/look.py speaker): "T48 查登录页的报错".
    threaded: bool = False  # A reply in the thread of the owner's question (the record's ``in_thread``).


def head_words(request) -> str:
    words = " ".join(str(request or "").split()) or "派出去的事"
    return words if len(words) <= HEAD_CHARS else words[:HEAD_CHARS - 1] + "…"


def topic_words(dispatch) -> str:
    """The topic doing the work, "T53 查登录页的报错"; the owner's request when the topic has neither number nor title."""
    return " ".join(part for part in (dispatch.label, " ".join(str(dispatch.title or "").split())) if part) or dispatch.request


def header(dispatch):
    color, icon, _ = LOOKS[dispatch.status]
    words = topic_words(dispatch) if dispatch.threaded else dispatch.request
    head = panel_header(icon or "waiting_outlined", head_words(words), "", [(dispatch.status, color)], color=color)
    if not icon:
        head.pop("icon")
    return head


def meta_line(dispatch) -> str:
    parts = ["" if dispatch.threaded else dispatch.label, f"{dispatch.started} 起" if dispatch.started else "",
             f"用时 {dispatch.took}" if dispatch.took else ""]
    return " · ".join(part for part in parts if part)


def thread_title(dispatch) -> str:
    if dispatch.threaded:  # The header names the topic already.
        return " · ".join(part for part in ("进度", dispatch.workspace) if part)
    title = " ".join(str(dispatch.title or "").split())
    title = title if len(title) <= TOPIC_TITLE else title[:TOPIC_TITLE - 1] + "…"
    return "话题 · " + " · ".join(part for part in (dispatch.label, title, dispatch.workspace) if part)


def buttons(dispatch) -> list:
    """The buttons that can be used now: 补充 and 停止 while the job works (they act on its ``job_id``, which also
    routes a click to its task process), 打开话题 whenever the topic's thread has a link."""
    row = []
    if dispatch.status == RUNNING and dispatch.job_id:
        value = {"topic_id": dispatch.topic_id, "job_id": str(dispatch.job_id)}
        row.append(topic_button("补充", element_id="dp_steer", value={"kind": STEER_KIND, **value}))
        row.append(topic_button("停止", element_id="dp_stop", tone="danger", value={"kind": STOP_KIND, **value}))
    if dispatch.url:
        row.append(topic_button("打开话题", element_id="dp_open",
                                behaviors=[{"type": "open_url", "default_url": dispatch.url}]))
    return [button_row(row, "dp_btns")] if row else []


def summary(dispatch) -> str:
    """The chat list's preview (in the thread: the preview under the owner's question), "T53 在做 · 查登录页的报错"."""
    if dispatch.threaded and (dispatch.label or dispatch.title):
        return " ".join(part for part in (dispatch.label, dispatch.status) if part) + (
            f" · {head_words(dispatch.title)}" if dispatch.title else "")
    return f"{dispatch.status} · {head_words(dispatch.request)}"


def dispatch_card(dispatch):
    """The live card: ``dispatch`` drawn whole."""
    _, _, opened = LOOKS[dispatch.status]
    inside = [md(literal_text(dispatch.body) if dispatch.body else grey("—"), element_id="dp_body", size="normal_v2")]
    if dispatch.notes:
        inside.append(md("\n".join(grey(literal_text(line)) for line in dispatch.notes), element_id="dp_notes",
                         size="notation"))
    # Who speaks and what it does with the owner's words (样卡 B, cards/answer_card.py says): the topic, by its state.
    doing = {DONE: "done", FAILED: "stopped", STOPPED: "stopped", WAITING: "waiting"}.get(dispatch.status, "running")
    ask = None if dispatch.threaded else answer_card.ask_block(dispatch.request, at=dispatch.ask_at, url=dispatch.ask_url,
                                                               who=dispatch.who, doing=doing, meta=False)
    elements = [ask,
                md(grey(literal_text(meta_line(dispatch))), element_id="dp_meta", size="notation"),
                collapsible("dp_thread", thread_title(dispatch), inside, expanded=opened, size="normal_v2"),
                answer_card.box("dp_io", answer_card.input_lines(dispatch.inputs), list(dispatch.outputs)),
                *buttons(dispatch)]
    return styled_panel(header(dispatch), [element for element in elements if element], summary(dispatch))


def settled_card(status, request, *, url="", reason="", label="", threaded=False, title=""):
    """What a card becomes once its conclusion went out (docs/butler-internals.md 派发卡 · 结论沉底): one grey line,
    "✅ 做完 · 结论在下方 ›" opening the conclusion at ``url`` (in the owner's question's thread, ``threaded``: "看结论 ›",
    the conclusion being at the chat's top level, and the topic's ``title`` in place of his request); for 失败 and 已停 the
    line says why (``reason``) and opens nothing. No fold, no buttons."""
    mark = LINE_MARKS.get(status, "")
    if status == DONE:
        words = f"{mark} {status} · " + ("看结论" if threaded else "结论在下方") + ("　›" if url else "")
    else:
        words = f"{mark} {status}" + (f" · {reason}" if reason else "")
    text = " · ".join(part for part in (label, head_words(title if threaded and title else request)) if part)
    block = {"tag": "interactive_container", "element_id": "dp_line", "width": "fill", "padding": "6px 10px 6px 10px",
             "corner_radius": "6px", "background_style": "grey-50", "vertical_spacing": "2px",
             "elements": [md(f"**{literal_text(words)}**", size="normal_v2"), note(literal_text(text))]}
    if url and status == DONE:
        block["behaviors"] = [{"type": "open_url", "default_url": url}]
    built = card([block], f"{words} · {text}", update_multi=True)
    built["config"]["width_mode"] = "compact"
    return built

