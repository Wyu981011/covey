"""Events the SDK connection took in, kept in the state directory until they are handled, so a stop, a restart or a
crash between the two does not lose them: the next start hands them to their consumers before what came since
(``COVEY_EVENT_TRANSPORT=sdk``, feishu/ws_intake.py; docs/architecture.md 事件长连接走 SDK).

Feishu counts an event delivered once the connection has it (a click's toast says 收到), and the Bridge handles it later
on its key's consumer thread. In between it was only in memory: on 2026-11-23 the message consumer waited 18 minutes on
a lock held over a read hung on the NAS, a restart came, and the two messages behind it were gone.

One file an event, ``<state>/event-spool/<received ms>-<seq>-<kind>-<digest of its event_id>.json``. It is written when
the event is taken in and removed once its handler is done with it, both on this module's own thread (``event-spool``),
never on the SDK's: that one answers a click within 3 s and runs the pings, and a write on the NAS can hang for
minutes. So what a stop or a kill finds unhandled is on disk already, unless the disk held the write up as well: a stop
waits for the writes still queued at most FLUSH_SECONDS (none queued, not at all), and says how many it left.

Handling one again is safe: a message is claimed once (``claim_once`` in app/card_routing.py), a menu click too
(app/bot_menu.py), and a card click again is what a second click of the owner is, which its handler checks against
the card's state. Read receipts are not kept. One taken in longer ago than its kind's REPLAY_SECONDS is dropped by
the next start, not handled; daily maintenance removes what no start took (core/maintenance_rules.py Temporary)."""
from __future__ import annotations

import collections
import contextlib
import hashlib
import itertools
import json
import os
import queue
import threading
import time
import uuid
from pathlib import Path

from covey.core import state as state_files
from covey.feishu.events import CARD_ACTION_EVENT_KEY, MENU_EVENT_KEY, MESSAGE_EVENT_KEY

FOLDER = 'event-spool'
KINDS = {MESSAGE_EVENT_KEY: 'message', CARD_ACTION_EVENT_KEY: 'card', MENU_EVENT_KEY: 'menu'}  # The keys kept.
# How long ago an event may have been taken in for the next start to handle it. The owner's message is his request
# however late; a click or a menu click asked for an answer then, and long after it would surprise him.
REPLAY_SECONDS = {MESSAGE_EVENT_KEY: 24 * 3600, CARD_ACTION_EVENT_KEY: 10 * 60, MENU_EVENT_KEY: 2 * 60}
LEFT_OUT = ('token',)  # A click's callback token: never written (no handler reads it).
FLUSH_SECONDS = 2.0  # What a stop waits at most for the writes still queued; within the Manager's 15 s to SIGKILL.
LOAD_SECONDS = 5.0  # What a consumer waits at most for what the last run left before it takes a new event.

_local = threading.local()


@contextlib.contextmanager
def settling(settle):
    """Run the block with ``settle`` as the event this thread is handling: called when the block ends, unless ``hold``
    took it over inside it (the event's work went on to another thread, which settles it once that is done)."""
    previous = getattr(_local, 'settle', None)
    _local.settle = settle
    try:
        yield
    finally:
        left = getattr(_local, 'settle', None)
        _local.settle = previous
        if left is not None:
            left()


def hold():
    """For a handler that queues its event's work for another thread (app/card_lanes.py, app/card_queue.py): the
    callable that settles the event, to be run there inside ``settling`` once the work is over; the event stays kept
    until then, so a stop that drops the queued work leaves it for the next start. None when this thread handles no
    kept event (lark-cli's consumers, a read receipt, a test)."""
    settle = getattr(_local, 'settle', None)
    _local.settle = None
    return settle


class Spool:
    """The kept events of one state directory: what this process takes in (``keep``, ``done``) and what the last run
    left (``left``), read once by the writer thread before it writes anything."""

    def __init__(self, state_dir, log, remember):
        self.folder = Path(state_dir) / FOLDER
        self.log = log
        self.remember = remember  # event_id -> False when it was taken in already (ws_intake.Intake.first_time).
        self.ops = queue.SimpleQueue()
        self.changed = threading.Condition()
        self.queued = 0  # Writes and removals not done yet.
        self.kept: set[str] = set()  # Names of this process's events not handled yet.
        self.leftovers = {key: collections.deque() for key in KINDS}
        self.loaded = threading.Event()
        self.serial = itertools.count()
        self.thread: threading.Thread | None = None
        self.made = False  # The folder exists and is private.
        self.lock = threading.Lock()

    def start(self) -> None:
        with self.lock:
            if self.thread is not None:
                return
            self.thread = threading.Thread(target=self._run, name='event-spool', daemon=True)
        self.thread.start()

    def close(self) -> None:
        """End the writer thread (tests): what is queued before is done first."""
        if self.thread is not None:
            self.ops.put(None)
            self.thread.join(5)

    # -- this process's events --

    def keep(self, key: str, event: dict) -> str:
        """The name ``event`` is kept under, its write queued for the writer thread; '' for a key not kept. Never
        touches the disk: this runs on the SDK's thread."""
        kind = KINDS.get(key)
        if kind is None:
            return ''
        now = time.time()
        ident = str(event.get('event_id') or event.get('message_id') or '') or uuid.uuid4().hex
        name = (f'{int(now * 1000):013d}-{next(self.serial):06d}-{kind}-'
                f'{hashlib.sha256(ident.encode()).hexdigest()[:16]}.json')
        record = {'v': 1, 'key': key, 'received_at': now,
                  'event': {field: value for field, value in event.items() if field not in LEFT_OUT}}
        self._queue(('keep', name, record), self.kept.add)
        return name

    def done(self, name: str) -> None:
        """The event kept under ``name`` was handled: its file goes (and is never written when it was not yet)."""
        if name:
            self._queue(('done', name, None), self.kept.discard)

    def _queue(self, op, note) -> None:
        with self.changed:
            note(op[1])
            self.queued += 1
        self.ops.put(op)

    # -- what the last run left --

    def wait_loaded(self, seconds: float) -> bool:
        return self.loaded.wait(seconds)

    def left(self, key: str):
        """The oldest event of ``key`` the last run left and this one has not handed out yet, as (event, name); None."""
        try:
            return self.leftovers[key].popleft() if key in self.leftovers else None
        except IndexError:
            return None

    # -- the writer thread --

    def _run(self) -> None:
        try:
            self._load()
        except Exception as exc:  # noqa: BLE001 - the events of this run are kept all the same
            self.log(f'event spool: what the last run left was not read ({type(exc).__name__})')
        finally:
            self.loaded.set()
        while True:
            batch = [self.ops.get()]
            while True:
                try:
                    batch.append(self.ops.get_nowait())
                except queue.Empty:
                    break
            closing = None in batch
            ops = [op for op in batch if op is not None]
            kept_now = {name for kind, name, _ in ops if kind == 'keep'}
            done_now = {name for kind, name, _ in ops if kind == 'done'}
            try:
                for kind, name, record in ops:
                    try:
                        if kind == 'keep' and name not in done_now:  # Handled before it was written: never written.
                            self._write(name, record)
                        elif kind == 'done' and name not in kept_now:
                            self._remove(name)
                    except Exception as exc:  # noqa: BLE001 - one event must not end the thread
                        self.log(f'event spool: {kind} failed ({type(exc).__name__})')
            finally:
                with self.changed:
                    self.queued -= len(ops)
                    self.changed.notify_all()
            if closing:
                return

    def _write(self, name, record) -> None:
        try:
            if not self.made:
                state_files.ensure_private_dir(self.folder)
                self.made = True
            data = json.dumps(record, ensure_ascii=False, separators=(',', ':')).encode()
            state_files.atomic_write_bytes(self.folder / name, data, notify=False,
                                           remake=lambda: state_files.ensure_private_dir(self.folder))
        except (OSError, TypeError, ValueError) as exc:
            self.log(f'event spool: could not keep an event of {record.get("key")} ({type(exc).__name__}); '
                     'a stop before it is handled loses it')

    def _remove(self, name) -> None:
        try:
            (self.folder / name).unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.log(f'event spool: could not remove a handled event ({type(exc).__name__}); the next start '
                     'hands it over again')

    def _load(self) -> None:
        """Read what the last run left, oldest first: kept for its consumer (``left``) unless taken in too long ago
        (REPLAY_SECONDS) or again since; files that cannot be read and half-written ones go."""
        try:
            names = sorted(os.listdir(self.folder))
        except FileNotFoundError:
            return
        except OSError as exc:
            self.log(f'event spool: what the last run left cannot be read ({type(exc).__name__})')
            return
        now, taken, dropped = time.time(), collections.Counter(), collections.Counter()
        for name in names:
            path = self.folder / name
            if name.startswith('.'):  # A write a stop or a crash cut short.
                self._remove(name)
                continue
            if not name.endswith('.json'):
                continue
            try:
                record = json.loads(path.read_text())
                key, event, received = record['key'], record['event'], float(record['received_at'])
                if key not in KINDS or not isinstance(event, dict):
                    raise ValueError(key)
            except (OSError, ValueError, KeyError, TypeError):
                dropped['unreadable'] += 1
                self._remove(name)
                continue
            if now - received > REPLAY_SECONDS[key]:
                dropped[f'{key} taken in too long ago'] += 1
                self._remove(name)
            elif not self.remember(event.get('event_id')):
                dropped[f'{key} taken in again since'] += 1
                self._remove(name)
            else:
                self.leftovers[key].append((event, name))
                taken[key] += 1
        if taken:
            self.log('event spool: what the last run took in and did not handle goes first: '
                     + ' '.join(f'{key}={n}' for key, n in sorted(taken.items())))
        if dropped:
            self.log('event spool: dropped ' + ', '.join(f'{n} {why}' for why, n in sorted(dropped.items())))

    # -- a stop --

    def flush(self, seconds: float = FLUSH_SECONDS) -> None:
        """At a stop, once nothing new comes in: wait up to ``seconds`` for the queued writes and removals (none
        queued, not at all), then say how many events the next start will hand over, or how many writes the disk
        held up."""
        deadline = time.monotonic() + seconds
        with self.changed:
            if self.thread is None or not self.thread.is_alive():
                waiting = self.queued
            else:
                while self.queued and deadline > time.monotonic():
                    self.changed.wait(deadline - time.monotonic())
                waiting = self.queued
            kept = len(self.kept) + sum(map(len, self.leftovers.values()))  # Left by the last run, not handed out.
        if waiting:
            self.log(f'event spool: {waiting} writes still queued at stop (the disk held them up); '
                     f'what they would keep is lost if this process ends now')
        elif kept:
            self.log(f'event spool: {kept} events taken in and not handled are kept for the next start')


def spool_for(ctx, log, remember):
    """The Spool of ``ctx``'s state directory; None without one (a test's bare context)."""
    state_dir = getattr(ctx, 'state_dir', None)
    return Spool(state_dir, log, remember) if state_dir else None

