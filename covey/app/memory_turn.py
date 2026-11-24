"""What a turn reads of the owner's memory (COVEY_MEMORY=1, core/memory.py, docs/butler.md 记忆), for app/runs.py: ``block`` is
the one block that stands in for the principles', the knowledge entries' and the project memory's own (a new session's rules and
a resumed session's reminder carry it whole every turn), ``record`` writes the numbers of the entries a turn carried into its
job record (``memory_ids``), ``fix_rule`` whether the turn's rules tell the model it may write ``memory`` and ``memory_void`` into
its checkpoint (app/memory_collect.py reads them once the turn has ended).

Who reads what is as it was: a 代答 topic nothing; the owner's 全局 entries only on the owner's own turn (``owner_turn()``), the
workspace's on any; the project's lines in an ordinary topic of a project; the topic's own always. A line from a topic with
redaction on is only read by one with it on (a setting that cannot be read counts as off here). The project's lines come with
what its parts left out, the lines voided since the topic's previous turn and the version (app/project_context.py
memory_view, the read the lead's pack and the web page take too). Nothing is written but ``memory_ids``; nothing raises into
the turn.

With COVEY_MEMORY_LEARN=1 too (core/memory.py learning, docs/butler.md 记忆自己长): the candidates the Bridge distilled and
has not had decided are read as 它总结的 (app/memory_candidates.py carried; 全局 ones on the owner's turn only, as his
principles), each item's last use orders it (core/memory_usage.py), the block ends with how to look up what it could not
carry (``search_command``: bin/covey_memory.py, not on a device, whose files are not the hub's) and asks for ``memory_used``;
the correction rule is never carried (``fix_rule``): the Bridge reads the owner's words itself after the turn
(app/memory_learn.py)."""
from __future__ import annotations

import shlex
import sys

from covey.app import knowledge_turn, memory_candidates, project_context
from covey.app.prompts import memory_block
from covey.core import knowledge, memory, memory_usage, principles, topic_memory, turn_source
from covey.core.butler import is_butler_topic
from covey.core.butler_opened import handed_on
from covey.core.jobs import job_key, upsert_job_record
from covey.core.paths import entry_script
from covey.core.process import device_of
from covey.core.redaction import topic_redaction
from covey.core.topics import proxy_topic

WORDS = memory.CORRECTION_WORDS  # The owner's words that start a correction.
SAVED_WORDS = ("记一下", "记住", "记下来")  # COVEY_KNOWLEDGE's own (app/knowledge_collect.py): it takes those.


def owner_words(record, state_dir=None) -> str:
    """The owner's own words of the turn of job ``record``: its ``user_text``, but of an answer's turn (app/answers.py
    answer_message) only what he answered and the notes he added, and of a feedback only the feedback; the question's own
    words, written by the Bridge or a model, are never his. ``state_dir``: where the question record is, to tell an answer of
    several lines from its question exactly (app/answer_cards.py asked_questions)."""
    from covey.app.answer_cards import asked_questions
    from covey.app.answers import FEEDBACK_START, answer_parts
    said = str(record.get("user_text") or "")
    if said.startswith(FEEDBACK_START):
        return said[len(FEEDBACK_START):]
    asked = asked_questions(state_dir, str(record.get("message_id") or "")) if state_dir is not None else []
    parts = answer_parts(said, asked)
    if parts:
        return "\n".join(text for kind, text in parts if kind in ("answer", "note"))
    return said


def active(ctx) -> bool:
    return memory.enabled() and not proxy_topic(ctx)


def redacted(ctx, topic_id) -> bool:
    """Whether the topic has redaction on; off when it cannot be read (the lines that need it are then left out)."""
    return project_context.marked(ctx.state_dir, topic_id)


def gather(ctx, job, owner_turn) -> list:
    topic_id = getattr(job, "topic_id", "") or ctx.topic_id
    owner = owner_turn()
    state = ctx.state_dir
    mine, space = principles.for_turn(state, ctx.workspace_name)
    entries = knowledge.for_turn(state, ctx.workspace_name) if knowledge.enabled() else ((), ())
    project_id, rows = project_context.memory_rows(ctx, job)
    drafts, used = ((), ()), None
    if memory.learning():
        found = memory_candidates.carried(state, ctx.workspace_name)
        drafts, used = (found[0] if owner else [], found[1]), memory_usage.last_used(state)
    return memory.items(principles=(mine if owner else [], space), entries=(entries[0] if owner else [], entries[1]),
                        project=rows, topic=topic_memory.live(state, topic_id), project_id=project_id,
                        redacted=redacted(ctx, topic_id), drafts=drafts, used=used)


def build(ctx, job, owner_turn) -> tuple[list, int]:
    return memory.select(gather(ctx, job, owner_turn))


def block(ctx, job, *, owner_turn) -> str:
    """The memory block of ``job``'s turn; '' with COVEY_MEMORY off, for a 代答 topic, or with nothing to say."""
    try:
        if not active(ctx):
            return ""
        kept, left = build(ctx, job, owner_turn)
        topic_id = getattr(job, "topic_id", "") or ctx.topic_id
        learn = {"search": search_command(ctx, job, owner_turn())} if memory.learning() else None
        return memory_block(kept, left, project_context.memory_view(ctx, job, redacted=redacted(ctx, topic_id)), learn=learn)
    except Exception:  # noqa: BLE001 - the turn goes on without it
        return ""


def search_command(ctx, job, owner) -> str:
    """The command line a turn looks its memory up with (bin/covey_memory.py search, core/memory_search.py): this
    deployment's state and the turn's topic, ``--owner`` on the owner's own turn (his 全局 lines), ``--redacted`` in a topic
    with redaction on (the lines only such a topic reads); '' on a device, whose files are not this machine's."""
    if device_of(ctx):
        return ""
    topic_id = str(getattr(job, "topic_id", "") or ctx.topic_id or "")
    try:
        hidden = bool(topic_redaction(ctx.state_dir, topic_id))
    except ValueError:
        hidden = False  # Its redacted lines are then not looked up, as the block leaves them out.
    words = [sys.executable, "-B", str(entry_script("covey_memory.py")), "search", "--state", str(ctx.state_dir),
             "--topic", topic_id, *(["--owner"] if owner else []), *(["--redacted"] if hidden else [])]
    return " ".join(shlex.quote(word) for word in words) + ' "<一句话>"'


def record(ctx, job, owner_turn, log=None) -> None:
    """Write the numbers of the entries the turn's rules carry into its job record (``memory_ids``: [{n, ref, scope, by}])."""
    try:
        if not active(ctx):
            return
        kept, _ = build(ctx, job, owner_turn)
        upsert_job_record(ctx.state_dir, job_key(job.message_id, job.job_id), memory_ids=memory.ids_of(kept))
    except Exception as exc:  # noqa: BLE001 - the record is a convenience for the correction after the turn
        if log is not None:
            log(f"memory ids not recorded: {type(exc).__name__}")


def triggered(text, *, knowledge_takes=False) -> bool:
    """Whether the owner's words of the turn hold one of ``WORDS``; ``knowledge_takes``: COVEY_KNOWLEDGE's 记住 and the like
    are its own (the entry goes there, once)."""
    text = str(text or "")
    return any(word in text for word in WORDS if not (knowledge_takes and word in SAVED_WORDS))


def fix_rule(ctx, job, owner_turn) -> bool:
    """Whether the rules of this turn carry the memory correction rule: memory on, the owner's own turn in a topic (not the
    butler's, which has its tools; not one the butler handed on), and their words hold one of ``WORDS``."""
    try:
        if not active(ctx) or memory.learning() or not owner_turn() or handed_on(getattr(job, "message_id", "")):
            return False  # With the memory learning, the Bridge reads the owner's words after the turn (app/memory_learn.py).
        if not turn_source.behavior(job).owner_words:
            return False  # A 协作 turn's words are not the owner's (core/turn_source.py): nothing of them is his to correct.
        if is_butler_topic(getattr(job, "topic_id", "") or ctx.topic_id, getattr(job, "chat_id", "")):
            return False
        takes = knowledge_turn.remembers(ctx, job, owner_turn=owner_turn)
        said = owner_words({"user_text": getattr(job, "user_text", ""), "message_id": getattr(job, "message_id", "")},
                           ctx.state_dir)
        return triggered(said, knowledge_takes=takes)
    except Exception:  # noqa: BLE001
        return False
