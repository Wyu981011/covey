"""deploy.py 的测试：用假 lark-cli（tests/fake_lark_cli.py）和本机的裸 git 仓库，不连飞书。

跑法（在 covey 仓库根目录）：python3 -B -m unittest discover -s web/deploy/miaoda/tests
临时文件放在 TMPDIR 下，跑完删掉。
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import deploy  # noqa: E402

OWNER = "ou_" + "0" * 30 + "aa"


class DeployTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="covey-deploy-test-"))
        self.addCleanup(subprocess.run, ["rm", "-rf", str(self.tmp)])
        bin_dir = self.tmp / "bin"
        bin_dir.mkdir()
        wrapper = bin_dir / "lark-cli"
        wrapper.write_text(f"#!/bin/sh\nexec {sys.executable} {HERE / 'fake_lark_cli.py'} \"$@\"\n")
        wrapper.chmod(0o755)
        npm = bin_dir / "npm"  # 部署前会看 npm 的大版本（npm 12 起妙搭的初始化拉不了模板）
        npm.write_text("#!/bin/sh\necho \"${FAKE_NPM_VERSION:-10.9.0}\"\n")
        npm.chmod(0o755)
        self.out = self.tmp / "out"
        self.env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_LARK_STATE": str(self.tmp / "fake.json"), "FAKE_OWNER": OWNER}
        self.saved_env = {k: os.environ.get(k) for k in ("PATH", "FAKE_LARK_STATE", "FAKE_OWNER", "FAKE_FAIL", "FAKE_RELEASE", "FAKE_MULTIENV", "FAKE_NPM_VERSION")}
        os.environ.update(self.env)
        for k in ("FAKE_FAIL", "FAKE_RELEASE", "FAKE_MULTIENV", "FAKE_NPM_VERSION"):
            os.environ.pop(k, None)
        self.addCleanup(self.restore_env)

    def restore_env(self):
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def run_deploy(self, *extra: str) -> tuple[int, str]:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = deploy.main(["--out-dir", str(self.out), "--owner-open-id", OWNER, "--poll-seconds", "0", *extra])
        return code, buf.getvalue()

    def fake(self) -> dict:
        path = Path(os.environ["FAKE_LARK_STATE"])
        return json.loads(path.read_text()) if path.exists() else {"calls": []}

    def writes(self) -> list[str]:
        names = ("+create", "+feature-enable", "+init", "+db-execute", "+db-env-migrate", "+env-set",
                 "+openapi-key-create", "+release-create", "+access-scope-set")
        return [c for c in self.fake()["calls"] if any(f" {n} " in f" {c} " for n in names)]

    def test_dry_run_writes_nothing(self):
        code, text = self.run_deploy("--dry-run")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.writes(), [])
        self.assertFalse((self.out / "miaoda-deploy.json").exists())
        self.assertIn("[不执行]", text)

    def test_without_yes_refuses(self):
        code, text = self.run_deploy()
        self.assertEqual(code, 2)
        self.assertIn("--yes", text)
        self.assertEqual(self.fake()["calls"], [])

    def test_full_run_then_rerun(self):
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 0, text)
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        self.assertEqual(state["app_id"], "app_demo01")
        self.assertEqual(state["release"]["status"], "finished")
        for k in ("database", "schema", "env", "key", "scope"):
            self.assertTrue(state.get(k), k)
        self.assertNotIn("fake-secret", json.dumps(state))
        self.assertNotIn("fake-secret", text)
        key = Path(state["key_file"])
        self.assertEqual(key.read_text().strip(), "fake-secret-abcd")
        self.assertEqual(stat.S_IMODE(key.stat().st_mode), 0o600)
        cfg = json.loads((self.out / "web.json").read_text())
        self.assertEqual(cfg["base_url"], "https://fake.example.com/app/app_demo01/openapi")
        self.assertEqual(cfg["key_file"], str(key))
        f = self.fake()
        sql = f["sql"]
        self.assertTrue(sql.startswith("BEGIN;"))
        self.assertTrue(sql.rstrip().endswith("COMMIT;"))
        self.assertNotIn("<OWNER_UID>", sql)
        self.assertFalse([line for line in sql.splitlines() if line.lstrip().startswith("--")])
        self.assertEqual(sql.count("100000000042"), 7 + 3 * 2)  # 7 条只读策略各 1 处，3 条读写策略 USING 和 WITH CHECK 各 1 处
        self.assertEqual(sorted(f["tables"]), sorted(deploy.TABLES))
        self.assertEqual(f["env"], {"dev:COVEY_OWNER_USER_ID": "100000000042", "online:COVEY_OWNER_USER_ID": "100000000042"})
        self.assertEqual(f["scope"], {"scope": "specific", "targets": [{"type": "user", "id": OWNER}]})
        self.assertTrue(f["keys"][0]["scope_all"])
        order = [c.split()[1] for c in self.writes()]
        self.assertEqual(order, ["+create", "+feature-enable", "+init", "+db-execute", "+env-set", "+env-set",
                                 "+openapi-key-create", "+release-create", "+access-scope-set"])
        # 推上去的代码：web/ 覆盖进去，平台文件留着，三个代码目录里的模板残留删掉，部署脚本不进应用
        repo = self.tmp / "check"
        subprocess.run(["git", "clone", "-q", "-b", "sprint/default", str(self.tmp / "remote.git"), str(repo)], check=True)
        self.assertTrue((repo / ".spark" / "meta.json").is_file())
        self.assertEqual((repo / "README.md").read_text(), "模板自带的说明\n")
        self.assertTrue((repo / "client" / "src" / "cv" / "Shell.tsx").is_file())
        self.assertFalse((repo / "client" / "src" / "components" / "business-ui").exists())
        self.assertFalse((repo / "server" / "modules" / "hello").exists())
        self.assertFalse((repo / "deploy").exists())
        self.assertEqual((repo / "scripts" / "build.sh").read_bytes(), (deploy.WEB / "scripts" / "build.sh").read_bytes())
        self.assertIn('"name": "covey-web"', (repo / "package.json").read_text())

        # 再跑一遍：什么都不重复做
        before = len(self.fake()["calls"])
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 0, text)
        again = self.fake()["calls"][before:]
        self.assertFalse([c for c in again if any(n in c for n in ("+create", "+db-execute", "+openapi-key-create", "+release-create", "+access-scope-set", "+env-set"))], again)
        self.assertIn("已发布过", text)

    def test_existing_app_needs_adopt_flag(self):
        code, text = self.run_deploy("--yes", "--app-id", "app_other01")
        self.assertEqual(code, 2)
        self.assertIn("--adopt-existing", text)
        self.assertEqual(self.writes(), [])

    def test_no_miaoda_points_to_selfhost(self):
        os.environ["FAKE_FAIL"] = "create"
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 1)
        self.assertIn("自托管", text)

    def test_release_waiting_for_approval(self):
        os.environ["FAKE_RELEASE"] = "pending"
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 3)
        self.assertIn("审批", text)
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        self.assertEqual(state["release"]["status"], "pending_approval")

    def test_multi_env_publishes_schema_to_online(self):
        os.environ["FAKE_MULTIENV"] = "1"
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.fake()["migrated"], 25)
        self.assertIn("发布到 online", text)

    def test_owner_must_be_the_logged_in_user(self):
        os.environ["FAKE_OWNER"] = "ou_" + "1" * 32
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 2)
        self.assertIn("不是 Covey 的主人", text)
        self.assertEqual(self.writes(), [])

    def test_lost_key_file_is_not_silently_replaced(self):
        code, _ = self.run_deploy("--yes")
        self.assertEqual(code, 0)
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        Path(state["key_file"]).unlink()
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 1)
        self.assertIn("重置", text)
        self.assertEqual(len(self.fake()["keys"]), 1)

    def test_npm_12_stops_before_init_and_resumes(self):
        os.environ["FAKE_NPM_VERSION"] = "12.2.1"
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 2)
        self.assertIn("npm 11", text)
        self.assertNotIn("+init", " ".join(self.writes()))
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        self.assertTrue(state["app_id"])
        os.environ["FAKE_NPM_VERSION"] = "11.6.0"
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 0, text)
        self.assertEqual([c.split()[1] for c in self.writes()].count("+create"), 1)

    def test_render_schema(self):
        sql = deploy.render_schema("100000000042")
        self.assertTrue(sql.startswith("BEGIN;"))
        self.assertEqual(sql.count("CREATE TABLE IF NOT EXISTS"), 10)
        self.assertEqual(sql.count("CREATE POLICY"), 20)
        self.assertNotIn("anon", sql)
        with self.assertRaises(deploy.StepFailed):
            deploy.render_schema("1' OR '1'='1")


if __name__ == "__main__":
    unittest.main()
