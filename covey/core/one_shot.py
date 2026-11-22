"""One question to a Harness CLI and nothing else (core/harness.py HarnessCapabilities.ask_once): the process, the JSON
lines it prints and its deadline, shared by backends/codex/judge.py and backends/agy/judge.py.

``run_lines`` starts the command in a process group of its own, writes the question to its standard input from a thread of
its own (a CLI that does not read it yet never holds the caller past the limit) and closes it, and reads its standard
output line by line until the caller's ``done`` says the answer is in: the whole group is killed then (a CLI may take
seconds more to exit after its answer), when the output ends, or when ``limit`` seconds pass. Every failure is an AskFailed
with its reason; its detail is the exit code and the last line of standard error, cut and with anything secret-looking
hidden, never the question. Standard library and core/ only.
"""
from __future__ import annotations

import contextlib
import json
import os
import queue
import signal
import subprocess
import threading
import time

from covey.core.harness import AskFailed
from covey.core.text import cut, redact

STDERR_KEPT = 160


def _read(stream, out: queue.Queue) -> None:
    try:
        for line in stream:
            out.put(line)
    except (OSError, ValueError):
        pass
    finally:
        out.put(None)


def _write(stream, data: bytes) -> None:
    try:
        stream.write(data)
    except (OSError, ValueError):
        pass  # It died, or was killed at the limit: its exit says why.
    finally:
        with contextlib.suppress(OSError, ValueError):
            stream.close()


def kill_group(proc) -> None:
    """SIGKILL to ``proc``'s whole process group (the CLI and whatever it started), then the CLI reaped. The group is
    signalled before the CLI is reaped, so its id is still the group's own even when the CLI has exited already."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except OSError:
        with contextlib.suppress(OSError):
            proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def close_pipes(proc, *readers) -> None:
    """The CLI's output pipes closed once their readers are done (the group is gone: they end at once). A reader still
    held (a process outside the group keeps a pipe open) leaves its pipe alone: closing it would wait on that read."""
    for reader in readers:
        reader.join(timeout=1)
    if any(reader.is_alive() for reader in readers):
        return
    for stream in (proc.stdout, proc.stderr):
        with contextlib.suppress(OSError, ValueError):
            stream.close()


def last_stderr_line(text: str, skip=()) -> str:
    """The last line of ``text`` with words in it and none of ``skip`` (a sign-in URL), secrets hidden and cut to
    STDERR_KEPT."""
    lines = [line.strip() for line in str(text or "").splitlines()
             if line.strip() and not any(word in line for word in skip)]
    return cut(redact(lines[-1]), STDERR_KEPT) if lines else ""


def run_lines(argv, stdin_text: str, *, env, cwd, limit: float, done, skip=()) -> list:
    """The JSON objects ``argv`` printed (one per line; other lines are skipped) up to the one ``done(row)`` is true for.
    AskFailed("spawn_failed") when it does not start, ("timeout") past ``limit`` seconds, ("exit_nonzero", "code=N …")
    when the output ends without ``done`` and the exit code is not 0 (``skip``: words of a stderr line never shown); with
    code 0 the rows it printed (``done`` never said yes: the caller decides). The process group is always gone when this
    returns."""
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
                                cwd=cwd, start_new_session=True)
    except OSError as exc:
        raise AskFailed("spawn_failed", type(exc).__name__) from None
    lines: queue.Queue = queue.Queue()
    errors: list = []
    out_reader = threading.Thread(target=_read, args=(proc.stdout, lines), name="one-shot-out", daemon=True)
    out_reader.start()
    err_reader = threading.Thread(target=lambda: errors.append(proc.stderr.read()), name="one-shot-err", daemon=True)
    err_reader.start()
    threading.Thread(target=_write, args=(proc.stdin, stdin_text.encode()), name="one-shot-in", daemon=True).start()
    deadline = time.monotonic() + max(0.1, limit)
    rows = []
    try:
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                raise AskFailed("timeout")
            try:
                line = lines.get(timeout=left)
            except queue.Empty:
                raise AskFailed("timeout") from None
            if line is None:
                break
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if isinstance(row, dict):
                rows.append(row)
                if done(row):
                    return rows
    finally:
        kill_group(proc)
        close_pipes(proc, out_reader, err_reader)
    code = proc.returncode
    if code not in (0, None) and code != -signal.SIGKILL:
        said = last_stderr_line(errors[0].decode("utf-8", "replace") if errors and errors[0] else "", skip)
        raise AskFailed("exit_nonzero", f"code={code}" + (f" {said}" if said else ""))
    return rows
