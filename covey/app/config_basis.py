"""Why a topic the butler or a project's lead opens, or a batch of topics it switches, names a Harness, model or budget
(T786): the owner's words, not a preference stretched past the kind of work it was said for.

A model's call of topic_start or project_topic_start (``CHECKED``, refused by app/butler_tools.py before it runs) that names
``harness``, ``model`` or ``effort``, and every call of topics_switch (app/batch_switch.py), gives ``basis``: a run of the owner's own words of the turn (app/butler_handoff.py
``asked``: the message the turn answers and the supplements it took), a run of a principle's text or of a line of the lead's
project memory, or the id of a principle (core/principles.py, ``p1a2b3c``) or of a memory line the turn carried (``M12``,
its job record's ``memory_ids``, app/memory_turn.py). ``check`` finds it or says why not; the caller refuses the call then, so
the model leaves the fields empty (the settings' default) or asks. What it found (``shown``) is kept with the plan and said
where the owner sees the configuration: the topic card's line (按「…」) and the batch switch card.

Words are compared without spaces, punctuation and case (``compact``): "用 Codex" is "用codex". A quote shorter than
``SHORTEST`` characters so compared is never a basis (a bare "codex" could come from anywhere).
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from covey.app.butler_env import arg_text

FIELDS = ("harness", "model", "effort")
# The model's calls app/butler_tools.py checks before they run (ButlerTools.refusal): topics_switch checks its own.
CHECKED = frozenset({"topic_start", "project_topic_start"})
SHORTEST = 3  # Characters of a quote, compacted.
SHOWN = 24  # Characters of what the cards say of a basis.
PRINCIPLE_ID = re.compile(r"\bp[0-9a-f]{6}\b")
MEMORY_ID = re.compile(r"\bM\d{2,3}\b")
QUOTES = "「」『』“”\"'‘’《》"
MISSING = ("填了 harness、model 或 effort 就要写 basis：主人这一轮原话里连续的一段，或记下的原则编号（p1a2b3c）、"
           "这一轮带的记忆编号（M12）。主人没点名、原则也没明说这一类事用它时，不要填这几项，用设置里的默认。")
NOT_FOUND = ("basis「{basis}」在主人这一轮的原话、记下的原则和这一轮带的记忆里都没找到，没有执行。"
             "写主人原话里连续的一段或编号；原则或记忆只管它说的那类事（如“监视进程这类用 Codex”不管修代码），"
             "对不上就不要填 harness、model、effort，用设置里的默认。")


def named(args) -> bool:
    """Whether a call names a Harness, model or budget of its own."""
    return any(arg_text(args.get(field)) for field in FIELDS)


def compact(text) -> str:
    """``text`` lower-cased without spaces, punctuation and symbols: what a quote is compared by."""
    return "".join(ch for ch in unicodedata.normalize("NFKC", str(text or "")).lower()
                   if not ch.isspace() and not unicodedata.category(ch).startswith(("P", "S")))


def short(text, limit=SHOWN) -> str:
    text = " ".join(str(text or "").split()).strip(QUOTES + " ")
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _principles(state_dir):
    from covey.core import principles

    try:
        return principles.entries(state_dir)
    except (OSError, ValueError):
        return []


def _project_lines(state_dir, project_id):
    """The texts of the project's memory lines (core/project_memory.py), for a lead's basis; () without a project."""
    if not project_id:
        return ()
    try:
        from covey.core import project_memory, projects

        rows = project_memory.live(Path(state_dir), projects.read_record(Path(state_dir), project_id))
    except Exception:  # noqa: BLE001 - only a basis the lead may quote; no project memory is none
        return ()
    return tuple(str(row.get("text") or "") for row in rows if isinstance(row, dict))


def check(state_dir, job_key, basis, *, project_id="") -> tuple[str, str]:
    """(what the cards say of ``basis``, '') when it is found as the module says; ('', why not) otherwise."""
    from covey.app.butler_handoff import asked
    from covey.core.jobs import find_job_record

    basis = arg_text(basis, 300)
    if not basis:
        return "", MISSING
    rows = _principles(state_dir)
    for pid in PRINCIPLE_ID.findall(basis):
        row = next((row for row in rows if row.get("id") == pid), None)
        if row is not None:
            return short(row.get("text")), ""
    record = find_job_record(Path(state_dir), str(job_key or "")) or {}
    carried = {str(row.get("n")) for row in record.get("memory_ids") or () if isinstance(row, dict)}
    for number in MEMORY_ID.findall(basis):
        if number in carried:
            return f"记忆 {number}", ""
    wanted = compact(re.sub(PRINCIPLE_ID.pattern + "|" + MEMORY_ID.pattern, "", basis))
    if len(wanted) >= SHORTEST:
        said = asked(state_dir, job_key).words
        sources = [said, *(str(row.get("text") or "") for row in rows), *_project_lines(state_dir, project_id)]
        if any(wanted in compact(source) for source in sources if source):
            return short(basis), ""
    return "", NOT_FOUND.format(basis=short(basis, 60))


def line(shown) -> str:
    """The part of a configuration line that says what picked it: 按「…」; '' without a basis."""
    return f"按「{shown}」" if shown else ""
