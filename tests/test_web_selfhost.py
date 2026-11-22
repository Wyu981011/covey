"""自托管网页工作台 (service/web_selfhost.py, service/manager.py ``ensure_selfhost``): the switches a manifest carries become the page
process's command and environment; the preparation writes a 0600 key (never over one that is there) and web.json that load_config
takes; the Manager runs the process only when asked, starts it again after an exit with its backoff, stops its whole group when
the switch goes off or the Manager ends, and does nothing at all when the switch is off."""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from covey.core import web_sync
from covey.core.state import write_json
from covey.service import manager, web_selfhost
from support import exec_tempdir

FAKE_NODE = """#!/bin/sh
env > "$(dirname "$0")/node-env.$$"
echo "$@" >> "$(dirname "$0")/node-args"
exec sleep 300
"""


def manifest(root, **environment):
    write_json(root / "services" / "s1.json", {"id": "s1", "desired_state": "running", "generation": 1, "environment": environment})


class SpecTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_off_unless_asked_and_told_where(self):
        self.assertIsNone(web_selfhost.spec({}, self.root))
        self.assertIsNone(web_selfhost.spec({"COVEY_WEB_SELFHOST": "0", "COVEY_WEB_SELFHOST_DIR": "/absolute/page"}, self.root))
        self.assertIsNone(web_selfhost.spec({"COVEY_WEB_SELFHOST": "1"}, self.root))
        self.assertIsNone(web_selfhost.spec({"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": "relative"}, self.root))

    def test_the_command_and_environment(self):
        found = web_selfhost.spec({"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": "/absolute/page"}, self.root)
        self.assertEqual(found["argv"], ["node", "/absolute/page/server/selfhost/main.js"])  # Not server/main.js: the hosted platform's entry.
        self.assertEqual(found["env"], {"COVEY_WEB_HOST": "127.0.0.1", "COVEY_WEB_PORT": "18650",
                                        "COVEY_WEB_DB_DIR": str(self.root / "web" / "db"),
                                        "COVEY_WEB_KEY_FILE": str(self.root / "web" / "web-openapi.key"),
                                        "COVEY_WEB_DATABASE_URL_FILE": str(self.root / "web" / "database-url")})
        self.assertEqual(found["log"], str(self.root / "web" / "logs" / "selfhost.log"))
        for text, port in (("19000", 19000), ("0", 18650), ("70000", 18650), ("x", 18650)):
            self.assertEqual(web_selfhost.port_of({"COVEY_WEB_SELFHOST_PORT": text}), port)

    def test_wanted_reads_running_manifests_only(self):
        settings = {"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": "/absolute/page", "COVEY_DATA_HOME": str(self.root)}
        self.assertIsNone(web_selfhost.wanted(self.root, {}, manager.service_environment))
        manifest(self.root, **settings)
        self.assertEqual(web_selfhost.wanted(self.root, {}, manager.service_environment)["home"], str(self.root / "web"))
        write_json(self.root / "services" / "s1.json", {"id": "s1", "desired_state": "stopped", "environment": settings})
        self.assertIsNone(web_selfhost.wanted(self.root, {}, manager.service_environment))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)

    def test_key_and_config(self):
        result = web_selfhost.prepare(self.home, 19000, "/absolute/page")
        key = Path(result["key_file"])
        self.assertTrue(result["created_key"])
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        self.assertGreaterEqual(len(key.read_text().strip()), 32)
        config = json.loads(Path(result["config"]).read_text())
        self.assertEqual(config, {"base_url": "http://127.0.0.1:19000/openapi", "key_file": str(key), "push_seconds": 1, "poll_seconds": 1,
                                  "page_url": "http://127.0.0.1:19000/"})
        loaded = web_sync.load_config(result["config"])  # What the Bridge reads takes it: loopback http is allowed.
        self.assertEqual((loaded.base_url, loaded.key), (config["base_url"], key.read_text().strip()))
        self.assertEqual(result["switches"], ["COVEY_WEB=1", f"COVEY_WEB_CONFIG={result['config']}", "COVEY_WEB_SELFHOST=1",
                                              "COVEY_WEB_SELFHOST_DIR=/absolute/page", "COVEY_WEB_SELFHOST_PORT=19000"])

    def test_page_url_default_explicit_and_kept(self):
        first = web_selfhost.prepare(self.home, 19000)
        self.assertEqual(first["page_url"], "http://127.0.0.1:19000/")
        self.assertEqual(json.loads(Path(first["config"]).read_text())["page_url"], "http://127.0.0.1:19000/")
        with mock.patch.dict(os.environ, {"COVEY_WEB": "1"}):
            self.assertEqual(web_sync.page_url(first["config"]), "http://127.0.0.1:19000/")  # What the cards read.
        again = web_selfhost.prepare(self.home, 19000, page_url="https://page.example/app")  # Given: used.
        self.assertEqual(json.loads(Path(again["config"]).read_text())["page_url"], "https://page.example/app")
        kept = web_selfhost.prepare(self.home, 19001)  # Not given: the one there stays, even when the port changed.
        self.assertEqual(json.loads(Path(kept["config"]).read_text())["page_url"], "https://page.example/app")
        Path(kept["config"]).write_text(json.dumps({"page_url": "not a url"}))
        self.assertEqual(web_selfhost.prepare(self.home, 19001)["page_url"], "http://127.0.0.1:19001/")  # A bad one is replaced.

    def test_the_page_url_option(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            web_selfhost.main(["--data-root", str(self.home), "--page-url", "https://page.example/app"])
        self.assertIn("page_url：https://page.example/app", out.getvalue())
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            web_selfhost.main(["--data-root", str(self.home), "--page-url", "page.example"])

    def test_nothing_that_is_there_is_overwritten(self):
        first = web_selfhost.prepare(self.home)
        text = Path(first["key_file"]).read_text()
        Path(first["config"]).write_text(json.dumps({"base_url": "x", "key_file": "x", "page_url": "https://page.example/app"}))
        again = web_selfhost.prepare(self.home)
        self.assertFalse(again["created_key"])
        self.assertEqual(Path(again["key_file"]).read_text(), text)
        self.assertEqual(json.loads(Path(again["config"]).read_text())["page_url"], "https://page.example/app")  # Kept.

    def test_the_command_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(web_selfhost.main(["--data-root", str(self.home), "--dir", "/absolute/page"]), 0)
        self.assertIn("COVEY_WEB_SELFHOST=1", out.getvalue())
        self.assertIn("COVEY_WEB_SELFHOST_DIR=/absolute/page", out.getvalue())
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            web_selfhost.main(["--data-root", str(self.home), "--dir", "relative"])


class LoopbackTests(unittest.TestCase):
    def test_http_only_to_this_machine(self):
        for url in ("https://page.example/openapi", "http://127.0.0.1:18650/openapi", "http://localhost/openapi", "http://[::1]:8080/openapi"):
            self.assertTrue(web_sync.base_url_ok(url), url)
        for url in ("http://page.example/openapi", "http://127.0.0.1.example/openapi", "http://user@127.0.0.1/x", "http://127.0.0.1:x/o",
                    "http://localhost:0/o", "ftp://127.0.0.1/o", "127.0.0.1:18650", ""):
            self.assertFalse(web_sync.base_url_ok(url), url)

    def test_load_config_says_so(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key = Path(tmp.name) / "k"
        key.write_text("secret-value")
        for url, ok in (("http://127.0.0.1:18650/openapi/", True), ("http://example.invalid/openapi", False)):
            config = Path(tmp.name) / "c.json"
            write_json(config, {"base_url": url, "key_file": str(key)})
            if ok:
                self.assertEqual(web_sync.load_config(config).base_url, "http://127.0.0.1:18650/openapi")
            else:
                with self.assertRaises(ValueError) as caught:
                    web_sync.load_config(config)
                self.assertIn("https://", str(caught.exception))
                self.assertNotIn("secret-value", str(caught.exception))


class ManagerTests(unittest.TestCase):
    def setUp(self):
        tmp = exec_tempdir()  # The fake node is run directly: not on a noexec /dev/shm.
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / "services-root"
        self.data = Path(tmp.name) / "data"
        self.page = Path(tmp.name) / "page"
        self.bin = Path(tmp.name) / "bin"
        (self.page / "server" / "selfhost").mkdir(parents=True)
        (self.page / "server" / "selfhost" / "main.js").write_text("")
        self.bin.mkdir()
        node = self.bin / "node"
        node.write_text(FAKE_NODE)
        node.chmod(0o755)
        self.logged = []
        for patch in (mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}", "SECRET_TOKEN": "must-not-reach-the-page"}),
                      mock.patch.object(manager, "say", self.logged.append)):
            patch.start()
            self.addCleanup(patch.stop)
        self.manager = manager.Manager(self.root, base_delay=0, max_delay=0)
        self.addCleanup(self.manager.stop_selfhost)
        self.settings = {"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": str(self.page), "COVEY_WEB_SELFHOST_PORT": "19001",
                         "COVEY_DATA_HOME": str(self.data)}

    def alive(self, child):
        return child.poll() is None

    def wait_env(self):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            found = sorted(self.bin.glob("node-env.*"))
            if found and found[-1].read_text():
                return dict(line.split("=", 1) for line in found[-1].read_text().splitlines() if "=" in line)
            time.sleep(0.05)
        self.fail("the page process did not start")

    def test_off_by_default_nothing_runs_nothing_is_written(self):
        manifest(self.root)
        self.manager.ensure_selfhost()
        self.assertIsNone(self.manager.selfhost["child"])
        self.assertFalse(self.data.exists())
        self.assertEqual(self.logged, [])

    def test_starts_with_its_environment_and_goes_with_the_switch(self):
        manifest(self.root, **self.settings)
        self.manager.ensure_selfhost()
        child = self.manager.selfhost["child"]
        env = self.wait_env()
        self.assertEqual((env["COVEY_WEB_HOST"], env["COVEY_WEB_PORT"]), ("127.0.0.1", "19001"))
        self.assertEqual(env["COVEY_WEB_DB_DIR"], str(self.data / "web" / "db"))
        self.assertEqual(env["COVEY_WEB_KEY_FILE"], str(self.data / "web" / "web-openapi.key"))
        self.assertNotIn("SECRET_TOKEN", env)
        self.assertEqual(env["COVEY_WEB_PARENT_PID"], str(os.getpid()))  # The page ends itself once this Manager is gone.
        self.assertEqual((self.bin / "node-args").read_text().strip(), str(self.page / "server" / "selfhost" / "main.js"))
        self.assertTrue((self.data / "web" / "logs" / "selfhost.log").exists())
        self.manager.ensure_selfhost()
        self.assertIs(self.manager.selfhost["child"], child)  # Running: left alone.
        manifest(self.root)  # Switch off.
        self.manager.ensure_selfhost()
        self.assertIsNone(self.manager.selfhost["child"])
        self.assertFalse(self.alive(child))

    def test_an_exit_is_started_again(self):
        manifest(self.root, **self.settings)
        self.manager.ensure_selfhost()
        first = self.manager.selfhost["child"]
        os.killpg(first.pid, 9)
        first.wait(5)
        self.manager.ensure_selfhost()  # Sees the exit, backs off (0 s here) and starts again in the same pass or the next.
        self.manager.ensure_selfhost()
        second = self.manager.selfhost["child"]
        self.assertIsNotNone(second)
        self.assertNotEqual(second.pid, first.pid)
        self.assertTrue(any("exited" in line for line in self.logged))

    def test_the_backoff_is_the_services(self):
        manifest(self.root, **self.settings)
        slow = manager.Manager(self.root, base_delay=5, max_delay=300)
        self.addCleanup(slow.stop_selfhost)
        slow.ensure_selfhost()
        child = slow.selfhost["child"]
        os.killpg(child.pid, 9)
        child.wait(5)
        slow.ensure_selfhost()
        self.assertIsNone(slow.selfhost["child"])
        self.assertEqual(slow.selfhost["failures"], 1)
        slow.ensure_selfhost()  # Not before the delay.
        self.assertIsNone(slow.selfhost["child"])

    def test_no_node_or_no_page_is_said_once_and_retried(self):
        manifest(self.root, **self.settings)
        (self.page / "server" / "selfhost" / "main.js").unlink()
        self.manager.ensure_selfhost()
        self.manager.ensure_selfhost()
        self.assertEqual([line for line in self.logged if "not started" in line].__len__(), 1)
        self.assertIsNone(self.manager.selfhost["child"])

    def test_node_is_looked_for_on_the_services_path(self):
        os.environ["PATH"] = os.environ["PATH"].replace(f"{self.bin}:", "")  # Not on the Manager's own PATH (a boot's)...
        manifest(self.root, **self.settings, PATH=f"{self.bin}:/usr/bin:/bin")  # ...but on the one the service registered with.
        self.manager.ensure_selfhost()
        self.assertIsNotNone(self.manager.selfhost["child"])
        self.assertEqual(self.wait_env()["PATH"], f"{self.bin}:/usr/bin:/bin")

    def test_what_an_exit_leaves_in_its_session_is_stopped(self):
        (self.bin / "node").write_text("#!/bin/sh\nsleep 300 &\necho $! > \"$(dirname \"$0\")/left\"\nexit 3\n")
        manifest(self.root, **self.settings)
        self.manager.ensure_selfhost()
        child = self.manager.selfhost["child"]
        child.wait(5)
        deadline = time.monotonic() + 5
        while not (self.bin / "left").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        left = int((self.bin / "left").read_text())
        self.manager.ensure_selfhost()  # Sees the exit.
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(left, 0)
            except ProcessLookupError:
                break
            with contextlib.suppress(ChildProcessError):
                os.waitpid(left, os.WNOHANG)
            time.sleep(0.05)
        else:
            self.fail("the page's leftover was not stopped")
        self.assertTrue(any("exited rc=3" in line for line in self.logged))

    def test_the_manager_ending_takes_it_along(self):
        manifest(self.root, **self.settings)
        self.manager.ensure_selfhost()
        child = self.manager.selfhost["child"]
        self.manager.stop_selfhost()
        self.assertFalse(self.alive(child))
        with self.assertRaises(ProcessLookupError):
            os.killpg(child.pid, 0)  # The group is gone, the sleep under the shell too.


if __name__ == "__main__":
    unittest.main()
