"""主人消息的去向 (core/inbound_ledger.py, bin/covey_inbound.py): where a message the owner sent went, read from the job
records, the supplements' delivery records and the small entry each message keeps in inbound-messages/; the notes written
as it is decided (never raising), and the owner told of a message taken in and never handled."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from support import REPO
from support.records import state_dir, write_job, write_topic

from covey.app.access import Access
from covey.app.card_routing import CardRouting
from covey.core import deliveries, inbound_ledger as ledger

CHAT, MESSAGE = "oc_owner_dm", "om_first"
EVENT = {"message_id": MESSAGE, "chat_id": CHAT, "chat_type": "p2p", "content": json.dumps({"text": "帮我看下日志"})}


class Case(unittest.TestCase):
    def setUp(self):
        self.state = state_dir(self)
        write_topic(self.state, topic_id="t1", topic_number=12, chat_id=CHAT, origin={"title": "日志排查"})

    def says(self, message=MESSAGE, **options):
        return ledger.where(self.state, message, **options)


class ReadTest(Case):
    def test_a_message_nothing_is_known_of_says_so(self):
        found = self.says("om_nothing")
        self.assertEqual(found["kind"], "unknown")
        self.assertIn("查不到", found["says"])

    def test_reading_creates_nothing(self):
        self.says()
        ledger.recent(self.state)
        self.assertFalse((self.state / "inbound-messages").exists())
        self.assertFalse((self.state / "jobs").exists())

    def test_a_message_that_became_a_turn_names_its_topic_and_job(self):
        write_job(self.state, MESSAGE, job_id=34, topic_id="t1", chat_id=CHAT, status="running")
        found = self.says()
        self.assertEqual((found["kind"], found["job_id"], found["status"]), ("round", 34, "running"))
        self.assertIn("T12「日志排查」的任务 #34", found["says"])

    def test_a_message_merged_into_a_task_names_that_task(self):
        write_job(self.state, "om_target", job_id=33, topic_id="t1", chat_id=CHAT, status="running")
        write_job(self.state, MESSAGE, job_id=34, topic_id="t1", chat_id=CHAT, status="cancelled",
                  status_message="已并入上一任务 #33，开始后会一并处理；本条不再单独执行", merged_into_job_id=33)
        found = self.says()
        self.assertEqual((found["kind"], found["into"]), ("merged", 33))
        self.assertIn("没有单独成一轮", found["says"])
        self.assertIn("T12「日志排查」的任务 #33", found["says"])

    def test_a_supplement_to_the_butler_says_how_far_it_got(self):
        ledger.note(self.state, MESSAGE, "supplement", event=EVENT, topic_id="t1", job_id=7)
        deliveries.save_delivery(deliveries.delivery_path(self.state, "t1", MESSAGE), {"status": "read"})
        found = self.says()
        self.assertEqual(found["kind"], "supplement")
        self.assertIn("任务 #7（已读）", found["says"])

    def test_fates_with_no_job_say_why(self):
        for fate, reason, text in (("ignored", "no_text", "不支持的消息类型"), ("refused", "话题已冻结", "话题已冻结"),
                                   ("answer", "", "问题的回答"), ("held_note", "", "暂存"), ("not_queued", "", "没有排上队")):
            message = f"om_{fate}"
            ledger.note(self.state, message, fate, event={**EVENT, "message_id": message}, reason=reason, topic_id="t1")
            self.assertIn(text, self.says(message)["says"], fate)
        self.assertIn("T12", self.says("om_answer")["says"])

    def test_taken_in_and_never_handled_is_lost_after_a_while(self):
        ledger.received(self.state, EVENT)
        self.assertEqual(self.says()["kind"], "pending")
        late = time.time() + ledger.STALE_SECONDS + 1
        self.assertEqual(self.says(now=late)["kind"], "lost")
        self.assertTrue(ledger.lost_before(self.state, MESSAGE, now=late))
        self.assertFalse(ledger.lost_before(self.state, MESSAGE))
        ledger.note(self.state, MESSAGE, "lost")
        self.assertFalse(ledger.lost_before(self.state, MESSAGE, now=late))

    def test_a_turn_found_is_never_lost(self):
        ledger.received(self.state, EVENT)
        write_job(self.state, MESSAGE, job_id=1, topic_id="t1", chat_id=CHAT, status="queued")
        self.assertFalse(ledger.lost_before(self.state, MESSAGE, now=time.time() + 999))

    def test_recent_lists_the_owners_messages_newest_first_and_skips_empty_markers(self):
        (self.state / "inbound-messages").mkdir()
        (self.state / "inbound-messages" / "abc").write_text("")  # A menu click's marker.
        for index, at in enumerate((100, 300, 200)):
            message = f"om_{index}"
            ledger.note(self.state, message, "job", event={**EVENT, "message_id": message}, topic_id="t1", job_id=index)
            path = ledger.marker(self.state, message)
            path.write_text(json.dumps({**json.loads(path.read_text()), "at": at}))
        rows = ledger.recent(self.state, 2)
        self.assertEqual([row["message_id"] for row in rows], ["om_1", "om_2"])
        self.assertEqual(rows[0]["text"], "帮我看下日志")


class WriteTest(Case):
    def test_the_marker_is_the_one_the_duplicate_check_claims(self):
        self.assertEqual(ledger.marker(self.state, MESSAGE).name, hashlib.sha256(MESSAGE.encode()).hexdigest())

    def test_a_note_keeps_what_was_there_and_never_raises(self):
        ledger.received(self.state, EVENT)
        ledger.note(self.state, MESSAGE, "job", topic_id="t1", job_id=3)
        saved = ledger.entry(self.state, MESSAGE)
        self.assertEqual((saved["fate"], saved["job_id"], saved["chat_id"]), ("job", 3, CHAT))
        with mock.patch.object(ledger, "write_json", side_effect=OSError("disk")):
            ledger.note(self.state, MESSAGE, "error")
        ledger.note(None, MESSAGE, "error")
        ledger.note(self.state, "", "error")

    def test_a_long_message_is_cut(self):
        ledger.received(self.state, {**EVENT, "content": "字" * 100})
        self.assertEqual(len(ledger.entry(self.state, MESSAGE)["text"]), ledger.PREVIEW + 1)


class AccessTest(Case):
    def access(self):
        return Access(SimpleNamespace(state_dir=self.state, owner_open_id="ou_me", log=lambda _: None))

    def test_the_owners_ignored_message_is_noted_and_a_strangers_or_unaddressed_one_is_not(self):
        access = self.access()
        access.ignore({**EVENT, "sender_id": "ou_me"}, "empty")
        self.assertEqual(ledger.entry(self.state, MESSAGE)["fate"], "ignored")
        self.assertIn("没有内容", self.says()["says"])
        for other, sender, reason in (("om_a", "ou_me", "not_mentioned"), ("om_b", "ou_other", "empty")):
            access.ignore({**EVENT, "message_id": other, "sender_id": sender}, reason)
            self.assertEqual(ledger.entry(self.state, other), {})


class RoutingTest(Case):
    def test_a_replayed_message_that_was_never_handled_is_told_once_in_its_thread(self):
        sent = []
        messenger = SimpleNamespace(reply=lambda ctx, chat, text, key, voice=None: sent.append((ctx.reply_to_message_id, chat, text, key)))
        routing = CardRouting()
        routing.messenger, routing.voice = messenger, SimpleNamespace(key=lambda tag, ident: f"{tag}:{ident}")
        routing.runtime = SimpleNamespace(log=lambda _: None)
        ctx = SimpleNamespace(state_dir=self.state, reply_to_message_id="")
        routing.tell_lost = CardRouting.tell_lost.__get__(routing)
        with mock.patch("covey.app.card_routing.dataclasses.replace", lambda c, **kw: SimpleNamespace(**{**vars(c), **kw})):
            routing.tell_lost(ctx, EVENT, MESSAGE)
        self.assertEqual(sent[0][:2], (MESSAGE, CHAT))
        self.assertIn("再发一次", sent[0][2])
        self.assertEqual(ledger.entry(self.state, MESSAGE)["fate"], "lost")


class CommandTest(Case):
    def run_cli(self, *args):
        env = {**os.environ, "PYTHONPATH": ""}
        done = subprocess.run([sys.executable, "-B", str(REPO / "bin" / "covey_inbound.py"), *args], capture_output=True,
                              text=True, env=env, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def test_where_and_recent(self):
        write_job(self.state, MESSAGE, job_id=34, topic_id="t1", chat_id=CHAT, status="done")
        ledger.received(self.state, EVENT)
        out = self.run_cli("where", MESSAGE, "--state", str(self.state))
        self.assertIn("T12「日志排查」的任务 #34", out)
        rows = json.loads(self.run_cli("recent", "--state", str(self.state), "--json"))
        self.assertEqual(rows[0]["message_id"], MESSAGE)
        self.assertIn("查不到", self.run_cli("where", "om_none", "--state", str(self.state)))


if __name__ == "__main__":
    unittest.main()
