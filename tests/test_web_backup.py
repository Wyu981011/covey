"""The self-hosted page's database in the daily backup (core/web_backup.py, core/backup.py): the snapshot asks the page on the loopback
only when COVEY_WEB_SELFHOST=1 and says why it did not; the backup package holds it as selfhost-web/pglite.tar.gz, the state
directory's restore leaves it alone, maintenance-status.json records web_backup, and with the switch off nothing changes."""
from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from covey.core import backup, web_backup
from covey.core.maintenance import maintain
from covey.core.state import write_json
from test_web_selfhost import fake_page
from unittest import mock

DUMP = b"\x1f\x8b" + b"not really a database but gzip-shaped"


def pglite_tar(members):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w:gz") as tar:
        for name, data in members:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return out.getvalue()


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def page(self, backup_body=DUMP, status=200):
        server, seen = fake_page({"ok": True}, backup_body, status)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        key = self.root / "key"
        key.write_text("fake-key-for-tests\n")
        config = self.root / "web.json"
        write_json(config, {"base_url": f"http://127.0.0.1:{server.server_address[1]}/openapi", "key_file": str(key)})
        return seen, {"COVEY_WEB": "1", "COVEY_WEB_CONFIG": str(config), "COVEY_WEB_SELFHOST": "1"}

    def test_the_page_is_asked_with_the_key_and_its_dump_is_the_member(self):
        seen, environ = self.page()
        name, data, info = web_backup.snapshot(environ)
        self.assertEqual((name, data, info), ("selfhost-web/pglite.tar.gz", DUMP, {"bytes": len(DUMP)}))
        self.assertEqual(seen, [("/openapi/selfhost/backup", "Bearer fake-key-for-tests")])

    def test_off_or_not_applicable_asks_nothing(self):
        seen, environ = self.page()
        for change, reason in (({"COVEY_WEB_SELFHOST": "0"}, None), ({"COVEY_WEB_SELFHOST": ""}, None), ({"COVEY_WEB": "0"}, "COVEY_WEB 没开"),
                               ({"COVEY_WEB_CONFIG": ""}, "COVEY_WEB_CONFIG 没设")):
            name, data, info = web_backup.snapshot({**environ, **change})
            self.assertEqual((name, data), (None, None))
            self.assertEqual(info, {} if reason is None else {"skipped": reason})
        write_json(self.root / "far.json", {"base_url": "https://page.example/openapi", "key_file": str(self.root / "key")})
        self.assertEqual(web_backup.snapshot({**environ, "COVEY_WEB_CONFIG": str(self.root / "far.json")})[2], {"skipped": "网页不在本机回环上"})
        self.assertEqual(seen, [])  # Not one request.

    def test_a_page_that_cannot_or_will_not_says_why(self):
        for status, want in ((409, "skipped"), (413, "error"), (500, "error")):
            _, environ = self.page(b"{}", status)
            name, data, info = web_backup.snapshot(environ)
            self.assertEqual((name, data, list(info)), (None, None, [want]), status)
        _, environ = self.page(b"not gzip")
        self.assertIn("error", web_backup.snapshot(environ)[2])
        _, environ = self.page(DUMP * 10)
        self.assertEqual(web_backup.snapshot(environ, limit=20)[2], {"error": "数据库超过备份上限"})
        _, environ = self.page()
        (self.root / "key").write_text("")  # The key file says nothing: said, and never the key.
        self.assertIn("error", web_backup.snapshot(environ)[2])
        write_json(self.root / "web.json", {"base_url": "http://127.0.0.1:9/openapi", "key_file": str(self.root / "key")})
        (self.root / "key").write_text("fake-key-for-tests\n")
        self.assertIn("error", web_backup.snapshot(environ)[2])  # Nothing listens there.


class UnpackTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_leading_slashes_go_and_files_are_private(self):
        target = self.root / "out"
        self.assertEqual(web_backup.unpack(pglite_tar([("/PG_VERSION", b"16"), ("/base/1/x", b"y")]), target), 2)
        self.assertEqual((target / "base" / "1" / "x").read_bytes(), b"y")
        self.assertEqual((target / "PG_VERSION").stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.stat().st_mode & 0o777, 0o700)

    def test_too_big_and_unsafe_are_refused_and_the_folder_is_removed(self):
        for data, kwargs in ((pglite_tar([("/a", b"x" * 10)]), {"limit": 5}), (pglite_tar([("../a", b"x")]), {}), (b"junk", {})):
            with self.assertRaises(ValueError):
                web_backup.unpack(data, self.root / "out", **kwargs)
            self.assertFalse((self.root / "out").exists())


class BackupTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.state = self.root / "state"
        (self.state / "jobs").mkdir(parents=True)
        (self.state / "jobs" / "one.json").write_text(json.dumps({"key": "one", "status": "done"}))

    def status(self):
        return json.loads((self.state / "maintenance-status.json").read_text())

    def test_extra_members_are_in_the_package_and_its_manifest_and_a_state_restore_skips_them(self):
        archive = backup.create_backup(self.state, [("selfhost-web/pglite.tar.gz", DUMP)])
        manifest = backup.verify_backup(archive)
        self.assertEqual(sorted(manifest), ["jobs/one.json", "selfhost-web/pglite.tar.gz"])
        with tarfile.open(archive) as tar:
            self.assertEqual(tar.extractfile("selfhost-web/pglite.tar.gz").read(), DUMP)
        restored = self.root / "restored"
        backup.restore_backup(archive, restored)
        self.assertTrue((restored / "jobs" / "one.json").is_file())
        self.assertFalse((restored / "selfhost-web").exists())
        for bad in ("../x", "/abs", "jobs/one.json"):
            with self.assertRaises(ValueError):
                backup.create_backup(self.state, [(bad, b"x")])

    def test_switch_off_the_package_and_the_status_are_as_before(self):
        with mock.patch.object(web_backup, "snapshot", wraps=web_backup.snapshot) as snap:
            archive = backup.back_up(self.state, now=1000.0)
        snap.assert_called_once()
        self.assertEqual(sorted(backup.verify_backup(archive)), ["jobs/one.json"])
        self.assertNotIn("web_backup", self.status())

    def test_back_up_records_what_the_page_gave_or_why_not(self):
        with mock.patch.object(web_backup, "snapshot", return_value=("selfhost-web/pglite.tar.gz", DUMP, {"bytes": len(DUMP)})):
            archive = backup.back_up(self.state, now=1000.0)
        self.assertIn("selfhost-web/pglite.tar.gz", backup.verify_backup(archive))
        self.assertEqual(self.status()["web_backup"], {"at": 1000.0, "bytes": len(DUMP)})
        with mock.patch.object(web_backup, "snapshot", return_value=(None, None, {"error": "URLError"})):
            archive = backup.back_up(self.state, now=2000.0)  # The page is down: the state directory is still backed up.
        self.assertEqual(sorted(backup.verify_backup(archive)), ["jobs/one.json"])
        self.assertEqual(self.status()["web_backup"], {"at": 2000.0, "error": "URLError"})
        self.assertEqual(self.status()["last_backup"], 2000.0)

    def test_the_idle_maintenance_backup_takes_it_too_and_keeps_the_record(self):
        with mock.patch.object(web_backup, "snapshot", return_value=("selfhost-web/pglite.tar.gz", DUMP, {"bytes": len(DUMP)})):
            plan = maintain(self.state, apply=True, now=5000.0)
        self.assertIn("selfhost-web/pglite.tar.gz", backup.verify_backup(Path(plan["backup"])))
        self.assertEqual(self.status()["web_backup"], {"at": 5000.0, "bytes": len(DUMP)})
        maintain(self.state, apply=True, now=5001.0, backup=False)  # No backup this time: the last word on the page's stays.
        self.assertEqual(self.status()["web_backup"], {"at": 5000.0, "bytes": len(DUMP)})


if __name__ == "__main__":
    unittest.main()
