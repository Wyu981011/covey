"""The buttons that rerun a stopped task, and the card of one whose task card cannot take them any more
(app/task_controls.py, app/auto_retry.py and app/cards.py decide which; app/outbox.py names the label);
``recovery_view`` draws that card from what app/recovery_cards.py read."""
from __future__ import annotations

import datetime as _dt
import json
from types import SimpleNamespace

from covey.cards.elements import card, column_button, fold, grey, markdown_panel, md, plain
from covey.cards.streaming import task_head
from covey.cards.topic_actions import SWITCH_OPEN, switch_panel
from covey.cards.ui import BODY_PADDING, BODY_SPACING, banded
from covey.core import look
from covey.core.text import literal
from covey.cards.trace_view import TraceView
from covey.core.trace import ToolTrace, finish_record_trace
from covey.cards.trace_updates import panel_json

RETRY_KIND = "bridge_job_retry"
# The next steps of a task that did not succeed that start a turn of their own (core/failure.py actions):
# 看原因, a read-only turn that looks into why, and 拆小再试 (app/task_controls.py follow_up).
DIAGNOSE_KIND, SPLIT_KIND = "bridge_job_diagnose", "bridge_job_split"
FOLLOW_UPS = {"diagnose": ("看原因", DIAGNOSE_KIND), "split": ("拆小再试", SPLIT_KIND)}
# 复制诊断 beside 看原因 (app/diag_summary.py): the topic gets a block of the version, ids, last good step, retries and the
# error to copy to whoever helps; no turn starts.
REPORT_KIND, REPORT_LABEL = "bridge_job_report", "复制诊断"
REPORT_NOTE = "复制诊断：在话题里发一段诊断摘要（版本、任务编号、最近成功的一步、重试和打了码的错误），复制给帮你排障的人。"
FOLLOW_UP_NOTES = {"diagnose": "看原因：开一轮只读排查，看看这一轮为什么没成功，不改文件、不重跑。",
                   "split": "拆小再试：把这件事拆成更小的几步重新做，被拦下的那块先跳过。",
                   "switch_model": "换个模型：打开换配置，换一个模型接着做这件事。",
                   "other_harness": "换个 Harness：打开换配置，预选一个现在能用的别的 Harness，你确认后才换，接着做这件事。"}
# 换个模型 (core/failure.py SWITCH_MODEL): the 换配置 card's own click (bridge_switch_open), so a failure whose retry cannot
# succeed (额度用完, 账号被拦, 安全拒绝) offers the one next step that can right in its row, not only under 执行过程.
SWITCH_MODEL = "switch_model"
SWITCH_LABEL = "换个模型"
# 换个 Harness on a limit's failure (app/auto_retry.py other_harness, #36): the same 换配置 click with ``other``, which
# preselects another Harness usable now (app/harness_switch.py); never switched without the owner's 确认更换.
OTHER_HARNESS = "other_harness"
OTHER_LABEL = "换个 Harness"
DETAILS_ID = "failure_details"


def interrupted_summary(name, label="", due_at=None):
    """An interrupted task's chat-list preview (``name``: its topic, else #job): when it continues by itself
    (``due_at``, an automatic retry's time), else whether ``label`` 检查并继续 applies."""
    if due_at is not None:
        return f"{name} 停住了 · {_dt.datetime.fromtimestamp(due_at).astimezone().strftime('%H:%M')} 自动检查并继续"
    return f"{name} 停住了" + (" · 可以检查并继续" if label == "检查并继续" else "")


def stopped_card(text, *, retry=None, actions=(), panels=(), header=None, summary=None, head=None, lead=None):
    """An interrupted, failed or moved task's card: ``head``, its task card's row (cards/streaming.py task_head), and
    ``lead``, what became of it, over ``text``; ``retry``, a (label, topic_id, job_id), as its button, or ``actions`` in
    its place (a pending automatic retry's line and row, what the buttons do folded under them, ``result_note``); then
    ``panels``. ``header``: its (template, title) title bar, of a card sent before it had a row; ``summary``: its
    chat-list preview, which a topic's row shows while it is the topic's latest message."""
    elements = [part for part in (head, lead) if part] + ([md(text[:10000])] if text.strip() else [])
    if retry:
        label, topic_id, job_id = retry
        elements.append({"tag": "column_set", "element_id": "recovery_actions", "columns": [
            {"tag": "column", "width": "weighted", "elements": [
                {"tag": "button", "text": plain(label), "type": "primary",
                 "value": {"kind": RETRY_KIND, "topic_id": topic_id, "job_id": job_id}}]}]})
    elements.extend(actions)
    look_of = dict(padding=BODY_PADDING, spacing=BODY_SPACING) if head else {}  # As every card that opens with a row.
    return banded(card(elements + list(panels), summary, header=header, **look_of))  # The badge's colour.


def switch_route(record):
    """(harness_id, binding_revision) of ``record``'s topic, which the 换配置 click needs; None without one."""
    if record.get("harness_id") and record.get("topic_id") and record.get("binding_revision"):
        return record["harness_id"], record["binding_revision"]
    return None


def offers_switch(elements) -> bool:
    """Whether ``elements`` hold a 换个模型 button already."""
    return f'"kind": "{SWITCH_OPEN}"' in json.dumps(list(elements), ensure_ascii=False)


def result_actions(topic_id, job_id, label, *, stop_kind="", follow_ups=(), route=None):
    """The row after a failed task's answer: ``label`` (检查并继续, 现在重试, 重新投递结果; "" for none), with
    ``stop_kind`` 停止自动重试, then ``follow_ups`` (FOLLOW_UPS: 看原因, with 复制诊断 after it, 拆小再试; SWITCH_MODEL:
    换个模型 and OTHER_HARNESS: 换个 Harness, both with the topic's ``route``, its (harness_id, binding_revision), and left
    out without one)."""
    value = {"topic_id": topic_id, "job_id": job_id}
    columns = [column_button(label, {"kind": RETRY_KIND, **value})] if label else []
    if stop_kind:
        columns.append(column_button("停止自动重试", {"kind": stop_kind, **value}))
    for name in follow_ups:
        if name in FOLLOW_UPS:
            columns.append(column_button(FOLLOW_UPS[name][0], {"kind": FOLLOW_UPS[name][1], **value}))
            if name == "diagnose":
                columns.append(column_button(REPORT_LABEL, {"kind": REPORT_KIND, **value}))
        elif name in (SWITCH_MODEL, OTHER_HARNESS) and route:
            columns.append(column_button(SWITCH_LABEL if name == SWITCH_MODEL else OTHER_LABEL, {
                "kind": SWITCH_OPEN, **value, "harness_id": route[0], "binding_revision": route[1],
                **({"other": True} if name == OTHER_HARNESS else {})}))
    return {"tag": "column_set", "element_id": "result_actions", "columns": columns}


def failure_details(text):
    """技术详情 under a failed task card's one-line reason: the words it said before (core/failure.py card_body)."""
    return markdown_panel(DETAILS_ID, grey("技术详情"), text[:6000], boxed=True, size="notation")


def retry_status(content):
    """A pending automatic retry's line above the row."""
    return md(content, element_id="auto_retry_status")


NOTE_ID = "result_actions_note"


def result_note(content, gist=""):
    """What the buttons above do, under them: ``gist`` as one small grey line that opens on ``content``, each button's
    note, as 怎么回答 under a question's buttons (cards/question_cards.py answer_help; the owner, 2026-11-23: the notes
    were three lines of print under every stopped task's buttons). Without ``gist`` the notes as small print, as before."""
    if not gist:
        return md(content, element_id=NOTE_ID, size="notation")
    return fold(NOTE_ID, md(grey(literal(gist)), size="notation"), [md(content, size="notation")],
                title_padding="0px 0px 0px 0px", icon_position="follow_text", spacing="4px")


MOVED_LINE = "不用处理，接着做的进展在后面。"  # A task an automatic retry moved on (``recovery_view``).
ANSWERED = "↪ 已收到回答"  # The status of a task card whose question was answered (cards.md 状态行).


def recovery_view(record, text, *, word, headline, line="", topic, label, continued, moved_to, how, retry, actions,
                  snapshot, detail="", title=""):
    """The recovery card of ``record``'s task from what app/recovery_cards.py read and worded, in its task card's look
    (docs/ui.md 5.2 停住的卡): its row (cards/streaming.py task_head: ``topic``'s badge, the turn's ``title`` with its
    number grey, ``word``'s tag, a key of core/look.py STATES), then ``headline`` (what became of it or why, bold) and
    ``line`` (what can be done next, grey), then ``text``; ``retry`` and ``actions`` as ``stopped_card`` takes them;
    ``detail``, the internal words (the record's status line, an error code or exception, core/failure.py
    failure_view) in 技术详情, folded; ``snapshot``, its trace for the 执行过程 panel, which a turn with no step does
    without (how long it ran goes on the row); then the 换配置 panel of a task with a binding. ``continued``: its
    question was answered and the task goes on (the row says ↪ 已收到回答). ``how``, how an automatic retry moved it to
    ``moved_to``: the row says that, one line that nothing is asked of the owner, and only its 执行过程 when it has a
    step (its next turn has its own card and buttons).

    No conclusion band (the owner, 2026-11-23, on "停住了 · T666 #6047 / 已转到任务 #6055 继续（限流后自动重试）"
    over 停在：准备处理本轮请求 / 已完成：尚无记录 / 检查并继续：新开一个任务…: 这种UI还没改呢): the row says the state
    as the task card says it, and no task number of another card is named."""
    status = look.word(word)
    lead = md("\n".join([f"**{literal(headline)}**", *([grey(literal(line))] if line else [])])) if headline else None
    if continued:
        status, lead = ANSWERED, None
    elif moved_to is not None:
        status, lead = "↪ " + (how or "已重新开始"), md(grey(MOVED_LINE))
        text, retry, actions, detail = "", None, (), ""
    panels = [failure_details(literal(detail))] if detail else []
    if snapshot:
        model = TraceView(finish_record_trace(ToolTrace.restore(snapshot), record).snapshot()).panel_model(False, timed=True)
        if not model.ended_empty:  # What this turn did stays to look back on, moved on or not.
            panels.append(panel_json(model))
        elif not continued and moved_to is None:  # "无执行记录 · 用时 5秒" said nothing to open: how long goes on the row.
            status = " · ".join([status, *model.state.split(" · ")[1:]])
    if moved_to is None and switch_route(record) and not offers_switch(actions):  # Else 换个模型 in the row opens it.
        panels.append(switch_panel(record["topic_id"], record["job_id"], record["harness_id"],
                                   record.get("binding_revision", 1)))
    name = topic or f"#{record['job_id']}"
    if moved_to is not None:
        summary = f"{name} {status}"  # As its row says it: "T12 ↪ 限流后自动重试".
    elif continued or word != "stopped" or record.get("status") != "interrupted":
        summary = f"{name} {look.word(word)} · {headline}"
    else:
        pending = actions and record.get("auto_retry_state") == "pending"  # Else they are 看原因 and 拆小再试 alone.
        summary = interrupted_summary(name, label, record["auto_retry_at"] if pending else None)
    head = task_head(SimpleNamespace(topic_label=topic, job_id=record.get("job_id")), title or "任务", status)
    return stopped_card(text.lstrip("\n"), retry=retry, actions=actions, panels=panels, summary=summary, head=head,
                        lead=lead)
