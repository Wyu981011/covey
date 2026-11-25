"""网页上点一下就升级 (app/self_upgrade.py, data contract v39; T778): the upgrader the installer sets up (``<data home>/upgrade.json``),
its check kept and turned into the ``upgrade`` item the page draws, the upgrade started in a session of its own whose end is written
for the next Bridge, the ``upgrade`` operation, and nothing at all without an upgrader (no thread, no ``upgrade`` in ``ops``)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from test_web_sync import WebCase
from covey.app import self_upgrade
from covey.app.self_upgrade import SelfUpgrade
from covey.app.web_ops import Ops
from covey.app.web_settings import page_ops

STATUS = {"live": "aaaaaaaa-bbbbbbbb", "latest": "aaaaaaaa-cccccccc", "bridge": True,
          "web": {"kind": "app", "current": False, "manual": False}, "count": 2,
          "changes": [{"repo": "covey-internal", "sha": "cccccccc", "subject": "新功能 (T1)", "at": 1795600000},
                      {"repo": "covey", "sha": "dddddddd", "subject": "修了一处 (T2)", "at": 1795590000}],
          "blocked": "", "extra": "a newer installer's field"}


def upgrader_file(home, status_argv=None, run_argv=None):
    data = {"by": "covey-internal", "status": status_argv or ["/usr/bin/python3", "/absolute/ext/dev/install.py", "status", "--json"],
            "run": run_argv or ["/usr/bin/python3", "/absolute/ext/dev/install.py", "upgrade"]}
    (Path(home) / self_upgrade.CONFIG).write_text(json.dumps(data))


def answered(status, code=0):
    def run(argv, **kwargs):
        return subprocess.CompletedProcess(argv, code, "[准备] …\n" + json.dumps(status, ensure_ascii=False) + "\n", "")
    return run


class Case(TestCase):
    def setUp(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.home, self.state = root / "data", root / "data" / "state"
        self.state.mkdir(parents=True)
        self.now = 1795600000.0
        self.logs = []

    def up(self, **kw):
        return SelfUpgrade(self.state, self.logs.append, home=self.home, clock=lambda: self.now, **kw)


class ConfigTests(Case):
    def test_only_two_absolute_commands_count(self):
        self.assertIsNone(self_upgrade.config(self.home))
        (self.home / self_upgrade.CONFIG).write_text('{"status": ["install.py", "status"], "run": ["/x/install.py"]}')
        self.assertIsNone(self_upgrade.config(self.home))  # A relative command is not run.
        (self.home / self_upgrade.CONFIG).write_text('["not", "an", "object"]')
        self.assertIsNone(self_upgrade.config(self.home))
        upgrader_file(self.home)
        found = self_upgrade.config(self.home)
        self.assertEqual((found["by"], found["run"][-1]), ("covey-internal", "upgrade"))


class CheckTests(Case):
    def test_a_check_keeps_what_the_page_reads_and_says_an_update_is_there(self):
        upgrader_file(self.home)
        seen = {}

        def run(argv, **kwargs):
            seen.update(argv=argv, **kwargs)
            return answered(STATUS)(argv)
        status = self.up(run=run).check()
        self.assertEqual(seen["argv"][-2:], ["status", "--json"])
        self.assertEqual(seen["stdin"], subprocess.DEVNULL)
        self.assertNotIn("extra", status)
        self.assertEqual((status["latest"], status["count"], status["checked_at"], status["error"]), ("aaaaaaaa-cccccccc", 2, self.now, ""))
        view = self.up().view()
        self.assertTrue(view["available"])
        self.assertEqual([c["subject"] for c in view["changes"]], ["新功能 (T1)", "修了一处 (T2)"])
        self.assertIsNone(view["running"])
        self.assertIsNone(view["last"])

    def test_only_a_page_left_behind_is_an_update_too_and_a_manual_page_is_not(self):
        same = {**STATUS, "latest": STATUS["live"], "bridge": False, "count": 0, "changes": []}
        self.assertTrue(self_upgrade.available(self_upgrade.clean_status(same)))
        self.assertFalse(self_upgrade.available(self_upgrade.clean_status({**same, "web": {"kind": "app", "current": True}})))
        self.assertFalse(self_upgrade.available(self_upgrade.clean_status({**same, "web": {"kind": "app", "manual": True}})))
        self.assertFalse(self_upgrade.available(self_upgrade.clean_status({**same, "latest": ""})))

    def test_a_failed_check_says_why_and_keeps_the_last_answer(self):
        upgrader_file(self.home)
        self.up(run=answered(STATUS)).check()
        self.now += 60

        def broken(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "停在这里：git fetch 失败\n")
        status = self.up(run=broken).check()
        self.assertIn("git fetch 失败", status["error"])
        self.assertEqual((status["latest"], status["checked_at"]), ("aaaaaaaa-cccccccc", self.now))

        def slow(argv, **kwargs):
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
        self.assertIn("没结束", self.up(run=slow).check()["error"])

    def test_due_after_the_start_then_every_few_hours_and_soon_after_an_upgrade(self):
        upgrader_file(self.home)
        up = self.up(run=answered(STATUS))
        self.assertFalse(up.due())  # Just started.
        self.now += self_upgrade.FIRST_CHECK_SECONDS
        self.assertTrue(up.due())
        up.check()
        self.assertFalse(up.due())
        self.now += self_upgrade.CHECK_SECONDS
        self.assertTrue(up.due())
        up.check()
        self_upgrade.write(up.run_path, {"state": "running", "code": 0, "finished_at": self.now + 1})
        self.now += 1 + self_upgrade.AFTER_RUN_SECONDS
        self.assertTrue(up.due())  # What is new now, so the page stops offering what was just deployed.


class StartTests(Case):
    def test_nothing_starts_without_an_upgrader_when_blocked_or_up_to_date(self):
        with self.assertRaisesRegex(ValueError, "upgrade.json"):
            self.up().start("op-1")
        upgrader_file(self.home)
        with self.assertRaisesRegex(ValueError, "不能升级：检出有没提交的改动"):
            self.up(run=answered({**STATUS, "blocked": "检出有没提交的改动"})).start("op-1")
        latest = {**STATUS, "latest": STATUS["live"], "bridge": False, "web": {"kind": "app", "current": True}}
        with self.assertRaisesRegex(ValueError, "已经是最新"):
            self.up(run=answered(latest)).start("op-1")

    def test_the_upgrade_runs_in_a_session_of_its_own_and_once_at_a_time(self):
        upgrader_file(self.home)
        started = []

        def popen(argv, **kwargs):
            started.append((argv, kwargs))
            return SimpleNamespace(pid=os.getpid(), wait=lambda: 0)
        up = self.up(run=answered(STATUS), popen=popen)
        said = up.start("op-1")
        self.assertIn("aaaaaaaa-cccccccc", said)
        argv, kwargs = started[0]
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(argv[-1], "upgrade")  # The upgrader's ``run``, behind the wrapper.
        record = self_upgrade.read(up.run_path)
        self.assertEqual((record["state"], record["op_id"], record["to"]), ("running", "op-1", "aaaaaaaa-cccccccc"))
        self.assertTrue(Path(record["log"]).parent.is_dir())
        self.assertIsNotNone(up.running())  # Its wrapper has not written its pid yet: under way for SPAWN_SECONDS.
        with self.assertRaisesRegex(ValueError, "已经在升级"):
            up.start("op-2")
        self.assertFalse(up.view()["available"])
        self.assertEqual(up.view()["running"]["op_id"], "op-1")
        self.now += self_upgrade.SPAWN_SECONDS
        self.assertIsNone(up.running())
        self.assertEqual(up.view()["last"]["state"], "failed")  # Gone without a word: the page says the result is not known.

    def test_the_wrapper_writes_the_end_the_next_bridge_reads(self):
        script = Path(self.home) / "fake_upgrade.py"
        script.write_text("print('Bridge 升级完成。回滚：…')\n"
                          "print('[网页] 没更新上（Bridge 已经是新版，不用回滚）：平台发布在等审批')\n"
                          "raise SystemExit(4)\n")
        upgrader_file(self.home, run_argv=[sys.executable, "-B", str(script)])
        up = SelfUpgrade(self.state, self.logs.append, home=self.home, run=answered(STATUS))
        up.start("op-1")
        deadline = time.time() + 30
        while "code" not in self_upgrade.read(up.run_path) and time.time() < deadline:
            time.sleep(0.05)
        record = self_upgrade.read(up.run_path)
        self.assertEqual(record["code"], 4)
        self.assertTrue(record["pid"])
        self.assertIn("Bridge 升级完成", Path(record["log"]).read_text())
        last = up.view()["last"]
        self.assertEqual(last["state"], "partial")
        self.assertIn("平台发布在等审批", last["message"])
        self.assertEqual(last["tail"][-1], "[网页] 没更新上（Bridge 已经是新版，不用回滚）：平台发布在等审批")

    def test_what_each_end_says(self):
        self.assertEqual(self_upgrade.outcome({"code": 0, "tail": ["[网页] 更新好了（日志 x）：网页刷新一下就是新版"]})[0], "done")
        self.assertEqual(self_upgrade.outcome({"code": 3, "tail": []})[0], "failed")
        state, message = self_upgrade.outcome({"code": 1, "tail": ["[预检] …", "预检没过，什么都没换。", "…"]})
        self.assertEqual(state, "failed")
        self.assertIn("预检没过", message)
        self.assertIn("退出码 2", self_upgrade.outcome({"code": 2, "tail": []})[1])
        line = "[网页] 没更新上（Bridge 已经是新版，不用回滚）：平台发布在等审批"
        self.assertEqual(self_upgrade.outcome({"code": 4, "tail": ["Bridge 升级完成。", line]}), ("partial", "平台发布在等审批"))


class OpTests(Case):
    def ops(self, up):
        return SimpleNamespace(self_upgrade=up)

    def test_check_and_run_from_the_page(self):
        with self.assertRaisesRegex(ValueError, "没配"):
            Ops.upgrade(self.ops(self.up()), self.state, "oc_chat", {}, {"action": "check"})
        upgrader_file(self.home)
        up = self.up(run=answered(STATUS), popen=lambda argv, **kw: SimpleNamespace(pid=os.getpid(), wait=lambda: 0))
        self.assertEqual(Ops.upgrade(self.ops(up), self.state, "oc_chat", {}, {"action": "check"}), "已检查：有 2 个更新")
        with self.assertRaisesRegex(ValueError, "check 或 run"):
            Ops.upgrade(self.ops(up), self.state, "oc_chat", {}, {"action": "now"})
        with self.assertRaisesRegex(ValueError, "不带话题"):
            Ops.upgrade(self.ops(up), self.state, "oc_chat", {"topic_key": "t"}, {"action": "run"})
        self.assertTrue(Ops.upgrade(self.ops(up), self.state, "oc_chat", {"op_id": "op-9"}, {"action": "run"}).startswith("开始升级"))
        up.run_path.unlink()  # The fake upgrade "runs" as this process: a check during an upgrade keeps the last answer.
        latest = self.up(run=answered({**STATUS, "latest": STATUS["live"], "bridge": False, "web": {"kind": "app", "current": True}}))
        self.assertEqual(Ops.upgrade(self.ops(latest), self.state, "oc_chat", {}, {"action": "check"}), "已检查：已经是最新")


class UpgradePushTest(WebCase):
    """The ``settings`` item ``upgrade``: only with an upgrader set up, alone in its request, again when the check or the upgrade changed;
    the ``upgrade`` operation in its own lane, its item pushed before the ack; the thread and ``ops`` only with an upgrader."""

    def setUp(self):
        super().setUp()
        self.home = self.state / "home"
        self.home.mkdir()
        self.enterContext(mock.patch.dict(os.environ, {"COVEY_DATA_HOME": str(self.home)}))

    def pushed(self):
        return [each for batch in self.web.upserts for each in batch["items"] if each["key"] == "upgrade"]

    def names(self):
        return [name for name, _ in self.sync.threads()]

    def test_nothing_without_an_upgrader(self):
        self.assertNotIn("web-upgrade", self.names())
        self.assertEqual(self.sync.push_upgrade(full=True), 0)
        self.assertNotIn("upgrade", page_ops())
        self.assertEqual(self.sync.ops.run({"kind": "upgrade", "op_id": "op-1", "payload": {"action": "check"}})[0], "failed")
        self.assertEqual(self.pushed(), [])

    def test_pushed_when_it_changed_and_before_the_ack_of_a_check(self):
        upgrader_file(self.home)
        self.assertEqual(self.names()[0], "web-upgrade")
        self.assertIn("upgrade", page_ops())
        self.assertEqual(self.sync.push_upgrade(), 1)
        self.assertEqual(self.pushed()[-1]["data"]["checked_at"], 0)  # Not checked yet.
        self.assertEqual(self.sync.push_upgrade(), 0)  # Nothing changed.
        self.assertEqual(self.sync.ops.self_upgrade.run_status.__name__, "run")
        self.sync.ops.self_upgrade.run_status = answered(STATUS)
        self.web.op("upgrade", 1, "op-u1", action="check")
        self.assertEqual(self.sync.inbox_once(), 1)
        self.assertEqual((self.web.acks[-1]["state"], self.web.acks[-1]["message"]), ("done", "已检查：有 2 个更新"))
        data = self.pushed()[-1]["data"]
        self.assertTrue(data["available"])
        self.assertEqual(data["latest"], "aaaaaaaa-cccccccc")
        self.assertEqual(self.sync.lane_of({"kind": "upgrade", "op_id": "x"}), "upgrade")
