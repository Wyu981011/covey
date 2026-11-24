"""Bounded concurrency across topics; FIFO within each topic.

How many tasks run at once is ``worker_limit``: COVEY_MAX_WORKERS, DEFAULT_WORKERS when it is unset or not a whole number
above 0, at most WORKERS_CEILING. Of those slots RESERVED are kept for the butler's and the projects' leads' turns
(``keeps_slot``): ordinary topics filling the rest never leave the owner's private chat or a project waiting behind them.
2026-11-24 T744: the limit was 10, written in, and a new topic waited with "排队中 · 并发已满（最多 10 个任务）" while the
machine had room for many more; app/submission.py says the same limit as this scheduler (``room_for``)."""

from __future__ import annotations

import queue
import threading
import time
from covey.core import env as cenv
from covey.core.metrics import mark

WORKERS_ENV = "COVEY_MAX_WORKERS"
DEFAULT_WORKERS = 32
WORKERS_CEILING = 512  # A value with a few zeros too many is not a run of thousands of processes.
RESERVED = 2  # Of the limit, the slots only the butler's and the leads' turns take.
# The old name, for an import from before T744 (an extension's): the default now.
MAX_WORKERS = DEFAULT_WORKERS


def worker_limit() -> int:
    """How many tasks may run at once: COVEY_MAX_WORKERS when it is a whole number above 0 (at most WORKERS_CEILING),
    else DEFAULT_WORKERS. Read when the Bridge starts its scheduler and when a message is queued."""
    raw = str(cenv.get(WORKERS_ENV, "") or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_WORKERS
    return min(WORKERS_CEILING, value) if value > 0 else DEFAULT_WORKERS


def topic_limit(limit) -> int:
    """Of ``limit`` slots, how many an ordinary topic's tasks may take together: all but RESERVED, at least one."""
    return max(1, limit - RESERVED)


def keeps_slot(job) -> bool:
    """Whether ``job`` is a turn of the butler or of a project's lead (core/butler.py traits, its row's ``keeps_slot``), which
    may take the reserved slots; False for anything else, and for a job its row cannot be read of."""
    from covey.core.butler import traits_of
    try:
        return traits_of(job).keeps_slot
    except Exception:  # noqa: BLE001 - a job the rows cannot place is an ordinary one.
        return False


def room_for(job, running_topics, limit) -> bool:
    """Whether ``job`` may start while ``running_topics`` (the topics of the tasks running: a count, or how many of them are
    ordinary topics' with ``(all, ordinary)``) take slots of ``limit``: any slot for the butler's and the leads' turns, all
    but the reserved ones for an ordinary topic's."""
    total, ordinary = running_topics if isinstance(running_topics, tuple) else (running_topics, running_topics)
    if total >= limit:
        return False
    return ordinary < topic_limit(limit) or keeps_slot(job)  # Its row read only when the topics' share is full.


def topic_key(job):
    return (job.chat_id, job.topic_id)


class WorkspaceScheduler:
    def __init__(self, shutdown, incoming, process, log, max_workers=None):
        self.shutdown, self.incoming = shutdown, incoming
        self.process, self.log = process, log
        self.max_workers = max(1, worker_limit() if max_workers is None else int(max_workers))
        self.active = {}
        self.reserved = set()  # The message ids of the active jobs that are the butler's or a lead's (``keeps_slot``).
        self.roles = {}  # message id -> keeps_slot of a pending or active job, read once: the loop asks every 0.1 s.
        self.lock = threading.Lock()
        self.pending = []

    def keeps(self, job):
        """``keeps_slot`` of ``job``, read once while it waits or runs."""
        if job.message_id not in self.roles:
            self.roles[job.message_id] = keeps_slot(job)
        return self.roles[job.message_id]

    def room(self, job):
        """Whether a slot is free for ``job`` now (``room_for``, its role read once); the caller holds ``lock``."""
        total, ordinary = len(self.active), len(self.active) - len(self.reserved)
        if total >= self.max_workers:
            return False
        return ordinary < topic_limit(self.max_workers) or self.keeps(job)

    def eligible(self, index):
        job = self.pending[index]
        key = topic_key(job)
        if (getattr(job, "start_held_until", 0) or 0) > time.time():
            return False  # Held for the owner's words (app/butler.py); its topic's later jobs wait behind it.
        return key not in self.active.values() and not any(topic_key(j) == key for j in self.pending[:index])

    def execute(self, job):
        try:
            mark(job, 'dispatched')
            self.process(job)
        except Exception as exc:  # noqa: BLE001 - keep other workspaces running.
            self.log(f"workspace job failed: {exc}")
        finally:
            with self.lock:
                self.active.pop(job.message_id, None)
                self.reserved.discard(job.message_id)
                self.roles.pop(job.message_id, None)
            self.incoming.task_done()

    def run(self):
        threads = []
        while not self.shutdown.is_set():
            try:
                job = self.incoming.get(timeout=0.1)
                self.pending.append(job)
            except queue.Empty:
                pass
            cancelled = [job for job in self.pending if getattr(job, "cancelled_before_start", False)]
            for job in cancelled:
                self.pending.remove(job)
                self.roles.pop(job.message_id, None)
                self.incoming.task_done()
            with self.lock:
                for index in range(len(self.pending)):
                    if len(self.active) >= self.max_workers:
                        break
                    if self.eligible(index) and self.room(self.pending[index]):
                        job = self.pending.pop(index)
                        self.active[job.message_id] = topic_key(job)
                        if self.keeps(job):
                            self.reserved.add(job.message_id)
                        thread = threading.Thread(target=self.execute, args=(job,), daemon=True)
                        threads = [t for t in threads if t.is_alive()]
                        threads.append(thread)
                        thread.start()
                        break
        for job in self.pending:
            job.cancel_event.set()
        for thread in threads:
            thread.join(timeout=12)
