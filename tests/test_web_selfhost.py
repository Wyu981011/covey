"""自托管网页工作台 (service/web_selfhost.py, service/manager.py ``ensure_selfhost``): the switches a manifest carries become the page
process's command and environment; the preparation writes a 0600 key (never over one that is there) and web.json that load_config
takes; the Manager runs the process only when asked, starts it again after an exit with its backoff, stops its whole group when
the switch goes off or the Manager ends, and does nothing at all when the switch is off."""
from __future__ import annotations

import contextlib
import hashlib
import http.server
import io
import json
import os
import shutil
import signal
import socket
import stat
import subprocess
import tarfile
import tempfile
import threading
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


def fake_page(health, backup=b"", backup_status=200):
    """A loopback server (port 0) that answers /healthz with ``health`` and /openapi/selfhost/backup with ``backup``."""
    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            seen.append((self.path, self.headers.get("Authorization")))
            if self.path == "/healthz":
                body, code = json.dumps(health).encode(), 200
            elif self.path == "/openapi/selfhost/backup":
                body, code = backup, backup_status
            else:
                body, code = b"{}", 404
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, seen


def make_cert(folder, days=365, names="IP:203.0.113.10,DNS:page.example"):
    """A self-signed certificate and key in ``folder`` (openssl); None without openssl."""
    if not shutil.which("openssl"):
        return None
    cert, key = Path(folder) / "cert.pem", Path(folder) / "key.pem"
    subprocess.run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes", "-keyout", str(key),
                    "-out", str(cert), "-days", str(days), "-subj", "/CN=page.example", "-addext", f"subjectAltName={names}"],
                   check=True, capture_output=True)
    os.chmod(key, 0o600)
    return cert, key


class PublicTests(unittest.TestCase):
    def setUp(self):
        tmp = exec_tempdir()  # A fake node is run directly: not on a noexec /dev/shm.
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def settings(self, **more):
        return {"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": "/absolute/page", **more}

    def test_names_are_validated_as_a_whole(self):
        names = lambda text: web_selfhost.public_names({"COVEY_WEB_SELFHOST_PUBLIC": text})  # noqa: E731
        self.assertEqual(names("203.0.113.10, page.example,2001:db8::1,203.0.113.10"), ["203.0.113.10", "page.example", "2001:db8::1"])
        for bad in ("", "[2001:db8::1]", "203.0.113.10,bad name", "1.2.3", "fe80::1%eth0", "a_b.example", "x" * 64 + ".example"):
            self.assertEqual(names(bad), [], bad)
        self.assertIn("公网地址不合法", web_selfhost.public_problem({"COVEY_WEB_SELFHOST_PUBLIC": "203.0.113.10,bad name"}))
        self.assertEqual(web_selfhost.public_problem({}), "")
        self.assertEqual(web_selfhost.public_port_of({"COVEY_WEB_SELFHOST_PUBLIC_PORT": "9443"}), 9443)
        self.assertEqual(web_selfhost.public_port_of({"COVEY_WEB_SELFHOST_PUBLIC_PORT": "0"}), 18443)
        self.assertEqual(web_selfhost.bind_of({}), "0.0.0.0")
        self.assertEqual(web_selfhost.bind_of({"COVEY_WEB_SELFHOST_BIND": "::"}), "::")

    def test_spec_without_public_has_none_and_the_same_environment_as_before(self):
        found = web_selfhost.spec(self.settings(), self.root)
        self.assertIsNone(found["public"])
        self.assertFalse([name for name in found["env"] if "PUBLIC" in name or "TLS" in name])
        self.assertIsNone(web_selfhost.spec(self.settings(COVEY_WEB_SELFHOST_PUBLIC="bad name"), self.root)["public"])

    def test_spec_with_public_adds_the_environment_and_the_block(self):
        found = web_selfhost.spec(self.settings(COVEY_WEB_SELFHOST_PUBLIC="203.0.113.10,page.example", COVEY_WEB_SELFHOST_PUBLIC_PORT="9443",
                                                COVEY_WEB_SELFHOST_BIND="::"), self.root)
        web = self.root / "web"
        self.assertEqual(found["env"]["COVEY_WEB_PUBLIC_NAMES"], "203.0.113.10,page.example")
        self.assertEqual((found["env"]["COVEY_WEB_PUBLIC_PORT"], found["env"]["COVEY_WEB_PUBLIC_HOST"]), ("9443", "::"))
        self.assertEqual(found["env"]["COVEY_WEB_TLS_DIR"], str(web / "tls"))
        self.assertNotIn("COVEY_WEB_TLS_CERT", found["env"])
        self.assertEqual(found["public"], {"names": ["203.0.113.10", "page.example"], "port": 9443, "bind": "::", "tls": "self-signed",
                                           "cert": str(web / "tls" / "cert.pem"), "key": str(web / "tls" / "key.pem")})
        own = web_selfhost.spec(self.settings(COVEY_WEB_SELFHOST_PUBLIC="page.example", COVEY_WEB_SELFHOST_TLS_CERT="/absolute/c.pem",
                                              COVEY_WEB_SELFHOST_TLS_KEY="/absolute/k.pem"), self.root)
        self.assertEqual((own["env"]["COVEY_WEB_TLS_CERT"], own["env"]["COVEY_WEB_TLS_KEY"]), ("/absolute/c.pem", "/absolute/k.pem"))
        self.assertEqual((own["public"]["tls"], own["public"]["cert"]), ("provided", "/absolute/c.pem"))
        half = web_selfhost.spec(self.settings(COVEY_WEB_SELFHOST_PUBLIC="page.example", COVEY_WEB_SELFHOST_TLS_CERT="/absolute/c.pem"), self.root)
        self.assertEqual(half["public"]["tls"], "self-signed")  # One of the two is no certificate.

    def test_prepare_public_url_switches_ports_and_a_fake_tls_command(self):
        page = self.root / "page"
        (page / "server" / "selfhost").mkdir(parents=True)
        cli = page / "server" / "selfhost" / "tls-cli.js"
        cli.write_text("")
        node = self.root / "node"
        node.write_text("#!/bin/sh\necho \"$@\" > \"$(dirname \"$0\")/args\"\n"
                        "echo '{\"cert\":\"c\",\"key\":\"k\",\"fingerprint\":\"AB:CD\",\"not_after\":\"x\",\"names\":[],\"generated\":true}'\n")
        node.chmod(0o755)
        with mock.patch.object(web_selfhost.shutil, "which", return_value=str(node)):
            result = web_selfhost.prepare(self.root / "data", folder=str(page), public=["2001:db8::1", "page.example"], public_port=9443, bind="::")
        self.assertEqual(result["page_url"], "https://[2001:db8::1]:9443/")
        self.assertEqual(result["open_ports"], [9443])
        self.assertEqual(result["fingerprint"], "AB:CD")
        self.assertIn("COVEY_WEB_SELFHOST_PUBLIC=2001:db8::1,page.example", result["switches"])
        self.assertIn("COVEY_WEB_SELFHOST_PUBLIC_PORT=9443", result["switches"])
        self.assertIn("COVEY_WEB_SELFHOST_BIND=::", result["switches"])
        self.assertEqual((self.root / "args").read_text().split(), [str(cli), "--dir", str(self.root / "data" / "web" / "tls"), "--names",
                                                                    "2001:db8::1,page.example"])
        self.assertEqual(json.loads(Path(result["config"]).read_text())["page_url"], "https://[2001:db8::1]:9443/")
        given = web_selfhost.prepare(self.root / "data", public=["page.example"], page_url="https://front.example/")
        self.assertEqual(given["page_url"], "https://front.example/")  # --page-url wins.
        self.assertFalse([line for line in given["switches"] if "PUBLIC_PORT" in line or "BIND" in line])  # Defaults are not written.
        self.assertEqual(given["fingerprint"], "")  # No command to make one now: the page makes it when it starts.

    def test_prepare_without_public_is_as_before_and_refuses_what_is_wrong(self):
        result = web_selfhost.prepare(self.root / "data")
        self.assertEqual((result["public"], result["open_ports"], result["fingerprint"]), (None, [], ""))
        for kwargs in ({"public": ["bad name"]}, {"public": ["page.example"], "tls_cert": "/absolute/c.pem"},
                       {"public": ["page.example"], "tls_cert": "c.pem", "tls_key": "k.pem"}, {"public": ["page.example"], "bind": "nope"},
                       {"public": ["page.example"], "public_port": 0}):
            with self.assertRaises(ValueError, msg=str(kwargs)):
                web_selfhost.prepare(self.root / "data", **kwargs)

    def test_ensure_cert_needs_the_command_and_node(self):
        self.assertIsNone(web_selfhost.ensure_cert("", self.root, ["page.example"]))
        self.assertIsNone(web_selfhost.ensure_cert(str(self.root / "nowhere"), self.root, ["page.example"], node="/absolute/node"))

    def test_suggest_address_only_a_global_one_and_no_packet(self):
        class Sock:
            def __init__(self, found):
                self.found, self.sent = found, []
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def connect(self, target): self.target = target
            def getsockname(self): return (self.found, 0)

        for found, want in (("198.51.100.7", ""), ("169.254.10.20", ""), ("8.8.8.8", "8.8.8.8")):
            with mock.patch.object(web_selfhost.socket, "socket", lambda *a, found=found: Sock(found)):
                self.assertEqual(web_selfhost.suggest_address(), want, found)
        with mock.patch.object(web_selfhost.socket, "socket", side_effect=OSError):
            self.assertEqual(web_selfhost.suggest_address(), "")

    def test_the_command_line_prints_the_ports_url_fingerprint_and_login_steps(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(web_selfhost, "ensure_cert", return_value={"fingerprint": "AB:CD"}):
            self.assertEqual(web_selfhost.main(["--data-root", str(self.root), "--dir", "/absolute/page", "--public", "2001:db8::1",
                                                "--public-port", "9443"]), 0)
        text = out.getvalue()
        for part in ("放行 TCP 端口 9443", "https://[2001:db8::1]:9443/", "AB:CD", "继续访问", "用飞书确认登录", "「允许」",
                     "COVEY_WEB_SELFHOST_PUBLIC=2001:db8::1", "COVEY_WEB_SELFHOST_PUBLIC_PORT=9443"):
            self.assertIn(part, text)
        plain = io.StringIO()
        with contextlib.redirect_stdout(plain):
            web_selfhost.main(["--data-root", str(self.root / "plain"), "--dir", "/absolute/page"])
        self.assertNotIn("公网", plain.getvalue())  # Not asked: nothing about it.
        for argv in (["--public", "bad name"], ["--public", "auto"], ["--tls-cert", "/absolute/c.pem"], ["--public-port", "0"],
                     ["--public", "page.example", "--tls-cert", "c.pem", "--tls-key", "k.pem"]):
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                web_selfhost.main(["--data-root", str(self.root), *argv])

    def test_auto_asks_once_in_a_terminal_and_otherwise_wants_the_address_written(self):
        with mock.patch.object(web_selfhost, "suggest_address", return_value="8.8.8.8"), \
                mock.patch.object(web_selfhost.sys, "stdin") as stdin, mock.patch.object(web_selfhost.sys, "stdout") as stdout:
            stdin.isatty.return_value = stdout.isatty.return_value = True
            with mock.patch("builtins.input", return_value=""):
                self.assertEqual(web_selfhost.main(["--data-root", str(self.root), "--public", "auto"]), 0)
            self.assertEqual(json.loads((self.root / "web" / "web.json").read_text())["page_url"], "https://8.8.8.8:18443/")
            with mock.patch("builtins.input", return_value="n"), self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
                web_selfhost.main(["--data-root", str(self.root), "--public", "auto"])
        with mock.patch.object(web_selfhost, "suggest_address", return_value="8.8.8.8"), self.assertRaises(SystemExit), \
                contextlib.redirect_stderr(io.StringIO()):
            web_selfhost.main(["--data-root", str(self.root), "--public", "auto"])  # Not a terminal.


class CheckTests(unittest.TestCase):
    def setUp(self):
        tmp = exec_tempdir()  # A fake node is run directly: not on a noexec /dev/shm.
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.page = self.root / "page"
        (self.page / "server" / "selfhost").mkdir(parents=True)
        (self.page / "server" / "selfhost" / "main.js").write_text("")
        self.bin = self.root / "bin"
        self.bin.mkdir()
        (self.bin / "node").write_text("#!/bin/sh\n")
        (self.bin / "node").chmod(0o755)
        self.data = self.root / "data"

    def serve(self, health):
        server, seen = fake_page(health)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        return server.server_address[1], seen

    def environ(self, port, **more):
        return {"COVEY_WEB_SELFHOST": "1", "COVEY_WEB_SELFHOST_DIR": str(self.page), "COVEY_WEB_SELFHOST_PORT": str(port),
                "PATH": str(self.bin), **more}

    def whats(self, found):
        return [problem["what"] for problem in found["problems"]]

    def test_all_well_on_the_loopback(self):
        port, seen = self.serve({"ok": True, "pid": 7, "db": "pglite", "public": None})
        web_selfhost.prepare(self.data, port, str(self.page))
        found = web_selfhost.check(self.environ(port), self.data)
        self.assertEqual((found["status"], found["problems"], found["public"]), ("ready", [], None))
        self.assertEqual((found["url"], found["page_url"], found["pid"], found["db"]), (f"http://127.0.0.1:{port}/", f"http://127.0.0.1:{port}/", 7, "pglite"))
        self.assertEqual(seen, [("/healthz", None)])  # Asked the loopback only; the key is not sent.

    def test_each_thing_that_is_wrong_is_said(self):
        port, _ = self.serve({"ok": True, "pid": 7, "db": "pglite"})
        found = web_selfhost.check({"COVEY_WEB_SELFHOST": "1", "PATH": str(self.bin)}, self.data)  # No directory: nothing to ask but the port.
        self.assertEqual(found["status"], "degraded")
        self.assertTrue(any("COVEY_WEB_SELFHOST_DIR" in what for what in self.whats(found)))
        (self.page / "server" / "selfhost" / "main.js").unlink()
        found = web_selfhost.check(self.environ(port, PATH="/absolute/nowhere"), self.data)
        text = "\n".join(self.whats(found))
        for part in ("构建产物不在", "node 不在", "密钥文件不在", "web.json 不在"):
            self.assertIn(part, text)
        self.assertTrue(all(problem["next"] for problem in found["problems"]))
        web_selfhost.prepare(self.data, port + 1)  # A web.json for another port, and a key that others can read.
        os.chmod(self.data / "web" / "web-openapi.key", 0o644)
        found = web_selfhost.check(self.environ(port), self.data)
        text = "\n".join(self.whats(found))
        self.assertIn("权限是 644", text)
        self.assertIn("没指向本机", text)

    def test_no_answer_from_the_page(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            port = taken.getsockname()[1]
        web_selfhost.prepare(self.data, port, str(self.page))
        found = web_selfhost.check(self.environ(port), self.data, timeout=1)
        self.assertEqual(found["status"], "degraded")
        self.assertTrue(any("没有回应" in what for what in self.whats(found)))

    def test_public_all_well_with_a_certificate(self):
        made = make_cert(self.root)
        if made is None:
            self.skipTest("no openssl")
        cert, key = made
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            listener.listen()
            public_port = listener.getsockname()[1]
            port, _ = self.serve({"ok": True, "pid": 7, "db": "pglite", "public": {"listening": True, "error": "", "fingerprint": "AB", "not_after": "x"}})
            web_selfhost.prepare(self.data, port, str(self.page))
            environ = self.environ(port, COVEY_WEB_SELFHOST_PUBLIC="203.0.113.10,page.example", COVEY_WEB_SELFHOST_PUBLIC_PORT=str(public_port),
                                   COVEY_WEB_SELFHOST_BIND="127.0.0.1", COVEY_WEB_SELFHOST_TLS_CERT=str(cert), COVEY_WEB_SELFHOST_TLS_KEY=str(key))
            found = web_selfhost.check(environ, self.data)
            self.assertEqual((found["status"], found["problems"]), ("ready", []))
            public = found["public"]
            self.assertEqual((public["names"], public["port"], public["tls"], public["listening"]), (["203.0.113.10", "page.example"], public_port, "provided", True))
            self.assertEqual(public["fingerprint"], "AB")  # The page's own word for it.
            self.assertRegex(public["not_after"], r"^\d{4}-\d\d-\d\dT")
            fingerprint = web_selfhost.fingerprint_of(cert)  # sha256 of the DER, as browsers show it.
            der = subprocess.run(["openssl", "x509", "-in", str(cert), "-outform", "der"], capture_output=True, check=True).stdout
            self.assertEqual(fingerprint.replace(":", "").lower(), hashlib.sha256(der).hexdigest())
            # A name the certificate does not cover, a key others can read, and a certificate about to expire.
            os.chmod(key, 0o644)
            environ["COVEY_WEB_SELFHOST_PUBLIC"] = "203.0.113.10,other.example"
            found = web_selfhost.check(environ, self.data)
            text = "\n".join(self.whats(found))
            self.assertIn("没盖住这些公网地址：other.example", text)
            self.assertIn("私钥文件权限是 644", text)
            self.assertEqual(found["status"], "degraded")
            os.chmod(key, 0o600)
            with mock.patch.object(web_selfhost.time, "time", return_value=time.time() + 340 * 86400):
                found = web_selfhost.check({**environ, "COVEY_WEB_SELFHOST_PUBLIC": "page.example"}, self.data)
            self.assertEqual([(p["level"], "天后过期" in p["what"]) for p in found["problems"]], [("note", True)])
            self.assertEqual(found["status"], "ready")  # Soon-to-expire is a note, not a fault.
            with mock.patch.object(web_selfhost.time, "time", return_value=time.time() + 400 * 86400):
                self.assertTrue(any("已过期" in what for what in self.whats(web_selfhost.check(environ, self.data))))
            with mock.patch.object(web_selfhost, "cert_facts", return_value=None):  # The private decoder is not there: only said.
                found = web_selfhost.check({**environ, "COVEY_WEB_SELFHOST_PUBLIC": "page.example"}, self.data)
            self.assertEqual([(p["level"], "读不出内容" in p["what"]) for p in found["problems"]], [("note", True)])

    def test_public_not_listening_unreachable_and_a_bad_address(self):
        with socket.socket() as taken:
            taken.bind(("127.0.0.1", 0))
            closed = taken.getsockname()[1]
        port, _ = self.serve({"ok": True, "pid": 7, "db": "pglite", "public": {"listening": False, "error": "证书准备不了：x"}})
        web_selfhost.prepare(self.data, port, str(self.page))
        found = web_selfhost.check(self.environ(port, COVEY_WEB_SELFHOST_PUBLIC="page.example", COVEY_WEB_SELFHOST_PUBLIC_PORT=str(closed),
                                                COVEY_WEB_SELFHOST_BIND="127.0.0.1"), self.data)
        text = "\n".join(self.whats(found))
        self.assertIn("公网 HTTPS 监听没开：证书准备不了：x", text)
        self.assertIn("连不上", text)
        self.assertEqual(found["status"], "degraded")
        found = web_selfhost.check(self.environ(port, COVEY_WEB_SELFHOST_PUBLIC="bad name"), self.data)
        self.assertIsNone(found["public"])
        self.assertTrue(any("公网地址不合法" in what and "没开" in what for what in self.whats(found)))


class RestoreTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.home = self.data / "web"
        self.home.mkdir(parents=True)

    def pglite(self, name="pglite.tar.gz", members=(("/PG_VERSION", b"16\n"), ("/base/1/PG_VERSION", b"16\n"))):
        path = self.root / name
        with tarfile.open(path, "w:gz") as tar:
            for member, data in members:
                info = tarfile.TarInfo(member)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        return path

    def test_a_pglite_tar_is_unpacked_with_its_marker_last(self):
        done = web_selfhost.restore_db(self.pglite(), self.data)
        target = self.home / "db.restore"
        self.assertEqual((done["restored"], done["files"], done["pid"]), (str(target), 2, None))
        self.assertEqual((target / "PG_VERSION").read_text(), "16\n")  # The leading / of a member is dropped.
        self.assertEqual((target / "base" / "1" / "PG_VERSION").read_text(), "16\n")
        self.assertTrue((target / ".covey-restore-complete").is_file())
        self.assertIn("下次它起来", done["message"])
        web_selfhost.restore_db(self.pglite(members=(("/PG_VERSION", b"17\n"),)), self.data)  # An older one is cleared first.
        self.assertEqual(sorted(p.name for p in target.iterdir()), [".covey-restore-complete", "PG_VERSION"])

    def test_a_daily_backup_gives_its_page_member(self):
        inner = self.pglite().read_bytes()
        archive = self.root / "bridge-1.tar.gz"
        with tarfile.open(archive, "w:gz") as tar:
            for name, data in (("jobs/a.json", b"{}"), ("selfhost-web/pglite.tar.gz", inner)):
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
        self.assertEqual(web_selfhost.restore_db(archive, self.data)["files"], 2)
        self.assertTrue((self.home / "db.restore" / "PG_VERSION").is_file())
        plain = self.root / "bridge-2.tar.gz"
        with tarfile.open(plain, "w:gz") as tar:
            info = tarfile.TarInfo("jobs/a.json")
            info.size = 2
            tar.addfile(info, io.BytesIO(b"{}"))
        with self.assertRaises(ValueError):
            web_selfhost.restore_db(plain, self.data)

    def test_unsafe_members_and_wrong_files_are_refused_and_nothing_is_left(self):
        def link(kind):
            path = self.root / "x.tar.gz"
            with tarfile.open(path, "w:gz") as tar:
                info = tarfile.TarInfo("/PG_VERSION")
                info.size = 1
                tar.addfile(info, io.BytesIO(b"1"))
                info = tarfile.TarInfo("/base/link")
                info.type = kind
                info.linkname = "/etc/passwd"
                tar.addfile(info)
            return path

        for source in (self.pglite("up.tar.gz", (("/PG_VERSION", b"1"), ("/../evil", b"x"))), self.pglite("up2.tar.gz", (("/PG_VERSION", b"1"), ("a/../../evil", b"x"))),
                       link(tarfile.SYMTYPE), link(tarfile.LNKTYPE), link(tarfile.CHRTYPE), self.root / "missing.tar.gz"):
            with self.assertRaises(ValueError, msg=str(source)):
                web_selfhost.restore_db(source, self.data)
            self.assertFalse((self.home / "db.restore").exists())
            self.assertFalse((self.root / "evil").exists())
        not_tar = self.root / "bad.tar.gz"
        not_tar.write_bytes(b"nope")
        with self.assertRaises(ValueError):
            web_selfhost.restore_db(not_tar, self.data)
        with self.assertRaises(ValueError):
            web_selfhost.restore_db(self.pglite("other.tar.gz", (("/readme", b"x"),)), self.data)  # Not a database.
        (self.home / "database-url").write_text("postgres://user@db.example/web\n")  # An external Postgres: its own tools.
        with self.assertRaises(ValueError):
            web_selfhost.restore_db(self.pglite(), self.data)

    def test_a_running_page_is_stopped_so_the_manager_starts_it_again(self):
        port_page, _ = fake_page({"ok": True, "pid": 4242, "db": "pglite"})
        self.addCleanup(port_page.shutdown)
        self.addCleanup(port_page.server_close)
        web_selfhost.prepare(self.data, port_page.server_address[1])
        with mock.patch.object(web_selfhost.os, "kill") as kill, mock.patch.object(web_selfhost, "_is_page", return_value=True):
            done = web_selfhost.restore_db(self.pglite(), self.data)
        kill.assert_called_once_with(4242, signal.SIGTERM)
        self.assertEqual(done["pid"], 4242)
        with mock.patch.object(web_selfhost.os, "kill") as kill, mock.patch.object(web_selfhost, "_is_page", return_value=False):
            self.assertIsNone(web_selfhost.restore_db(self.pglite(), self.data)["pid"])  # Not a page process: no signal.
        kill.assert_not_called()

    def test_the_command_line(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(web_selfhost.main(["--data-root", str(self.data), "--restore-db", str(self.pglite())]), 0)
        self.assertIn("db.restore", out.getvalue())
        self.assertFalse((self.home / "web.json").exists())  # Only the restore: nothing else prepared.
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertEqual(web_selfhost.main(["--data-root", str(self.data), "--restore-db", str(self.root / "missing.tar.gz")]), 1)
        self.assertIn("恢复失败", err.getvalue())


if __name__ == "__main__":
    unittest.main()
