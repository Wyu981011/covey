"""The Bridge's background threads: ``supervised`` keeps one running, ``every`` is the loop most of them run, ``Worker`` runs
the steps of a loop that must go on when one of them is stuck in a system call (an NFS open that never returns).
``runtime`` is anything with a ``shutdown`` event and a ``log(line)``, as app/runtime.py's Runtime. Standard library
only, and here rather than in app/runtime.py: core/maintenance.py runs one, and app/runtime.py imports modules
that start them."""
from __future__ import annotations

import queue
import threading
import time


def supervised(runtime, name, target, *args):
    """Start the daemon thread ``name`` that calls ``target(*args)`` until ``runtime.shutdown``, again 5 s after each
    return or failure (logged as "worker <name> failed: <type>; restarting"). The thread."""
    def run():
        while not runtime.shutdown.is_set():
            try:
                target(*args)
            except Exception as exc:  # noqa: BLE001
                runtime.log(f'worker {name} failed: {type(exc).__name__}; restarting')
            if runtime.shutdown.wait(5):
                break
    thread = threading.Thread(target=run, name=name, daemon=True)
    thread.start()
    return thread


def every(runtime, seconds, *steps, args=(), isolate=""):
    """Until ``runtime.shutdown``: call each of ``steps`` with ``args``, then wait ``seconds``. A step that raises
    ends the loop, unless ``isolate`` names it: then the failure is logged as "<isolate> step <module>.<name>
    failed: <type>" and the next step runs."""
    while not runtime.shutdown.is_set():
        for step in steps:
            try:
                step(*args)
            except Exception as exc:
                if not isolate:
                    raise
                runtime.log(f"{isolate} step {step.__module__}.{step.__name__} failed: {type(exc).__name__}")
        runtime.shutdown.wait(seconds)


class Stuck(Exception):
    """A step that did not end within its time."""


class Worker:
    """A thread that runs the steps it is handed, one at a time. A step stuck in a system call is left to it: the caller hands the
    next steps to a new Worker, and this thread ends when the stuck step does."""

    def __init__(self, name) -> None:
        self.steps, self.ends = queue.Queue(), queue.Queue()
        self.thread = threading.Thread(target=self.run, name=name, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while True:
            step = self.steps.get()
            if step is None:
                return
            try:
                self.ends.put((step(), None))
            except Exception as exc:  # noqa: BLE001 - raised in the caller's thread
                self.ends.put((None, exc))

    def call(self, step, seconds, moved=None):
        """``step``'s value (its exception is raised here). Stuck when it has not ended ``seconds`` after it began, or, with ``moved`` (the
        monotonic time of the step's last progress), ``seconds`` after its last progress: a long first push that keeps sending is not stuck."""
        self.steps.put(step)
        last = time.monotonic()
        while True:
            try:
                value, exc = self.ends.get(timeout=max(0.0, last + seconds - time.monotonic()))
                break
            except queue.Empty:
                newer = moved() if moved is not None else 0.0
                if newer <= last:
                    self.steps.put(None)
                    raise Stuck from None
                last = newer
        if exc is not None:
            raise exc
        return value
