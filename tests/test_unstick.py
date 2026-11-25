"""app/unstick.py (T784): a butler's turn whose model request hangs no longer holds up the owner's next words. It says
under each waiting message which turn it waits for, then stops the hung turn so they run; the stop is the Bridge's,
not the owner's, so what waited is queued again and the turn offers 检查并继续."""
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from covey.app import unstick
from covey.app.worker import _turn_from_exception
from covey.core import butler as contract
from covey.core.deliveries import delivery_path, save_delivery
from covey.core.failure import failure_code, failure_view
from covey.core.harness import JobCancelled
from covey.core.jobs import job_key


def facts(quiet, now, **extra):
    progress = {"last_activity_at": now - quiet, **extra.pop("progress", {})}
    return SimpleNamespace(**{"progress": progress, "waiting": False, "retry": None, "queue": None, "alive": True,
                              **extra})


class UnstickTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.state = Path(folder.name)
        self.ctx = SimpleNamespace(state_dir=self.state)
        self.job = SimpleNamespace(job_id=41, message_id="om_first", topic_id="butler-topic", chat_id="oc_owner",
                                   user_text="帮我查一下昨天的训练", cancel_event=threading.Event(),
                                   timings={"submitted": time.time() - 900, "backend_requested": time.time() - 900})
        self.lines = []
        self.reply = lambda ctx, chat, mid, text: self.lines.append((chat, mid, text))
        patcher = mock.patch.object(unstick, "traits_of", return_value=contract.BUTLER)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.logs = []

    def supplement(self, mid, status="sent"):
        path = delivery_path(self.state, self.job.topic_id, mid)
        save_delivery(path, {"mid": mid, "status": status, "job_key": job_key(self.job.message_id, self.job.job_id),
                             "job_id": self.job.job_id, "topic_id": self.job.topic_id})

    def check(self, quiet, now, **extra):
        return unstick.check(self.ctx, self.job, facts(quiet, now, **extra), reply=self.reply, log=self.logs.append,
                             now=now)

    def test_a_quiet_turn_with_the_owners_words_waiting_is_told_then_stopped(self):
        now = time.time()
        self.supplement("om_second")
        self.assertFalse(self.check(60, now))  # Quiet one minute: nothing yet.
        self.assertEqual(self.lines, [])
        self.assertFalse(self.check(unstick.NOTICE_SECONDS + 5, now))
        self.assertEqual(len(self.lines), 1)
        chat, mid, text = self.lines[0]
        self.assertEqual((chat, mid), ("oc_owner", "om_second"))
        self.assertIn("这句话在等前一轮 #41", text)
        self.assertIn("「帮我查一下昨天的训练」", text)
        self.assertIn("到 10 分钟仍没动静会停下它，先跑这句", text)
        self.assertFalse(self.check(unstick.NOTICE_SECONDS + 20, now + 10))  # Within LOOK_EVERY: not looked at.
        self.assertFalse(self.job.cancel_event.is_set())
        self.assertTrue(self.check(unstick.hung_seconds() + 1, now + unstick.LOOK_EVERY + 1))
        self.assertTrue(self.job.cancel_event.is_set())
        self.assertEqual(self.job.hung_stop["waiting"], 1)
        self.assertEqual(len(self.lines), 1)  # Told once a message.
        self.assertTrue(any(line.startswith("hung turn stopped job=#41") for line in self.logs))

    def test_a_queued_message_of_the_same_topic_waits_too(self):
        (self.state / "queued").mkdir()
        (self.state / "queued" / "x.json").write_text(json.dumps(
            {"schema_version": 1, "harness": "claude", "job": {"job_id": 42, "message_id": "om_q", "topic_id": "butler-topic",
                                                                "chat_id": "oc_owner"}}))
        (self.state / "queued" / "y.json").write_text(json.dumps(
            {"schema_version": 1, "harness": "claude", "job": {"job_id": 43, "message_id": "om_other", "topic_id": "t2"}}))
        self.assertEqual([item["message_id"] for item in unstick.waiting_behind(self.state, self.job)], ["om_q"])
        self.assertTrue(self.check(unstick.hung_seconds() + 1, time.time()))

    def test_nothing_waits_or_it_is_not_hung_or_not_the_butlers_nothing_happens(self):
        now = time.time()
        self.assertFalse(self.check(3600, now))  # Nothing waits behind it.
        self.supplement("om_read", status="read")
        self.assertFalse(self.check(3600, now + 100))
        self.supplement("om_second")
        for extra in ({"waiting": True}, {"retry": {"attempt": 2}}, {"queue": {"ahead": 1}}, {"alive": False},
                      {"progress": {"command": {"since": now - 3600}}}):
            self.job.hung_looked = 0.0
            self.assertFalse(unstick.check(self.ctx, self.job, facts(3600, now, **extra), reply=self.reply, now=now),
                             extra)
        self.assertFalse(self.job.cancel_event.is_set())
        with mock.patch.object(unstick, "traits_of", return_value=contract.TOPIC):
            self.job.hung_looked = 0.0
            self.assertFalse(self.check(3600, now + 200))
        self.assertEqual(self.lines, [])

    def test_off_with_zero_minutes_it_only_says_what_waits(self):
        self.supplement("om_second")
        with mock.patch.dict("os.environ", {unstick.SWITCH: "0"}):
            self.assertEqual(unstick.hung_seconds(), 0)
            self.assertFalse(self.check(7200, time.time()))
        self.assertFalse(self.job.cancel_event.is_set())
        self.assertEqual(len(self.lines), 1)
        self.assertNotIn("停下", self.lines[0][2])
        with mock.patch.dict("os.environ", {unstick.SWITCH: "abc"}):
            self.assertEqual(unstick.hung_seconds(), unstick.HUNG_MINUTES * 60)

    def test_the_stopped_turn_fails_with_its_reason_never_as_the_owners_stop(self):
        job = SimpleNamespace(job_id=41, topic_id="", chat_id="", cancel_event=threading.Event(), interrupted=False,
                              hung_stop={"quiet": 725, "waiting": 2})
        job.cancel_event.set()
        found = _turn_from_exception(JobCancelled("Claude task cancelled"), job, False)
        self.assertEqual(found["status"], "failed")
        self.assertEqual(found["status_message"], unstick.HUNG_STATUS)
        self.assertIn("（12 分钟没有动静），好让你之后发的 2 条消息先跑", found["final_text"])
        record = {"status": "failed", "status_message": found["status_message"], "topic_id": "t"}
        self.assertEqual(failure_code(record), "request_hung")
        self.assertIn("模型请求长时间没有回应", failure_view(record)["title"])
        del job.hung_stop
        self.assertEqual(_turn_from_exception(JobCancelled("x"), job, False)["status"], "cancelled")  # The owner's.

    def test_the_hung_turns_unread_supplements_are_queued_again(self):
        from covey.app.steering import Steering
        steering = Steering.__new__(Steering)
        steering.runtime = SimpleNamespace(in_runner=True)
        self.supplement("om_second")
        record = json.loads(delivery_path(self.state, self.job.topic_id, "om_second").read_text())
        record.update(requeue={"text": "第二句"}, target_ended=True)  # As the turn's end (end_unread) leaves it.
        save_delivery(delivery_path(self.state, self.job.topic_id, "om_second"), record)
        self.job.cancel_event.set()
        ctx = SimpleNamespace(state_dir=self.state)
        self.assertEqual(steering.requeue_lost(ctx, self.job, [record]), [])  # The owner's stop: as before.
        self.job.hung_stop = {"quiet": 700, "waiting": 1}
        marked = steering.requeue_lost(ctx, self.job, [record])
        self.assertEqual([one["mid"] for one in marked], ["om_second"])


if __name__ == "__main__":
    unittest.main()
