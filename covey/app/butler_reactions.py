"""Reactions on the message a turn answers when its card is not under it: a butler turn's when its topics hang under his
question (core/placement.py Row.quiet; docs/butler.md 提问不开串), and a topic's turn of a message quoted from outside its
thread (``top_message``). The turn opens no thread under the message, so the message says how it
stands: OnIt once it is queued (app/submission.py, in the Bridge), then, when the turn ends (app/worker.py, in its
task runner), DONE for an answer, Get for work handed on to topics, CrossMark for a failure or an official refusal;
nothing more for a stop or a question (the question card at the top level asks).

As probed: on the web a reaction makes no unread mark, moves no chat up
and adds no message, only an icon before the chat list's preview. Adding a reaction the bot has already is the same
one again (its reaction_id too), removing one removed already succeeds: the end adds OnIt again to learn its id, then
removes it. A failure is a log line, never the answer's; no record lock is held (rules 1 and 2).

多路并行 (COVEY_BUTLER_TRACKS=1, app/butler_tracks.py ``Tracks.noted``) adds two: QUEUED (OneSecond) on a message that waits
behind a track's tasks, in the Bridge, instead of OnIt; the task process takes it off and puts OnIt on when the turn
starts (``begin``: the ids come from Messenger.reaction_ids, so no state is kept between the two processes), and MERGED
(THUMBSUP) on a message that joined a running task, which stays until the owner quotes it with 单独答 (``split``). Feishu
takes OneSecond and THUMBSUP, not WAIT. With the switch off none
of them is called.

A topic's message quoted from outside its thread (docs/usage.md 引用卡片接着说; ``top_message``, saved on its job and its
record) has the same four and QUEUED, whatever the switch: OnIt as it is queued to start, QUEUED while it waits behind its
topic's tasks or a free slot (``top_queued``; ``begin`` turns it into OnIt), DONE (never Get) or CrossMark at its end, nothing
for a stop or a question; DONE as soon as it went into the task before it (app/steering.py, ``top_steered``, QUEUED while
that task cannot take it yet) or went with an answer (app/questions.py, app/held_notes.py), QUEUED while it waits as a note
for an answer, CrossMark when it was refused; a retry or a requeue of it takes the earlier end off (``top_queued`` again).
A task runner of a release before it ignores the field: the reactions of a turn it runs stop at OnIt."""
from __future__ import annotations

import time

from covey.core import butler_tracks, placement
from covey.core.butler import traits
from covey.core.jobs import job_field
from covey.core.topics import message_topic, proxy_topic

ON_IT, DONE, GOT, FAILED = "OnIt", "DONE", "Get", "CrossMark"
QUEUED, MERGED = "OneSecond", "THUMBSUP"
HELD_SECONDS = 600
HELD: dict = {}  # message id -> when QUEUED went on it in this process: ``start`` leaves OnIt for ``begin``.


def ending(status, routed, refused=False) -> str:
    """The reaction a turn ending in ``status`` leaves: DONE (Get when it ``routed`` work to topics), CrossMark for a
    failure or an official refusal (``refused``: its status is cancelled, as a stop's), '' for any other end (a stop,
    a question)."""
    if status == "done":
        return GOT if routed else DONE
    return FAILED if status == "failed" or refused else ""


def start(messenger, state_dir, profile, job, log, again=False) -> bool:
    """OnIt on the owner's message of the queued ``job``, when it is a quiet one (core/placement.py ``marked``).
    ``again``: a retry or resume of an earlier turn (app/task_controls.py requeue), whose CrossMark comes off first."""
    if not placement.marked(state_dir, job):
        return False
    message = placement.owner_message(job)
    if not again and HELD.pop(message, None) is not None:
        return True  # 排队中 is on it: OnIt comes when the turn starts (``begin``).
    try:
        if again:
            mark = messenger.react(profile, message, FAILED)  # Its id, as ``finish`` learns OnIt's.
            if mark and not messenger.unreact(profile, message, mark):
                log(f"main thread reaction not removed job=#{job.job_id} emoji={FAILED}")
        if messenger.react(profile, message, ON_IT):
            return True
    except Exception as exc:  # noqa: BLE001 - the turn goes on without it
        log(f"main thread reaction failed job=#{job.job_id}: {type(exc).__name__}")
        return False
    log(f"main thread reaction not added job=#{job.job_id} emoji={ON_IT}")
    return False


def finish(messenger, profile, job, emoji, log) -> bool:
    """OnIt taken off the message ``job``'s reactions are on (its ``top_message``, else the owner's message of a quiet
    turn) and ``emoji`` ('' none) put on; whether ``emoji`` is there now (True for '' once OnIt went)."""
    message = top_of(job) or placement.owner_message(job)
    try:
        mark = messenger.react(profile, message, ON_IT)  # Its id: the one there already, or a new one.
        if mark and not messenger.unreact(profile, message, mark):
            log(f"main thread reaction not removed job=#{job.job_id} emoji={ON_IT}")
        done = bool(messenger.react(profile, message, emoji)) if emoji else bool(mark)
    except Exception as exc:  # noqa: BLE001 - the answer is the turn's, not its reaction
        log(f"main thread reaction failed job=#{job.job_id}: {type(exc).__name__}")
        return False
    log(f"main thread reaction job=#{job.job_id} emoji={emoji or '-'} ok={done}")
    return done


# -- 多路并行 ----------------------------------------------------------------------------------------------------------

def owner_quiet(state_dir, chat, message) -> bool:
    """Whether ``message`` is one of the owner's own that a butler turn of the 话题区 layout answers (as
    ``placement.marked`` says of a job), from the topic its alias names. Never raises."""
    try:
        topic = message_topic(state_dir, chat, message)
        return message.startswith("om_") and bool(topic) and placement.plan(
            state_dir, {"topic_id": topic, "chat_id": chat}).row.quiet
    except Exception:  # noqa: BLE001 - no reaction
        return False


def put(messenger, profile, message, emoji, what, log) -> bool:
    """``emoji`` on ``message``; whether it is there. A failure is a log line."""
    try:
        if messenger.react(profile, message, emoji):
            return True
    except Exception as exc:  # noqa: BLE001 - the turn goes on without it
        log(f"main thread reaction failed {what} message={message[-10:]}: {type(exc).__name__}")
        return False
    log(f"main thread reaction not added {what} message={message[-10:]} emoji={emoji}")
    return False


def take_off(messenger, profile, message, emoji, what, log) -> int | None:
    """The bot's ``emoji`` reactions taken off ``message``: how many went, None when they could not be listed (logged)."""
    try:
        ids = messenger.reaction_ids(profile, message, emoji)
        if ids is None:
            log(f"main thread reactions not listed {what} message={message[-10:]} emoji={emoji}")
            return None
        gone = 0
        for reaction in ids:
            if messenger.unreact(profile, message, reaction):
                gone += 1
            else:
                log(f"main thread reaction not removed {what} message={message[-10:]} emoji={emoji}")
        return gone
    except Exception as exc:  # noqa: BLE001 - the turn goes on without it
        log(f"main thread reaction failed {what} message={message[-10:]}: {type(exc).__name__}")
        return None


def queue(messenger, state_dir, profile, chat, message, log) -> bool:
    """QUEUED on the owner's ``message``, which waits behind a track's tasks (Tracks.noted); ``start`` then leaves OnIt
    to ``begin``. False when it is not a message a quiet turn answers or the reaction is not on."""
    if not owner_quiet(state_dir, chat, message):
        return False
    now = time.time()
    for old in [key for key, at in HELD.items() if now - at > HELD_SECONDS]:
        HELD.pop(old, None)  # Never queued after all: nothing came to take it.
    if not put(messenger, profile, message, QUEUED, "queued", log):
        return False
    HELD[message] = now
    return True


def merge(messenger, state_dir, profile, chat, message, log) -> bool:
    """MERGED on the owner's ``message`` that joined a running task (Tracks.noted); it stays."""
    return owner_quiet(state_dir, chat, message) and put(messenger, profile, message, MERGED, "merged", log)


def split(messenger, profile, message, log) -> bool:
    """MERGED off the owner's ``message`` that he quoted to have it answered on its own (Tracks.noted "alone"); False
    when it could not be taken off."""
    return take_off(messenger, profile, message, MERGED, "alone", log) is not None


def begin(messenger, state_dir, profile, job, log) -> bool:
    """In the task process, as the turn of ``job`` starts: QUEUED off its message and OnIt on, when it had QUEUED (or
    when that cannot be told: OnIt again is the same reaction). A quiet turn's with the switch on, a ``top_message``'s
    always; with the switch off, or a message that never queued, no reaction is added (OnIt went on when it was
    queued). Whether OnIt was put on."""
    message = (placement.owner_message(job) if butler_tracks.enabled() and placement.marked(state_dir, job)
               else top_of(job))
    if not message:
        return False
    gone = take_off(messenger, profile, message, QUEUED, f"start job=#{job.job_id}", log)
    return gone != 0 and put(messenger, profile, message, ON_IT, f"start job=#{job.job_id}", log)  # None: unknown


def unqueue(messenger, state_dir, profile, job, log) -> None:
    """QUEUED off the message of a job cancelled before it started (its ``begin`` never comes); a ``top_message``'s
    OnIt too (put on as it was queued to start), so a stop or a recall leaves nothing."""
    if butler_tracks.enabled() and placement.marked(state_dir, job):
        take_off(messenger, profile, placement.owner_message(job), QUEUED, f"cancel job=#{job.job_id}", log)
    elif message := top_of(job):
        clear(messenger, profile, message, (QUEUED, ON_IT), f"cancel job=#{job.job_id}", log)


# -- 引用卡片接着说: a topic's message quoted from outside its thread (docs/usage.md) ----------------------------------

def top_message(ctx, event) -> str:
    """The message of ``event`` when nothing under it will say how its turn stands, so its reactions do: a person's
    message (``om_``) whose turn's cards go to the thread of ctx's topic (its root, ``reply_to_message_id``) while the
    message is neither that root nor in its thread. That is a reply quoting a relay card, a question card's copy, a
    派发卡 or a hook at the chat's top level (引用直达, core/topics.py context_for_topic), or a quote of such a card in
    another thread (the butler's card in the owner's message's thread). '' for every other: a topic's first message
    (its card goes under it), one in the topic's thread (its ``thread_id`` with the root's ``root_id``, or none), the
    butler's and a lead's (they answer quoting it: core/placement.py ``marked``), one whose turn replies to nothing (a
    lead's wake-up, the web page's), a 代答 topic's. Never raises."""
    try:
        message = str(event.get("message_id") or event.get("id") or "")
        root = str(getattr(ctx, "reply_to_message_id", "") or "")
        if not message.startswith("om_") or not root or root == message:
            return ""
        if str(event.get("thread_id") or "") and str(event.get("root_id") or "") in ("", root):
            return ""  # In the topic's own thread: its cards are there.
        if traits(ctx.topic_id, str(event.get("chat_id") or "")).top_level or proxy_topic(ctx):
            return ""
        return message
    except Exception:  # noqa: BLE001 - no reactions, as before
        return ""


def top_of(job) -> str:
    """``job``'s ``top_message`` (a job or its record; an older release's has none): '' unless a person's message."""
    try:
        top = str(job_field(job, "top_message") or "")
    except Exception:  # noqa: BLE001 - none
        return ""
    return top if top.startswith("om_") else ""


def steered_top(record) -> str:
    """The ``top_message`` a supplement's delivery record keeps in its ``requeue`` (app/steering.py steer_queued_job: the
    message went into a running task as it arrived, or by a click on its queued card), ''."""
    again = record.get("requeue") if isinstance(record, dict) else None
    return top_of({"top_message": again.get("top")}) if isinstance(again, dict) else ""


def clear(messenger, profile, message, emojis, what, log) -> None:
    """Each of ``emojis`` the bot put on ``message`` taken off (``take_off``: listed first, so one that is not there is
    never put on to learn its id). A failure is a log line."""
    for emoji in emojis:
        take_off(messenger, profile, message, emoji, what, log)


def top_queued(messenger, profile, job, log, *, waits=False, again=False) -> bool:
    """The queued ``job``'s ``top_message`` says it: OnIt, or QUEUED while it ``waits`` behind its topic's tasks or a free
    slot (``begin`` turns it into OnIt as the turn starts). QUEUED goes on under the job's execution lock, the one the
    hand-off to its task runner and its worker take, so a turn that starts meanwhile either finds QUEUED to take off or
    gets OnIt here instead; nothing for a job stopped, merged or sent into another one already. ``again``: a turn of a
    message an earlier turn of it ended on (a retry, a requeued supplement): the DONE or CrossMark that one left comes
    off first. Whether the reaction is on."""
    message = top_of(job)
    if not message:
        return False
    what = f"top job=#{job.job_id}"
    if again:
        clear(messenger, profile, message, (DONE, FAILED), what, log)
    if waits:
        with job.execution_lock:
            if job.cancelled_before_start or job.cancel_event.is_set():
                return False
            if not job.execution_started:
                return put(messenger, profile, message, QUEUED, what, log)
    if job.cancelled_before_start or job.cancel_event.is_set():
        return False
    return put(messenger, profile, message, ON_IT, what, log)


def top_steered(messenger, profile, message, status, log, *, auto) -> None:
    """``message``'s queued turn went into the task before it (app/steering.py steer_queued_job) and runs no more on its
    own: DONE once it is in (``status`` sent or read; joined a queued task's request too), QUEUED while that task cannot
    take it yet (held: ``top_settled`` follows), nothing once it cannot be told (uncertain: its receipt says it, and it
    never runs again by itself). ``auto``: as it arrived, nothing on the message yet; else a click on its queued card,
    whose QUEUED comes off first."""
    what = "top steered"
    if status in ("sent", "read"):
        if not auto:
            take_off(messenger, profile, message, QUEUED, what, log)
        put(messenger, profile, message, DONE, what, log)
    elif status == "held":
        if auto:
            put(messenger, profile, message, QUEUED, what, log)
    elif not auto:
        take_off(messenger, profile, message, QUEUED, what, log)


def top_settled(messenger, profile, message, status, log) -> None:
    """A supplement of ``message`` that waited for its task (``top_steered`` held, QUEUED) settled as ``status``: QUEUED off,
    and DONE when it was sent (or read). Refused, withdrawn or uncertain leave nothing; one requeued as a turn of its own
    gets that turn's reactions, put on after this."""
    take_off(messenger, profile, message, QUEUED, f"top settled {status or '-'}", log)
    if status in ("sent", "read"):
        put(messenger, profile, message, DONE, "top settled", log)


def top_took(messenger, profile, message, log) -> bool:
    """``message`` went into a running task or with an answer (an answer typed for a live question, a held note an
    answer took): QUEUED off (a note waited), DONE on. Whether DONE is there."""
    if not message:
        return False
    take_off(messenger, profile, message, QUEUED, "top took", log)
    return put(messenger, profile, message, DONE, "top took", log)


def top_waits(messenger, profile, message, log) -> bool:
    """``message`` waits, kept, for something the owner has still to do (a note held for the answer of a card with several
    questions): QUEUED. Whether it is on."""
    return bool(message) and put(messenger, profile, message, QUEUED, "top waits", log)


def top_refused(messenger, profile, message, log) -> bool:
    """``message`` was refused before anything took it (an answer the question no longer takes, a topic whose result or
    question card has not arrived): QUEUED off, CrossMark on; why is said in the topic's thread. Whether it is on."""
    if not message:
        return False
    take_off(messenger, profile, message, QUEUED, "top refused", log)
    return put(messenger, profile, message, FAILED, "top refused", log)
