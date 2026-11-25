"""A Claude command that waits for a free seat at its gateway before it starts the CLI (backends/claude/process.py
QUEUE_LINE): the turn waits for it instead of failing its initialize, and the card says it waits."""
from __future__ import annotations

import dataclasses
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

from support import make_job, slow
from support.fake_backends import CLAUDE_JSONL, RUN, codex_context
from support.world import build_claude_app

from covey.backends.claude import process as claude_process
from covey.backends.claude.bridge import ClaudeBackend
from covey.backends.claude.process import ClaudeProcess
from covey.core.harness import RunCallbacks, RunInputs, RunRequest


# A Claude command as a gateway's wrapper may be: ``queued <seconds> <every> <cli> <scenario>`` says it waits for
# <seconds>, a line every <every> seconds, then starts the CLI (the fixture); ``quiet`` says it waits once and then
# nothing; ``silent`` says nothing. The input sent meanwhile waits in its stdin for the CLI.
WRAPPER = r'''
import json, os, sys, time
mode = sys.argv[1]
def say(**fields):
    sys.stderr.write("covey queue: " + json.dumps(fields) + "\n")
    sys.stderr.flush()
if mode == "queued":
    seconds, every, cli, scenario = float(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]
    sys.stderr.write("gateway-a queued: 3 running (cap 3)\n")
    began = time.monotonic()
    while time.monotonic() - began < seconds:
        say(ahead=1 if time.monotonic() - began < seconds / 2 else 0, running=3, cap=3, limit=3600, name="gateway-a")
        time.sleep(every)
    say(admitted=True)
    time.sleep(0.3)  # So the test hears it before the CLI answers; a turn ends the wait either way (QueueNotes.end).
    os.execv(sys.executable, [sys.executable, cli, scenario])
if mode in ("quiet", "gives-up"):
    say(ahead=0, running=3, cap=3, limit=3600)
if mode == "gives-up":
    time.sleep(0.3)
    sys.stderr.write("gateway-a gave up waiting\n")
    sys.exit(75)
time.sleep(60)
'''


class QueueLineTests(unittest.TestCase):
    def test_a_queue_line_keeps_only_the_fields_it_may_say(self):
        from covey.backends.claude.process import QUEUE_NAME_CHARS, queue_line
        line = 'covey queue: {"ahead": 2, "running": 3, "cap": 3, "limit": 3600, "name": "  gateway-a  ", "token": "x"}'
        self.assertEqual(queue_line(line), {"ahead": 2, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a"})
        self.assertEqual(queue_line('covey queue: {"admitted": true, "ahead": 1}'), {"admitted": True})
        self.assertEqual(queue_line('covey queue: {"ahead": "1", "running": -1, "cap": true, "limit": 0}'), {})
        self.assertEqual(len(queue_line('covey queue: {"name": "%s"}' % ("n" * 100))["name"]), QUEUE_NAME_CHARS)
        for other in ("covey queue: not json", "covey queue: [1]", "gateway-a queued: 3 running", ""):
            self.assertIsNone(queue_line(other), other)


class InitializeDeadlineTests(unittest.TestCase):
    def test_the_wait_lasts_while_the_command_says_it_waits_but_not_past_its_limit(self):
        from covey.backends.claude.process import (INITIALIZE_SECONDS, QUEUE_LIMIT, QUEUE_SILENCE,
                                                   initialize_deadline)
        start = 1000.0
        first = start + INITIALIZE_SECONDS
        self.assertEqual(initialize_deadline(start, first, None), first)  # A command that says nothing: as before.
        queued = {"ahead": 0, "running": 3, "cap": 3, "limit": 3600}
        self.assertEqual(initialize_deadline(start, first, (queued, start + 500)), start + 500 + QUEUE_SILENCE)
        # Never past its limit and the CLI's own start; never earlier than it was.
        self.assertEqual(initialize_deadline(start, first, (queued, start + 3599)), start + 3599 + QUEUE_SILENCE)
        self.assertEqual(initialize_deadline(start, first, (queued, start + 3610)), start + 3600 + INITIALIZE_SECONDS)
        self.assertEqual(initialize_deadline(start, start + 9999, (queued, start + 1)), start + 9999)
        endless = {"limit": 10 ** 9}
        self.assertEqual(initialize_deadline(start, first, (endless, start + 10 ** 8)),
                         start + QUEUE_LIMIT + INITIALIZE_SECONDS)
        self.assertEqual(initialize_deadline(start, first, ({}, start + 10 ** 8)), start + QUEUE_LIMIT + INITIALIZE_SECONDS)
        # Its turn came: the CLI has INITIALIZE_SECONDS from then.
        self.assertEqual(initialize_deadline(start, start + 700, ({"admitted": True}, start + 690)),
                         start + 690 + INITIALIZE_SECONDS)


class QueuedProcessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wrapper = self.root / "wrapper.py"
        self.wrapper.write_text(WRAPPER)
        self.ctx = dataclasses.replace(codex_context(self.root, "stream-json"), workdir=self.root, timeout=20)
        # The test's own seconds: 1 s for the CLI's answer and for the command's silence instead of 30.
        for name in ("INITIALIZE_SECONDS", "QUEUE_SILENCE"):
            patch = mock.patch.object(claude_process, name, 1, create=True)
            patch.start()
            self.addCleanup(patch.stop)

    def start(self, *args):
        process = ClaudeProcess([sys.executable, str(self.wrapper), *args], self.ctx, dict(os.environ))
        self.addCleanup(process.close)
        return process

    def test_a_command_that_waits_for_a_seat_is_waited_for_and_its_cli_then_answers(self):
        process = self.start("queued", "2.5", "0.2", str(CLAUDE_JSONL), "success")
        said = []
        began = time.monotonic()
        data = process.initialize(on_queue=said.append)
        self.assertGreater(time.monotonic() - began, 2)  # Twice the initialize seconds, and it did not fail.
        self.assertEqual(data["models"][0]["value"], "fixture-model")
        self.assertEqual(said[0], {"ahead": 1, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a"})
        self.assertIn({"ahead": 0, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a"}, said)
        self.assertEqual(said[-1], {"admitted": True})
        self.assertEqual(len(said), 3)  # Only what changed, not every line.
        # The queue's lines stay out of the failure log's stderr; the command's own words stay in it.
        self.assertEqual(list(process.stderr_tail), ["gateway-a queued: 3 running (cap 3)"])

    def test_a_queue_that_goes_quiet_fails_as_a_queue_timeout_soon_after(self):
        process = self.start("quiet")
        began = time.monotonic()
        with self.assertRaisesRegex(RuntimeError, "queue went quiet"):
            process.initialize()
        self.assertLess(time.monotonic() - began, 8)

    def test_a_command_that_gives_up_its_wait_fails_as_a_queue_timeout(self):
        process = self.start("gives-up")
        with self.assertRaisesRegex(RuntimeError, "queue went quiet or past its limit"):
            process.initialize()
        process.close()
        self.assertEqual(list(process.stderr_tail), ["gateway-a gave up waiting"])

    def test_a_command_that_says_nothing_still_fails_after_the_initialize_seconds(self):
        process = self.start("silent")
        with self.assertRaisesRegex(RuntimeError, "Claude initialization timed out"):
            process.initialize()

    @slow("waits out the real 30 s initialize")
    def test_a_turn_queued_past_thirty_seconds_still_starts(self):
        # 2026-11-25 17:24-17:31: each turn the gateway's wrapper held in its queue failed 30 s after it started
        # (initialize_timeout, exit 143) though the queue would have waited 60 minutes. Real constants here.
        mock.patch.stopall()
        self.ctx = dataclasses.replace(self.ctx, timeout=120)
        process = self.start("queued", "36", "5", str(CLAUDE_JSONL), "success")
        self.assertEqual(process.initialize()["models"][0]["value"], "fixture-model")


class QueuedTurnTests(unittest.TestCase):
    def test_a_turn_says_it_waits_then_that_its_wait_ended_and_completes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "wrapper.py").write_text(WRAPPER)
            ctx = dataclasses.replace(codex_context(root, "stream-json"), timeout=20, options={"transport": "stream-json"},
                                      backend_cmd=[sys.executable, str(root / "wrapper.py"), "queued", "2", "0.2",
                                                   str(CLAUDE_JSONL), "success"])
            events = []
            with mock.patch.object(claude_process, "INITIALIZE_SECONDS", 1, create=True):
                answer = ClaudeBackend().run(RunRequest(ctx, "prompt", callbacks=RunCallbacks(
                    event=lambda kind, data, control: events.append((kind, data))),
                    inputs=RunInputs(threading.Event(), run_id=RUN)))
        self.assertFalse(answer.is_error, events)
        self.assertEqual(answer.public_reply.text, "Complete answer")
        notes = [data for kind, data in events if kind == "progress_note" and data["id"] == "backend-queue"]
        self.assertEqual(notes[0]["text"], "gateway-a 排队等空位，前面还有 1 个")
        self.assertEqual({k: v for k, v in notes[0]["queue"].items() if k != "since"},
                         {"ahead": 1, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a"})
        self.assertAlmostEqual(notes[0]["queue"]["since"] / 1000, time.time(), delta=30)
        self.assertEqual(notes[-1], {"id": "backend-queue", "text": "排队结束，开始执行"})
        self.assertFalse([data for kind, data in events if kind == "backend_failure"])


class QueueStatusTests(unittest.TestCase):
    def setUp(self):
        self.app = build_claude_app()
        self.app.cards.queue_trace = mock.Mock()
        self.ctx = SimpleNamespace(topic_id="topic", state_dir=Path("unused-test-state"))
        self.job = make_job(progress=SimpleNamespace(card_id="card_test"))

    def emit(self, kind, data):
        self.app.interaction.structured_harness_event(self.ctx, self.job, kind, data, None)

    def test_the_wait_takes_the_status_line_until_the_main_task_moves_and_is_not_its_first_output(self):
        from covey.core.protocol import queue_note
        self.emit("progress_note", queue_note({"ahead": 1, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a",
                                               "token": "x"}, 5000))
        self.assertEqual(self.job.backend_queue, {"ahead": 1, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a",
                                                  "since": 5000})
        self.assertNotIn("first_output", self.job.timings)
        self.assertEqual(self.job.tool_trace.steps["backend-queue"]["detail"], "gateway-a 排队等空位，前面还有 1 个")
        # A sub-task's work leaves it; the end of the wait, or the main task's own work, ends it.
        self.emit("tool", {"id": "t", "name": "bash", "status": "running", "started_at": 10, "child_id": "sub"})
        self.assertEqual(self.job.backend_queue["ahead"], 1)
        self.emit("progress_note", queue_note({"admitted": True}, 5000))
        self.assertEqual(self.job.backend_queue, {})
        self.assertEqual(self.job.tool_trace.steps["backend-queue"]["detail"], "排队结束，开始执行")
        self.emit("progress_note", queue_note({"ahead": 0}, 5000))
        self.emit("tool", {"id": "m", "name": "bash", "status": "running", "started_at": 11})
        self.assertEqual(self.job.backend_queue, {})

    def test_the_status_line_says_it_waits_for_a_seat_and_is_never_stuck_for_it(self):
        from covey.core.longtask import TaskMonitor
        with tempfile.TemporaryDirectory() as folder:
            job = make_job(tool_trace=object(), backend_queue={
                "ahead": 2, "running": 3, "cap": 3, "limit": 3600, "name": "gateway-a",
                "since": (time.time() - 125) * 1000})
            rendered, saved = [], {}
            monitor = TaskMonitor(job, Path(folder) / "cp.json", rendered.append, saved.update,
                                  lambda *a: None, lambda *a: None, lambda: None)
            monitor.tick()
            first, now, stop = rendered[-1].split("\n")
            self.assertTrue(first.startswith("排队 · 已运行 "), first)  # The card colours 排队 as queued.
            self.assertIn(" · 已等 2 分 ", first)
            self.assertEqual(now, "现在：等空位：gateway-a 3/3 路在跑，前面还有 2 个，轮到就开始（最长等 60 分钟）。")
            self.assertIn("停止按钮", stop)
            self.assertFalse(monitor.progress(time.time(), 10 ** 6, 10 ** 6, bool(job.backend_queue))["maybe_stuck"])
            job.backend_queue = {"ahead": 0}
            monitor.tick()
            self.assertIn("现在：等空位：暂无空位，前面还有 0 个，轮到就开始。", rendered[-1])
            job.backend_queue = {}
            monitor.tick()
            self.assertNotIn("排队", rendered[-1])


if __name__ == "__main__":
    unittest.main()
