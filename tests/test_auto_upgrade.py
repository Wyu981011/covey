"""定时自动升级 (app/auto_upgrade.py, COVEY_AUTO_UPGRADE): once a day at its time, only to a newer version, only when nothing runs
(15 minutes later, three times at most, then the next day), never forced, never rolled back, its end told to the owner once and out
of the quiet hours; nothing at all without the switch."""
from __future__ import annotations

import datetime
import json
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from test_self_upgrade import STATUS, answered, upgrader_file
from covey.app import auto_upgrade, self_upgrade
from covey.app.auto_upgrade import AutoUpgrade
from covey.app.self_upgrade import SelfUpgrade
from covey.core import quiet_hours

ZONE = quiet_hours.ZONE


def stamp(day, hour, minute=0):
    return datetime.datetime(2026, 11, day, hour, minute, tzinfo=ZONE).timestamp()


class Case(TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home, self.state = root / "data", root / "data" / "state"
        self.state.mkdir(parents=True)
        upgrader_file(self.home)
        self.now = stamp(26, 4, 50)
        self.logs, self.sent, self.busy, self.ok = [], [], "", True
        self.started = []
        self.status = dict(STATUS)
        self.environ = {"COVEY_AUTO_UPGRADE": "05:00"}

        def popen(argv, **kwargs):
            self.started.append(argv)
            return SimpleNamespace(pid=4242, wait=lambda: 0)

        self.upgrader = SelfUpgrade(self.state, self.logs.append, home=self.home, clock=lambda: self.now,
                                    run=lambda argv, **kw: answered(self.status)(argv, **kw), popen=popen)
        self.auto = AutoUpgrade(self.upgrader, busy=lambda: self.busy, notify=self.notify, log=self.logs.append,
                                clock=lambda: self.now, environ=self.environ)

    def notify(self, text):
        self.sent.append(text)
        return self.ok

    def record(self):
        return json.loads((self.state / "upgrade" / auto_upgrade.RECORD).read_text())

    def end_run(self, code, tail=()):
        """The upgrade the wrapper ran ended with ``code`` (what the wrapper writes into run.json)."""
        path = self.state / "upgrade" / "run.json"
        run = json.loads(path.read_text())
        path.write_text(json.dumps({**run, "code": code, "finished_at": self.now, "tail": list(tail)}))

    def step(self, at):
        self.now = at
        with mock.patch.object(self_upgrade, "alive", lambda pid: False):
            return self.auto.step()


class SwitchTests(TestCase):
    def test_only_a_time_turns_it_on(self):
        for value, want in (("05:00", (5, 0)), ("5:30", (5, 30)), ("23:59", (23, 59)), ("", None), ("0", None),
                            ("off", None), ("25:00", None), ("5", None)):
            self.assertEqual(auto_upgrade.at({"COVEY_AUTO_UPGRADE": value}), want, value)
        self.assertIsNone(auto_upgrade.at({}))
        self.assertEqual(auto_upgrade.at({"LARK_BRIDGE_AUTO_UPGRADE": "06:15"}), (6, 15))  # The old spelling.

    def test_no_thread_without_the_switch(self):
        app = SimpleNamespace()
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(auto_upgrade.targets(app), [])
        with mock.patch.dict("os.environ", {"COVEY_AUTO_UPGRADE": "05:00"}, clear=True):
            self.assertEqual([name for name, _ in auto_upgrade.targets(app)], ["auto-upgrade"])

    def test_the_thread_ends_at_once_without_an_upgrader(self):
        with tempfile.TemporaryDirectory() as home:
            logs = []
            runtime = SimpleNamespace(log=logs.append, shutdown=mock.Mock(is_set=lambda: False))
            with mock.patch.dict("os.environ", {"COVEY_AUTO_UPGRADE": "05:00", "COVEY_DATA_HOME": home}, clear=True):
                auto_upgrade.loop(SimpleNamespace(runtime=runtime), SimpleNamespace(state_dir=home))
            self.assertTrue(any("no upgrade.json" in line for line in logs))


class DayTests(Case):
    def test_nothing_before_its_time_or_after_its_window(self):
        self.assertEqual(self.step(stamp(26, 4, 59)), "")
        self.assertFalse((self.state / "upgrade" / auto_upgrade.RECORD).exists())
        self.assertEqual(self.step(stamp(26, 12, 0)), "")  # A Bridge up at noon does not upgrade in the middle of the day.
        self.assertEqual(self.started, [])

    def test_idle_and_newer_starts_the_upgrade(self):
        self.assertEqual(self.step(stamp(26, 5, 0)), auto_upgrade.STARTED)
        self.assertEqual(len(self.started), 1)
        self.assertEqual(self.started[0][-1], "upgrade")  # The upgrader's ``run``.
        run = json.loads((self.state / "upgrade" / "run.json").read_text())
        self.assertEqual((run["by"], run["op_id"]), ("auto", "auto-2026-11-26-0"))
        self.assertIn("-auto", run["log"])
        record = self.record()
        self.assertEqual((record["state"], record["to"], record["count"]), ("started", STATUS["latest"], 2))
        self.assertEqual(self.sent, [])

    def test_nothing_newer_ends_the_day_quietly(self):
        self.status = {**STATUS, "bridge": False, "web": {"kind": "app", "current": True, "manual": False}}
        self.assertEqual(self.step(stamp(26, 5, 0)), auto_upgrade.CURRENT)
        self.assertEqual(self.step(stamp(26, 5, 20)), "")
        self.assertEqual((self.started, self.sent), ([], []))

    def test_blocked_is_said_once_and_not_tried(self):
        self.status = {**STATUS, "blocked": "检出和远端分叉了"}
        self.assertEqual(self.step(stamp(26, 5, 0)), auto_upgrade.BLOCKED)
        self.step(stamp(26, 5, 1))
        self.assertEqual(self.started, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("检出和远端分叉了", self.sent[0])

    def test_busy_waits_fifteen_minutes_three_times_then_gives_the_day_up(self):
        self.busy = "2 个任务在跑"
        self.assertEqual(self.step(stamp(26, 5, 0)), auto_upgrade.WAITING)
        self.assertEqual(self.step(stamp(26, 5, 10)), "")  # Not yet 15 minutes.
        self.assertEqual(self.step(stamp(26, 5, 15)), auto_upgrade.WAITING)
        self.assertEqual(self.step(stamp(26, 5, 30)), auto_upgrade.WAITING)
        self.assertEqual(self.step(stamp(26, 5, 45)), auto_upgrade.GAVE_UP)
        self.assertEqual(self.started, [])
        self.assertEqual(len(self.sent), 1)
        self.assertIn("推迟了 3 次", self.sent[0])
        self.assertIn("没有强行重启", self.sent[0])
        self.assertIn("2 个任务在跑", self.sent[0])
        self.step(stamp(26, 6, 0))
        self.assertEqual(len(self.sent), 1)
        self.busy = ""
        self.assertEqual(self.step(stamp(27, 5, 0)), auto_upgrade.STARTED)  # The next day again.

    def test_free_on_a_later_look_starts_then(self):
        self.busy = "1 个任务在跑"
        self.step(stamp(26, 5, 0))
        self.busy = ""
        self.assertEqual(self.step(stamp(26, 5, 15)), auto_upgrade.STARTED)
        self.assertEqual(self.record()["op_id"], "auto-2026-11-26-1")


class EndTests(Case):
    def setUp(self):
        super().setUp()
        self.assertEqual(self.step(stamp(26, 5, 0)), auto_upgrade.STARTED)

    def test_running_waits(self):
        with mock.patch.object(self_upgrade, "alive", lambda pid: True):
            (self.state / "upgrade" / "run.json").write_text(json.dumps({**json.loads(
                (self.state / "upgrade" / "run.json").read_text()), "pid": 4242}))
            self.now = stamp(26, 5, 3)
            self.assertEqual(self.auto.step(), "")
        self.assertEqual(self.record()["state"], "started")

    def test_done_is_told_with_its_changes(self):
        self.end_run(0, ["[网页] 更新好了"])
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.DONE)
        self.assertEqual(len(self.sent), 1)
        self.assertIn(STATUS["latest"], self.sent[0])
        self.assertIn("新功能 (T1)", self.sent[0])
        self.assertEqual(self.record()["told"], "sent")
        self.step(stamp(26, 5, 9))
        self.assertEqual(len(self.sent), 1)

    def test_web_not_updated_is_partial(self):
        self.end_run(self_upgrade.WEB_UNDONE, ["[网页] 没更新上（Bridge 已经是新版，不用回滚）：npm 装不上"])
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.PARTIAL)
        self.assertIn("npm 装不上", self.sent[0])
        self.assertIn("不用回滚", self.sent[0])

    def test_a_failure_is_told_never_rolled_back(self):
        self.end_run(1, ["部署没有全部通过：看 post 里没过的项和日志"])
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.FAILED)
        self.assertIn("没有自动回滚", self.sent[0])
        self.assertIn("deploy-runs", self.sent[0])  # The log.
        self.assertEqual(len(self.started), 1)  # No second run of any kind.

    def test_another_deploy_or_a_task_at_the_pre_check_waits_like_busy(self):
        self.end_run(self_upgrade.DEPLOY_RUNNING)
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.WAITING)
        self.assertEqual(self.step(stamp(26, 5, 23)), auto_upgrade.STARTED)
        self.end_run(1, ["拦下：{\"restart_blockers\": [{\"key\": \"k\"}]}", "预检没过，什么都没换"])
        self.assertEqual(self.step(stamp(26, 5, 25)), auto_upgrade.WAITING)
        self.assertEqual(self.sent, [])

    def test_a_run_that_vanished_is_uncertain(self):
        path = self.state / "upgrade" / "run.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "pid": 4242}))
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.FAILED)
        self.assertIn("结果不确定", self.sent[0])

    def test_quiet_hours_hold_the_message_and_an_uncertain_send_is_not_repeated(self):
        self.environ["COVEY_QUIET_HOURS"] = "23:00-08:30"
        self.end_run(0)
        self.assertEqual(self.step(stamp(26, 5, 8)), auto_upgrade.DONE)
        self.assertEqual(self.sent, [])
        self.ok = False
        self.step(stamp(26, 8, 30))
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.record()["told"], "uncertain")
        self.step(stamp(26, 8, 31))
        self.assertEqual(len(self.sent), 1)


class BusyTests(TestCase):
    def test_running_tasks_or_restart_blockers(self):
        with tempfile.TemporaryDirectory() as state:
            with mock.patch("covey.app.detached.live_keys", return_value=set()), \
                    mock.patch("covey.app.detached.restart_blockers", return_value=[]):
                self.assertEqual(auto_upgrade.busy_words(state), "")
            with mock.patch("covey.app.detached.live_keys", return_value={"a", "b"}), \
                    mock.patch("covey.app.detached.restart_blockers", return_value=[]):
                self.assertEqual(auto_upgrade.busy_words(state), "2 个任务在跑")
            with mock.patch("covey.app.detached.live_keys", return_value=set()), \
                    mock.patch("covey.app.detached.restart_blockers", return_value=[{"key": "k"}]):
                self.assertEqual(auto_upgrade.busy_words(state), "1 个任务重启会被打断")


class SharedTests(TestCase):
    def test_one_upgrader_a_state_directory(self):
        with tempfile.TemporaryDirectory() as state:
            self.assertIs(self_upgrade.shared(state), self_upgrade.shared(Path(state) / "."))
