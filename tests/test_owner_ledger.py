"""等主人的账 (app/owner_ledger.py, core/owner_ledger.py; docs/architecture.md 等主人的账): one ledger every reader counts from,
each thing once with the card it is opened on; a question whose card never went is on it without a card and counted
nowhere until 对账 sends its card again, each try counted first and its outcome after, at most TRIES; the 诊断 and
covey_ledger.py say how many tries went out (the owner, 2026-11-25: 结论、要我定的、停住了的都要在私聊里有张卡, 补发次数可查)."""
from __future__ import annotations

import io
import json
import os
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.records import state_dir, write_job, write_topic

from covey.app import owner_ledger, pins
from covey.app.web_collect import Collector
from covey.cards import doctor_card
from covey.core import owner_ledger as records
from covey.core.state import write_json
from covey.service import doctor, doctor_words

CHAT = "oc_dm"
HOUR, DAY = 3600, 86400


class Case(unittest.TestCase):
    def setUp(self):
        self.state = Path(state_dir(self))
        self.now = time.time()
        self.topics = {}
        self.enterContext(mock.patch.dict(os.environ, {owner_ledger.SWITCH: ""}))

    def topic(self, number):
        topic = f"{number:02d}" * 16
        self.topics[number] = topic
        write_topic(self.state, topic_id=topic, chat_id=CHAT, topic_number=number, harness_id="claude",
                    root_id=f"om_root{number}")
        return topic

    def question(self, number, token, asked, **fields):
        topic = self.topics.get(number) or self.topic(number)
        write_json(self.state / "questions" / f"{token}.json", {
            "token": token, "topic_id": topic, "chat_id": CHAT, "job_id": number, "job_key": f"om_j{number}",
            "status": "pending", "created_at": asked, "question_message_id": f"om_{token}",
            "questions": [{"question": f"问 {token}？"}], **fields})

    def job(self, number, status, **fields):
        topic = self.topics.get(number) or self.topic(number)
        ended = {} if status in ("running", "waiting_user") else {"execution_finished": self.now - 1200}
        return write_job(self.state, f"om_j{number}", chat_id=CHAT, topic_id=topic, job_id=number, status=status,
                         card_message_id=f"om_card{number}", harness_id="claude",
                         timings={"backend_started": self.now - HOUR, **ended}, **fields)

    def ledger(self):
        looked = pins.PinnedTopics(None, None)
        looked.look(self.state, CHAT, self.now)
        return owner_ledger.of(self.state, CHAT, self.now, looked, proposals=True)


class LedgerTest(Case):
    def setUp(self):
        super().setUp()
        now = self.now
        long_ago = now - 30 * DAY  # The board has been on for a while (its rules hold since then).
        write_json(self.state / pins.RECORD, {"schema_version": 1, "chat_id": CHAT, "since": long_ago, "keep_since": long_ago,
                                              "stopped_since": long_ago, "pins": [], "dismissed": {}, "results": {}})
        self.job(1, "waiting_user")
        self.question(1, "q1", now - 300)  # 等你, its card in the topic.
        self.job(2, "failed")  # 停住了, its task card.
        self.job(3, "done")  # 有结果, not seen.
        self.job(4, "waiting_user")
        self.question(4, "q4", now - 600, display_pending=True, question_message_id="")  # Its card never went.
        self.job(5, "waiting_user")
        self.question(5, "q5", now - 600, display_pending=True,
                      triage={"state": "held", "at": now - 600})  # Held for a project's lead: the lead's.
        self.job(6, "waiting_user")
        self.question(6, "q6", now - 30, display_pending=True)  # Asked half a minute ago: its card may be on its way.

    def test_every_thing_once_with_its_card_and_the_missing_one_without(self):
        ledger = self.ledger()
        rows = {entry.key: (entry.state, entry.topic, entry.card) for entry in ledger.entries()}
        self.assertEqual(rows, {
            "question:q1": ("waiting", self.topics[1], "om_q1"),
            "stop:om_j2": ("stopped", self.topics[2], "om_card2"),
            "result:om_j3": ("result", self.topics[3], "om_card3"),
            "question:q4": ("waiting", self.topics[4], ""),
        })
        self.assertEqual([entry.key for entry in ledger.missing()], ["question:q4"])
        # Counted as the cards count: the missing one not until its card is there.
        self.assertEqual(ledger.counts(), {"waiting": 1, "stopped": 1, "stuck": 0, "result": 1})
        self.assertEqual({key: ledger.counts()[key] for key in ("waiting", "stopped", "stuck")}, ledger.asks.counts())

    def test_the_web_page_counts_from_the_ledger(self):
        looked = pins.PinnedTopics(None, None)
        looked.look(self.state, CHAT, self.now)
        self.assertEqual(Collector.asked(self.state, CHAT, self.now, looked).counts(), self.ledger().asks.counts())


class ReconcileTest(Case):
    def setUp(self):
        super().setUp()
        self.job(4, "waiting_user")
        self.question(4, "q4", self.now - 600, display_pending=True, question_message_id="")
        self.logs = []
        self.access = SimpleNamespace(owner_chat=lambda: CHAT, notify_chat=lambda: CHAT, agent_groups=frozenset())
        self.runtime = SimpleNamespace(access=self.access, log=self.logs.append)
        self.env = SimpleNamespace(state_dir=self.state, runtime=self.runtime)
        self.reconcile = owner_ledger.Reconcile(self.runtime, self.env)
        self.show = self.enterContext(mock.patch("covey.app.triage.show", return_value=True))
        self.mend = self.enterContext(mock.patch("covey.app.triage.mend"))

    def record(self):
        return records.read(self.state)

    def test_a_card_that_never_went_is_sent_again_once_and_counted(self):
        self.reconcile.tick(SimpleNamespace(state_dir=self.state), self.now)
        self.show.assert_called_once()
        self.assertEqual(self.show.call_args.args[1]["token"], "q4")
        self.mend.assert_called_once()
        record = self.record()
        self.assertEqual(record["chats"][CHAT]["missing"], ["question:q4"])
        self.assertEqual(record["resends"]["question:q4"]["tries"], 1)
        self.assertIs(record["resends"]["question:q4"]["ok"], True)
        self.assertEqual(record["totals"], {"tries": 1, "ok": 1})
        self.assertTrue(any("owner ledger resend key=question:q4" in line and "ok=True" in line for line in self.logs))
        # Sent: the next 对账 sends nothing, however long after.
        self.reconcile.tick(SimpleNamespace(state_dir=self.state), self.now + 2 * records.RESEND_EVERY)
        self.show.assert_called_once()

    def test_a_card_that_does_not_go_is_tried_at_most_three_times_apart(self):
        self.show.return_value = False
        ctx = SimpleNamespace(state_dir=self.state)
        self.reconcile.tick(ctx, self.now)
        self.reconcile.tick(ctx, self.now + 60)  # Too soon after the first try.
        self.assertEqual(self.show.call_count, 1)
        for step in range(1, 5):
            self.reconcile.tick(ctx, self.now + step * records.RESEND_EVERY)
        self.assertEqual(self.show.call_count, records.TRIES)
        record = self.record()
        self.assertEqual((record["resends"]["question:q4"]["tries"], record["resends"]["question:q4"]["ok"]),
                         (records.TRIES, False))
        self.assertEqual(record["totals"], {"tries": records.TRIES, "failed": records.TRIES})
        self.mend.assert_not_called()

    def test_a_send_that_raised_counts_as_not_sent_with_its_reason(self):
        self.show.side_effect = OSError("disk")
        self.reconcile.tick(SimpleNamespace(state_dir=self.state), self.now)
        found = self.record()["resends"]["question:q4"]
        self.assertEqual((found["ok"], found["why"]), (False, "OSError: disk"))

    def test_what_is_not_the_reconciles_to_send(self):
        cases = {
            "escalated": {"triage": {"state": "escalated", "at": self.now - 600}},  # app/triage.py's sweep sends it.
            "result-first": {"body_delivery_required": True, "body_delivery_confirmed": False},  # The outbox's first.
            "young": {"created_at": self.now - 30},
            "old": {"created_at": self.now - 3 * DAY},
            "held": {"triage": {"state": "held", "at": self.now - 600}},
        }
        for name, fields in cases.items():
            with self.subTest(name):
                self.question(4, "q4", fields.pop("created_at", self.now - 600), display_pending=True,
                              question_message_id="", **fields)
                self.reconcile.tick(SimpleNamespace(state_dir=self.state), self.now)
                self.show.assert_not_called()
        self.job(8, "done")
        self.question(4, "q4", self.now - 600, display_pending=True, question_message_id="", job_key="om_j8")  # Its task ended.
        self.reconcile.tick(SimpleNamespace(state_dir=self.state), self.now)
        self.show.assert_not_called()

    def test_its_thread_unless_switched_off(self):
        self.assertEqual([name for name, _ in self.reconcile.threads()], ["owner-ledger"])
        with mock.patch.dict(os.environ, {owner_ledger.SWITCH: "0"}):
            self.assertEqual(self.reconcile.threads(), ())
        with mock.patch.dict(os.environ, {owner_ledger.SWITCH: "120"}):
            self.assertEqual(owner_ledger.every(), 120)


class DiagnosisTest(Case):
    def test_nothing_before_any_reconcile(self):
        self.assertIsNone(doctor.ledger_row(self.state))
        self.assertEqual(doctor_words.ledger_rows({}), [])

    def test_the_tries_and_what_is_missing_are_said(self):
        entry = records.Entry(records.QUESTION, "q4", "t" * 32, self.now - 600, "", True)
        records.looked(self.state, CHAT, [entry, records.Entry(records.RESULT, "om_j3", "u" * 32, self.now, "om_c")], self.now)
        self.assertTrue(records.trying(self.state, CHAT, entry, self.now))
        records.tried(self.state, entry, False, "卡没发出去")
        self.assertFalse(records.trying(self.state, CHAT, entry, self.now + 60))  # Not due yet: nothing counted.
        found = doctor.ledger_row(self.state)
        self.assertEqual((found["tries"], found["ok"], found["failed"], found["missing"]), (1, 0, 1, ["question:q4"]))
        self.assertEqual(found["counts"]["result"], 1)
        self.assertEqual(found["recent"][0]["why"], "卡没发出去")
        words = [row[1] for row in doctor_words.ledger_rows(found, " --state-dir /s")]
        self.assertTrue(words[0].startswith("等你的事：有结果 1（"), words[0])
        self.assertIn("有 1 张卡没到聊天里，对账会补发", words)
        self.assertIn("对账补发过 1 次卡：发出 0 次，没发出 1 次", words)
        ok, what, detail = doctor_card.ledger_row({"counts": found["counts"], "missing": 1, "tries": 1, "ok": 0,
                                                    "failed": 1, "checked_at": self.now})
        self.assertEqual((ok, what), (None, "有卡没到聊天里"))
        self.assertIn("补发过 1 次，发出 0 次", detail)

    def test_the_command_says_the_record_and_now(self):
        self.job(4, "waiting_user")
        self.question(4, "q4", self.now - 600, display_pending=True, question_message_id="")
        write_json(self.state / "owner-chat.json", {"chat_id": CHAT})
        out = io.StringIO()
        with redirect_stdout(out):
            owner_ledger.main(["--state-dir", str(self.state), "--json"])
        said = json.loads(out.getvalue())
        self.assertEqual(said["record"]["tries"], 0)
        self.assertEqual([row["key"] for row in said["now"][CHAT]["entries"]], ["question:q4"])
        out = io.StringIO()
        with redirect_stdout(out):
            owner_ledger.main(["--state-dir", str(self.state)])
        self.assertIn("还没对过账", out.getvalue())
        self.assertIn("等你 · T4 · question:q4（卡没到聊天里）", out.getvalue())


if __name__ == "__main__":
    unittest.main()
