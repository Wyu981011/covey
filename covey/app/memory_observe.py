"""What the Bridge sees of a turn's use of the memory (docs/butler.md 记忆): the strong signals the ranking counts, nothing else.

After a turn ``observe`` (app/memory_collect.py ``collect`` calls it, once a turn's record is settled) adds to each entry's counts
(core/memory_usage.py): the entries whose whole text the turn carried (``memory_ids``, ``e``), the ones it only listed
(``memory_listed``, ``t``), and the ones the checkpoint's ``memory_used`` names (a short code, a ref or an older M number,
read against the turn's own ``memory_ids``; a signal of half weight, core/memory_rank.py SIGNAL_WEIGHTS). The other signals are
counted where they happen: ``covey memory show``, question_dedup, the owner confirming. Restating an entry's words is not a
signal. A turn is counted once (the record's ``memory_observed``); nothing is counted with COVEY_MEMORY off or in a 代答 topic.
Never raises: a failure is a log line.
"""
from __future__ import annotations

import logging
from pathlib import Path

from covey.core import memory, memory_usage, memstore
from covey.core.checkpoint import read_checkpoint
from covey.core.jobs import job_key, job_path, read_job_record, upsert_job_record
from covey.core.topics import proxy_topic

log = logging.getLogger(__name__)


def _refs(rows) -> list:
    return list(dict.fromkeys(str(row["ref"]) for row in rows or () if isinstance(row, dict) and row.get("ref")))


def _used(state, record, carried) -> list:
    """The refs the checkpoint's ``memory_used`` names, of the entries the turn carried."""
    path = str(record.get("checkpoint_path") or "")
    try:
        named = read_checkpoint(Path(path)).get("memory_used") if path else None
    except Exception:  # noqa: BLE001 - a checkpoint that cannot be read says nothing
        return []
    refs = []
    for key in named if isinstance(named, list) else ():
        if not isinstance(key, str) or not key.strip():
            continue
        entry = memstore.find_in_turn(state, key.strip(), carried)
        if entry is not None and entry.ref not in refs:
            refs.append(entry.ref)
    return refs


def observe(ctx, job, result) -> None:
    """Count the signals of ``job``'s finished turn (the module's docstring); ``result`` is not read."""
    if not memory.enabled():
        return
    try:
        state = ctx.state_dir
        key = job_key(str(getattr(job, "message_id", "") or ""), getattr(job, "job_id", ""))
        record = read_job_record(job_path(state, key))
        if not record or record.get("memory_observed") or proxy_topic(ctx):
            return
        carried = [row for row in record.get("memory_ids") or () if isinstance(row, dict)]
        memory_usage.carried(state, _refs(carried))
        memory_usage.listed(state, _refs(record.get("memory_listed")))
        used = _used(state, record, carried)
        if used:
            memory_usage.signal(state, used, "memory_used")
        upsert_job_record(state, key, memory_observed=True)
    except Exception as exc:  # noqa: BLE001 - the turn's ending goes on
        log.warning("memory observe failed: %s", type(exc).__name__)
