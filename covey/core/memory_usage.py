"""Which memory lines the turns used (COVEY_MEMORY_LEARN=1, docs/butler.md 记忆自己长), so what is never of use goes first
and in time out of the way: ``<state>/memory-usage.json`` {schema_version, refs: {ref: {n, last}}}, ``ref`` as core/memory.py
names an item ("principle:<id>", "project:<project>:<id>", "candidate:<id>", …), ``n`` how many turns used it, ``last`` when
the latest did. The Bridge writes it once a turn has ended (app/memory_learn.py: the numbers the turn's checkpoint lists in
``memory_used`` and the ones its reply names, of the items the turn carried); core/memory.py orders by it and the nightly
整理记忆 (app/memory_tidy.py) lets what nobody used for ``IDLE_DAYS`` go to the history. At most ``KEPT`` refs, the ones used
longest ago dropped first. Written whole under its own lock; a read takes none; a file that cannot be read is read as empty
and written over by the next note (it only ever orders and ages, nothing is lost with it). Standard library and core only."""
from __future__ import annotations

import time
from pathlib import Path

from covey.core.locks import shared_file_lock
from covey.core.state import read_object, write_json

FILE = "memory-usage.json"
SCHEMA = 1
KEPT = 2000
IDLE_DAYS = 30  # A line of 它总结的 or a 当前决定 no turn used for this long is let go by 整理记忆 (app/memory_tidy.py).


def path(state_dir) -> Path:
    return Path(state_dir) / FILE


def _number(value) -> float:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0.0


def read(state_dir) -> dict:
    """ref -> {n, last} of every line some turn used; {} when there is no record or it cannot be read."""
    refs = read_object(path(state_dir)).get("refs")
    found = {}
    for ref, row in (refs.items() if isinstance(refs, dict) else ()):
        if isinstance(ref, str) and isinstance(row, dict):
            found[ref] = {"n": int(_number(row.get("n"))), "last": _number(row.get("last"))}
    return found


def last_used(state_dir) -> dict:
    """ref -> when a turn last used it (core/memory.py items ``used``)."""
    return {ref: row["last"] for ref, row in read(state_dir).items() if row["last"]}


def note(state_dir, refs, *, now=None) -> int:
    """``refs`` used by one turn now: each one's count up by one, its ``last`` now. How many were noted."""
    refs = list(dict.fromkeys(str(ref) for ref in refs or () if ref))
    if not refs:
        return 0
    stamp = time.time() if now is None else now
    with shared_file_lock(path(state_dir)):
        found = read(state_dir)
        for ref in refs:
            row = found.get(ref) or {"n": 0, "last": 0.0}
            found[ref] = {"n": row["n"] + 1, "last": stamp}
        kept = dict(sorted(found.items(), key=lambda pair: -pair[1]["last"])[:KEPT])
        write_json(path(state_dir), {"schema_version": SCHEMA, "refs": kept}, ensure_ascii=False)
    return len(refs)


def carry(state_dir, old, new) -> bool:
    """The use of the line ``old`` goes to ``new`` (a candidate turned principle, a project's or a topic's line made global): the
    later ``last``, the counts added, ``old`` gone, so what was in use does not start from nothing and drop out of the room.
    Whether there was anything to carry."""
    old, new = str(old or ""), str(new or "")
    if not old or not new or old == new:
        return False
    with shared_file_lock(path(state_dir)):
        found = read(state_dir)
        row = found.pop(old, None)
        if row is None:
            return False
        kept = found.get(new) or {"n": 0, "last": 0.0}
        found[new] = {"n": kept["n"] + row["n"], "last": max(kept["last"], row["last"])}
        write_json(path(state_dir), {"schema_version": SCHEMA, "refs": found}, ensure_ascii=False)
    return True


def idle(usage, ref, written_at, *, now=None, days=IDLE_DAYS) -> bool:
    """Whether the line ``ref`` (written at ``written_at``) has gone ``days`` days with no turn using it: written that long
    ago and not used since. ``usage`` is ``read``'s."""
    stamp = time.time() if now is None else now
    last = max(_number(written_at), (usage.get(ref) or {}).get("last", 0.0))
    return bool(last) and stamp - last >= days * 86400
