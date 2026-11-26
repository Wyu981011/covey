"""A resumed topic turn whose previous turn left the context high in its window is told the figures, to update its
checkpoint first and to go on with the turn as usual (app/prompts.py context_high, app/runs.py _context_note)."""
from __future__ import annotations

import dataclasses
import unittest
from pathlib import Path

from support.world import UnifiedCase
from test_auto_retry import Failing

from covey.app.prompts import CONTEXT_HIGH, context_high
from covey.core.jobs import find_job_record, upsert_job_record


class ContextHighTest(unittest.TestCase):
    def test_sixty_percent_of_a_window_up_to_room_short_of_it(self):
        # Windows of up to 75 万: from 60 % on, as before (Codex's 25.84 万, a 20 万 one).
        self.assertTrue(context_high({"context_tokens": 155_040, "context_window": 258_400}))
        self.assertEqual(context_high({"context_tokens": 155_039, "context_window": 258_400}), "")
        self.assertTrue(context_high({"context_tokens": 120_000, "context_window": 200_000}))
        # A 1M window: from 30 万 short of it, not from 60 万 (T774 was told at 82.7 万 of 100 万 that it was full).
        self.assertEqual(context_high({"context_tokens": 600_000, "context_window": 1_000_000}), "")
        self.assertEqual(context_high({"context_tokens": 699_999, "context_window": 1_000_000}), "")
        self.assertTrue(context_high({"context_tokens": 700_000, "context_window": 1_000_000}))

    def test_the_line_has_the_figures_and_says_go_on(self):
        line = context_high({"context_tokens": 827_000, "context_window": 1_000_000})
        self.assertEqual(line, CONTEXT_HIGH.format(used="82.7 万", window="100 万"))
        self.assertIn("上一轮结束时上下文 82.7 万 / 100 万 token", line)
        for words in ("会话照常接着用", "自动压缩", "completed 和 next_step", "照常做完这一轮", "不要因为上下文高就停下",
                      "提前收尾", "等新会话", "不要说上下文满了"):
            self.assertIn(words, line)
        self.assertNotIn("快满了", line)

    def test_no_window_or_no_count_is_no_line(self):
        for record in (None, {}, {"context_tokens": 900_000}, {"context_window": 1_000_000},
                       {"context_tokens": 900_000, "context_window": 0}, {"context_tokens": "9", "context_window": 10},
                       {"context_tokens": 9.5, "context_window": 10}):
            self.assertEqual(context_high(record), "", record)


class WiredTest(UnifiedCase):
    def setUp(self):
        super().setUp()
        self.claude = self.app.apps["claude"]
        self.claude.harness.backend = Failing()

    def started(self, **fields):
        """A topic's first task ended with ``fields`` on its record: (its context, a next job of the topic)."""
        self.receive("task", "initial")
        _, ctx = self.route("task")
        self.app.topics.select_harness(ctx, "chat", "claude")
        app, ctx = self.route("task")
        app.submission.start_workspace(ctx, "chat", ctx.workspace_name)
        job = self.app.runtime.jobs.queue.get_nowait()
        app.process_reply_job(job, app.harness.context)
        record = find_job_record(self.ctx.state_dir, job.message_id)
        upsert_job_record(self.ctx.state_dir, "om_done", topic_id=record["topic_id"], chat_id=record["chat_id"], job_id=2,
                          kind="chat", backend=record["backend"], status="done", created_at="2099-01-01T00:00:00Z",
                          updated_at="2099-01-01T00:00:00Z", **fields)
        nxt = dataclasses.replace(job, job_id=3, message_id="next", recovery_context=None)
        nxt.checkpoint_path = str(Path(self.root) / "cp.json")
        return ctx, nxt

    def test_a_resumed_turn_after_a_high_context_is_told_first(self):
        ctx, job = self.started(context_tokens=827_000, context_window=1_000_000)
        note = self.claude.runs._context_note(ctx, job, "sid")
        line = CONTEXT_HIGH.format(used="82.7 万", window="100 万")
        self.assertEqual(note, "\n\n" + line)
        self.assertIn(line, self.claude.runs._prompt(type("L", (), {"ctx": ctx, "rules_session": True})(), job, "sid")[0])

    def test_sixty_percent_of_a_large_window_gets_no_line(self):
        ctx, job = self.started(context_tokens=650_000, context_window=1_000_000)
        self.assertEqual(self.claude.runs._context_note(ctx, job, "sid"), "")

    def test_a_new_session_gets_no_line(self):
        ctx, job = self.started(context_tokens=700_000, context_window=1_000_000)
        self.assertEqual(self.claude.runs._context_note(ctx, job, None), "")

    def test_a_small_context_gets_no_line(self):
        ctx, job = self.started(context_tokens=100_000, context_window=1_000_000)
        self.assertEqual(self.claude.runs._context_note(ctx, job, "sid"), "")

    def test_an_unknown_window_gets_no_line(self):
        ctx, job = self.started(context_tokens=900_000)
        self.assertEqual(self.claude.runs._context_note(ctx, job, "sid"), "")

    def test_the_butler_gets_none(self):
        from unittest import mock
        ctx, job = self.started(context_tokens=700_000, context_window=1_000_000)
        with mock.patch("covey.app.runs.is_butler_topic", return_value=True):
            self.assertEqual(self.claude.runs._context_note(ctx, job, "sid"), "")


if __name__ == "__main__":
    unittest.main()
