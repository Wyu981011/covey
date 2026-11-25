"""core/storage_watch.py, app/storage_alerts.py and the diagnostics' lines (T784): a write refused for want of space is
kept, told once and said by the doctor; a lock or a record read that hangs has its stack logged once."""
import errno
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from covey.app import storage_alerts
from covey.app.storage_alerts import StorageAlerts, alert_text
from covey.core import locks, loops, storage_watch
from covey.service import doctor_words


def quota_error():
    return OSError(errno.EDQUOT, "Disk quota exceeded", "/absolute/state/jobs/.index.tmp")


class StorageWatchTests(unittest.TestCase):
    def setUp(self):
        storage_watch.reset()
        self.addCleanup(storage_watch.reset)

    def test_a_write_refused_for_want_of_space_is_kept_and_nothing_else_is(self):
        self.assertFalse(storage_watch.note_failure(OSError(errno.EACCES, "Permission denied"), "x"))
        self.assertFalse(storage_watch.note_failure(ValueError("Disk quota exceeded"), "x"))
        self.assertEqual(storage_watch.snapshot(), {})
        self.assertTrue(storage_watch.note_failure(quota_error(), "outbox step a.b"))
        self.assertTrue(storage_watch.note_failure(OSError(errno.ENOSPC, "No space left on device"), "outbox step a.b"))
        full = storage_watch.snapshot()["full"]
        self.assertEqual((full["error"], full["where"], full["count"]), ("No space left on device", "outbox step a.b", 2))
        self.assertEqual(storage_watch.snapshot(now=time.time() + storage_watch.RECENT + 1), {})

    def test_a_loop_step_says_an_oserrors_words_and_keeps_a_full_disk(self):
        """The log said "save_record_indexes failed: OSError" 130 times a day, never why."""
        lines, calls = [], []
        runtime = SimpleNamespace(shutdown=threading.Event(), log=lines.append)

        def step():
            calls.append(1)
            runtime.shutdown.set()
            raise quota_error()

        loops.every(runtime, 0, step, isolate="outbox")
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].endswith("step.<locals>.step failed: OSError: Disk quota exceeded") or
                        lines[0].endswith("failed: OSError: Disk quota exceeded"), lines[0])
        self.assertNotIn("/absolute/state", lines[0])  # The words, not the path.
        self.assertEqual(storage_watch.snapshot()["full"]["directory"], "/absolute/state/jobs")
        self.assertEqual(storage_watch.reason(RuntimeError("secret words")), "RuntimeError")  # Others as before.

    def test_a_step_past_its_time_is_logged_once_with_its_stack_and_how_long_it_took_in_the_end(self):
        lines = []
        with mock.patch.object(storage_watch, "_log", lines.append):
            step = storage_watch.watched("读记录 x.json").enter()
            started = storage_watch._inflight[id(step)][2]
            self.assertEqual(storage_watch.look(now=started + 1.0), [])  # Not yet.
            rows = storage_watch.look(now=started + storage_watch.SLOW_SECONDS + 0.5)
            self.assertEqual(len(rows), 1)
            self.assertEqual(storage_watch.look(now=started + 10), [])  # Once.
            step.leave()
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("slow 读记录 x.json: 2.5 s so far, at "), lines[0])
        self.assertIn("test_storage_watch.py", lines[0])  # The waiting thread's own stack.
        slow = storage_watch.snapshot()["slow"]
        self.assertEqual((slow[0]["what"], slow[0]["ended"]), ("读记录 x.json", True))
        self.assertEqual(storage_watch._inflight, {})

    def test_a_held_lock_is_watched_and_reentry_and_timeouts_behave_as_an_rlock(self):
        lock = locks.WatchedRLock("TEST")
        with lock:
            self.assertTrue(lock._is_owned())
            held = [entry[0] for entry in storage_watch._inflight.values()]
            self.assertEqual(held, ["持锁 TEST"])
            with lock:  # Reentrant: still the one hold.
                self.assertEqual(len(storage_watch._inflight), 1)
            self.assertEqual(len(storage_watch._inflight), 1)
            other = []
            thread = threading.Thread(target=lambda: other.append(lock.acquire(timeout=0.05)))
            thread.start()
            thread.join(5)
            self.assertEqual(other, [False])
        self.assertFalse(lock._is_owned())
        self.assertEqual(storage_watch._inflight, {})
        self.assertTrue(lock.acquire(blocking=False))
        lock.release()
        self.assertIsInstance(locks.LOCK, locks.WatchedRLock)

    def test_a_shared_file_lock_is_watched_while_held(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            lock = locks.shared_file_lock(Path(folder) / "record.json")
            with lock:
                self.assertEqual([entry[0] for entry in storage_watch._inflight.values()], ["持锁 record.json.lock"])
                with lock:
                    self.assertEqual(len(storage_watch._inflight), 1)
            self.assertEqual(storage_watch._inflight, {})


class StorageAlertTests(unittest.TestCase):
    def setUp(self):
        storage_watch.reset()
        self.addCleanup(storage_watch.reset)
        self.sent = []
        messenger = SimpleNamespace(send_message=lambda profile, chat, text, key, **kw: self.sent.append((chat, text)) or True)
        voice = SimpleNamespace(safe_key=lambda key: key)
        runtime = SimpleNamespace(log=lambda line: None, access=SimpleNamespace(notify_chat=lambda: "oc_owner"))
        self.alerts = StorageAlerts(runtime, messenger, voice)
        self.ctx = SimpleNamespace(profile="bot", state_dir="/absolute/state")

    def test_a_full_disk_is_told_once_then_again_only_after_a_while(self):
        now = time.time()
        self.assertFalse(self.alerts.tick(self.ctx, now=now))  # Nothing seen.
        storage_watch.note_failure(quota_error(), "outbox step a.b")
        self.assertTrue(self.alerts.tick(self.ctx, now=now + 1))
        self.assertEqual(self.sent[0][0], "oc_owner")
        self.assertIn("状态目录的磁盘写不进了：Disk quota exceeded（/absolute/state/jobs）", self.sent[0][1])
        storage_watch.note_failure(quota_error(), "outbox step a.b")
        self.assertFalse(self.alerts.tick(self.ctx, now=now + 60))
        storage_watch._full["at"] = now + storage_alerts.EVERY  # Still refused six hours on.
        self.assertTrue(self.alerts.tick(self.ctx, now=now + storage_alerts.EVERY + 2))
        self.assertIn("，2 次", self.sent[1][1])

    def test_a_send_that_failed_is_tried_again_later(self):
        storage_watch.note_failure(quota_error(), "x")
        self.alerts.messenger = SimpleNamespace(send_message=lambda *a, **k: False)
        now = time.time()
        self.assertFalse(self.alerts.tick(self.ctx, now=now))
        self.alerts.messenger = SimpleNamespace(send_message=lambda *a, **k: True)
        self.assertFalse(self.alerts.tick(self.ctx, now=now + 30))  # Within RETRY.
        self.assertTrue(self.alerts.tick(self.ctx, now=now + storage_alerts.RETRY + 1))

    def test_the_text_names_no_path_when_there_is_none(self):
        self.assertNotIn("（", alert_text({"error": "No space left on device", "at": time.time()}).split("。")[0])


class DoctorWordsTests(unittest.TestCase):
    def test_the_doctor_says_a_refused_write_and_slow_steps(self):
        storage = {"full": {"at": time.time(), "error": "Disk quota exceeded", "count": 3},
                   "slow": [{"at": time.time(), "what": "持锁 LOCK", "seconds": 2.4},
                            {"at": time.time(), "what": "读记录 a.json", "seconds": 7.0}]}
        rows = doctor_words.storage_rows(storage, "/absolute/state", "/absolute/state/bridge.log")
        self.assertEqual(rows[0][0], doctor_words.FAULT)
        self.assertIn("状态目录的磁盘写不进：Disk quota exceeded（最近一次 ", rows[0][1])
        self.assertIn("共 3 次", rows[0][1])
        self.assertEqual(rows[1][0], doctor_words.NOTE)
        self.assertIn("最近 2 次持锁或读盘超过 2 秒，最长 7.0 秒：读记录 a.json", rows[1][1])
        self.assertEqual(doctor_words.storage_rows({}, "", ""), [])


if __name__ == "__main__":
    unittest.main()
