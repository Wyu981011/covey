"""Indexed JSON records with legacy-compatible reads and isolated invalid files."""
from __future__ import annotations

import copy
import itertools
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

from covey.core import storage_watch, timing
from covey.core.locks import resource_lock
from covey.core.statuses import QUESTION_TRANSITIONS
from covey.core.state import atomic_write_bytes

FRESH_SECONDS = 1.0  # A scan older than this is redone whatever the directory says.
# A scan reads this many files at a time. On NAS, 927 job records read one by one took 2.0-2.3 s for a
# new process (a task runner's first query) and 0.65 s eight at a time; their stats 0.2 s and 0.03 s (S35).
SCAN_THREADS = 8
# Writers note each record they write in its directory's journal (note_change, from write_private_text),
# so a store catches up from the names added since its last look instead of listing the directory:
# with ~1000 job records a changed directory's listing took about 100 ms on NFS, the new lines 1-3 ms (S45).
JOURNAL = ".journal"  # Not *.json: Path.glob('*.json') matches dot files too.
JOURNALED = frozenset({"jobs", "questions", "held-notes"})
LIST_SECONDS = 60.0  # A full listing still runs this often: for a write the journal missed (a hand edit).
INDEX = ".index"  # JsonDirectoryStore.save_index; not *.json either.
INDEXED = ('topic_id', 'chat_id', 'job_id', 'status', 'request_id')  # The fields a query can filter on.
# Fields kept beside INDEXED (in .index too) for ``narrow``, a query's cheap test on them before any record is read;
# no index entry is made of them. An .index of a release before them has none: ``narrow`` is then told so (None).
CARRIED = ('updated_at',)
# A file two threads read at about the same time, with different results, is read once more, so the later read stays;
# this many times at most, then the next look reads it (JsonDirectoryStore._fetch).
ROUNDS = 3
# A catch-up under way is waited for until it is this old (one takes milliseconds from the journal, a listing of a large
# directory on NFS a few hundred); a reader that finds one older answers from the last catch-up instead (T677).
PATIENCE = 1.0
_scope = threading.local()
_listeners = []  # Called with (folder name, record name) after each note_change of this process (listen).


class Busy(Exception):
    """A store was not free within the ``bounded`` time of the asking thread: another thread holds its lock, or is in
    the catch-up the query must wait for (JsonDirectoryStore._look: the first one, or reading records the query needs),
    which may be stuck on the network disk (an NFS open of the journal hung for minutes, 2026-11-23 T673)."""


@contextmanager
def bounded(seconds):
    """Inside, a query, count or max_field of this thread waits at most ``seconds`` for a store and raises Busy instead
    of waiting on: for its lock, or for another thread's catch-up when there is nothing yet to answer from or the query
    needs records known only by their fields. For a reader that must not hang behind another thread's stuck scan (the
    web page's push, app/web_sync.py). Outside it, and on other threads, such a query waits as long as it takes."""
    before = getattr(_scope, "wait", None)
    _scope.wait = seconds
    try:
        yield
    finally:
        _scope.wait = before


def listen(callback):
    """``callback(folder name, record name)`` after each record this process writes in a journaled folder (note_change):
    a reader that wants to look at once, not at its next poll. It must return at once (it runs in the writer's thread,
    maybe under the record's lock): set an event, nothing more. Without one, nothing changes."""
    if callback not in _listeners:
        _listeners.append(callback)


def unlisten(callback):
    if callback in _listeners:
        _listeners.remove(callback)


def note_change(folder, name):
    """A writer's note that it wrote record ``name`` in ``folder``, for the folders that keep a journal.
    One short append (2-4 ms on NAS); if it fails, readers see the write at their next full listing."""
    folder = Path(folder)
    if folder.name not in JOURNALED:
        return
    try:
        fd = os.open(folder / JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            os.write(fd, (name + "\n").encode())
        finally:
            os.close(fd)
    except OSError:
        pass
    for callback in tuple(_listeners):
        try:
            callback(folder.name, name)
        except Exception:  # noqa: BLE001 - a listener never fails a write
            pass


def _record_name(name):
    """A record file's name: ``*.json``, not a dot file (a writer's temp file, the journal), no path."""
    return name.endswith('.json') and not name.startswith('.') and '/' not in name


@contextmanager
def one_scan():
    """One message or click: inside, each store is checked as usual on its first query (or answered from the last
    catch-up while another thread's is stuck, JsonDirectoryStore._look), and later
    queries rescan only when that scan is over FRESH_SECONDS old, not on every change of the
    directory; a record this process writes meanwhile is re-read by name. Another process's write
    shows within FRESH_SECONDS, as it may anyway with coarse directory timestamps. The 870 job
    files cost 0.13-0.2 s a scan on NAS, several times per message before. Outside
    the block, and on other threads, nothing changes."""
    if getattr(_scope, "checked", None) is not None:
        yield
        return
    _scope.checked = set()
    try:
        yield
    finally:
        _scope.checked = None


class JsonDirectoryStore:
    """One directory of JSON records, known to this process: each record's indexed fields (INDEXED)
    always, the whole record once a query needed it. A new process learns the fields from .index
    (saved by the Bridge, save_index) and the journal since, so it reads only the records it asks
    for; without .index it reads them all, as a long-lived Bridge does anyway.

    No read of the disk holds ``lock``, which guards what is in memory: an NFS open of the journal hung for minutes
    under it, and every reader and writer of the records with it (T673, T677). One thread at a time catches up or
    reads the records a query needs (``refreshing``) and puts what it read in under ``lock``. The others wait for it,
    as before, until it is PATIENCE old, then answer from the last catch-up, with this process's own writes since read
    again by name. A query waits on only when there is nothing to answer from yet (a new process's first catch-up),
    it needs a record known only by its fields, or a write was not named."""

    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.RLock()  # What is in memory; never held while the disk is read.
        self.refreshing = threading.RLock()  # The one thread catching up (_check) or reading records a query needs.
        self.since = 0.0  # When the thread holding ``refreshing`` took it.
        self.known = False  # A catch-up has ended: a query can answer from it while another one is under way.
        self.marks = itertools.count(1)  # Taken around each read and at each write: their order across threads.
        self.signature = None
        self.checked_at = 0.0
        self.cache = ({}, {})  # (fingerprints, records), replaced whole under ``lock``: _read takes it without.
        self.fields = {}  # name -> its INDEXED fields, for every record known.
        self.inodes = {}  # name -> inode number of the file the fields came from.
        self.seen = {}  # name -> (first, last) marks of the read its entry comes from; a gone file's while needed.
        self.journaled = self.directory.name in JOURNALED
        self.journal = None  # (inode, offset) of the journal read up to; None: list instead.
        self.listed_at = 0.0
        self.seeded = False  # .index tried (_seed).
        self.version, self.saved, self.saved_at = 0, -1, 0.0
        self.index = {}
        self.invalid = set()
        self.refused = set()  # (name, fingerprint) of the records a ``where`` raised on, already logged.
        self.written = {}  # name -> mark of this process's write of it not yet read back; None: unknown, list again.
        self.blind = 0  # The mark of the latest write while ``written`` is None.
        self.flying = 0  # Reads under way (_fetch): a gone file's marks are kept while one is.

    @property
    def records(self):
        """name -> the whole record, once read."""
        return self.cache[1]

    @property
    def fingerprints(self):
        return self.cache[0]

    def query(self, where=None, *, log=None, narrow=None, **filters):
        """(path, a copy of the record) per record matching the indexed ``filters`` and, when given,
        ``where(record)``. A filter's value is one value, or a set (frozenset) of them: any of those
        (status=RUNNING). ``where`` sees the cached record (it must not change it), so only the
        records it accepts are copied. A record ``where`` raises on (a field of the wrong type) is
        left out, and ``log`` gets one line for it until the file changes: one bad record must not
        stop a loop over the others. Inside one_scan() a repeated query reuses the scan. Only the
        records the filters select are read, if not read before. ``narrow(fields)``, when given, tests a record's
        INDEXED and CARRIED fields (a dict of those it has and the store knows: one from an .index before CARRIED
        has none of them) and must be true for every record ``where`` would accept; a record it is false for is not
        read at all. It must say True when a field it needs is missing. ``narrow``, ``where``, ``log`` and the copies
        run with no lock of the store held."""
        self._look(time.monotonic())
        rows, missing = self._rows(filters, narrow)
        if missing:  # Known only by their fields (from .index): read by one thread at a time.
            with self._leading(wait=True):
                with self._held():  # Less those another thread read while this one waited.
                    records = self.records
                    missing = [path for path in missing if path.name not in records and path.name in self.fields]
                self._fetch(missing)
            rows, _ = self._rows(filters, narrow)
        return [(self.directory / name, copy.deepcopy(record)) for name, record in rows
                if where is None or self._accepts(where, name, record, log)]

    def _rows(self, filters, narrow):
        """((name, the cached record) of each record ``filters`` and ``narrow`` select, in name order; the paths of those
        known only by their fields), from one look at what is in memory: its records are replaced whole, never
        changed, so ``narrow`` runs on them after the lock is let go."""
        with self._held():
            fields = {name: self.fields[name] for name in self._selected(filters)}
            records = self.records
        names = sorted(name for name, each in fields.items() if narrow is None or self._narrows(narrow, each))
        return ([(name, records[name]) for name in names if name in records],
                [self.directory / name for name in names if name not in records])

    def count(self, **filters):
        """How many records the indexed ``filters`` (as query's) select, from the fields alone: none is read or copied."""
        self._look(time.monotonic())
        with self._held():
            return len(self._selected(filters))

    def _take(self, lock, within=None):
        """``lock`` acquired: waited for as long as it takes, or (inside ``bounded``) at most that long: Busy then.
        ``within`` seconds, when given: False when not acquired by then, or by the end of ``bounded``'s wait."""
        wait = getattr(_scope, "wait", None)
        if within is not None:
            return lock.acquire(timeout=max(0.0, within if wait is None else min(within, wait)))
        if wait is None:
            lock.acquire()
        elif not lock.acquire(timeout=max(0.0, wait)):
            raise Busy(self.directory.name)
        return True

    @contextmanager
    def _held(self):
        """The store's lock, waited for as long as it takes, or (inside ``bounded``) at most that long: Busy then."""
        self._take(self.lock)
        try:
            yield
        finally:
            self.lock.release()

    @contextmanager
    def _leading(self, wait, within=None):
        """``refreshing``: whether this thread holds it inside. ``wait``: as long as it takes, or (inside ``bounded``)
        at most that long, Busy then, or at most ``within`` seconds when given; otherwise only when no other thread
        holds it."""
        if not (self._take(self.refreshing, within) if wait else self.refreshing.acquire(blocking=False)):
            yield False
            return
        self.since = time.monotonic()
        try:
            yield True
        finally:
            self.refreshing.release()

    def _selected(self, filters):
        """The names of the records whose indexed fields match ``filters``."""
        names = set(self.fields)
        for key, value in filters.items():
            if isinstance(value, (set, frozenset)):
                names &= set().union(*(self.index.get((key, one), set()) for one in value))
            else:
                names &= self.index.get((key, value), set())
        return names

    def _missing(self, names):
        """The paths of the records among ``names`` known only by their fields (from .index)."""
        records = self.records
        return [self.directory / name for name in names if name not in records and name in self.fields]

    def max_field(self, field):
        """The largest whole number in indexed ``field`` (one of INDEXED) over the records, 0 when none:
        from the fields alone, no record is read (the Bridge's first job number at start, repo review R4)."""
        self._look(time.monotonic())
        with self._held():
            return max((int(value) for fields in self.fields.values() if (value := fields.get(field)) is not None
                        and (isinstance(value, int) or value.isdigit())), default=0)

    def _look(self, asked):
        """Catch up for a query asked at ``asked``; inside one_scan() a fresh scan is reused. Another thread's catch-up
        under way is waited for, as before, until it is PATIENCE old; one older (stuck on the disk) is left behind:
        the query answers from the last catch-up, with this process's writes since read again by name. It waits on
        when there is nothing to answer from yet or a write it cannot name (``written`` None)."""
        checked = getattr(_scope, "checked", None)
        with self._held():
            reuse = (checked is not None and self in checked and self.written is not None
                     and time.monotonic() - self.checked_at <= FRESH_SECONDS)
            mine = list(self.written) if reuse else None
        if reuse:
            self._reread(mine)
            return
        with self._leading(wait=False) as leading:
            if leading:
                self._check(self._waited(asked))
        if not leading:
            with self._held():
                behind = self.known and self.written is not None
            with self._leading(wait=True, within=self._patience() if behind else None) as leading:
                if leading:
                    self._check(self._waited(asked))
            if not leading:  # Left behind: answer from the last catch-up and this process's writes since.
                with self._held():
                    mine, since = (None if self.written is None else list(self.written)), self.since
                if mine is not None:
                    timing.add("behind", f"{self.directory.name}:{round((time.monotonic() - since) * 1000)}")
                    self._reread(mine)
                    return
                with self._leading(wait=True):  # A write it cannot name came meanwhile: wait for the catch-up.
                    self._check(self._waited(asked))
        if checked is not None:
            checked.add(self)

    def _patience(self):
        """How much longer the catch-up under way is waited for: until it is PATIENCE old."""
        return max(0.0, PATIENCE - (time.monotonic() - self.since))

    def _waited(self, asked):
        """Now, noting the wait since ``asked`` when there was one: behind another thread's scan, wait=jobs:850 (S41)."""
        now = time.monotonic()
        if now - asked > 0.005:
            timing.add("wait", f"{self.directory.name}:{round((now - asked) * 1000)}")
        return now

    def catch_up(self):
        """Know the directory as it is now, reading no record that has not changed since .index: a new
        process's head start (app/runner.py warm_records). A query meanwhile waits for it when it has nothing else
        to answer from or needs a record it reads."""
        with self._leading(wait=True):
            self._check(time.monotonic())

    def warm(self):
        """``catch_up`` and read every record known only by its fields: the head start of a process about to read them
        all (the Bridge's start, app/unified.py warm_records). A query that needs a record meanwhile waits for it, as
        for any scan; a count, or a query over records already read, answers from the fields it caught up."""
        with self._leading(wait=True):
            self._check(time.monotonic())
            with self._held():
                missing = self._missing(self.fields)
            self._fetch(missing)

    def _check(self, now):
        """Catch up when the directory changed or the last look is over FRESH_SECONDS old: from the
        journal's new lines when it can (_from_journal), else by listing the directory. The caller holds
        ``refreshing``, not ``lock``: the disk is read without it, and what was read goes in under it, this process's
        writes meanwhile kept to be read again (``written``)."""
        if not self.seeded:
            self._seed(now)
        try:
            stat = self.directory.stat()
            signature = (stat.st_ino, stat.st_mtime_ns)
        except FileNotFoundError:
            signature = None
        with self._held():
            if signature == self.signature and now - self.checked_at <= FRESH_SECONDS:
                return
            self.checked_at = now
            before, journal, listed_at = self.signature, self.journal, self.listed_at
            written = None if self.written is None else set(self.written)

        def settle():
            if self.signature is before:  # Not written by this process meanwhile (invalidate_directory).
                self.signature = signature
            self.known = True
        found = self._from_journal(now, journal, written, listed_at)
        if found is not None:
            names, position = found

            def caught_up():
                self.journal = position
                settle()
            self._fetch([self.directory / name for name in names], again=True, always=bool(names), settle=caught_up)
            timing.add("journal", f"{self.directory.name}:{round((time.monotonic() - now) * 1000)}")
            return
        # A rescan reads only the files whose inode changed: every writer replaces a record whole
        # (write_private_text renames a new file over it), and this NAS never reuses an inode
        # (300 rewrites, S39). On NFS a stat per file cost 0.3-0.9 s for 976 job records, as
        # each one went to the server once the directory had changed; the listing 1.3 ms.
        position = self._journal_end()
        first = next(self.marks)
        inodes = self._list()
        last = next(self.marks)
        with self.lock:
            changed = [self.directory / name for name, inode in inodes.items()
                       if self.inodes.get(name) != inode or (name not in self.fields and name not in self.invalid)]
            gone = [(name, first, last, None, None, False) for name in set(self.fields) | self.invalid
                    if name not in inodes]

        def listed():
            self.listed_at, self.journal = now, position
            if self.written is None and self.blind < first:  # Every write it could not name was before the listing.
                self.written = {}
            if self.flying == 1:  # No other read under way: no read older than a gone file's is left to drop.
                self.seen = {name: marks for name, marks in self.seen.items() if name in self.fields or name in self.invalid}
            settle()
        self._fetch(changed, made=gone, always=True, settle=listed)
        # Which phase of a flow paid for a rescan, and how much: scan=jobs:254 (S39).
        timing.add("scan", f"{self.directory.name}:{round((time.monotonic() - now) * 1000)}")

    def _seed(self, now):
        """Start from .index: every record's fields and inode, and the journal position they reflect.
        The journal since then (or a listing, should it have been replaced) brings them up to date."""
        with self._held():
            self.seeded = True
            if not self.journaled or self.fields or self.invalid:
                return
        try:
            saved = json.loads((self.directory / INDEX).read_text())
            position = tuple(saved["journal"])
            entries = {name: (int(inode), dict(fields)) for name, (inode, fields) in saved["entries"].items()
                       if _record_name(name)}
            age = max(0.0, time.time() - float(saved["saved_at"]))
            position = (int(position[0]), int(position[1]))
        except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError):
            return
        with self.lock:
            if self.fields or self.invalid:
                return
            self.fields = {name: fields for name, (_, fields) in entries.items()}
            self.inodes = {name: inode for name, (inode, _) in entries.items()}
            self.journal, self.listed_at = position, now - age
            self._reindex()

    def save_index(self, every=30.0):
        """Write .index when something changed since the last one, at most every ``every`` seconds; the
        Bridge does, for the processes it starts (_seed). Whether it wrote one."""
        with self.lock:
            now = time.monotonic()
            if (not self.journaled or self.journal is None or self.written is None or self.version == self.saved
                    or now - self.saved_at < every):
                return False
            # The fields as of self.journal, plus this process's writes not yet read back: those are in
            # the journal after it, read again by whoever starts from this.
            saved = {"saved_at": time.time(), "journal": list(self.journal),
                     "entries": {name: [self.inodes[name], fields] for name, fields in self.fields.items()
                                 if name in self.inodes}}
            version = self.version
            self.saved_at = now
        text = json.dumps(saved, ensure_ascii=False, separators=(",", ":"))
        atomic_write_bytes(self.directory / INDEX, text.encode("utf-8"), prefix=INDEX + ".", notify=False)
        with self.lock:
            self.saved = max(self.saved, version)
        return True

    def _list(self):
        """Name -> inode number of each record file (_record_name), without a stat per file."""
        try:
            with os.scandir(self.directory) as entries:
                return {e.name: e.inode() for e in entries if _record_name(e.name)}
        except OSError:
            return {}

    def _journal_end(self):
        """(inode, size) of the journal, taken before a listing: what is noted after it is read next."""
        if not self.journaled:
            return None
        try:
            stat = os.stat(self.directory / JOURNAL)
        except OSError:
            return None
        return stat.st_ino, stat.st_size

    def _from_journal(self, now, position, written, listed_at):
        """(names, position): the records written since ``position`` (where the journal was read up to), from the
        journal's new lines and this process's own writes (``written``), and where it is read up to now; None when
        the directory must be listed instead: no journal (yet), LIST_SECONDS passed, or the journal was replaced
        or cut. Reads the disk: never under ``lock``."""
        if position is None or written is None or now - listed_at > LIST_SECONDS:
            return None
        inode, offset = position
        path = self.directory / JOURNAL
        try:
            stat = os.stat(path)
            if stat.st_ino != inode or stat.st_size < offset:
                return None
            data = b""
            if stat.st_size > offset:
                with open(path, "rb") as handle:
                    if os.fstat(handle.fileno()).st_ino != inode:  # Replaced since the stat.
                        return None
                    handle.seek(offset)
                    data = handle.read(stat.st_size - offset)
        except OSError:
            return None
        end = data.rfind(b"\n") + 1  # A line still being appended is read next time, whole.
        names = {name for name in data[:end].decode("utf-8", "replace").splitlines() if _record_name(name)}
        return names | written, (inode, offset + end)

    def _reread(self, names):
        """Re-read only ``names`` (written since they were read); the rest stays."""
        if names:
            self._fetch([self.directory / name for name in names], again=True, always=True)

    def _fetch(self, paths, *, again=False, made=(), always=False, settle=None):
        """Read ``paths`` without ``lock`` (_observe) and put what was read in under it (_merge) with ``made`` (what a
        listing found gone), then ``settle()`` in the same hold; the index is redone when ``always`` or a record's
        fields changed. A file another thread read at about the same time with another result is read once more,
        so that the later read stays: ROUNDS times at most, then the next look reads it (_doubt) and ``settle`` is left
        undone, so the catch-up counts as not done (the journal is not taken as read past it)."""
        with self._held():
            self.flying += 1
        try:
            seen = list(made)
            for left in reversed(range(ROUNDS)):
                seen += self._observe(paths, again)
                with self.lock:  # What was read goes in: not given up for a ``bounded`` wait.
                    changed, doubts = self._merge(seen)
                    if not doubts or not left:
                        for name in doubts:
                            self._doubt(name)
                        if settle is not None and not doubts:  # Unsettled: the next catch-up reads the same again.
                            settle()
                        if always or changed:
                            self._reindex()
                        return
                    if changed:
                        self._reindex()
                paths, again, seen = [self.directory / name for name in doubts], True, []
        finally:
            with self.lock:
                self.flying -= 1

    def _observe(self, paths, again=False):
        """What each of ``paths`` holds now, read without ``lock``: (name, first, last, fingerprint, record, there),
        ``first`` and ``last`` marks taken before and after the read, which place it among other threads' reads and
        this process's writes. ``again``: a reread of what was written, where a file that is not there is gone;
        otherwise one that cannot be read is invalid, as a scan takes it."""
        paths = list(paths)
        if len(paths) > SCAN_THREADS:
            with ThreadPoolExecutor(SCAN_THREADS, thread_name_prefix='store-scan') as pool:
                return list(pool.map(lambda path: self._sample(path, again), paths))
        return [self._sample(path, again) for path in paths]

    def _sample(self, path, again):
        first = next(self.marks)
        if again and not (path.suffix == '.json' and path.exists()):  # What the scan's glob would find.
            return path.name, first, next(self.marks), None, None, False
        name, fingerprint, record = self._read(path)
        return name, first, next(self.marks), fingerprint, record, True

    def _merge(self, seen):
        """Put ``seen`` (_observe) in, under ``lock``: (whether a record's fields changed, the names to read again). A
        read begun after the one an entry comes from replaces it; one that ended before that one began is dropped (the
        file was read later); one at about the same time that found the file otherwise is read again. A write of this
        process counts as read back once a read begun after it is in (``written``)."""
        if not seen:
            return False, []
        fingerprints, records = dict(self.fingerprints), dict(self.records)
        changed, doubts = False, []
        for name, first, last, fingerprint, record, there in seen:
            was = self.seen.get(name)
            if was is not None and first <= was[1]:  # Not begun after the read the entry comes from.
                held = name in fingerprints or name in self.fields or name in self.invalid
                if last >= was[0] and (there, fingerprint) != (held, fingerprints.get(name)):
                    doubts.append(name)
                continue
            self.seen[name] = (first, last)
            before = self.fields.get(name)
            if there and fingerprint is not None:
                fingerprints[name] = fingerprint
                self.inodes[name] = fingerprint[0]
            else:
                fingerprints.pop(name, None)
                self.inodes.pop(name, None)
            if not there:
                records.pop(name, None)
                self.fields.pop(name, None)
                self.invalid.discard(name)
            elif record is None:
                records.pop(name, None)
                self.fields.pop(name, None)
                self.invalid.add(name)
            else:
                records[name] = record
                self.fields[name] = {field: record[field] for field in INDEXED + CARRIED
                                     if isinstance(record.get(field), (str, int))}
                self.invalid.discard(name)
            changed = changed or self.fields.get(name) != before
        self.cache = (fingerprints, records)
        if self.written:
            for name in [name for name, mark in self.written.items() if self.seen.get(name, (0, 0))[0] > mark]:
                del self.written[name]
        return changed, doubts

    def _doubt(self, name):
        """Read ``name`` again at the next look: reads of it at about the same time disagreed ROUNDS times over."""
        if self.written is not None:
            self.written[name] = next(self.marks)
        self.signature = object()

    def _read(self, path):
        """(name, fingerprint, record) of one file; the record this store has when the file is unchanged,
        None when it cannot be read or is not an object. Reads only: the scans run it in parallel."""
        try:
            st = path.stat()
        except OSError:
            return path.name, None, None
        fingerprint = (st.st_ino, st.st_mtime_ns, st.st_size)
        fingerprints, records = self.cache  # One pair, as it runs without the lock.
        if fingerprints.get(path.name) == fingerprint and path.name in records:  # A failed read is tried again.
            return path.name, fingerprint, records[path.name]
        try:
            with storage_watch.watched("读记录 " + path.name):
                value = json.loads(path.read_text())
        except (OSError, ValueError):
            return path.name, fingerprint, None
        return path.name, fingerprint, value if isinstance(value, dict) else None

    def _reindex(self):
        index = {}
        for name, fields in self.fields.items():
            for field, value in fields.items():
                if field in CARRIED:
                    continue
                index.setdefault((field, value), set()).add(name)
        self.index = index
        self.version += 1
        self.refused = {seen for seen in self.refused if self.fingerprints.get(seen[0]) == seen[1]}

    @staticmethod
    def _narrows(narrow, fields):
        try:
            return bool(narrow(fields))
        except Exception:  # noqa: BLE001 - a test that cannot tell leaves the record to ``where``, as without it
            return True

    def _accepts(self, where, name, record, log):
        try:
            return where(record)
        except Exception as exc:  # noqa: BLE001 - a malformed record is skipped, never the whole query
            with self.lock:
                seen = (name, self.fingerprints.get(name))
                if log is None or seen in self.refused:
                    return False
                self.refused.add(seen)
            log(f"record {self.directory.name}/{name} skipped: {type(exc).__name__}")
            return False


_stores = {}
_guard = threading.Lock()


def save_indexes(state_dir):
    """.index of each record directory this process has looked at (JsonDirectoryStore.save_index): the
    Bridge's, for the task runners it starts."""
    for name in sorted(JOURNALED):
        with _guard:
            store = _stores.get(str((Path(state_dir) / name).absolute()))
        if store is not None:
            store.save_index()


def directory_store(path):
    key = str(Path(path).absolute())
    with _guard:
        if key not in _stores:
            _stores[key] = JsonDirectoryStore(path)
        return _stores[key]


def update_question(path, change, *, expected=None):
    """The question record at ``path`` as ``change`` leaves it, under the record's lock: ``change`` gets a
    copy and returns the record to save, or None to leave it. A status moves only along
    QUESTION_TRANSITIONS. Written only when it changed, with the next revision (a record from before
    revisions stays without one): an untouched file keeps its mtime, which maintenance reads as the
    topic's last activity. The record, or None when its status is not in ``expected`` or ``change``
    left it. Never hold this lock while sending it."""
    from covey.core.state import write_private_text
    path = Path(path)
    with resource_lock('question', path):
        before = json.loads(path.read_text())
        if expected is not None and before.get('status') not in expected:
            return None
        after = change(copy.deepcopy(before))
        if after is None:
            return None
        old, new = before.get('status', 'pending'), after.get('status', 'pending')
        if old != new and new not in QUESTION_TRANSITIONS.get(old, set()):
            raise ValueError(f'无效的问题状态转换：{old} → {new}')
        if old != new:
            _stamp_settled(before, after, new)
        if after != before:
            if 'revision' in after:
                after['revision'] = int(after['revision']) + 1
            write_private_text(path, json.dumps(after, ensure_ascii=False))
        return after


# The time a question stopped waiting, written as its status moves there unless the change wrote it itself: an answer's
# when it is submitted (an uncertain one answered later keeps it), a cancellation's or a fold's when it happens. The
# records have no other time of it (the web page's 专项报告 drew every closed question as waiting until now).
SETTLED_STAMPS = {'submitting': 'answered_at', 'answered': 'answered_at', 'cancelled': 'cancelled_at', 'superseded': 'cancelled_at',
                  'set_aside': 'answered_at'}  # 不处理: it stops waiting then (撤销 drops the stamp with the rest).


def _stamp_settled(before, after, new):
    field = SETTLED_STAMPS.get(new)
    if not field or after.get(field) != before.get(field):
        return
    if new == 'answered' and after.get(field):
        return
    after[field] = time.time()


def transition_question(path, expected=None, **changes):
    """Compare-and-set a durable intent. Never hold this lock while sending it."""
    def change(record):
        if record.get("delivery_state") == "delivered" and changes.get("delivery_state") == "awaiting_ack":
            changes["delivery_state"] = "delivered"
        record.update(changes)
        record['schema_version'] = 1
        record.setdefault('revision', 0)
        return record
    return update_question(path, change, expected=expected)


def invalidate_directory(path, name=None):
    """This process wrote ``name`` in ``path`` (None: something there). The next query rescans,
    except inside one_scan(), where it re-reads ``name`` alone. Without a name, a query also waits for another
    thread's catch-up under way, however long: it cannot read back what it does not know (JsonDirectoryStore._look)."""
    # Filesystem directory timestamps may be coarser than successive writes.
    with _guard:
        store = _stores.get(str(Path(path).absolute()))
    if store is not None:
        with store.lock:  # Held for no read of the disk: another thread's catch-up stuck on one does not hold this up.
            store.signature = object()
            mark = next(store.marks)
            if name is None or store.written is None:
                store.written, store.blind = None, mark
            else:
                store.written[name] = mark
