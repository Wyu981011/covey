"""The 协作卡 (app/collab_cards.py, COVEY_COLLAB=1): one card in the integrator's thread that says how a collaboration stands,
drawn whole from ``core/collab_records.py view`` and redrawn as the record changes. It is a projection: the record is the
truth (the web page reads the same one), and the one button, 停止这次协作, carries the collaboration's id and acts on it
only through ``Collaboration.stop``, whichever side clicked first.

- The title bar says who integrates (🤝 协作 · 由 T3 汇总) and where it stands (在做, 做完, 已停止: core/look.py's words).
- Under it the participants, then each ask and clarification with its logical speaker (T3 → T5 · 咨询 · 已答复): the
  question and the answer cut short, what the answer stands on and when it was checked, why an ask was not taken, failed,
  expired or cancelled, and a note that an answer which came late is kept and went to nobody.
- 停止这次协作 is there only while the collaboration is open and something of it waits or runs.

Pure functions: no record is read and nothing is sent here."""
from __future__ import annotations

import time

from covey.cards.elements import button_row, callback, card, md, note, panel_header, plain
from covey.core import collab, look
from covey.core.text import cut, literal

KIND = "bridge_collab_stop"
STOP_LABEL = "停止这次协作"
ICON = "group_outlined"
QUESTION_CHARS = 80
ANSWER_CHARS = 200
REASON_CHARS = 120
LATE_NOTE = "答复到得太晚，只留档，没有交给汇总方。"

# The title bar's tag by the collaboration's state: (word, colour), the words and colours of core/look.py STATES (docs/glossary.md
# 状态词: 在做, 做完, 已停止), as on every other card and the web page.
STATES = {state: (look.STATES[key].word, look.STATES[key].color) for state, key in
          ((collab.OPEN, "running"), (collab.DONE, "done"), (collab.CANCELLED, "cancelled"))}
# An ask's word colour in its line.
ASK_COLORS = {collab.CHECKING: "grey", collab.QUEUED: "grey", collab.TAKEN: "blue", collab.REPLIED: "green",
              collab.READ: "green", collab.NOT_TAKEN: "orange", collab.FAILED: "red", collab.EXPIRED: "orange",
              collab.CANCELLED: "grey"}
PENDING = (collab.CHECKING, collab.QUEUED, collab.TAKEN)
WITH_REASON = (collab.NOT_TAKEN, collab.FAILED, collab.EXPIRED, collab.CANCELLED)


def name_of(view, key, names=None) -> str:
    """How the owner reads participant ``key``: ``names`` (key -> name) first, then the label its record row carries."""
    if names and names.get(key):
        return str(names[key])
    for row in [view.get("integrator") or {}, *(view.get("helpers") or ())]:
        if row.get("key") == key and row.get("label"):
            return str(row["label"])
    return str(key or "")[:8]


def stoppable(view) -> bool:
    """Whether 停止这次协作 does something: the collaboration is open and an ask waits or runs, or its continuation is
    queued."""
    if not view or view.get("state") != collab.OPEN:
        return False
    return (any(ask.get("state") in PENDING for ask in view.get("asks") or ())
            or any(reply.get("state") == "queued" for reply in view.get("replies") or ()))


def clock(epoch) -> str:
    try:
        return time.strftime("%H:%M", time.localtime(float(epoch))) if epoch else ""
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def stand_line(ask) -> str:
    """What an answer stands on: how it was grounded, up to which task of the helper, and when that was read."""
    evidence = (ask.get("reply") or {}).get("evidence") or ask.get("evidence") or {}
    level = collab.EVIDENCE_WORDS.get(evidence.get("level"), "")
    if not level:
        return ""
    since = f"，截至它的任务 #{evidence['job_id']}" if evidence.get("job_id") else ""
    when = f"，核查于 {clock(evidence.get('at'))}" if clock(evidence.get("at")) else ""
    return f"依据：{level}{since}{when}"


def ask_elements(ask, view, names) -> list:
    """The lines of one ask: its speaker line, the question, then the answer or the reason."""
    word = ask.get("words") or collab.ASK_WORDS.get(ask.get("state"), "")
    color = ASK_COLORS.get(ask.get("state"), "grey")
    which = "澄清" if int(ask.get("number") or 1) > 1 else "咨询"
    who = f"{literal(name_of(view, ask.get('from'), names))} → {literal(name_of(view, ask.get('to'), names))}"
    lines = [md(f"**{who}** · {which} · <font color='{color}'>**{word}**</font>")]
    if ask.get("text"):
        lines.append(note("问：" + literal(cut(ask["text"], QUESTION_CHARS))))
    reply = (ask.get("reply") or {}).get("text")
    if reply:
        lines.append(md("答：" + literal(cut(reply, ANSWER_CHARS))))
        stand = stand_line(ask)
        if stand:
            lines.append(note(literal(stand)))
    if ask.get("state") in WITH_REASON and ask.get("reason"):
        lines.append(note("原因：" + literal(cut(ask["reason"], REASON_CHARS))))
    if ask.get("late"):
        lines.append(note(LATE_NOTE))
    return lines


def collab_card(view, names=None) -> dict:
    """The whole card of the collaboration ``view`` (``collab_records.view``), the participants named by ``names``
    (key -> name) where it gives one, else by the labels in the view."""
    view = view or {}
    integrator = view.get("integrator") or {}
    boss = name_of(view, integrator.get("key"), names)
    state_word, tone = STATES.get(view.get("state"), STATES[collab.OPEN])
    helpers = [name_of(view, row.get("key"), names) for row in view.get("helpers") or ()]
    elements = [md(f"**汇总方** {literal(boss)}　**协助方** {literal('、'.join(helpers)) if helpers else '（没有）'}")]
    for ask in view.get("asks") or ():
        elements.extend(ask_elements(ask, view, names))
    if view.get("state") == collab.CANCELLED:
        elements.append(note("主人停了这次协作：还在排队或在跑的咨询已取消，协助方自己的话题没有动。"))
    elif view.get("state") == collab.DONE:
        elements.append(note("答复已交给汇总方，它做完了。"))
    if stoppable(view):
        elements.append(button_row([{"tag": "button", "type": "danger", "size": "medium", "text": plain(STOP_LABEL),
                                     "behaviors": callback({"kind": KIND, "collab": str(view.get("id") or "")})}]))
    head = panel_header(ICON, f"🤝 协作 · 由 {boss} 汇总", "", [(state_word, tone)],
                        color="blue" if tone == "blue" else "grey")
    return card(elements, f"协作 · 由 {boss} 汇总 · {state_word}", default_width=True, update_multi=True,
                padding="6px 14px 12px 14px", spacing="6px", header=head)
