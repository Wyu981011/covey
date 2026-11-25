"""The memory of a project (docs/projects.md 专项记忆): what the owner decided and what holds for the project for good, in
``<state>/projects/<id>/memory.json``. Entries are {id, text, kind, source, at, deleted}, the format every release reads:
``kind`` one of ``KINDS``, ``source`` who wrote it, set by the path that wrote it and never by what a model says (``SOURCES``:
``lead`` the lead's project_remember and project_style, ``owner`` the owner's own words a turn quoted (app/memory_collect.py),
``owner_answer`` one question of a question card the owner answered, ``owner_fix`` the owner's 不对 on an answer the lead gave
in his place), ``deleted`` 0 or the time of a delete. A delete writes a tombstone and keeps the text (the lead's pack lists
the last 30 days of them, so it does not note again what the owner struck out); tombstones go after ``TOMB_DAYS``.

What an older release does not know lives beside the file, in ``memory-meta.json`` (entry id -> ``META_KEYS``), so its rewrite
of memory.json never drops it: where a line came from (``origin``, ``ORIGIN_KEYS``), and what the owner's corrections made of it
(``fix``: ``scope`` its conditions ``applies``, ``once`` only for that time, ``confirm`` the owner's for good, with who said
it ``asserted_by`` and wrote it ``recorded_by``, and the log of them ``fixes``). ``entries`` gives each entry with its
meta; core/memory.py ``describe`` reads the source, the level (core/turn_source.py provenance) and the layer from them.

An answered question is an entry of its own (``note_answers``): its id is the question record's token and the question's place
(``answer_id``), so the same answer is noted once, one the owner deleted is not noted again, and its origin is read from the id
when the meta has none. The question record as it was answered (every question, its options and context, every answer, the
补充说明) is kept whole in ``answers/<token>.json`` (``answer_record``): the entry's text is the line a turn carries, at most
``ANSWER_TEXT`` characters; the file is what it was cut from.

Some lines are read across projects (``across``). A question that names an entry of another project's memory by its id
(``quoted``) sorts out that project's memory, as a migration asks how each of its lines counts: its answer is not a decision of
the project it was asked in (app/project_context.py notes it as history at once, ``note_answers`` with ``valid``). A question a
correction of some line names in its origin (``carried_out``) was carried out on that line, which holds what was decided from
then on; 整理记忆 (app/memory_tidy.py) puts the answer away.

Limits: a text of at most ``TEXT`` characters (``ANSWER_TEXT`` for an answer's), ``MAX_ENTRIES`` live entries, ``MAX_BYTES`` for
the file; past one the oldest tombstone goes first, then the oldest answer (its record stays in answers/), then the lead's
oldest fact or contact, then the lead's oldest other entry, the owner's own words last, never the style line (``_victim``). A
live entry that goes is kept, with its meta, in ``memory-archive.json`` (the last ``ARCHIVE_ENTRIES``), not dropped. A file that
cannot be read is not written over; one that cannot be parsed is kept as ``<name>.bad-<time>``. ``version`` names what a turn
reads of the memory, the same for every reader (core/memory.py project_view).

Older releases kept the entries in the project record's ``memory`` field (what the card never showed). They are still read
(``entries`` merges both); a write moves them into the file and leaves the field out of the record, and nothing writes the
field again. An older release reads memory.json as it always did (a long text cut to 200) and writes it with its own limits;
it never reads or writes the meta, the archive or answers/. Every write runs under the record's own lock (core/projects.py
``update``), so the lead's tools, the owner's click on 删 and the Bridge's own notes never overwrite one another; a read takes
no lock (each file is replaced whole).

Standard library and core only: the MCP server imports core/projects.py, which this does."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import sys
import time
from pathlib import Path

from covey.core import projects, turn_source
from covey.core.state import read_json, read_object, write_json

KINDS = ("decision", "constraint", "contact", "fact", "style")
LEGACY_KINDS = {"practice": "constraint", "pitfall": "constraint"}  # What the lead's tool called two of them before.
SOURCES = ("lead", "owner", "owner_answer", "owner_fix")  # Who wrote an entry, as the path that wrote it knows.
OWNERS = ("owner", "owner_answer", "owner_fix")  # The owner's own words (core/memory.py: 你说的); the rest is the lead's.
ANSWERS = ("owner_answer", "owner_fix")  # The owner's answers to a question: a line each, kept long, the first to go when full.
TEXT = 200
ANSWER_TEXT = 600
MAX_ENTRIES = 120
MAX_BYTES = 64 * 1024
MAX_TOMBSTONES = 20
TOMB_DAYS = 30
ARCHIVE_ENTRIES = 300
FILE = "memory.json"
META = "memory-meta.json"
ARCHIVE = "memory-archive.json"
ANSWERS_DIR = "answers"
SCHEMA = 1
TOKEN = re.compile(r"[0-9a-f]{16}")  # A question record's token (app/questions.py question_path).
ANSWER_ID = re.compile(r"([0-9a-f]{16})-([1-9][0-9]{0,2})")
# Of an entry's origin: the text keys and their lengths (``index``, the question's place from 1, is a number). ``message_id``
# and ``question`` are what core/turn_source.py provenance takes as the owner's (its ORIGIN_KEYS), ``topic`` where.
ORIGIN_KEYS = {"message_id": 120, "question": 16, "item": 64, "topic": 64, "job": 120, "quote": 200}
LAYERS = ("rule", "decision", "history")  # 长期约定, 当前决定, 历史记录 (docs/web.md 三层记忆): a fix's layer.
VALID = ("active", "done", "superseded")  # Of a live entry (a tombstone's is void).
FIXES = ("scope", "once", "confirm")  # The owner's corrections (docs/web.md memory_fix).
ONCE = "只限当次"  # The conditions ``once`` gives a line.
APPLIES = 200  # Characters of the conditions.
FIXES_KEPT = 10  # Of an entry's log of corrections.
META_KEYS = ("origin", "asserted_by", "recorded_by", "layer", "applies", "valid", "superseded_by", "fixes")


def memory_path(state_dir, project_id) -> Path:
    return projects.folder(state_dir) / project_id / FILE


def meta_path(state_dir, project_id) -> Path:
    return projects.folder(state_dir) / project_id / META


def archive_path(state_dir, project_id) -> Path:
    return projects.folder(state_dir) / project_id / ARCHIVE


def answer_path(state_dir, project_id, token) -> Path:
    """Where the question record ``token`` is kept as it was answered; ValueError for a token that is not one."""
    if not isinstance(token, str) or not TOKEN.fullmatch(token):
        raise ValueError("问题标识无效")
    return projects.folder(state_dir) / project_id / ANSWERS_DIR / f"{token}.json"


def answer_id(token, index) -> str:
    """The id of the entry of question ``index`` (from 1) of the question record ``token``."""
    return f"{token}-{int(index)}"


def kind_of(kind) -> str:
    """``kind`` as one of ``KINDS`` (the two older names mapped, anything unknown a fact)."""
    kind = LEGACY_KINDS.get(kind, kind)
    return kind if kind in KINDS else "fact"


def clean(text, limit=TEXT) -> str:
    return " ".join(str(text or "").split())[:limit]


def _origin(value) -> dict:
    """``value`` as an origin: the keys of ``ORIGIN_KEYS`` that are short texts (a question that is a token) and ``index``; {}
    for anything else."""
    if not isinstance(value, dict):
        return {}
    out = {key: " ".join(value[key].split())[:size] for key, size in ORIGIN_KEYS.items()
           if isinstance(value.get(key), str) and value[key].strip()}
    if "question" in out and not TOKEN.fullmatch(out["question"]):
        del out["question"]
    index = value.get("index")
    if isinstance(index, int) and not isinstance(index, bool) and 0 < index < 1000:
        out["index"] = index
    return out


def _origin_of(row_id, source) -> dict:
    """The origin an answer's id says (``answer_id``), for one whose meta has none."""
    found = ANSWER_ID.fullmatch(row_id) if source == "owner_answer" else None
    return {"question": found.group(1), "index": int(found.group(2))} if found else {}


def _meta(value) -> dict:
    """``value`` as one entry's meta: the ``META_KEYS`` that are well formed (a party one of core/turn_source.py PARTIES, a
    layer one of ``LAYERS``, a validity one of ``VALID``); {} for anything else."""
    if not isinstance(value, dict):
        return {}
    out = {"origin": _origin(value.get("origin"))}
    out.update({key: value[key] for key in ("asserted_by", "recorded_by") if value.get(key) in turn_source.PARTIES})
    if value.get("layer") in LAYERS:
        out["layer"] = value["layer"]
    if value.get("valid") in VALID:
        out["valid"] = value["valid"]
    for key, size in (("applies", APPLIES), ("superseded_by", 40)):
        if isinstance(value.get(key), str) and value[key].strip():
            out[key] = clean(value[key], size)
    fixes = [fix for fix in value.get("fixes") or () if isinstance(fix, dict) and fix.get("what") in FIXES]
    if fixes:
        out["fixes"] = fixes[-FIXES_KEPT:]
    return {key: value for key, value in out.items() if value}


def _entry(row, index=0):
    """``row`` of a file or of the record's list as an entry; None for one with no text."""
    if isinstance(row, str):
        text = clean(row)
        if not text:
            return None
        return {"id": "s" + hashlib.sha1(text.encode()).hexdigest()[:6], "text": text, "kind": "fact", "source": "owner",
                "at": 0, "deleted": 0}
    if not isinstance(row, dict) or not clean(row.get("text")):
        return None
    at, deleted = row.get("at"), row.get("deleted")
    entry = {"id": str(row.get("id") or f"i{index}"), "text": clean(row.get("text"), ANSWER_TEXT), "kind": kind_of(row.get("kind")),
             "source": str(row.get("source") or "lead")[:30], "at": at if isinstance(at, (int, float)) else 0,
             "deleted": deleted if isinstance(deleted, (int, float)) and not isinstance(deleted, bool) and deleted else 0}
    if row.get("redacted") is True:  # COVEY_MEMORY=1: a line from a topic with redaction on (core/memory.py); no key otherwise.
        entry["redacted"] = True
    return entry


def _shaped(data):
    rows = data.get("entries") if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else None


def _read(path, shape, *, writing=False):
    """``shape(data)`` of the JSON file at ``path``; None when there is none. A read that fails is None (a reader shows
    nothing). With ``writing`` (the next step writes the file whole) a file that cannot be read raises its OSError, so the write
    fails and what is in it stays; a file that is there but is not of its kind (``shape`` gives None) is moved aside
    (``<name>.bad-<time>``, one line in the log) and read as None."""
    try:
        found = shape(read_json(path))
        if found is None:
            raise ValueError("not a memory file")
        return found
    except FileNotFoundError:
        return None
    except ValueError:
        if writing:
            _set_aside(path)
        return None
    except OSError:
        if writing:
            raise
        return None


def _file_rows(path, *, writing=False, archive=False) -> list:
    """The entries of the memory file at ``path`` (``_read``'s rules when it cannot be read). ``archive``: the file is
    memory-archive.json, each entry with the time it went (``archived``) and its ``meta``."""
    found = []
    for index, row in enumerate(_read(path, _shaped, writing=writing) or ()):
        entry = _entry(row, index)
        if entry and archive:
            at = row.get("archived")
            entry["archived"] = at if isinstance(at, (int, float)) and not isinstance(at, bool) else 0
            if _meta(row.get("meta")):
                entry["meta"] = _meta(row.get("meta"))
        if entry:
            found.append(entry)
    return found


def _meta_rows(path, *, writing=False) -> dict:
    """Entry id -> its meta, of the meta file at ``path`` (``_read``'s rules when it cannot be read)."""
    def shape(data):
        rows = data.get("entries") if isinstance(data, dict) else None
        return rows if isinstance(rows, dict) else None
    found = _read(path, shape, writing=writing) or {}
    return {str(key): meta for key, meta in ((key, _meta(value)) for key, value in found.items()) if meta}


def _with_meta(state_dir, project_id, rows) -> list:
    """``rows`` each with what its meta says (``META_KEYS``); an answer with no origin there has the one its id says."""
    meta = _meta_rows(meta_path(state_dir, project_id))
    out = []
    for row in rows:
        extra = meta.get(row["id"], {})
        merged = {**row, **{key: value for key, value in extra.items() if key != "origin"}}
        origin = extra.get("origin") or _origin_of(row["id"], row["source"])
        if origin:
            merged["origin"] = origin
        out.append(merged)
    return out


def _set_aside(path) -> None:
    """A file that cannot be parsed, renamed so that what is in it is not written over."""
    aside = path.with_name(f"{path.name}.bad-{time.strftime('%Y%m%d-%H%M%S')}")
    try:
        os.replace(path, aside)
    except OSError as exc:
        raise OSError(f"{path} 解析不了，也没能改名留底：{exc}") from exc
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} project file unreadable, kept as {aside.name}", file=sys.stderr, flush=True)


def rows_at(path, *, writing=False) -> list:
    """The entries of the memory file at ``path`` (core/topic_memory.py keeps a topic's the same way); [] when there is none."""
    return _file_rows(Path(path), writing=writing)


def stored(state_dir, project_id) -> list:
    """The entries of the file alone (the maintenance rule of the memory's age reads them), the oldest first, with their meta."""
    return _with_meta(state_dir, project_id, _merge(_file_rows(memory_path(state_dir, project_id)), []))


def _legacy_rows(record) -> list:
    rows = record.get("memory") if isinstance(record, dict) else None
    return [item for item in (_entry(row, index) for index, row in enumerate(rows if isinstance(rows, list) else ())) if item]


def _merge(file_rows, legacy_rows) -> list:
    seen = {row["id"] for row in file_rows}
    merged = [*file_rows, *(row for row in legacy_rows if row["id"] not in seen)]
    return sorted(merged, key=lambda row: row["at"])  # Stable: entries of one time keep the order they came in.


def entries(state_dir, record) -> list:
    """Every entry of the project of ``record`` (live ones and tombstones), the oldest first, with their meta: the file's and,
    until a write moves them, the record's own."""
    pid = record.get("id") if isinstance(record, dict) else None
    if not projects.valid_id(pid):
        return []
    return _with_meta(state_dir, pid, _merge(_file_rows(memory_path(state_dir, pid)), _legacy_rows(record)))


def live(state_dir, record, *, style=True) -> list:
    """The entries not deleted (the style line left out with ``style=False``), the oldest first."""
    return [row for row in entries(state_dir, record) if not row["deleted"] and (style or row["kind"] != "style")]


def tombstones(state_dir, record, now=None, days=TOMB_DAYS) -> list:
    """The entries the owner or the lead deleted in the last ``days`` days, the oldest first."""
    cutoff = (time.time() if now is None else now) - days * 86400
    return [row for row in entries(state_dir, record) if row["deleted"] and row["deleted"] >= cutoff]


def dumps(rows) -> str:
    return json.dumps({"schema_version": SCHEMA, "entries": rows}, ensure_ascii=False, indent=1)


# What goes first when the memory is full, the oldest of each before the next (``_victim``): a tombstone, an answer (its question
# record stays in answers/), what the lead noted that is a fact or a contact, the rest of what the lead noted, the owner's own words.
VICTIMS = (lambda row: bool(row["deleted"]),
           lambda row: not row["deleted"] and row["source"] in ANSWERS,
           lambda row: not row["deleted"] and row["source"] not in OWNERS and row["kind"] in ("fact", "contact"),
           lambda row: not row["deleted"] and row["source"] not in OWNERS,
           lambda row: not row["deleted"])


def _victim(rows):
    """The entry that goes when ``rows`` are past a limit: the oldest that the first of ``VICTIMS`` with one says; never a style
    line. None when only style lines are left."""
    for test in VICTIMS:
        found = next((row for row in rows if row["kind"] != "style" and test(row)), None)
        if found is not None:
            return found
    return None


def _fitted(rows, now) -> tuple[list, list]:
    """(``rows`` inside the limits, the live entries that had to go): tombstones past ``TOMB_DAYS`` gone, then the oldest ones past
    ``MAX_TOMBSTONES``, then, until the count and the size fit, ``_victim`` after ``_victim``."""
    cutoff = now - TOMB_DAYS * 86400
    rows = [row for row in rows if not row["deleted"] or row["deleted"] >= cutoff]
    while sum(1 for row in rows if row["deleted"]) > MAX_TOMBSTONES:
        rows.remove(next(row for row in rows if row["deleted"]))
    gone = []
    while sum(1 for row in rows if not row["deleted"]) > MAX_ENTRIES or len(dumps(rows).encode()) > MAX_BYTES:
        victim = _victim(rows)
        if victim is None:
            break
        rows.remove(victim)
        if not victim["deleted"]:
            gone.append(victim)
    return rows, gone


def _fit(rows, now) -> list:
    return _fitted(rows, now)[0]


def _keep_gone(state_dir, project_id, gone, now, meta) -> None:
    """The live entries a full memory let go, at the end of memory-archive.json (the last ``ARCHIVE_ENTRIES`` of them) with the
    time they went and their meta: what was there is not lost when it no longer fits. Written before the memory itself, under
    the same lock: a failure here leaves the memory as it was."""
    if not gone:
        return
    path = archive_path(state_dir, project_id)
    rows = [*_file_rows(path, writing=True, archive=True),
            *({**row, "archived": now, **({"meta": meta[row["id"]]} if meta.get(row["id"]) else {})} for row in gone)]
    write_json(path, {"schema_version": SCHEMA, "entries": rows[-ARCHIVE_ENTRIES:]}, ensure_ascii=False, indent=1)


def archived(state_dir, project_id) -> list:
    """The entries a full memory let go (``_keep_gone``), the oldest first, each with ``archived`` and its ``meta``; [] when
    there are none."""
    return _file_rows(archive_path(state_dir, project_id), archive=True)


def _edit(state_dir, project_id, edit, also=None, now=None):
    """Run ``edit(rows, meta)`` (it changes the merged list and the meta, entry id -> ``META_KEYS``, in place and returns what
    the caller wants) under the record's lock, then write what changed: the meta (the entries the memory still has or had),
    the entries a full memory let go (``_keep_gone``), the file; take the legacy field out of the record, and run
    ``also(record)`` on the record in the same write. KeyError for a project with no record."""
    stamp = time.time() if now is None else now
    box = []

    def change(record):
        path, kept = memory_path(state_dir, project_id), meta_path(state_dir, project_id)
        before = _merge(_file_rows(path, writing=True), [])
        meta_before = _meta_rows(kept, writing=True)
        rows = _merge([dict(row) for row in before], _legacy_rows(record))
        meta = {key: dict(value) for key, value in meta_before.items()}
        box.append(edit(rows, meta))
        rows, gone = _fitted(rows, stamp)
        ids = {row["id"] for row in (*rows, *before)}
        meta = {key: _meta(value) for key, value in meta.items() if key in ids and _meta(value)}
        if meta != meta_before:
            write_json(kept, {"schema_version": SCHEMA, "entries": meta}, ensure_ascii=False, indent=1)
        _keep_gone(state_dir, project_id, gone, stamp, meta)
        if rows != before:
            write_json(path, {"schema_version": SCHEMA, "entries": rows}, ensure_ascii=False, indent=1)
        record.pop("memory", None)
        if also is not None:
            also(record)
    projects.update(state_dir, project_id, change)
    return box[0]


def add(state_dir, project_id, text, kind="fact", source="lead", *, now=None, also=None, redacted=False, origin=None) -> tuple:
    """(the entry, whether it is new): ``text`` as an entry of ``kind``. The same text of the same kind that is still
    there is the one returned, not noted twice. ``also(record)``: more to change in the project's record in the same write.
    ``redacted``: the line came from a topic with redaction on (it is only read back by such a topic, core/memory.py).
    ``source`` is one of ``SOURCES`` (any other is the lead's); ``origin`` where the line came from (``ORIGIN_KEYS``, kept in
    the meta)."""
    stamp = time.time() if now is None else now
    source = source if source in SOURCES else "lead"
    wanted = {"id": secrets.token_hex(3), "text": clean(text, ANSWER_TEXT if source in ANSWERS else TEXT), "kind": kind_of(kind),
              "source": source, "at": stamp, "deleted": 0, **({"redacted": True} if redacted else {})}
    origin = _origin(origin)
    if not wanted["text"]:
        raise ValueError("text 不能为空")

    def edit(rows, meta):
        same = next((row for row in rows if not row["deleted"] and row["kind"] == wanted["kind"] and row["text"] == wanted["text"]), None)
        if same is not None:
            return same, False
        rows.append(wanted)
        if origin:
            meta[wanted["id"]] = {"origin": origin}
        return {**wanted, **({"origin": origin} if origin else {})}, True
    return _edit(state_dir, project_id, edit, also, stamp)


def note_answers(state_dir, project_id, record, lines, *, now=None) -> list:
    """The owner's answers to one question card: the question record ``record`` (its ``token``, ``topic_id``, ``job_id``,
    ``questions``, ``answers``, ``supplement``) kept whole in answers/<token>.json the first time, and each of ``lines``
    ({index, item, text, valid?}: the question's place from 1, its id and the line a turn carries) an entry of its own, a
    decision of ``owner_answer`` whose id is ``answer_id``, its origin in the meta; one with ``valid`` (``SETTLED``) is history
    from the start, never carried. An answer that is there already, or that the owner deleted, is not noted again. [(the
    entry, whether it is new)], one a line. ValueError for a record with no token."""
    stamp = time.time() if now is None else now
    token = str(record.get("token") or "")
    path = answer_path(state_dir, project_id, token)
    kept = {key: record[key] for key in ("token", "topic_id", "job_id", "job_key", "questions", "answers", "supplement",
                                         "attachments", "created_at") if key in record}
    job = str(record.get("job_key") or record.get("job_id") or "")

    def edit(rows, meta):
        if not path.exists():
            write_json(path, {"schema_version": SCHEMA, **kept, "noted_at": stamp}, ensure_ascii=False, indent=1)
        out = []
        for line in lines:
            entry_id = answer_id(token, line["index"])
            same = next((row for row in rows if row["id"] == entry_id), None)  # A tombstone too: the owner's delete stands.
            if same is not None:
                out.append((same, False))
                continue
            origin = _origin({"question": token, "item": str(line.get("item") or ""), "index": line["index"],
                              "topic": str(record.get("topic_id") or ""), "job": job})
            entry = {"id": entry_id, "text": clean(line["text"], ANSWER_TEXT), "kind": "decision", "source": "owner_answer",
                     "at": stamp, "deleted": 0}
            settled = {"valid": line["valid"]} if line.get("valid") in SETTLED else {}
            if entry["text"]:
                rows.append(entry)
                meta[entry_id] = {"origin": origin, **settled}
                out.append(({**entry, "origin": origin, **settled}, True))
        return out
    return _edit(state_dir, project_id, edit, None, stamp)


def fix(state_dir, project_id, entry_id, what, *, origin, applies="", now=None) -> dict:
    """The owner's correction ``what`` (``FIXES``) of the live entry ``entry_id``, in its meta: ``scope`` its conditions
    (``applies``), ``once`` a 当前决定 only for that time (``applies`` given, or ``ONCE``), ``confirm`` a 长期约定 the owner says
    holds (``asserted_by`` owner, ``recorded_by`` bridge, ``origin`` this correction's, so its level is the owner's,
    core/turn_source.py provenance). ``origin`` is where the correction came in (a ``message_id`` the Bridge took it in with);
    each is logged in ``fixes``. Only a caller that checked it is the owner's calls this (app/project_context.py fix_memory).
    The entry as ``entries`` gives it. ValueError for another ``what``, no origin, no conditions to ``scope`` with or an
    entry that is not there; KeyError for a project with no record."""
    stamp = time.time() if now is None else now
    origin, conditions = _origin(origin), clean(applies, APPLIES)
    if what not in FIXES:
        raise ValueError("纠正只有 " + "、".join(FIXES))
    if not origin.get("message_id"):
        raise ValueError("纠正要带这次操作的出处（message_id）")
    if what == "scope" and not conditions:
        raise ValueError("改适用范围要写 applies")

    def edit(rows, meta):
        row = next((row for row in rows if row["id"] == str(entry_id) and not row["deleted"] and row["kind"] != "style"), None)
        if row is None:
            return None
        entry, log = dict(meta.get(row["id"]) or {}), {"what": what, "at": stamp, "origin": origin}
        if what == "scope":
            entry["applies"] = log["applies"] = conditions
        elif what == "once":
            entry["layer"], entry["applies"] = "decision", conditions or ONCE
            log["applies"] = entry["applies"]
        else:
            log["was"] = {key: entry[key] for key in ("asserted_by", "recorded_by", "origin", "layer") if key in entry}
            entry.update(layer="rule", asserted_by=turn_source.PARTY_OWNER, recorded_by=turn_source.PARTY_BRIDGE, origin=origin)
        entry["fixes"] = [*entry.get("fixes", ()), log][-FIXES_KEPT:]
        meta[row["id"]] = entry
        return row["id"]
    found = _edit(state_dir, project_id, edit, None, stamp)
    if found is None:
        raise ValueError("这条记忆已经不在了")
    return next(row for row in stored(state_dir, project_id) if row["id"] == found)


SETTLED = ("done", "superseded")  # What 整理记忆 makes of a line no longer carried (``settle``).


def settle(state_dir, project_id, changes, *, now=None) -> list:
    """Lines that no longer hold for a turn to carry (整理记忆, app/memory_tidy.py): each of ``changes`` {id, valid (one of
    ``SETTLED``), superseded_by?} written into the meta of its live entry (not the style line), which core/memory.py describe
    then reads as history. [(entry id, what its meta said of ``valid`` and ``superseded_by`` before)] of the ones changed, for
    ``unsettle``. Who may be settled is the caller's to decide (never the owner's 长期约定). KeyError for a project with no
    record."""
    def edit(rows, meta):
        live = {row["id"] for row in rows if not row["deleted"] and row["kind"] != "style"}
        out = []
        for change in changes:
            entry_id, valid = str(change.get("id") or ""), change.get("valid")
            if entry_id not in live or valid not in SETTLED or any(done == entry_id for done, _ in out):
                continue
            entry = dict(meta.get(entry_id) or {})
            before = {key: entry[key] for key in ("valid", "superseded_by") if key in entry}
            entry["valid"] = valid
            if valid == "superseded" and str(change.get("superseded_by") or "").strip():
                entry["superseded_by"] = clean(change["superseded_by"], 40)
            else:
                entry.pop("superseded_by", None)
            meta[entry_id] = entry
            out.append((entry_id, before))
        return out
    return _edit(state_dir, project_id, edit, None, now)


def unsettle(state_dir, project_id, settled, *, now=None) -> list:
    """整理记忆's 撤销: each (entry id, before) of ``settle`` put back as its meta was; the ids put back (one the owner or a
    lead changed since, or that is gone, is left as it is)."""
    def edit(rows, meta):
        live = {row["id"] for row in rows if not row["deleted"]}
        out = []
        for entry_id, before in settled:
            entry = dict(meta.get(str(entry_id)) or {})
            if str(entry_id) not in live or entry.get("valid") not in SETTLED:
                continue
            entry.pop("valid", None)
            entry.pop("superseded_by", None)
            entry.update({key: value for key, value in (before or {}).items() if key in ("valid", "superseded_by")})
            meta[str(entry_id)] = entry
            out.append(str(entry_id))
        return out
    return _edit(state_dir, project_id, edit, None, now)


def answer_record(state_dir, project_id, token) -> dict:
    """The question record ``token`` as it was answered (``note_answers``), {} when it was not kept or cannot be read."""
    try:
        return read_object(answer_path(state_dir, project_id, token))
    except ValueError:
        return {}


# An entry's id written in a text as a word of its own: six hex digits (``add``'s), an answer's (``answer_id``) or the token
# of its question record.
QUOTE = re.compile(r"(?<![0-9A-Za-z])([0-9a-f]{16}(?:-[0-9]{1,3})?|[0-9a-f]{6})(?![0-9A-Za-z])")


def across(state_dir) -> dict:
    """Every project's memory at once, for what is read across projects (``ids``, ``carried_out``): project id -> its entries
    as ``entries`` gives them (tombstones too, with their meta), then what a full memory let go (``archived``)."""
    return {record["id"]: [*entries(state_dir, record), *archived(state_dir, record["id"])]
            for record in projects.records(state_dir)}


def ids(found) -> dict:
    """Entry id -> its project, of ``found`` (``across``'s); an answer's entry is there by its question record's token too."""
    out = {}
    for pid, rows in found.items():
        for row in rows:
            out[row["id"]] = pid
            answer = ANSWER_ID.fullmatch(row["id"])
            if answer:
                out[answer.group(1)] = pid
    return out


def quoted(known, project_id, text) -> list:
    """The projects but ``project_id`` an entry of whose memory ``text`` names by its id (``known`` is ``ids``'s), the first
    named first."""
    out = []
    for word in QUOTE.findall(str(text or "")):
        pid = known.get(word)
        if pid and pid != project_id and pid not in out:
            out.append(pid)
    return out


def carried_out(found) -> dict:
    """The questions a correction of a line came from (``fix`` whose ``origin`` names the question record and the question,
    as a migration that asked the owner how each line counts writes it), of ``found`` (``across``'s): (token, the question's
    id) and (token, its place) -> the refs "<project>:<entry>" of the lines corrected."""
    out = {}
    for pid, rows in found.items():
        for row in rows:
            for fix in row.get("fixes") or (row.get("meta") or {}).get("fixes") or ():
                origin = _origin(fix.get("origin"))
                for key in (origin.get("item"), origin.get("index")) if origin.get("question") else ():
                    if key:
                        out.setdefault((origin["question"], key), set()).add(f"{pid}:{row['id']}")
    return out


def version(rows) -> str:
    """What a turn reads of the memory, as eight hex digits: a hash of the live entries but the style line (``rows`` as ``entries``
    gives them), with what a correction changed of them. The same for every reader of the same files; an entry added, deleted
    or corrected changes it, a tombstone going does not."""
    live = sorted((row["id"], row["kind"], row["source"], row["text"], *(str(row.get(key) or "") for key in
                   ("layer", "applies", "valid", "asserted_by", "superseded_by")))
                  for row in rows if not row["deleted"] and row["kind"] != "style")
    return hashlib.sha1(json.dumps(live, ensure_ascii=False).encode()).hexdigest()[:8]


def set_style(state_dir, project_id, text, *, now=None, also=None) -> dict:
    """The one style line of the project: ``text`` replaces the one before (the last word the owner gave)."""
    stamp = time.time() if now is None else now
    wanted = {"id": secrets.token_hex(3), "text": clean(text), "kind": "style", "source": "lead", "at": stamp, "deleted": 0}

    def edit(rows, meta):
        rows[:] = [row for row in rows if row["kind"] != "style"]
        rows.append(wanted)
        return wanted
    return _edit(state_dir, project_id, edit, also, stamp)


def delete(state_dir, project_id, entry_id, *, now=None) -> bool:
    """Whether ``entry_id`` was a live entry: it becomes a tombstone (``deleted`` is the time)."""
    stamp = time.time() if now is None else now

    def edit(rows, meta):
        row = next((row for row in rows if row["id"] == str(entry_id) and not row["deleted"]), None)
        if row is None:
            return False
        row["deleted"] = stamp
        return True
    return _edit(state_dir, project_id, edit, None, stamp)


def forget(state_dir, project_id, before) -> int:
    """How many entries (tombstones too) written before ``before`` (an epoch; one with no time is kept) the file lost: the
    maintenance rule of the memory's age. Style lines stay."""
    def edit(rows, meta):
        gone = [row for row in rows if row["kind"] != "style" and 0 < row["at"] < before]
        rows[:] = [row for row in rows if row not in gone]
        return len(gone)
    try:
        return _edit(state_dir, project_id, edit)
    except KeyError:
        return 0
