"""One command changes one setting of a service (bin/covey_service.py set / unset, docs/configuration.md 改开关三步)."""
from __future__ import annotations

import contextlib
import fcntl
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from covey.core import switches
from covey.service import manager
from covey.service.manager import change_settings, main, parse_settings, read_json, register, service_key, set_desired

PROXY = "http://proxy.example.invalid:3128"


class SettingsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        self.services = self.root / "services"
        self.environment = {"PATH": "/absolute/bin:/usr/bin", "HTTPS_PROXY": PROXY, "LARK_BRIDGE_DATA_HOME": "/absolute/data",
                            "LARK_BRIDGE_DIGEST_TIMES": "09:30", "LARK_BRIDGE_MAIN_TRACKS": "1"}
        self.command = [sys.executable, "-B", "/absolute/release/bin/covey_bridge.py", "--harness", "unified"]
        self.first = register(self.services, self.state, self.command, workdir=self.root, profile="bot",
                              environment=dict(self.environment), health_timeout=90)
        started = mock.patch.object(manager, "ensure_manager")
        self.started = started.start()
        self.addCleanup(started.stop)
        # The Manager running now has none of these in its own environment.
        inherited = mock.patch.object(manager, "manager_environment", return_value={"PATH": "/usr/bin"})
        self.inherited = inherited.start()
        self.addCleanup(inherited.stop)

    def manifest(self):
        return read_json(self.services / "services" / (service_key(self.state) + ".json"))

    def change(self, words, unset=False, **kwargs):
        return change_settings(self.services, self.state, parse_settings(words, unset=unset), **kwargs)

    def test_one_setting_changes_and_everything_else_stays(self):
        report = self.change(["COVEY_DIGEST_TIMES=09:30,21:30", "COVEY_DOWN_NOTICE=0"])
        after = self.manifest()
        self.assertEqual(report["changed"], {"LARK_BRIDGE_DIGEST_TIMES": {"from": "09:30", "to": "09:30,21:30"},
                                             "LARK_BRIDGE_DOWN_NOTICE": {"from": None, "to": "0"}})
        self.assertEqual(report["generation"], self.first["generation"] + 1)
        self.assertEqual(after["environment"], {**self.environment, "LARK_BRIDGE_DIGEST_TIMES": "09:30,21:30",
                                                "LARK_BRIDGE_DOWN_NOTICE": "0"})
        for field in ("command", "workdir", "profile", "log", "health_timeout", "state_dir", "desired_state"):
            self.assertEqual(after[field], self.first[field], field)
        self.assertEqual(after["generation"], self.first["generation"] + 1)
        self.started.assert_called_once_with(self.services)
        # A renamed switch is kept under the name every release reads (core/env.py canonical).
        self.change(["COVEY_BUTLER_TRACKS=0"])
        self.assertEqual(self.manifest()["environment"]["LARK_BRIDGE_MAIN_TRACKS"], "0")
        self.assertNotIn("COVEY_BUTLER_TRACKS", self.manifest()["environment"])

    def test_a_dry_run_and_a_value_already_set_change_nothing(self):
        report = self.change(["COVEY_DIGEST_TIMES=21:30"], dry_run=True)
        self.assertEqual(report["changed"], {"LARK_BRIDGE_DIGEST_TIMES": {"from": "09:30", "to": "21:30"}})
        self.assertTrue(report["dry_run"])
        self.assertEqual(self.manifest(), self.first)
        report = self.change(["LARK_BRIDGE_DIGEST_TIMES=09:30"])
        self.assertEqual(report["changed"], {})
        self.assertEqual(self.manifest(), self.first)
        self.started.assert_not_called()

    def test_unset_removes_it_unless_the_managers_own_environment_would_put_it_back(self):
        report = self.change(["COVEY_DIGEST_TIMES"], unset=True)
        self.assertEqual(report["changed"], {"LARK_BRIDGE_DIGEST_TIMES": {"from": "09:30", "to": None}})
        self.assertNotIn("LARK_BRIDGE_DIGEST_TIMES", self.manifest()["environment"])
        self.inherited.return_value = {"COVEY_BUTLER_TRACKS": "1"}
        with self.assertRaisesRegex(ValueError, "COVEY_BUTLER_TRACKS is also in the Manager's own environment.*"
                                                "set COVEY_BUTLER_TRACKS=0"):
            self.change(["COVEY_BUTLER_TRACKS"], unset=True)
        self.assertEqual(self.manifest()["environment"]["LARK_BRIDGE_MAIN_TRACKS"], "1")
        self.assertEqual(self.change(["COVEY_NOT_THERE"], unset=True)["changed"], {})

    def test_credentials_and_what_the_manifest_does_not_keep_are_refused(self):
        for word, why in (("COVEY_WEB_TOKEN=abc", "credential"), ("LARK_BRIDGE_API_KEY=abc", "credential"),
                          ("COVEY_MANAGED=1", "sets it itself"), ("COVEY_REQUIRED_MOUNT=/x", "sets it itself"),
                          ("COVEY_TASK_DIR=/x", "sets it itself"), ("EDITOR=vim", "only COVEY_")):
            with self.subTest(word=word), self.assertRaisesRegex(ValueError, why):
                self.change([word])
        with self.assertRaisesRegex(ValueError, "only non-secret proxy URLs"):
            self.change(["HTTPS_PROXY=http://user:secret@proxy.example.invalid:3128"])  # privacy: allow a fake proxy password to be refused
        with self.assertRaisesRegex(ValueError, "only explicit non-secret"):
            self.change(["COVEY_DIGEST_TIMES=09:30\n21:30"])
        self.assertEqual(self.manifest(), self.first)

    def test_what_the_deploy_pre_check_stops_is_refused(self):
        with self.assertRaisesRegex(ValueError, "LARK_BRIDGE_CODEX_SANDBOX=read-only is no longer read"):
            self.change(["LARK_BRIDGE_CODEX_SANDBOX=read-only"])
        with mock.patch("covey.core.run_dir.restart_blockers", return_value=[{"key": "k", "job_id": 12, "status": "running"}]):
            with self.assertRaisesRegex(ValueError, r"job #12 \(running\) would be interrupted"):
                self.change(["COVEY_DIGEST_TIMES=21:30"])
        forms = self.state / "launch-forms"
        forms.mkdir()
        (forms / "abc.json").write_text(json.dumps({"status": "creating_worktree"}))
        with self.assertRaisesRegex(ValueError, "a launch form is creating its worktree"):
            self.change(["COVEY_DIGEST_TIMES=21:30"])
        (forms / "abc.json").unlink()
        held = os.open(self.services / "deploy.lock", os.O_RDWR | os.O_CREAT, 0o644)
        self.addCleanup(os.close, held)
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)  # As scripts/deploy_bridge.sh holds it, and says who.
        os.ftruncate(held, 0)
        os.pwrite(held, json.dumps({"pid": 4242, "commit": "abcdef"}).encode(), 0)
        with self.assertRaisesRegex(ValueError, 'a deploy is running .*"pid": 4242'):
            self.change(["COVEY_DIGEST_TIMES=21:30"])
        fcntl.flock(held, fcntl.LOCK_UN)
        self.assertEqual(self.manifest(), self.first)
        self.assertEqual(self.change(["COVEY_DIGEST_TIMES=21:30"])["changed"]["LARK_BRIDGE_DIGEST_TIMES"]["to"], "21:30")

    def test_a_stopped_or_unregistered_service_is_refused(self):
        set_desired(self.services, self.state, "stopped")
        with self.assertRaisesRegex(ValueError, "the service is stopped: start it first"):
            self.change(["COVEY_DIGEST_TIMES=21:30"])
        with self.assertRaisesRegex(ValueError, "no service is registered"):
            change_settings(self.services, self.root / "other", {"COVEY_DIGEST_TIMES": "21:30"})

    def test_the_showcase_preset_turns_on_what_is_unset_or_off_and_keeps_the_rest(self):
        self.change(["COVEY_CARD_TRANSPORT=0"])
        first = self.manifest()
        report = change_settings(self.services, self.state, {}, preset="showcase", dry_run=True)
        self.assertEqual(self.manifest(), first)
        self.assertEqual(report["preset"], "showcase")
        changed = {name: row["to"] for name, row in report["changed"].items()}
        # The owner's own digest time and the tracks stay (not the preset's since T813); COVEY_CARD_TRANSPORT=0 is off, so
        # it is turned on.
        self.assertNotIn("LARK_BRIDGE_DIGEST_TIMES", changed)
        self.assertNotIn("LARK_BRIDGE_MAIN_TRACKS", changed)
        self.assertEqual(report["changed"]["LARK_BRIDGE_CARD_TRANSPORT"], {"from": "0", "to": "sdk"})
        self.assertEqual(len(changed), len(switches.SHOWCASE))
        report = self.change(["COVEY_COLLAB=0"], preset="showcase")  # A setting given with it wins.
        environment = self.manifest()["environment"]
        self.assertEqual(report["generation"], first["generation"] + 1)
        self.assertEqual(manager.cenv.get("COVEY_COLLAB", None, environment), "0")
        self.assertEqual(manager.cenv.get("COVEY_DIGEST_TIMES", None, environment), "09:30")
        for name in set(switches.SHOWCASE) - {"COVEY_COLLAB", "COVEY_DIGEST_TIMES"}:
            self.assertEqual(manager.cenv.get(name, None, environment), switches.SHOWCASE[name], name)
        # Set off is the preset's to turn on again; once all are on, it changes nothing.
        self.assertEqual(change_settings(self.services, self.state, {}, preset="showcase")["changed"],
                         {"LARK_BRIDGE_COLLAB": {"from": "0", "to": "1"}})
        self.assertEqual(change_settings(self.services, self.state, {}, preset="showcase")["changed"], {})

    def test_the_words_of_the_command(self):
        self.assertEqual(parse_settings(["COVEY_A=1", "COVEY_B="]), {"COVEY_A": "1", "COVEY_B": ""})
        self.assertEqual(parse_settings(["COVEY_A"], unset=True), {"COVEY_A": None})
        for words, unset in ((["COVEY_A"], False), (["COVEY_A=1"], True), (["=1"], False),
                             (["COVEY_DIGEST_TIMES=1", "LARK_BRIDGE_DIGEST_TIMES=2"], False)):
            with self.subTest(words=words), self.assertRaises(ValueError):
                parse_settings(words, unset=unset)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            self.assertEqual(main(["--root", str(self.services), "set", "--state-dir", str(self.state), "--dry-run",
                                   "COVEY_DIGEST_TIMES=21:30"]), 0)
        self.assertEqual(json.loads(said.getvalue())["changed"]["LARK_BRIDGE_DIGEST_TIMES"]["to"], "21:30")
        self.assertEqual(self.manifest(), self.first)
        said = io.StringIO()
        with contextlib.redirect_stdout(said):  # A preset alone is enough.
            self.assertEqual(main(["--root", str(self.services), "set", "--state-dir", str(self.state), "--dry-run",
                                   "--preset", "showcase"]), 0)
        self.assertEqual(json.loads(said.getvalue())["changed"]["LARK_BRIDGE_COLLAB"]["to"], "1")
        for argv in (["set", "--state-dir", str(self.state)], ["set", "--state-dir", str(self.state), "--preset", "other"],
                     ["unset", "--state-dir", str(self.state), "--preset", "showcase", "COVEY_A"]):
            with self.subTest(argv=argv), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(["--root", str(self.services), *argv])
        self.assertEqual(self.manifest(), self.first)


class LockRootTests(unittest.TestCase):
    """The management commands take the lock directory the service manifests keep (manager.adopt_lock_root): on a cloud
    file system whose flock fails (ENOSYS) ``set`` locked config.lock in place and failed (T818)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.root = self.home / "services"
        self.state = self.home / "state"
        self.state.mkdir()
        self.runtime = self.home / "runtime"
        self.command = [sys.executable, "-B", "/absolute/release/bin/covey_bridge.py", "--harness", "unified"]
        clean = mock.patch.dict(os.environ)
        clean.start()
        self.addCleanup(clean.stop)
        for name in ("COVEY_LOCK_ROOT", "LARK_BRIDGE_LOCK_ROOT"):
            os.environ.pop(name, None)
        started = mock.patch.object(manager, "ensure_manager")
        started.start()
        self.addCleanup(started.stop)
        inherited = mock.patch.object(manager, "manager_environment", return_value={"PATH": "/usr/bin"})
        inherited.start()
        self.addCleanup(inherited.stop)

    def register(self, state, lock_root):
        environment = {"PATH": "/usr/bin", **({"LARK_BRIDGE_LOCK_ROOT": lock_root} if lock_root is not None else {})}
        with mock.patch.dict(os.environ, {"COVEY_LOCK_ROOT": lock_root} if lock_root is not None else {}):
            return register(self.root, state, self.command, workdir=self.home, profile=state.name, environment=environment)

    def run_set(self, *words):
        said = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(said):
            main(["--root", str(self.root), "set", "--state-dir", str(self.state), *words])
        return said.getvalue()

    def test_set_locks_in_the_manifests_lock_directory_without_one_in_this_shell(self):
        import hashlib
        self.register(self.state, str(self.runtime))
        said = self.run_set("COVEY_DIGEST_TIMES=21:30")
        self.assertIn(f"用服务清单里的锁目录 COVEY_LOCK_ROOT={self.runtime}", said)
        environment = read_json(self.root / "services" / (service_key(self.state) + ".json"))["environment"]
        self.assertEqual(environment["LARK_BRIDGE_DIGEST_TIMES"], "21:30")
        self.assertEqual(environment["LARK_BRIDGE_LOCK_ROOT"], str(self.runtime))
        name = hashlib.sha256(os.fsencode((self.root / "config.lock").resolve())).hexdigest() + ".lock"
        self.assertTrue((self.runtime / name).is_file())
        self.assertFalse((self.root / "config.lock").exists())  # Not locked in place on the cloud file system.
        # This process (and the Manager ensure_manager would start) has it under both spellings.
        self.assertEqual((os.environ["COVEY_LOCK_ROOT"], os.environ["LARK_BRIDGE_LOCK_ROOT"]), (str(self.runtime),) * 2)
        # A dry run says which lock directory it would use.
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            main(["--root", str(self.root), "set", "--state-dir", str(self.state), "--dry-run", "COVEY_DIGEST_TIMES=22:00"])
        self.assertEqual(json.loads(out.getvalue())["lock_root"], str(self.runtime))

    def test_another_value_in_this_shell_or_manifests_that_disagree_are_refused(self):
        first = self.register(self.state, str(self.runtime))
        with mock.patch.dict(os.environ, {"COVEY_LOCK_ROOT": str(self.home / "elsewhere")}), \
                self.assertRaisesRegex(ValueError, "both would lock apart"):
            self.run_set("COVEY_DIGEST_TIMES=21:30")
        with mock.patch.dict(os.environ, {"COVEY_LOCK_ROOT": str(self.runtime)}):  # The same value: as before.
            self.assertNotIn("用服务清单里的锁目录", self.run_set("COVEY_DIGEST_TIMES=21:30"))
        other = self.home / "other-state"
        other.mkdir()
        self.register(other, None)  # A second service without one: which lock directory is the root's is unclear.
        before = read_json(self.root / "services" / (service_key(self.state) + ".json"))
        with self.assertRaisesRegex(ValueError, "do not agree on COVEY_LOCK_ROOT"):
            self.run_set("COVEY_DIGEST_TIMES=08:00")
        self.assertEqual(read_json(self.root / "services" / (service_key(self.state) + ".json")), before)
        self.assertNotIn("COVEY_LOCK_ROOT", os.environ)
        self.assertGreater(before["generation"], first["generation"])

    def test_without_a_lock_directory_anywhere_nothing_changes(self):
        self.register(self.state, None)
        self.assertEqual(manager.adopt_lock_root(self.root, say=self.fail), None)
        self.assertEqual(self.run_set("COVEY_DIGEST_TIMES=21:30"), "")
        self.assertTrue((self.root / "config.lock").exists())  # flock on the file itself, as before.
        self.assertNotIn("COVEY_LOCK_ROOT", os.environ)
        self.assertEqual(manager.adopt_lock_root(self.home / "no-root", say=self.fail), None)  # A first install.

    def test_the_extension_commands_take_it_too(self):
        from covey.service import plugins
        self.register(self.state, str(self.runtime))
        data = self.home / "data"
        with mock.patch.dict(os.environ, {"COVEY_SERVICE_ROOT": str(self.root), "COVEY_DATA_HOME": str(data)}), \
                contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(plugins.main(["disable", "some_pkg"]), 0)
        self.assertIn("已停用 some_pkg", out.getvalue())
        self.assertIn("用服务清单里的锁目录", err.getvalue())
        self.assertTrue((data / "extensions" / "enabled").is_file())
        self.assertFalse((data / "extensions" / "enabled.lock").exists())
        import hashlib
        name = hashlib.sha256(os.fsencode((data / "extensions" / "enabled.lock").resolve())).hexdigest() + ".lock"
        self.assertTrue((self.runtime / name).is_file())


class ManagerEnvironmentTests(unittest.TestCase):
    def test_without_a_running_manager_it_is_this_processs_own(self):
        with tempfile.TemporaryDirectory() as root:
            with mock.patch.dict(os.environ, {"COVEY_PROBE_SETTING": "1"}):
                self.assertEqual(manager.manager_environment(Path(root)).get("COVEY_PROBE_SETTING"), "1")


if __name__ == "__main__":
    unittest.main()
