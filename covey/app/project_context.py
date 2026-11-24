"""What a project's memory and library (core/project_memory.py, core/project_library.py) do in the Bridge, when
COVEY_PROJECTS=1 and COVEY_PROJECT_MEMORY=1; with either off every function here does nothing and reads nothing.

- ``block``: the lines a topic of a project reads when it starts (app/runs.py puts them into the rules of a new session and
  into the reminder of a resumed one): the memory, and in a new session the library's index too. An ordinary topic, a
  lead's (it has its pack, app/project_lead.py) and a 代答 topic get none. The memory is ``memory_view``'s, the one read the
  lead's pack and the web page take too (core/memory.py project_view): its three layers, each with its own room, what was
  voided since the topic's previous turn, the version.
- ``remember_answer`` (app/questions.py): the owner's answer to a question card of a project's topic or lead becomes memory
  entries, one a question answered (kind decision, source owner_answer, "主人答：question→answer", ``answer_line``), and the
  question record as it was answered is kept whole beside them (core/project_memory.py note_answers). Feedback and skipped
  answers do not. A question that names an entry of another project's memory by its id (``elsewhere``) is history at once.
- ``fix_memory``: the owner's correction of a line (docs/web.md memory_fix: ``scope`` its conditions, ``once`` only that time,
  ``confirm`` his for good), for the page and the cards to call once they checked the click is the owner's.
- ``owner_files`` (app/app.py, the message of the owner in a lead's topic: quoting the project's card goes there): the files it
  carries are copied into the library with their sha256.
- ``turn_to_library`` (app/project_loop.py after_runner, the Bridge once a topic's run has ended; rule 8: a task process writes
  nothing of the project's): the artifacts the turn's checkpoint lists and its delivery become index lines, by path or link only,
  nothing copied.

Rule 1 (AGENTS.md): the records are written under their own lock; nothing is sent to Feishu. Nothing raises: a project's memory
is never why a turn or an answer does not go through."""
from __future__ import annotations

from pathlib import Path

from covey.app.answers import SKIPPED
from covey.app.prompts import project_block, project_memory_lines
from covey.core import board_read
from covey.core import memory as core_memory
from covey.core import project_library, project_memory, projects, triage
from covey.core.attachments import ATTACHMENTS_HEADER, parse_attachment_block
from covey.core.checkpoint import checkpoint_delivery, read_checkpoint
from covey.core.redaction import topic_redaction
from covey.core.text import cut
from covey.core.topics import proxy_topic

ANSWER_CHARS = 190  # Of an answer that does not fit with its question in one line: what it keeps before the question is cut.
ANSWER_HEAD = "主人答："
ARTIFACTS_PER_TURN = 8
FILES_PER_MESSAGE = 5


def member_record(ctx, job):
    """(project id, its record) of the project ``job``'s topic is an ordinary topic of, that is not cancelled; None otherwise
    (also with COVEY_PROJECTS or COVEY_PROJECT_MEMORY off, and for a 代答 topic)."""
    if not projects.memory_enabled() or proxy_topic(ctx):
        return None
    state = ctx.state_dir
    found = projects.topic_project(state, getattr(job, "topic_id", "") or ctx.topic_id)
    if found is None or found.role != projects.MEMBER:
        return None
    record = projects.read_record(state, found.id)
    if not record or record.get("state") == projects.CANCELLED:
        return None
    return found.id, record


def memory_rows(ctx, job) -> tuple[str, list]:
    """(project id, its live memory lines without the style line) for COVEY_MEMORY=1's one block (app/memory_turn.py); ('', [])
    when ``member_record`` has none. Never raises."""
    try:
        found = member_record(ctx, job)
        return (found[0], project_memory.live(ctx.state_dir, found[1], style=False)) if found else ("", [])
    except Exception:  # noqa: BLE001 - the turn goes on without it
        return "", []


def marked(state_dir, topic_id) -> bool:
    """Whether ``topic_id`` reads the lines from topics with redaction on: its own redaction is on (off when it cannot be read)."""
    try:
        return bool(topic_redaction(state_dir, topic_id))
    except ValueError:
        return False


def memory_view(ctx, job, *, redacted=None):
    """The project's memory as ``job``'s turn in a member topic reads it (core/memory.py project_view of every entry), None when
    ``member_record`` has none: ``since`` the start of the topic's previous turn (core/board_read.py previous_start), so the lines
    voided after it are said. ``redacted``: whether the topic reads the lines from topics with redaction on (None: its own
    setting, ``marked``)."""
    found = member_record(ctx, job)
    if found is None:
        return None
    pid, record = found
    topic = getattr(job, "topic_id", "") or ctx.topic_id
    since = board_read.previous_start(ctx.state_dir, topic, getattr(job, "job_id", 0))
    return core_memory.project_view(project_memory.entries(ctx.state_dir, record), pid,
                                    redacted=marked(ctx.state_dir, topic) if redacted is None else redacted, since=since)


def block(ctx, job, *, resumed: bool) -> str:
    """The project block for ``job``'s turn in ``ctx``'s topic: '' unless it is a topic of a project that is not cancelled.
    ``resumed``: the memory alone (the session read the library's index when it began). With COVEY_MEMORY=1 the memory is in
    the one memory block (app/memory_turn.py), so only the library's index is here."""
    try:
        found = member_record(ctx, job)
        if found is None:
            return ""
        pid, record = found
        state = ctx.state_dir
        memory = [] if core_memory.enabled() else project_memory_lines(memory_view(ctx, job))
        library = [] if resumed else ["- " + line for line in project_library.index_lines(state, pid)]
        return project_block(record.get("name"), memory, library, limit=None)
    except Exception:  # noqa: BLE001 - the turn goes on without it
        return ""


def answer_line(question, answer) -> str:
    """One answered question as a line of the project's memory, "主人答：<question>→<answer>": both whole when they fit in
    core/project_memory.py ANSWER_TEXT, else the question cut first, the answer keeping at least ``ANSWER_CHARS`` (the whole of
    both stays in the question record kept beside the memory)."""
    question, answer = " ".join(str(question or "").split()), " ".join(str(answer or "").split())
    room = project_memory.ANSWER_TEXT - len(ANSWER_HEAD) - 1
    if len(question) + len(answer) > room:
        answer = cut(answer, max(room - len(question), ANSWER_CHARS))
        question = cut(question, room - len(answer))
    return f"{ANSWER_HEAD}{question}→{answer}"


def elsewhere(state_dir, project_id, lines, log=None) -> None:
    """Of ``lines`` (``remember_answer``'s, each with ``asked``: the question's id, header and text), the ones whose question
    names an entry of another project's memory by its id (core/project_memory.py quoted) get ``valid`` done: the card sorted
    out that project's memory (a migration asking how each of its lines counts), and what the owner chose holds in that line,
    not as a decision of this project, so it is noted as history and never carried. Only a question with a word that looks
    like an id makes the projects' memories be read; when they cannot be, the answers are noted as decisions as before."""
    asked = [line for line in lines if project_memory.QUOTE.search(line["asked"])]
    if not asked:
        return
    try:
        known = project_memory.ids(project_memory.across(state_dir))
    except Exception as exc:  # noqa: BLE001 - noted as decisions, as before
        if log is not None:
            log(f"project memory answers not read against the other projects: {type(exc).__name__}")
        return
    for line in asked:
        about = project_memory.quoted(known, project_id, line["asked"])
        if about:
            line["valid"] = "done"
            if log is not None:
                log(f"project memory answer {line['index']} noted as history: it names project {about[0]}'s lines")


def remember_answer(state_dir, topic_id, record, log=None) -> None:
    """Note the owner's saved answer ``record`` (a question record with ``answers``) of ``topic_id`` in its project's memory:
    a decision for each question answered (``answer_line``), the record kept whole beside them (core/project_memory.py
    note_answers; a record with no token, as none is, an entry a question with no record kept); one whose question is about
    another project's memory is history (``elsewhere``).
    An answer the lead gave in the owner's place (COVEY_PROJECT_TRIAGE=1: the record is still ``held`` while it is saved,
    app/triage.py ``answer``) is not the owner's word and is not noted; the 分流记录 and the decision log hold it, and the
    owner's 不对 corrects it. A question the lead passed on (``escalated``) and the owner answered is noted as always."""
    try:
        if not projects.memory_enabled() or record.get("response_kind") == "feedback" or triage.state(record) in {triage.HELD, triage.ANSWERED}:
            return
        found = projects.topic_project(state_dir, topic_id)
        if found is None:
            return
        answers = record.get("answers") if isinstance(record.get("answers"), dict) else {}
        lines = []
        for index, question in enumerate(record.get("questions") or (), 1):
            if not isinstance(question, dict):
                continue
            given = (answers.get(question.get("id")) or {}).get("answers")
            parts = [str(part) for part in given or () if str(part).strip() and part != SKIPPED]
            if parts:
                lines.append({"index": index, "item": str(question.get("id") or ""),
                              "text": answer_line(question.get("question") or question.get("header"), "；".join(parts)),
                              "asked": " ".join(str(question.get(key) or "") for key in ("id", "header", "question"))})
        if not lines:
            return
        if project_memory.TOKEN.fullmatch(str(record.get("token") or "")):
            elsewhere(state_dir, found.id, lines, log)
            project_memory.note_answers(state_dir, found.id, {**record, "topic_id": record.get("topic_id") or topic_id}, lines)
            return
        for line in lines:
            project_memory.add(state_dir, found.id, line["text"], "decision", "owner_answer",
                               origin={"item": line["item"], "index": line["index"], "topic": topic_id})
    except Exception as exc:  # noqa: BLE001 - the answer is delivered whether or not it was noted
        if log is not None:
            log(f"project memory of an answer failed: {type(exc).__name__}")


def fix_memory(state_dir, project_id, entry_id, what, *, owner, message_id, applies="") -> dict:
    """The owner's correction ``what`` of the line ``entry_id`` of the project's memory (core/project_memory.py fix): ``scope``
    sets its conditions (``applies``), ``once`` makes it a 当前决定 for that one time, ``confirm`` makes it a 长期约定 the owner
    said, at the owner's level, its origin this correction. ``owner``: the caller checked the click or the page's operation is
    the owner's (app/access.py); anybody else's is refused, and no model's word comes here. ``message_id``: the id the Bridge
    took the correction in with. The line as core/memory.py describe reads it, with its text and id. ValueError for a refusal
    or a line that is not there."""
    if owner is not True:
        raise ValueError("只有主人能改专项记忆")
    row = project_memory.fix(state_dir, project_id, entry_id, what, origin={"message_id": str(message_id or "")}, applies=applies)
    return {"id": row["id"], "text": row["text"], **core_memory.describe(row)}


def owner_files(state_dir, topic_id, chat_id, text, media, log=None) -> None:
    """The files the owner's message ``text`` lists (the attachments block the Bridge wrote) copied into the library of the project
    whose lead's topic is ``topic_id``; only a file saved under ``media`` (the topic's incoming_media) is."""
    try:
        if not projects.memory_enabled() or ATTACHMENTS_HEADER not in str(text or "") or not projects.is_lead_topic(state_dir, topic_id, chat_id):
            return
        found = projects.topic_project(state_dir, topic_id)
        root = Path(media).resolve()
        for item in parse_attachment_block(text)[:FILES_PER_MESSAGE]:
            path = Path(item.path).resolve()
            if root in path.parents and path.is_file():
                project_library.add_file(state_dir, found.id, path, name=item.name or path.name, source="owner_file", topic_id=topic_id)
    except Exception as exc:  # noqa: BLE001 - the message goes on
        if log is not None:
            log(f"project library of a message failed: {type(exc).__name__}")


def turn_to_library(state_dir, project_id, topic_id, job_record, log=None) -> None:
    """The artifacts and the delivery of a topic's turn that ended well (``job_record``, its job record) noted in the library of
    ``project_id``: where they are, not copies."""
    try:
        if not projects.memory_enabled() or job_record.get("status") != "done":
            return
        path = str(job_record.get("checkpoint_path") or "")
        checkpoint = read_checkpoint(Path(path)) if path else {}
        artifacts = checkpoint.get("artifacts")
        for ref in [str(item) for item in artifacts if item][:ARTIFACTS_PER_TURN] if isinstance(artifacts, list) else ():
            project_library.add_ref(state_dir, project_id, "link" if ref.startswith(("http://", "https://")) else "path", ref,
                                    source="artifact", topic_id=topic_id)
        delivery = checkpoint_delivery(checkpoint)
        if delivery:
            line = "；".join(f"{label} {delivery[name]}" for name, label in (("commit", "提交"), ("deployed", "部署"), ("verified", "验收"))
                            if delivery.get(name))
            project_library.add_ref(state_dir, project_id, "delivery", line, name="交付", source="delivery", topic_id=topic_id)
    except Exception as exc:  # noqa: BLE001 - the task's end does not depend on it
        if log is not None:
            log(f"project library of a turn failed: {type(exc).__name__}")
