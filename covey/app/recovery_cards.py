"""The card of a task that did not end as it should (interrupted, failed, or its result not delivered) and the
status line of a task that asked once another went on after it: ``recovery_card`` reads what the card says (the
record's recovery state, checkpoint, topic and trace; core/recovery.py classify) and words it, cards/recovery.py
``recovery_view`` draws it; ``paint_answered`` writes the status line (app/task_controls.py TaskControls shows
both)."""
from __future__ import annotations

from pathlib import Path

from covey.app import auto_retry
from covey.app.butler_reply import dropped_lines
from covey.app.outbox import AUDIT_REFUSED_NOTE, REDELIVER_LABEL, REDELIVER_NOTE, RETRY_NOTE
from covey.cards.elements import md
from covey.cards.recovery import recovery_view, result_actions, switch_route
from covey.core import failure, recovery, turn_words
from covey.core.checkpoint import read_checkpoint
from covey.core.butler import traits_of, worded
from covey.core.metrics import ended, job_took, took_text
from covey.core.topics import topic_label
from covey.core.trace_store import load_trace


def asked_took(state_dir, record):
    """How long the run of ``record`` (a task that asked) took: its 用时 (core/metrics.py run_seconds, by its timings,
    else its process record), else what its task monitor last wrote; None when none says."""
    snapshot = load_trace(Path(state_dir), record) if state_dir else None
    timings = record.get("timings") if isinstance(record.get("timings"), dict) else {}
    seconds = record.get("elapsed_seconds")
    return job_took(timings, snapshot, gate=ended,
                    fallback=seconds if isinstance(seconds, (int, float)) and seconds > 0 else None)


# Task cards created from DASHBOARD_SINCE on have the 用时 tile (the A 仪表盘 look): their status lines do not say 用时 again. A record's created_at is UTC.
DASHBOARD_SINCE = "2026-11-03T17:33:51Z"


def answered_line(record, job_id, state_dir, *, answered=True):
    """The status line of a task that asked once task #job_id went on after it: ``↪ 已回答 → #1181 · 用时 2 分 22 秒``
    when #job_id carries the answer, ``↪ #1179 已接着开始，这组问题没有回答 · 用时 …`` when it is a message queued
    before the questions came (not 已收到回答 · 继续处理中 over questions no one answered). The run's
    time stays as 需要你回答 · 用时 had it."""
    took = asked_took(state_dir, record)
    line = f"↪ 已回答 → #{job_id}" if answered else f"↪ #{job_id} 已接着开始，这组问题没有回答"
    if str(record.get("created_at") or "") >= DASHBOARD_SINCE:
        return line  # Its 用时 tile says it.
    return line + (f" · 用时 {took_text(took)}" if took is not None else "")


def paint_answered(cards, log, ctx, chat, job_id, previous, *, answered=True):
    """The status line of ``previous`` (a task that asked), which said ❓ 需要你回答 · 用时 since the run
    ended, says what came after it (``answered_line``); its body, the lead of what it said or where that
    went, stays ("已收到回答 · 后续任务 #12 继续处理。结果见下方任务卡。" in its place said nothing the
    card below did not). A card without that line (sent before it existed) gets it in its
    body. Never the whole card (one replaced so lost its title, request and details)."""
    line = answered_line(previous, job_id, ctx.state_dir, answered=answered)
    try:
        if cards.set_record_activity(ctx, previous, line):
            return
        cards.update_record_panel(ctx, chat, f"answer-received-{job_id}", {
            "message_id": previous.get("card_message_id", "")}, previous,
            md(line, element_id=cards.stream.element_id))
    except Exception as exc:  # noqa: BLE001 - only the earlier card's display
        log(f"Previous question task display failed: {type(exc).__name__}")


# What became of the task, by its recovery state (core/recovery.py classify): the state's word (docs/ui.md 第 3 节) and
# the band's headline. One that did not succeed says why and what next in core/failure.py failure_view's words, the task
# card's, the 停住了 relay's and the web page's (an interrupted, refused, undelivered or never started one); these stand
# where it says none.
RECOVERY_WORDS = {recovery.SAVED_FAILED: ("stopped", "这一轮没有能发出的结果"),
                  recovery.SAVED_DELIVERED: ("result", "结果已经发出"),
                  recovery.SAVED_PENDING: ("stopped", "结果已保存，还没发出去"),
                  recovery.START_FAILED: ("stopped", "任务进程没能启动"),
                  recovery.POLICY_STOP: ("stopped", "被官方安全策略拦下"),
                  recovery.INTERRUPTED: ("stopped", "这一轮被打断了")}
SAVED_TEXT = {recovery.SAVED_FAILED: "这一轮的回复没通过发出前的核对，不能重新投递；在本话题再说一下要做什么。",
              recovery.SAVED_DELIVERED: "结果已经发到本话题（正文或文件）。",
              recovery.SAVED_PENDING: "结果已保存，还没发出去；重新投递只发这份结果，不会重新跑模型。"}
UNRECONCILED = "投递状态要先核对，这里不能重新投递；在本话题再说一下要做什么。"
NEW_SESSION = "这一轮的会话不能续接，下一轮会从新会话开始。"
NOT_STARTED = "没有执行任何操作，也没有提交外部任务。"  # After the band's 任务进程没能启动，这一轮没有开始.



def recovery_card(record, *, continued=False, state_dir=None, moved_to=None, automatic="", moved=""):
    """The recovery card of ``record``'s task, drawn by cards/recovery.py ``recovery_view`` from what is read here: its
    recovery state (core/recovery.py classify), checkpoint, topic and trace, and its words (``recovery_text``).
    ``automatic``: the auto_retry kind when an automatic retry moved the task to ``moved_to``; ``moved``: how the
    header says it went on instead (a retry on an older model after a safety refusal, app/policy_retry.py)."""
    decided = recovery.classify(record)
    state, label = decided.card, decided.label
    cp = read_checkpoint(Path(record["checkpoint_path"])) if record.get("checkpoint_path") else {}
    key, headline = ("running", "收到回答，接着做") if continued else RECOVERY_WORDS[state]
    line = ""
    view = None if continued else failure.failure_view(record)  # None for one it has no reason for (delivered, ...).
    lead = "" if continued or state != recovery.INTERRUPTED else turn_words.device_interrupted(record)
    if lead:  # A turn on a device: where its Agent is, and what continuing does.
        headline, line = failure.split_title(lead.rstrip("。"))
    elif view:
        headline, line = failure.split_title(view["title"])
    headline, line = worded(headline, record), worded(line, record)  # The butler is no topic.
    how = f"（{moved or auto_retry.KINDS[automatic].moved}）" if automatic or moved else ""
    topic = topic_label(Path(state_dir), record.get("topic_id", "")) if state_dir and record.get("topic_id") else ""
    text = recovery_text(record, state, label, cp, continued=continued, state_dir=state_dir)
    snapshot = load_trace(Path(state_dir), record) if state_dir else record.get("trace_snapshot")
    retry = (label, record["topic_id"], record["job_id"]) if not continued and label and moved_to is None else None
    actions = ()
    if retry and auto_retry.pending(record):
        # A pending automatic retry (a restart interrupted the task): its time and 停止自动重试 too, with the
        # element IDs auto_retry.show repaints when it is cancelled or refused.
        actions, retry = auto_retry.result_elements(record["topic_id"], record["job_id"], record), None
    elif not continued and moved_to is None and record.get("topic_id"):
        # 看原因 and 拆小再试 (core/failure.py) after its button, as a failed task card has them.
        follow = auto_retry.next_steps(record)[1]
        actions = ((result_actions(record["topic_id"], record["job_id"], "", follow_ups=follow,
                                   route=switch_route(record)),) if follow else ())
    return recovery_view(record, text, word=key, headline=headline, line=line, topic=topic, label=label, continued=continued, moved_to=moved_to,
                         how=how, retry=retry, actions=actions, snapshot=snapshot,
                         detail=(view or {}).get("detail", "") if moved_to is None else "")


def recovery_text(record, state, label, cp, *, continued, state_dir):
    """What the recovery card of ``record`` (its recovery ``state`` and button ``label``, its checkpoint ``cp``) says:
    the text starts with what to know next. In the butler's words (worded), but a reply or a checkpoint keeps
    the model's; a butler turn the policy guard stopped lists the supplements it took."""
    text = ""
    refused = not continued and record.get('delivery_error') == 'audit_rejected' and not record.get('delivery_ok')
    main = traits_of(record)  # The butler is no topic (worded).
    if continued:
        text += str(record.get("final_text") or "")
    elif state in SAVED_TEXT:
        text += SAVED_TEXT[state]
        if state == recovery.SAVED_PENDING and not label and not record.get('delivery_ok') and not refused:
            text += "\n" + UNRECONCILED
        if record.get('native_resume_allowed') is False:
            text += "\n" + NEW_SESSION
    elif state == recovery.START_FAILED:
        text += NOT_STARTED  # Why it did not start (the exception's kind) is in 技术详情 (core/failure.py detail).
        if label:
            text += "\n" + RETRY_NOTE
    elif state == recovery.POLICY_STOP:
        text += str(record.get("final_text") or "本轮因官方拒绝或降级已停止，请检查任务内容后提出新的要求。")
    else:
        # Why is the band's (recovery_card): a turn on a device's words, else core/failure.py's.
        text += f"停在：{cp.get('phase') or '尚无检查点'}\n"
        completed = cp.get("completed", [])
        text += "已完成：" + (
            "；".join(map(str, completed)) if isinstance(completed, list) and completed else "尚无记录"
        )
        text += f"\n下一步：{cp.get('next_step') or '检查已有产物和外部任务状态后继续'}"
        if not auto_retry.pending(record):  # Else the pending retry's row has the note under it.
            text += "\n" + {"检查并继续": RETRY_NOTE, REDELIVER_LABEL: REDELIVER_NOTE}.get(
                label, "继续前会核查已有工作，避免重复提交外部任务。")
    if refused:
        text += "\n" + worded(AUDIT_REFUSED_NOTE, main) + "。"
    if not continued and state != recovery.INTERRUPTED:  # Not a reply or a checkpoint: the model's words stay.
        text = worded(text, main)
    if main.lists_supplements and state == recovery.POLICY_STOP and state_dir and not continued:
        # A butler turn stopped by the policy guard: the supplements it took, in the owner's words (app/butler_reply.py).
        try:
            dropped = dropped_lines(state_dir, {**record, "job_key": record.get("message_id")}, True)
        except OSError:
            dropped = ""
        text += "\n\n" + dropped if dropped else ""
    return text
