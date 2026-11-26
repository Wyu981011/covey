"""What the Harnesses remember on their own (Claude Code, Codex, Antigravity), offered for import into the memory one entry at a time.

Read only: nothing here writes a Harness's files. Each Harness has an adapter (``ADAPTERS``) that lists its memory files on
this machine (``discover``) and cuts each into entries (``split``):

- Claude Code: ``<config dir>/projects/<the start directory, dashed>/memory/*.md`` (not the ``MEMORY.md`` index), one entry
  a file, its frontmatter's ``name``, ``description`` and ``type``; the bucket is the project directory's name.
- Codex: ``$CODEX_HOME/memories*/memory_summary.md``, one entry a list item of its sections on the user and its tips (not
  the index of what is in memory), and ``MEMORY.md``, one entry a list item of each task group's preferences, knowledge and
  failures, the bucket its ``applies_to`` cwd. ``raw_memories.md`` is not read (large, not sorted out).
- Antigravity: the global rules file (``~/.gemini/GEMINI.md``, ``~/.gemini/config/GEMINI.md``), one entry a list item or
  paragraph, and the IDE's knowledge items (``~/.gemini/antigravity/knowledge/*/metadata.json``) when there are any.

Each entry has a fingerprint of its Harness, file and text (``fingerprint``); ``memory/imports.json`` keeps each one's
state (new, imported, ignored) and, for the nightly scan, what each file was (``fresh``: only the entries of a file new or
changed since are offered, and the first night only notes what is there). The web's 导入 lists them a page at a time
(contract v43 ``memory:import:<page>``, ``page``), with the bucket's repository (the repo map's, core/repomap.py) and
``old_repo`` for one the map marks frozen. Nothing is imported without the owner ticking it (``take``).
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from covey.core import claude_retention, memstore, paths, repomap

HARNESSES = ("claude_code", "codex", "antigravity")
STATES = ("new", "imported", "ignored")
PAGE = 200
TEXT_CHARS = memstore.TEXT_CHARS
FILES_KEPT = 2000  # Files of one Harness read at most (the newest first).
FILE_BYTES = 512 * 1024  # A memory file larger than this is read up to here.
FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", re.S)
_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.*)$")
# Codex's memory_summary.md: the sections an entry is cut from, and what each is.
CODEX_SUMMARY = {"user profile": "user", "user preferences": "user", "general tips": "reference"}
# Codex's MEMORY.md: a task group's subsections and what each is.
CODEX_GROUP = {"user preferences": "feedback", "reusable knowledge": "reference",
               "failures and how to do differently": "reference"}
RULE_TYPES = ("user", "feedback", "rules")  # What becomes a rule; the rest a note.


@dataclass(frozen=True)
class ImportItem:
    fingerprint: str
    harness: str  # HARNESSES
    bucket: str  # Where it was found: the project or repository its Harness keeps it under.
    file: str
    title: str
    text: str
    type: str  # What the Harness calls it (a memory file's section, a rule…).
    repo: str = ""


def fingerprint(harness: str, file: str, text: str) -> str:
    """Stable across scans: the same text in the same file of the same Harness is the same candidate."""
    body = "\0".join((harness, str(file), " ".join(str(text).split())))
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:16]


def _read(path: Path) -> str:
    try:
        with open(path, "rb") as stream:
            return stream.read(FILE_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _items(lines) -> list:
    """The list items of ``lines`` (a continuation line joins the item above), each one line."""
    found, current = [], None
    for line in lines:
        item = _ITEM.match(line)
        if item:
            if current:
                found.append(current)
            current = item.group(1).strip()
        elif current is not None and line.strip() and line.startswith((" ", "\t")):
            current += " " + line.strip()
        else:
            if current:
                found.append(current)
            current = None
    if current:
        found.append(current)
    return [" ".join(text.split()) for text in found if text.strip()]


def _sections(text: str, level: str) -> list:
    """[(heading, lines)] of the ``level`` headings (``##``) of ``text``; lines before the first under heading ''."""
    out, heading, lines = [], "", []
    for line in text.splitlines():
        if line.startswith(level + " ") and not line.startswith(level + "#"):
            out.append((heading, lines))
            heading, lines = line[len(level) + 1:].strip(), []
        else:
            lines.append(line)
    out.append((heading, lines))
    return out


def _cut(text: str) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= TEXT_CHARS else text[:TEXT_CHARS - 1] + "…"


def _newest(files) -> list:
    stamped = []
    for file in files:
        try:
            stamped.append((file.stat().st_mtime, file))
        except OSError:
            pass
    return [file for _, file in sorted(stamped, key=lambda pair: -pair[0])[:FILES_KEPT]]


class ClaudeCodeAdapter:
    name = "claude_code"

    def discover(self, root: Path) -> list:
        """[(file, bucket)] of the auto memory files under ``root`` (Claude Code's config dir)."""
        try:
            folders = sorted(path for path in (root / "projects").iterdir() if path.is_dir())
        except OSError:
            return []
        files = []
        for folder in folders:
            try:
                files += [file for file in (folder / "memory").glob("*.md") if file.name != "MEMORY.md" and file.is_file()]
            except OSError:
                continue
        return [(file, file.parent.parent.name) for file in _newest(files)]

    def split(self, file: Path, text: str) -> list:
        """One entry a file: (title, text, type)."""
        head, body = {}, text
        found = FRONTMATTER.match(text)
        if found:
            body = found.group(2)
            for line in found.group(1).splitlines():
                key, _, value = line.partition(":")
                if key.strip() in ("name", "description", "type") and value.strip():
                    head.setdefault(key.strip(), value.strip().strip('"').strip("'"))
        kind = head.get("type") or "note"
        words = " ".join(part for part in (head.get("description", ""), " ".join(body.split())) if part)
        title = head.get("name") or memstore.auto_title(words)
        return [(title, words, kind)] if words.strip() else []


class CodexAdapter:
    name = "codex"

    def discover(self, root: Path) -> list:
        """[(file, bucket)] of memory_summary.md and MEMORY.md under ``root`` (CODEX_HOME)'s memories*/."""
        try:
            folders = sorted(path for path in root.iterdir() if path.is_dir() and path.name.startswith("memories"))
        except OSError:
            return []
        return [(folder / name, "") for folder in folders for name in ("memory_summary.md", "MEMORY.md")
                if (folder / name).is_file()]

    def split(self, file: Path, text: str) -> list:
        out = []
        if file.name == "memory_summary.md":
            for heading, lines in _sections(text, "##"):
                kind = CODEX_SUMMARY.get(heading.lower())
                out += [(memstore.auto_title(item), item, kind) for item in _items(lines)] if kind else []
            return out
        for group, lines in _sections(text, "#"):
            if not group.lower().startswith("task group"):
                continue
            body = "\n".join(lines)
            cwd = re.search(r"cwd=([^;\s]+)", body)
            bucket = cwd.group(1) if cwd else ""
            for heading, part in _sections(body, "##"):
                kind = CODEX_GROUP.get(heading.lower())
                if kind:
                    out += [(memstore.auto_title(re.sub(r"\s*\[Task \d+\]\s*$", "", item)),
                             re.sub(r"\s*\[Task \d+\]\s*$", "", item), kind, bucket) for item in _items(part)]
        return out


class AntigravityAdapter:
    name = "antigravity"

    def discover(self, root: Path) -> list:
        """[(file, bucket)] of the global rules files and the knowledge items under ``root`` (~/.gemini)."""
        found = [(file, "") for file in (root / "GEMINI.md", root / "config" / "GEMINI.md") if file.is_file()]
        try:
            found += [(file, file.parent.name) for file in sorted((root / "antigravity" / "knowledge").glob("*/metadata.json"))]
        except OSError:
            pass
        return found

    def split(self, file: Path, text: str) -> list:
        if file.name == "metadata.json":
            try:
                data = json.loads(text)
            except ValueError:
                return []
            if not isinstance(data, dict):
                return []
            title, summary = str(data.get("title") or ""), str(data.get("summary") or data.get("description") or "")
            words = " ".join(f"{title} {summary}".split())
            return [(title or memstore.auto_title(words), words, "knowledge")] if words else []
        out = []
        for heading, lines in _sections(text, "##"):
            items = _items(lines)
            if items:
                out += [(memstore.auto_title(item), item, "rules") for item in items]
                continue
            paragraph = " ".join(" ".join(line.split()) for line in lines if line.strip() and not line.startswith("#"))
            if paragraph and heading:
                out.append((heading[:memstore.TITLE_CHARS], paragraph, "rules"))
        return out


ADAPTERS = {"claude_code": ClaudeCodeAdapter(), "codex": CodexAdapter(), "antigravity": AntigravityAdapter()}


def roots(home) -> dict:
    """Harness -> the directory its memory is under, for the user whose home is ``home``: this process's settings
    (CLAUDE_CONFIG_DIR, CODEX_HOME) when it is this user's home, else the defaults under ``home``."""
    home = Path(home).expanduser()
    if home == Path.home():
        return {"claude_code": claude_retention.settings_path().parent, "codex": paths.codex_home(),
                "antigravity": home / ".gemini"}
    return {"claude_code": home / ".claude", "codex": home / ".codex", "antigravity": home / ".gemini"}


def _dashed(path: str) -> str:
    """A directory as Claude Code names its project folder: every character but a letter or a digit a dash."""
    return re.sub(r"[^A-Za-z0-9]", "-", str(path).rstrip("/"))


def repo_of(bucket: str, repos) -> object | None:
    """The repo map's repository a bucket is of: the same directory (Codex's cwd, under it too), or the dashed name of it
    (Claude Code's folder)."""
    best = None
    for repo in repos:
        where = str(repo.path).rstrip("/")
        if bucket == _dashed(where) or bucket == where or bucket.startswith(where + "/"):
            if best is None or len(str(repo.path)) > len(str(best.path)):
                best = repo
    return best


def _raw(home, *, root_of=None) -> list:
    """[(harness, file, bucket, title, text, type)] of every entry; ``root_of`` the Harness's directories (``roots``)."""
    found = []
    for name, root in (root_of or roots(home)).items():
        adapter = ADAPTERS.get(name)
        if adapter is None:
            continue
        for file, bucket in adapter.discover(Path(root)):
            for row in adapter.split(file, _read(file)):
                title, text, kind = row[:3]
                where = row[3] if len(row) > 3 and row[3] else bucket
                text = _cut(text)
                if text:
                    found.append((name, file, where, title, text, kind))
    return found


def scan(state_dir, home, *, root_of=None) -> list[ImportItem]:
    """Every candidate the Harnesses hold for the user whose home is ``home`` (``roots``; ``root_of`` other directories),
    each once (the first file that has the same text of a Harness wins), with the repo map's repository of its bucket."""
    repos = repomap.read(state_dir)
    seen, out = set(), []
    for harness, file, bucket, title, text, kind in _raw(home, root_of=root_of):
        fp = fingerprint(harness, str(file), text)
        if fp in seen:
            continue
        seen.add(fp)
        repo = repo_of(bucket, repos)
        out.append(ImportItem(fingerprint=fp, harness=harness, bucket=bucket, file=str(file),
                              title=memstore.clean(title, memstore.TITLE_CHARS) or memstore.auto_title(text), text=text,
                              type=kind, repo=repo.name if repo else ""))
    return out


def old_repo(item: ImportItem, repos) -> bool:
    """Whether ``item`` is of a repository the map marks frozen (an old one: not ticked by default)."""
    return any(repo.name == item.repo and repo.status == "frozen" for repo in repos)


def suggest(item: ImportItem) -> dict:
    """Where an entry would go: a preference or a rule of the user's a global rule, the rest a global note."""
    return {"kind": "rule" if item.type in RULE_TYPES else "note", "scope": "global"}


def _tail(file: str) -> str:
    parts = Path(file).parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else file


def view(item: ImportItem, record: dict | None, repos, *, dup_of: str = "") -> dict:
    """``item`` as the web's 导入 lists it (contract v43 MemoryImportItem)."""
    out = {key: value for key, value in asdict(item).items() if key not in ("file",)}
    out.update(file_tail=_tail(item.file), suggest=suggest(item), state=(record or {}).get("state") or "new")
    if not out["repo"]:
        out.pop("repo")
    if dup_of:
        out["dup_of"] = dup_of
    if old_repo(item, repos):
        out["old_repo"] = True
    return out


def known_texts(state_dir) -> dict:
    """same_key -> ref of every live entry: what an import would only say again (``dup_of``)."""
    return {memstore.same_key(entry.text): entry.ref
            for entry in memstore.entries(state_dir, statuses=("active", "pending")) if entry.kind != "decision"}


def page(state_dir, home, number: int = 0, *, items=None, root_of=None, dup_of=None) -> dict:
    """Page ``number`` (from 0, ``PAGE`` a page) of the candidates as the web lists them (``memory:import:<page>``): the new
    ones first, then the ignored, then the imported, the newest file first within each. ``items`` a ``scan`` already done;
    ``dup_of(item)`` the ref of an entry that says the same (default: the same words, ``known_texts``)."""
    items = scan(state_dir, home, root_of=root_of) if items is None else items
    records = memstore.imports(state_dir)["items"]
    repos = repomap.read(state_dir)
    order = {"new": 0, "ignored": 1, "imported": 2}
    ranked = sorted(items, key=lambda item: order.get((records.get(item.fingerprint) or {}).get("state") or "new", 0))
    chosen = ranked[number * PAGE:(number + 1) * PAGE]
    if dup_of is None:
        texts = known_texts(state_dir)
        dup_of = lambda item: texts.get(memstore.same_key(item.text), "")  # noqa: E731
    return {"page": number, "items": [view(item, records.get(item.fingerprint), repos, dup_of=dup_of(item)) for item in chosen]}


def summary(state_dir, items) -> dict:
    """{total, new, pages} of ``items`` (``scan``'s) for memory:index ``imports``."""
    records = memstore.imports(state_dir)["items"]
    new = sum(1 for item in items if (records.get(item.fingerprint) or {}).get("state", "new") == "new")
    return {"total": len(items), "new": new, "pages": (len(items) + PAGE - 1) // PAGE}


def _facts(item: ImportItem) -> dict:
    return {"harness": item.harness, "file": item.file, "bucket": item.bucket}


def take(state_dir, home, fingerprints, *, kind: str = "", scope: str = "global", owner_key: str = "", who: str = "owner",
         token: str = "", items=None, root_of=None, now=None) -> list:
    """The candidates ``fingerprints`` imported (the owner ticked them, so 你定的): each an entry of ``kind`` (default its
    ``suggest``) in ``scope``, its origin the Harness and the file, marked imported. The entries made."""
    stamp = time.time() if now is None else now
    wanted = {str(fp) for fp in fingerprints}
    by_fp = {item.fingerprint: item for item in (scan(state_dir, home, root_of=root_of) if items is None else items)}
    repos = repomap.read(state_dir)
    made = []
    for fp in [fp for fp in fingerprints if str(fp) in by_fp and str(fp) in wanted]:
        item = by_fp[str(fp)]
        entry = memstore.add(state_dir, kind=kind or suggest(item)["kind"], scope=scope, owner_key=owner_key, text=item.text,
                             title=item.title, said="owner", by="import", who=who, token=token,
                             origin={"at": stamp, "harness": item.harness, "file": _tail(item.file)},
                             repos=(item.repo,) if item.repo and not old_repo(item, repos) else (), now=stamp)
        memstore.imports_set(state_dir, [item.fingerprint], "imported", entry_ref=entry.ref, facts={fp: _facts(item)}, now=stamp)
        made.append(entry)
    return made


def ignore(state_dir, fingerprints, *, items=None, now=None) -> list:
    """The candidates ``fingerprints`` left in their Harness: not offered again while the file says the same."""
    facts = {item.fingerprint: _facts(item) for item in items or ()}
    return memstore.imports_set(state_dir, fingerprints, "ignored", facts=facts, now=now)


def fresh(state_dir, home, *, root_of=None, now=None) -> list[ImportItem]:
    """The candidates of the files new or changed since the last call and never seen before, marked new in
    memory/imports.json: what the night puts in 待审核 (app/memory_harvest.py). The first call only notes what is there
    and gives nothing (nothing floods 待审核 with what was always there)."""
    stamp = time.time() if now is None else now
    found = scan(state_dir, home, root_of=root_of)
    sigs = {}
    for item in found:
        if item.file not in sigs:
            try:
                stat = Path(item.file).stat()
                sigs[item.file] = [stat.st_mtime_ns, stat.st_size]
            except OSError:
                sigs[item.file] = None
    out = []

    def note(data):
        first = data["files"] is None
        before = data["files"] or {}
        for item in found:
            if item.fingerprint in data["items"]:
                continue
            data["items"][item.fingerprint] = {"state": "new", "at": stamp, **_facts(item)}
            if not first and before.get(item.file) != sigs.get(item.file):
                out.append(item)
        data["files"] = sigs
    memstore.imports_update(state_dir, note)
    return out
