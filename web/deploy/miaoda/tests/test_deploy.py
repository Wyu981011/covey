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
        self.saved_env = {k: os.environ.get(k) for k in ("PATH", "FAKE_LARK_STATE", "FAKE_OWNER", "FAKE_FAIL", "FAKE_RELEASE", "FAKE_MULTIENV", "FAKE_NPM_VERSION", "FAKE_OLD_CLI")}
        os.environ.update(self.env)
        for k in ("FAKE_FAIL", "FAKE_RELEASE", "FAKE_MULTIENV", "FAKE_NPM_VERSION", "FAKE_OLD_CLI"):
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
        return [c for c in self.fake()["calls"] if "--help" not in c and any(f" {n} " in f" {c} " for n in names)]

    def test_dry_run_writes_nothing(self):
        code, text = self.run_deploy("--dry-run")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.writes(), [])
        self.assertFalse((self.out / "miaoda-deploy.json").exists())
        self.assertIn("[不执行]", text)

    def test_old_lark_cli_stops_before_any_write_and_says_how_to_fix_it(self):
        os.environ["FAKE_OLD_CLI"] = "1"
        for extra in (("--yes",), ("--dry-run",)):
            with self.subTest(extra=extra):
                code, text = self.run_deploy(*extra)
                self.assertEqual(code, 2, text)
                self.assertIn("本机 lark-cli（版本 1.0.50）", text)
                self.assertIn("--apply-reason", text)
                self.assertIn("lark-cli update", text)
                self.assertIn("npm i -g @larksuite/cli@latest", text)
                calls = self.fake()["calls"]
                self.assertEqual(self.writes(), [])
                self.assertFalse([c for c in calls if c.startswith("apps +release-create") and "--help" not in c])
                self.assertFalse((self.out / "miaoda-deploy.json").exists())
                self.assertFalse((self.tmp / "remote.git").exists())  # 应用的代码仓库一次也没拉过、没推过

    def test_a_lark_cli_that_does_not_answer_is_not_called_old(self):
        from unittest import mock
        with mock.patch.object(deploy, "lark_cli_output", return_value=None):
            code, text = self.run_deploy("--dry-run")
        self.assertEqual(code, 2, text)
        self.assertIn("30 秒内没回答", text)
        self.assertNotIn("不支持 --apply-reason", text)
        self.assertEqual(self.writes(), [])

    def test_a_lark_cli_with_the_flag_passes_the_probe_and_release_still_sends_it(self):
        code, text = self.run_deploy("--yes")
        self.assertEqual(code, 0, text)
        calls = self.fake()["calls"]
        self.assertEqual(calls.index("apps +release-create --help") < calls.index(self.writes()[0]), True)
        self.assertTrue([c for c in calls if c.startswith("apps +release-create") and "--apply-reason" in c])

    def test_only_chat_tab_does_not_probe_because_it_does_not_release(self):
        os.environ["FAKE_OLD_CLI"] = "1"
        self.run_deploy("--only-chat-tab", "--dry-run")
        self.assertFalse([c for c in self.fake()["calls"] if "--help" in c])

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
        self.assertEqual(cfg["page_url"], "https://fake.example.com/app/app_demo01")  # 飞书卡片的「打开网页」靠它
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
        self.assertFalse([c for c in again if "--help" not in c and any(n in c for n in ("+create", "+db-execute", "+openapi-key-create", "+release-create", "+access-scope-set", "+env-set"))], again)
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

    # ---- 私聊顶栏的「工作台」标签 ----

    CHAT = "oc_fake0000000000000000000000000001"
    PAGE = "https://fake.example.com/app/app_demo01"

    def covey_state(self, *, chat=True, profile="bot-prof", app_id="cli_fake"):
        state = self.tmp / "covey-state"
        state.mkdir(exist_ok=True)
        (state / "bot-identity.json").write_text(json.dumps({"app_id": app_id, "owner": OWNER, "profile": profile}))
        if chat:
            (state / "owner-chat.json").write_text(json.dumps({"owner": OWNER, "chat_id": self.CHAT}))
        return str(state)

    def tab_calls(self) -> list[str]:
        return self.fake().get("tab_calls", [])

    def workbench_tabs(self) -> list[dict]:
        return [t for t in self.fake().get("tabs", []) if t.get("tab_name") == "工作台"]

    def test_full_run_makes_the_built_in_tab_as_the_bot_and_rerun_changes_nothing(self):
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), ["GET chat_tabs/list_tabs", "POST chat_tabs", "POST chat_tabs/sort_tabs"])
        self.assertIn("桌面端主页", text)  # 固定到主导航要手工开网页应用能力：只提示，不调接口
        self.assertIn(self.PAGE, text.split("桌面端主页")[1])
        tabs = self.workbench_tabs()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["tab_type"], "url")
        self.assertEqual(tabs[0]["tab_content"], {"url": self.PAGE})
        self.assertEqual([t["tab_id"] for t in self.fake()["tabs"]], ["1", tabs[0]["tab_id"], "2", "3"])  # 消息、工作台、其余原顺序
        self.assertIs(tabs[0]["tab_config"]["is_built_in"], True)  # 飞书内嵌打开，不跳外部浏览器
        api = [c for c in self.fake()["calls"] if c.startswith("api ")]
        self.assertTrue(all(" bot " in c and "--profile bot-prof" in c for c in api), api)  # 机器人身份和机器人的 profile，不是部署用的
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        self.assertEqual(state["chat_tab"]["tab_id"], tabs[0]["tab_id"])
        self.assertNotIn("_bot_profile", state)
        web_before = (self.out / "web.json").read_text()
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), ["GET chat_tabs/list_tabs", "POST chat_tabs", "POST chat_tabs/sort_tabs", "GET chat_tabs/list_tabs"])  # 第二次只读，已在第 2 位不再排
        self.assertEqual(len(self.workbench_tabs()), 1)
        self.assertIn("没动", text)
        self.assertEqual((self.out / "web.json").read_text(), web_before)

    def test_changed_url_updates_in_place(self):
        covey = self.covey_state()
        self.run_deploy("--yes", "--covey-state", covey)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", covey, "--page-url", "https://other.example.com/x")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls()[-1], "POST chat_tabs/update_tabs")
        tabs = self.workbench_tabs()
        self.assertEqual(len(tabs), 1)
        self.assertEqual(tabs[0]["tab_content"]["url"], "https://other.example.com/x")
        self.assertIs(tabs[0]["tab_config"]["is_built_in"], True)

    def test_an_old_tab_without_is_built_in_is_updated_not_duplicated(self):
        os.environ["FAKE_TABS_SEED"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_TABS_SEED", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), ["GET chat_tabs/list_tabs", "POST chat_tabs/update_tabs", "POST chat_tabs/sort_tabs"])
        tabs = self.workbench_tabs()
        self.assertEqual([(t["tab_id"], t["tab_content"]["url"], t["tab_config"]["is_built_in"]) for t in tabs], [("77", self.PAGE, True)])

    def test_dry_run_names_the_plan_and_calls_no_tab_api(self):
        code, text = self.run_deploy("--dry-run", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), [])
        self.assertFalse([c for c in self.fake()["calls"] if c.startswith("api ")])
        self.assertIn("is_built_in=true", text)
        self.assertIn("update_tabs", text)
        code, text = self.run_deploy("--only-chat-tab", "--dry-run", "--covey-state", self.covey_state(), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), [])

    def test_no_owner_chat_yet_does_not_block_and_says_how_to_redo(self):
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state(chat=False))
        self.assertEqual(code, 0, text)
        self.assertIn("还没和机器人私聊过", text)
        self.assertIn("--only-chat-tab --yes", text)
        self.assertEqual(self.tab_calls(), [])
        self.assertTrue((self.out / "web.json").is_file())
        self.assertIn("全部做完", text)

    def test_missing_scope_does_not_block_and_names_it(self):
        os.environ["FAKE_TABS_WRITE"] = "deny"
        self.addCleanup(os.environ.pop, "FAKE_TABS_WRITE", None)
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertIn("im:chat.tabs:write_only", text)
        self.assertIn("--only-chat-tab --yes", text)
        self.assertIn("--covey-state", text)
        self.assertEqual(self.workbench_tabs(), [])
        state = json.loads((self.out / "miaoda-deploy.json").read_text())
        self.assertNotIn("chat_tab", state)
        self.assertEqual(json.loads((self.out / "web.json").read_text())["page_url"], self.PAGE)

    def test_other_api_errors_do_not_block_either(self):
        os.environ["FAKE_TABS_WRITE"] = "error"
        self.addCleanup(os.environ.pop, "FAKE_TABS_WRITE", None)
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertIn("invalid chat_id", text)
        self.assertNotIn("缺 im:chat.tabs:write_only", text)

    def test_unreadable_tabs_fall_back_to_the_recorded_tab_id(self):
        covey = self.covey_state()
        self.run_deploy("--yes", "--covey-state", covey)  # 先建好并记下 tab_id
        os.environ["FAKE_TABS_READ"] = "deny"
        self.addCleanup(os.environ.pop, "FAKE_TABS_READ", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", covey, "--page-url", "https://other.example.com/y")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls()[-2:], ["GET chat_tabs/list_tabs", "POST chat_tabs/update_tabs"])
        self.assertEqual([t["tab_content"]["url"] for t in self.workbench_tabs()], ["https://other.example.com/y"])

    def test_unreadable_tabs_with_tab_id_given_never_create_a_second(self):
        os.environ["FAKE_TABS_READ"] = "deny"
        os.environ["FAKE_TABS_SEED"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_TABS_READ", None)
        self.addCleanup(os.environ.pop, "FAKE_TABS_SEED", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE, "--tab-id", "77")
        self.assertEqual(code, 0, text)
        self.assertNotIn("POST chat_tabs", self.tab_calls())
        self.assertEqual(len(self.workbench_tabs()), 1)

    def test_a_profile_of_another_app_is_not_used(self):
        os.environ["FAKE_APP_ID"] = "cli_someone_else"
        self.addCleanup(os.environ.pop, "FAKE_APP_ID", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertIn("不是同一个", text)
        self.assertEqual(self.tab_calls(), [])

    def test_no_known_bot_profile_asks_for_one(self):
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(profile=""), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertIn("--bot-profile", text)
        self.assertEqual(self.tab_calls(), [])
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(profile=""), "--page-url", self.PAGE,
                                     "--bot-profile", "given")
        self.assertEqual(code, 0, text)
        self.assertEqual(len(self.workbench_tabs()), 1)
        self.assertTrue(any("--profile given" in c for c in self.fake()["calls"] if c.startswith("api ")))

    def test_only_chat_tab_touches_nothing_else_and_reads_page_url_from_web_json(self):
        self.out.mkdir()
        (self.out / "web.json").write_text(json.dumps({"base_url": "https://x.example.com/openapi", "page_url": self.PAGE}))
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertEqual(self.writes(), [])
        self.assertFalse([c for c in self.fake()["calls"] if c.startswith("apps ")])
        self.assertEqual([t["tab_content"]["url"] for t in self.workbench_tabs()], [self.PAGE])

    def test_skip_chat_tab(self):
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state(), "--skip-chat-tab")
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls(), [])

    def test_sort_moves_only_the_workbench_next_to_the_message_tab(self):
        os.environ["FAKE_TABS_SEED"] = "1"  # 旧的「工作台」排在最后：消息、Pin、文件、工作台
        self.addCleanup(os.environ.pop, "FAKE_TABS_SEED", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertEqual([t["tab_id"] for t in self.fake()["tabs"]], ["1", "77", "2", "3"])
        self.assertIn("第 2 位", text)
        calls = self.fake()["calls"]
        sort = [c for c in calls if "sort_tabs" in c][0]
        self.assertIn('"tab_ids": ["1", "77", "2", "3"]', sort)  # 全部标签的 ID，消息在内

    def test_already_second_means_no_sort_call_and_only_chat_tab_sorts_too(self):
        covey = self.covey_state()
        self.run_deploy("--only-chat-tab", "--yes", "--covey-state", covey, "--page-url", self.PAGE)
        before = len(self.tab_calls())
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", covey, "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertEqual(self.tab_calls()[before:], ["GET chat_tabs/list_tabs"])
        self.assertIn("已经在第 2 位", text)

    def test_keep_tab_order_skips_sorting(self):
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE, "--keep-tab-order")
        self.assertEqual(code, 0, text)
        self.assertNotIn("POST chat_tabs/sort_tabs", self.tab_calls())

    def test_no_tab_list_in_the_response_skips_sorting_and_says_how_to_redo(self):
        os.environ["FAKE_TABS_NOLIST"] = "1"
        self.addCleanup(os.environ.pop, "FAKE_TABS_NOLIST", None)
        code, text = self.run_deploy("--only-chat-tab", "--yes", "--covey-state", self.covey_state(), "--page-url", self.PAGE)
        self.assertEqual(code, 0, text)
        self.assertNotIn("POST chat_tabs/sort_tabs", self.tab_calls())
        self.assertIn("没排", text)
        self.assertIn("--only-chat-tab --yes", text)

    def test_a_sort_error_does_not_block(self):
        os.environ["FAKE_TABS_SORT"] = "error"
        self.addCleanup(os.environ.pop, "FAKE_TABS_SORT", None)
        code, text = self.run_deploy("--yes", "--covey-state", self.covey_state())
        self.assertEqual(code, 0, text)
        self.assertIn("sort failed", text)
        self.assertIn("全部做完", text)
        self.assertEqual(len(self.workbench_tabs()), 1)

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
