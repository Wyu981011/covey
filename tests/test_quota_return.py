"""The one line when a spent quota that was too far off to wait for is back (app/quota_return.py)."""
from __future__ import annotations

import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import support  # Puts the repository on the path.
from covey.app import quota_return
from covey.core.jobs import upsert_job_record

del support
NOW = 1_800_000_000.0  # 2027-01-15 16:00 in Asia/Shanghai.
RESET = NOW + 8 * 3600
CHAT = "oc_fake_owner_chat"
OUTCOME = SimpleNamespace(status="failed", error_code="quota_exhausted", policy_event=None)


class ReturnTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.state = Path(self.dir.name)
        self.sent, self.logs, self.live, self.chat = [], [], [], CHAT
        self.result = True
        self.send = mock.Mock(side_effect=lambda profile, chat, text, key, **kw: self.sent.append((chat, text, key)) or self.result)
        self.gateway = SimpleNamespace(
            runtime=SimpleNamespace(access=SimpleNamespace(notify_chat=lambda: self.chat), log=self.logs.append,
                                    jobs=SimpleNamespace(topic_jobs=lambda topic, chat: self.live)),
            messenger=SimpleNamespace(send_message=self.send), voice=SimpleNamespace(safe_key=lambda key: key))
        self.ctx = SimpleNamespace(state_dir=self.state, profile="p")
        quota_return._last.clear()
        patch = mock.patch("covey.app.quota_return.quota_sources.enabled", return_value=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(mock.patch.stopall)

    def job(self, number, topic=None, backend="claude", **extra):
        topic = topic or f"topic-{number}"
        upsert_job_record(self.state, f"m{number}:{number}", job_id=number, topic_id=topic, chat_id=CHAT, status="failed", **extra)
        return SimpleNamespace(message_id=f"m{number}", job_id=number, topic_id=topic, chat_id=CHAT, backend=backend,
                               cancel_event=threading.Event(), source="owner")

    def turn(self, reset=RESET, outcome=OUTCOME, **limit):
        return SimpleNamespace(outcome=outcome, verified_delivery=None, limit={"reset_at": reset, **limit} if reset else None)

    def register(self, number, reset=RESET, **kw):
        return quota_return.register(self.ctx, self.job(number, **kw), self.turn(reset), None, now=NOW)

    def look(self, now):
        quota_return._last.clear()
        return quota_return.step(self.gateway, self.ctx, now)

    def test_only_a_spent_quota_further_off_than_the_automatic_retry_waits_is_registered(self):
        self.assertFalse(self.register(1, reset=NOW + 3600))  # That one is retried by itself.
        self.assertFalse(self.register(2, reset=0))
        self.assertFalse(quota_return.register(self.ctx, self.job(3), self.turn(), object(), now=NOW))  # A retry is planned.
        self.assertFalse(quota_return.register(self.ctx, self.job(4), self.turn(outcome=SimpleNamespace(
            status="failed", error_code="rate_limited", policy_event=None)), None, now=NOW))
        self.assertEqual(quota_return.read(self.state), {})
        self.assertTrue(self.register(5))
        self.assertFalse(self.register(5))  # The same topic and reset time: one entry.
        self.assertEqual(len(quota_return.read(self.state)), 1)

    def test_says_one_line_at_the_time_and_only_once_and_survives_a_restart(self):
        self.register(1)
        self.assertEqual(self.look(RESET - 60), "")
        quota_return._last.clear()  # A new Bridge reads the file again.
        text = self.look(RESET + 5)
        [(chat, said, _key)] = self.sent
        self.assertEqual(chat, CHAT)
        self.assertIn("额度用完", said)
        self.assertIn("可以接着做", said)
        self.assertEqual(text, said)
        self.assertEqual(self.look(RESET + 600), "")
        self.assertEqual(len(self.sent), 1)

    def test_the_line_names_the_source_that_ran_out(self):
        gateway = SimpleNamespace(title="Claude 网关")
        with mock.patch("covey.app.quota_return.quota_sources.claude_source", return_value=gateway):
            self.register(1)
        quota_return.register(self.ctx, self.job(2, backend="agy"), self.turn(group="3p"), None, now=NOW)
        quota_return.register(self.ctx, self.job(3, backend="agy"), self.turn(), None, now=NOW)
        quota_return.register(self.ctx, self.job(4, backend="codex"), self.turn(), None, now=NOW)
        sources = sorted(e["source"] for e in quota_return.read(self.state).values())
        self.assertEqual(sources, ["Claude 网关", "agy", "agy Claude/GPT", "codex"])
        self.look(RESET + 5)
        [(_chat, text, _key)] = self.sent
        self.assertIn("Claude 网关额度已恢复（", text)
        self.assertIn(" 停在额度用完，可以接着做。", text)
        self.assertIn("agy Claude/GPT额度已恢复", text)

    def test_two_topics_of_one_source_are_listed_under_it_and_an_old_entry_has_no_source_name(self):
        with mock.patch("covey.app.quota_return.quota_sources.claude_source", return_value=None):
            self.register(1)
            self.register(2, reset=RESET + 30)
        entries = quota_return.read(self.state)
        self.assertEqual({e["source"] for e in entries.values()}, {"Claude"})
        for entry in entries.values():
            del entry["source"]
        quota_return.write(self.state, entries)
        self.look(RESET + 100)
        [(_chat, text, _key)] = self.sent
        self.assertTrue(text.startswith("额度已恢复（"), text)
        self.assertIn("2 个话题", text)

    def test_topics_due_together_are_one_message(self):
        self.register(1)
        self.register(2, reset=RESET + 30)
        self.look(RESET + 100)
        [(_chat, text, _key)] = self.sent
        self.assertIn("2 个话题", text)
        self.assertEqual(text.count("\n- "), 2)

    def test_the_quiet_hours_hold_it_until_morning(self):
        self.register(1)  # The reset is at 00:00 Shanghai time.
        with mock.patch.dict("os.environ", {"COVEY_QUIET_HOURS": "23:00-08:30"}):
            self.assertEqual(self.look(RESET + 10), "")
            self.assertEqual(self.look(RESET + 8 * 3600), "")
            self.assertEqual(self.sent, [])
            self.assertNotEqual(self.look(RESET + 8.6 * 3600), "")
        self.assertEqual(len(self.sent), 1)

    def test_a_newer_task_or_a_retry_the_owner_clicked_says_nothing(self):
        self.register(1)
        self.register(2)
        self.register(3, topic="live")
        upsert_job_record(self.state, "m9:9", job_id=9, topic_id="topic-1", chat_id=CHAT, status="done")
        upsert_job_record(self.state, "m2:2", job_id=2, topic_id="topic-2", chat_id=CHAT, status="failed", retried_by="x")
        self.live = [SimpleNamespace(job_id=4)]
        self.assertEqual(self.look(RESET + 5), "")
        self.assertEqual(self.sent, [])
        self.assertEqual({e["state"] for e in quota_return.read(self.state).values()}, {"dropped"})

    def test_a_send_that_failed_is_tried_again_and_no_chat_waits(self):
        self.register(1)
        self.chat = ""
        self.assertEqual(self.look(RESET + 5), "")
        self.chat, self.result = CHAT, False
        self.assertEqual(self.look(RESET + 10), "")
        self.assertEqual(len(self.sent), 1)
        self.result = True
        self.assertNotEqual(self.look(RESET + 20), "")
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.look(RESET + 30), "")

    def test_a_send_that_raised_is_not_repeated(self):
        self.register(1)
        self.send.side_effect = OSError("boom")
        self.assertEqual(self.look(RESET + 5), "")
        self.send.side_effect = None
        self.assertEqual(self.look(RESET + 10), "")
        self.assertEqual(self.sent, [])


if __name__ == "__main__":
    unittest.main()
