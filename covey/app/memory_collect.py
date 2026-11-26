"""What the owner said in a topic's turn that holds from now on becomes memory (COVEY_MEMORY=1, docs/butler.md 记忆), and a
click takes it back.

The model may write ``memory`` ([{quote, text}], at most ``PER_TURN``) and ``memory_void`` ([{id, quote}]) into its checkpoint on a
turn whose rules said so (app/memory_turn.py fix_rule: the owner's words hold 以后 / 每次 / 别再 …). The Bridge, not the task
runner (rule 8: a task process changes only its own task's card and record), checks them here once the runner has exited and the
record is settled (app/detached.py finish_detached, app/job_dispatch.py for a run in this process): ``collect``.

- A ``quote`` must be a run of the owner's own words of that turn (app/memory_turn.py ``owner_words``: the job record's ``user_text``, but of an
  answer's turn only what he answered and added, never the question's own words); one that is not drops its line.
- A ``memory`` line becomes a line of 你说的 in the narrowest place there is: the project the topic belongs to (core/project_memory.py,
  source ``owner``), else the topic (core/topic_memory.py). A topic with redaction on (or whose setting cannot be read) marks it.
- A ``memory_void`` id must be a number the turn carried (the record's ``memory_ids``) of a line of 它总结的 of the project; it becomes a
  tombstone (core/project_memory.py delete: the text stays, nothing is lost). A line of 你说的 is never voided this way.
- The record gets ``memory_notes`` [{kind: remembered|voided|undone, text, scope, entry_id, redacted?}] and the turn's answer cards
  a line each (cards/answer_card.py memory_element); the 不对 on a "记下了" line takes that line back (``undo``): the entry becomes
  a tombstone, the note's kind ``undone``. 升为全局 beside it (``promote``, T647 E4: what he said in one topic held only there)
  makes the line one of the owner's principles for every topic (core/principles.py, 通用) and the entry a tombstone; the note
  says 管全局 then, its entry the principle, and 不对 takes the principle back.

It writes only when the turn ended well, was the owner's own in an ordinary topic (not the butler's, not a 代答 topic, not one the
butler handed on) whose words hold a trigger word, and not twice for one job. Never raises: a failure is a log line and the turn's
other ending steps go on."""
from __future__ import annotations

from pathlib import Path

from covey.app import answer_cards, memory_turn
from covey.app.card_actions import action_value
from covey.app.card_lanes import after_ack
from covey.cards.answer_card import memory_element
from covey.core import memory, memory_usage, principles, project_memory, projects, topic_memory, turn_source
from covey.core.butler import is_butler_topic
from covey.core.checkpoint import read_checkpoint
from covey.core.jobs import find_job_record, upsert_job_record
from covey.core.topics import proxy_topic

PER_TURN = 3
ENDED_WELL = ("done", "waiting_user")
PROJECT_WORDS, TOPIC_WORDS = "管这个专项", "管这个话题"
GLOBAL_WORDS = "管全局"  # A line 升为全局 (``promote``): one of the owner's principles now.
WORKSPACE_WORDS = "管这个工作区"  # A line the memory learned as a principle of the topic's workspace (app/memory_learn.py).
PRINCIPLE_WORDS = (GLOBAL_WORDS, WORKSPACE_WORDS)  # A note whose entry is a principle: 不对 removes the principle.
REDACTED_REFUSAL = "这条来自开着脱敏的话题，不能升为全局：全局的记忆会带进不脱敏的话题。"


def _squash(text) -> str:
    return "".join(str(text or "").split())


def from_owner(quote, said) -> bool:
    """Whether ``quote`` (not empty) is a run of ``said``, the owner's words of the turn, whitespace aside."""
    quote = _squash(quote)
    return bool(quote) and quote in _squash(said)


def reason_to_ignore(runtime, ctx, job, record) -> str:
    """Why the turn's lines are not taken; '' when they may be."""
    topic_id = str(record.get("topic_id") or getattr(job, "topic_id", "") or "")
    chat = str(record.get("chat_id") or getattr(job, "chat_id", ""))
    if record.get("status") not in ENDED_WELL:
        return "not-finished"
    if not turn_source.behavior(job, record).owner_words:
        return "not-owner-words"  # A 协作 turn's text is not the owner's (core/turn_source.py).
    if not runtime.access.owner_turn(chat, str(record.get("sender_id") or getattr(job, "sender_id", "") or "")):
        return "not-owner"
    if memory_turn.handed_on(record.get("message_id") or getattr(job, "message_id", "")):
        return "handed-on"
    if is_butler_topic(topic_id, chat):
        return "butler"
    if proxy_topic(ctx):
        return "proxy"
    if not memory_turn.triggered(memory_turn.owner_words(record, ctx.state_dir),
                                 knowledge_takes=_knowledge_takes(runtime, ctx, job, record)):
        return "no-trigger"
    return ""


def _knowledge_takes(runtime, ctx, job, record) -> bool:
    from covey.app import knowledge_turn
    return knowledge_turn.remembers(ctx, job, owner_turn=lambda: True)


def _topic_marked(ctx, topic_id) -> bool:
    """Whether a line from the topic carries the redaction mark: redaction on, or its setting cannot be read."""
    from covey.core.redaction import topic_redaction
    try:
        return bool(topic_redaction(ctx.state_dir, topic_id))
    except ValueError:
        return True


def _take(ctx, record, text, marked, quote=""):
    """(the note of one ``memory`` line, or None): the line written in the narrowest place; a project's keeps where it came
    from (the owner's message the turn answered, its topic and job, and the owner's words ``quote``d)."""
    topic_id = str(record.get("topic_id") or "")
    state = ctx.state_dir
    found = projects.topic_project(state, topic_id) if projects.memory_enabled() else None
    if found is not None and found.role == projects.MEMBER:
        entry, new = project_memory.add(state, found.id, text, "constraint", "owner", redacted=marked, origin={
            "message_id": str(record.get("message_id") or ""), "topic": topic_id, "job": str(record.get("key") or ""),
            "quote": str(quote or "")})
        scope = PROJECT_WORDS
    elif found is None:
        entry, new = topic_memory.add(state, topic_id, text, source="owner", redacted=marked)
        scope = TOPIC_WORDS
    else:
        return None  # A lead's own topic: the butler's tools are its way.
    return ({"kind": "remembered", "text": entry["text"], "scope": scope, "entry_id": entry["id"],
             **({"redacted": True} if marked else {})} if new else None)


def _void(ctx, record, item):
    """(the note of one ``memory_void`` item, or None): a line of 它总结的 the turn carried, struck out."""
    wanted = str(item.get("id") or "").strip()
    carried = next((row for row in record.get("memory_ids") or () if isinstance(row, dict) and row.get("n") == wanted), None)
    if carried is None or carried.get("by") != memory.LEAD or not str(carried.get("ref")).startswith("project:"):
        return None
    _, project_id, entry_id = str(carried["ref"]).split(":", 2)
    row = next((row for row in project_memory.stored(ctx.state_dir, project_id) if row["id"] == entry_id and not row["deleted"]), None)
    if row is None or memory.describe(row)["asserted_by"] == "owner" or not project_memory.delete(ctx.state_dir, project_id, entry_id):
        return None  # What the owner said (a correction of his included) is never voided by a model's word.
    return {"kind": "voided", "text": row["text"], "scope": PROJECT_WORDS, "entry_id": entry_id}


def collect(runtime, messenger, job, ctx) -> None:
    """Take the turn's ``memory`` and ``memory_void`` as the module says. Nothing when the switch is off."""
    if not memory.enabled():
        return
    try:
        record = find_job_record(ctx.state_dir, str(getattr(job, "message_id", "") or ""))
        path = str((record or {}).get("checkpoint_path") or "")
        found = read_checkpoint(Path(path)) if path else {}
        if not record:
            return
        wanted, voids = found.get("memory"), found.get("memory_void")
        wanted, voids = wanted if isinstance(wanted, list) else [], voids if isinstance(voids, list) else []
        if not (wanted or voids) or "memory_notes" in record:
            return
        reason = reason_to_ignore(runtime, ctx, job, record)
        if reason:
            runtime.log(f"memory lines ignored reason={reason} job=#{record.get('job_id')}")
            return
        said, marked, notes = memory_turn.owner_words(record, ctx.state_dir), _topic_marked(ctx, str(record.get("topic_id") or "")), []
        for item in voids[:PER_TURN]:
            if isinstance(item, dict) and from_owner(item.get("quote"), said):
                notes.append(_void(ctx, record, item))
        for item in wanted[:PER_TURN]:
            text = project_memory.clean(item.get("text")) if isinstance(item, dict) else ""
            if text and from_owner(item.get("quote"), said):
                notes.append(_take(ctx, record, text, marked, item.get("quote")))
        notes = [note for note in notes if note]
        runtime.log(f"memory lines written={len(notes)} of {len(wanted) + len(voids)} job=#{record.get('job_id')}")
        if notes:
            upsert_job_record(ctx.state_dir, str(record["key"]), memory_notes=notes)
            show(ctx, messenger, record, notes, runtime.log)
    except Exception as exc:  # noqa: BLE001 - the turn's ending goes on; the owner's words are in the record
        runtime.log(f"memory lines failed job=#{getattr(job, 'job_id', '?')}: {type(exc).__name__}")


def show(ctx, messenger, record, notes, log) -> None:
    """The memory lines of ``notes`` put on the job's answer cards."""
    element = memory_element(notes, str(record.get("topic_id") or ""), str(record.get("job_id") or ""))
    if element is not None and messenger is not None:
        answer_cards.put_memory(ctx.state_dir, ctx.profile, messenger, str(record["key"]), element, log,
                                answer_message_id=str(record.get("answer_message_id") or ""))


def undo(host, ctx, event) -> bool:
    """不对 on a "记下了" line (``host``: the TaskControls): the entry becomes a tombstone, the note ``undone``, the lines redrawn."""
    raw = action_value(event)
    if not ctx.topic_id or raw.get("topic_id") != ctx.topic_id:
        return True
    record = find_job_record(ctx.state_dir, str(raw.get("job_id") or ""))
    entry_id = str(raw.get("entry_id") or "")
    if not record or record.get("topic_id") != ctx.topic_id or not entry_id:
        raise ValueError("找不到这条记忆所在的任务")
    notes = take_back(ctx.state_dir, ctx.topic_id, record, entry_id)
    if notes is not None:  # None: taken back already (a second click), or not this turn's.
        after_ack(lambda: show(ctx, host.messenger, record, notes, host.runtime.log))
    return True


def take_back(state, topic_id, record, entry_id):
    """不对 on the entry ``entry_id`` the turn of job ``record`` (of ``topic_id``) wrote, the card's and the web page's
    (app/web_ops.py memory_undo, data contract v34): the entry a tombstone, its note ``undone`` in the job record. The job's
    notes as they are now (the caller redraws the answer card's lines from them); None when there is no such note still
    remembered (taken back already, or not this turn's), nothing changed."""
    notes = [dict(note) for note in record.get("memory_notes") or ()]
    note = next((note for note in notes if note.get("kind") == "remembered" and note.get("entry_id") == entry_id), None)
    if note is None:
        return None
    _forget(state, topic_id, entry_id, note.get("scope"))
    note["kind"] = "undone"
    notes = [note if old.get("entry_id") == entry_id and old.get("kind") == "remembered" else old for old in notes]
    upsert_job_record(state, str(record["key"]), memory_notes=notes)
    return notes


def _forget(state, topic_id, entry_id, scope="") -> None:
    """The entry ``entry_id`` a turn of ``topic_id`` wrote, a tombstone in its project's memory or the topic's; a line that
    is a principle (``scope`` one of PRINCIPLE_WORDS: it went 升为全局, or the memory learned it as one), the principle removed."""
    if scope in PRINCIPLE_WORDS:
        principles.delete(state, entry_id)
        return
    found = projects.topic_project(state, topic_id) if projects.memory_enabled() else None
    if found is not None:
        project_memory.delete(state, found.id, entry_id)
    topic_memory.delete(state, topic_id, entry_id)


def _entry(state, topic_id, entry_id):
    """The live entry ``entry_id`` a turn of ``topic_id`` wrote, in its project's memory or the topic's; None when it is gone."""
    found = projects.topic_project(state, topic_id) if projects.memory_enabled() else None
    rows = [row for row in (project_memory.stored(state, found.id) if found is not None else []) if not row.get("deleted")]
    rows = [*rows, *topic_memory.live(state, topic_id)]
    return next((row for row in rows if isinstance(row, dict) and row.get("id") == entry_id), None)


def promote(host, ctx, event) -> bool:
    """升为全局 on a "记下了" line of 管这个专项 or 管这个话题 (``host``: the TaskControls, COVEY_MEMORY=1): the line becomes one of the
    owner's principles (core/principles.py save, 通用: every topic reads it on his own turns), the entry it was a tombstone, the
    note 管全局 with the principle as its entry, the lines redrawn. ValueError says why nothing changed (a line from a topic with
    redaction on, a full group); a second click does nothing."""
    raw = action_value(event)
    if not ctx.topic_id or raw.get("topic_id") != ctx.topic_id:
        return True
    record = find_job_record(ctx.state_dir, str(raw.get("job_id") or ""))
    entry_id = str(raw.get("entry_id") or "")
    if not record or record.get("topic_id") != ctx.topic_id or not entry_id:
        raise ValueError("找不到这条记忆所在的任务")
    notes = [dict(note) for note in record.get("memory_notes") or ()]
    note = next((note for note in notes if note.get("kind") == "remembered" and note.get("entry_id") == entry_id
                 and note.get("scope") in (PROJECT_WORDS, TOPIC_WORDS)), None)
    if note is None:
        return True  # Promoted or taken back already (a second click), or not this turn's.
    entry = _entry(ctx.state_dir, ctx.topic_id, entry_id)
    if entry is None:
        raise ValueError("这条记忆已经不在了（在设置卡「记忆」里删掉过）")
    if note.get("redacted") or entry.get("redacted"):  # core/memory.py: only a topic with redaction on reads it.
        raise ValueError(REDACTED_REFUSAL)
    found, _ = principles.save(ctx.state_dir, principles.OWNER, note["text"], source={
        "job_key": str(record.get("key") or ""), "job_id": record.get("job_id"), "from": note.get("scope")})
    held = projects.topic_project(ctx.state_dir, ctx.topic_id) if projects.memory_enabled() else None
    memory_usage.carry(ctx.state_dir, f"project:{held.id}:{entry_id}" if held is not None else f"topic:{entry_id}", f"principle:{found['id']}")
    _forget(ctx.state_dir, ctx.topic_id, entry_id, note.get("scope"))
    note.update(scope=GLOBAL_WORDS, entry_id=found["id"])
    upsert_job_record(ctx.state_dir, str(record["key"]), memory_notes=notes)
    host.runtime.log(f"memory line promoted to a principle job=#{record.get('job_id')}")
    after_ack(lambda: show(ctx, host.messenger, record, notes, host.runtime.log))
    return True


def void_turn(runtime, messenger, ctx, record) -> int:
    """The owner recalled the message of the turn ``record`` (app/source_watch.py): every line it 记下了 is taken back as
    不对 does, its answer cards redrawn; how many."""
    notes = [dict(note) for note in record.get("memory_notes") or () if isinstance(note, dict)]
    topic, taken = str(record.get("topic_id") or ""), 0
    for note in notes:
        if note.get("kind") == "remembered" and note.get("entry_id"):
            _forget(ctx.state_dir, topic, str(note["entry_id"]), note.get("scope"))
            note["kind"], taken = "undone", taken + 1
    if taken:
        upsert_job_record(ctx.state_dir, str(record["key"]), memory_notes=notes)
        show(ctx, messenger, record, notes, runtime.log)
    return taken
