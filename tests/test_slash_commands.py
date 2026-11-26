"""Feishu official slash commands (core/app_manifest.py, feishu/slash_commands.py, app/bot_menu.py,
app/card_routing.py, service/app_check.py): manifest filtering, exact slash parsing, idempotent Bot OpenAPI sync
(create, skip unchanged, update changed, keep unrelated commands, tolerate missing scope or older lark-cli),
routing in private chat and personal groups with strict owner/scope boundaries, and zero-browser app_check apply."""
from __future__ import annotations

import io
import json
import subprocess
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

from support.world import UnifiedCase

from covey.core import app_manifest, spaces
from covey.core.groups import group_path
from covey.core.state import write_json
from covey.feishu import slash_commands
from covey.service import app_check


class ManifestSlashTests(unittest.TestCase):
    def test_slash_commands_always_have_the_board_and_follow_the_proxy_sender(self):
        with mock.patch.object(app_manifest, "proxy_sender", return_value=False):
            self.assertEqual([c.command for c in app_manifest.slash_commands({})], ["usage", "board", "settings"])
            self.assertEqual([c.command for c in app_manifest.slash_commands({"COVEY_DIGEST_TIMES": "off"})],
                             ["usage", "board", "settings"])
        with mock.patch.object(app_manifest, "proxy_sender", return_value=True):
            self.assertEqual([c.command for c in app_manifest.slash_commands({})],
                             ["usage", "board", "proxy", "settings"])

    def test_slash_key_matches_exact_commands_and_aliases_only(self):
        cases = {
            "/usage": "weekly_usage",
            "/USAGE ": "weekly_usage",
            "/用量": "weekly_usage",
            "/board": "digest_board",
            " /看板\u200b": "digest_board",
            "/proxy": "proxy_settings",
            "/代答\u00a0": "proxy_settings",
            "/settings": "bridge_settings",
            "/Settings": "bridge_settings",
            "/设置": "bridge_settings",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(app_manifest.slash_key(raw), expected)

        non_matches = (
            "", "/", "settings", "设置", "/settings 改模型", "/settings\n第二行",
            "/settings/sub", "/absolute/work/project", "/compact", "/goal", "/pair 123456",
            "/help", "帮我打开 /settings", None, 123,
        )
        for raw in non_matches:
            with self.subTest(raw=raw):
                self.assertEqual(app_manifest.slash_key(raw), "")


class SlashSyncTests(unittest.TestCase):
    def _item(self, spec, *, desc=None, icon_key=None):
        text = spec.description if desc is None else desc
        return {
            "command_id": "cmd_" + spec.command,
            "command": spec.command,
            "description": {"default_value": text, "i18n": {"zh_cn": text, "en_us": spec.en_description}},
            "icon": {"icon_key": icon_key or spec.icon_key},
        }

    def test_sync_creates_missing_skips_unchanged_updates_drifted_and_preserves_other_commands(self):
        specs = {s.command: s for s in app_manifest.SLASH_COMMANDS}
        existing = [
            self._item(specs["usage"]),
            self._item(specs["settings"], desc="旧说明"),
            {"command_id": "cmd_custom", "command": "custom", "description": {"default_value": "用户自定义"}},
        ]
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            if "+slash-command-list" in argv:
                return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "data": {"items": existing}}), "")
            if "+slash-command-create" in argv:
                cmd = argv[argv.index("--command") + 1]
                return subprocess.CompletedProcess(
                    argv, 0, json.dumps({"ok": True, "data": {"command_id": "new_" + cmd, "command": cmd}}), "")
            raise AssertionError(f"unexpected argv: {argv}")

        with mock.patch.object(app_manifest, "proxy_sender", return_value=False):
            result = slash_commands.sync("covey", {"COVEY_BOARD": "1"}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["wanted"], ["usage", "board", "settings"])
        self.assertEqual(result["unchanged"], ["usage"])
        self.assertEqual(result["synced"], ["board", "settings"])
        self.assertEqual(result["failed"], [])
        self.assertEqual(len(calls), 3)  # 1 list + 2 creates (board & settings); usage skipped, custom untouched.
        for write_argv in calls[1:]:
            self.assertIn("--force", write_argv)
            self.assertIn("--as", write_argv)
            self.assertEqual(write_argv[write_argv.index("--icon-key") + 1], app_manifest.SLASH_ICON)
            self.assertFalse(any("delete" in part for part in write_argv))

    def test_sync_makes_zero_writes_when_everything_already_matches(self):
        specs = {s.command: s for s in app_manifest.SLASH_COMMANDS}
        existing = [self._item(specs["usage"]), self._item(specs["board"]), self._item(specs["settings"])]
        calls = []

        def runner(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"ok": True, "data": {"items": existing}}), "")

        with mock.patch.object(app_manifest, "proxy_sender", return_value=False):
            result = slash_commands.sync("covey", {}, runner=runner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["synced"], [])
        self.assertEqual(result["unchanged"], ["usage", "board", "settings"])
        self.assertEqual(len(calls), 1)

    def test_sync_tolerates_missing_scope_and_older_lark_cli(self):
        no_scope = lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, json.dumps({"ok": False, "error": {"code": 99991672, "message": "Access denied: missing scope"}}), "")
        old_cli = lambda argv, **kw: subprocess.CompletedProcess(
            argv, 1, "", 'Error: unknown command "+slash-command-list" for "lark-cli application"')

        with mock.patch.object(app_manifest, "proxy_sender", return_value=False):
            r1 = slash_commands.sync("covey", {}, runner=no_scope)
            r2 = slash_commands.sync("covey", {}, runner=old_cli)
        self.assertEqual((r1["ok"], r1["error"]), (False, "no_scope"))
        self.assertEqual((r2["ok"], r2["error"]), (False, "unsupported"))


class SlashRoutingTests(UnifiedCase):
    def setUp(self):
        super().setUp()
        self.menu_calls = []
        self.butler_calls = []
        self.topic_calls = []
        self.sent_ids = iter([f"om_card_{i}" for i in range(1, 20)])
        self.keys = ("weekly_usage", "digest_board", "proxy_settings", "bridge_settings")
        self.app.menu.actions = {
            key: (lambda k: lambda ctx, chat, source, shown: (
                self.menu_calls.append((k, chat, source)), shown(next(self.sent_ids))))(key)
            for key in self.keys
        }
        self.app.butler.handle_event = lambda ctx, event, owner: self.butler_calls.append(event["message_id"]) or False
        self.app.topics.route_or_refuse = lambda ctx, event: (self.topic_calls.append(event["message_id"]), None)[1]

    def send(self, content, *, mid="m1", chat_id="oc_dm", chat_type="p2p", sender="owner", **extra):
        event = {"chat_id": chat_id, "chat_type": chat_type, "sender_type": "user", "sender_id": sender,
                 "message_id": mid, "content": content, **extra}
        self.app.handle_event(event, self.ctx)

    def test_owner_dm_slash_commands_open_menu_without_starting_topic_or_butler(self):
        self.send("/settings", mid="m1")
        self.send(json.dumps({"text": "/board "}), mid="m2", message_type="text")
        self.send("/用量\u200b", mid="m3")
        self.send("/代答", mid="m4")
        self.assertEqual(self.menu_calls, [
            ("bridge_settings", "oc_dm", "m1"),
            ("digest_board", "oc_dm", "m2"),
            ("weekly_usage", "oc_dm", "m3"),
            ("proxy_settings", "oc_dm", "m4"),
        ])
        self.assertEqual(self.butler_calls, [])
        self.assertEqual(self.topic_calls, [])

    def test_repeated_slash_command_sends_fresh_card_and_recalls_previous_and_dedups_message_id(self):
        self.send("/settings", mid="m1")
        self.send("/settings", mid="m1")  # Duplicate delivery of same message_id: skipped.
        self.assertEqual(len(self.menu_calls), 1)
        self.send("/settings", mid="m2")  # New /settings message: fresh card, recalls om_card_1.
        self.assertEqual(len(self.menu_calls), 2)
        self.app.messenger.recall.assert_called_once_with(self.ctx.profile, "om_card_1")

    def test_threads_quotes_attachments_args_paths_and_other_slash_messages_are_not_intercepted(self):
        self.send("/settings", mid="m_thread", thread_id="omt_1")
        self.send("/settings", mid="m_reply", reply_to="om_prev")
        self.send("/settings", mid="m_parent", parent_id="om_prev")
        self.send("/settings", mid="m_root", root_id="om_root")
        self.send("/settings", mid="m_img", message_type="image")
        self.send(json.dumps({"text": "/settings ![Image](img_v3_0123456789abcdef)"}), mid="m_attach")
        self.send("/settings 帮我改模型", mid="m_args")
        self.send("/absolute/work/project", mid="m_path")
        self.send("/compact", mid="m_other")
        self.assertEqual(self.menu_calls, [])
        self.assertEqual(len(self.butler_calls), 9)

    def test_disabled_menu_command_is_not_intercepted(self):
        del self.app.menu.actions["digest_board"]
        self.send("/board", mid="m1")
        self.assertEqual(self.menu_calls, [])
        self.assertEqual(self.butler_calls, ["m1"])

    def test_stranger_and_team_group_never_open_menu_while_personal_group_opens_safe_subset(self):
        # Stranger in DM is refused by access.admit.
        self.send("/settings", mid="m_stranger", sender="ou_stranger")
        self.assertEqual(self.menu_calls, [])

        # Active team group: even the owner's @bot /settings must not leak private settings card into a team chat.
        self.app.runtime.access.identify(app_id="cli_bot", bot_open_id="ou_bot")
        write_json(group_path(self.ctx.state_dir, "oc_team"), {"chat_id": "oc_team", "active": True, "external": False})
        mention = [{"id": "ou_bot", "key": "@_user_1", "name": "Covey"}]
        self.send("@_user_1 /settings", mid="m_team_owner", chat_id="oc_team", chat_type="group",
                  sender="owner", mentions=mention)
        self.send("@_user_1 /settings", mid="m_team_member", chat_id="oc_team", chat_type="group",
                  sender="ou_colleague", mentions=mention)
        self.assertEqual(self.menu_calls, [])

        # Personal group: owner can trigger /settings, /board, /usage, but NOT /proxy.
        self.app.runtime.access.spaces = spaces.Settings(personal_groups=frozenset({"oc_personal"}))
        self.send("@_user_1 /settings", mid="m_pg1", chat_id="oc_personal", chat_type="group",
                  sender="owner", mentions=mention)
        self.send("@_user_1 /board", mid="m_pg2", chat_id="oc_personal", chat_type="group",
                  sender="owner", mentions=mention)
        self.send("@_user_1 /proxy", mid="m_pg3", chat_id="oc_personal", chat_type="group",
                  sender="owner", mentions=mention)
        self.assertEqual(self.menu_calls, [
            ("bridge_settings", "oc_personal", "m_pg1"),
            ("digest_board", "oc_personal", "m_pg2"),
        ])
        self.assertIn("m_pg3", self.butler_calls)


class AppCheckSlashTests(unittest.TestCase):
    def test_apply_syncs_slash_commands_without_needing_playwright_when_app_needs_no_console_changes(self):
        args = SimpleNamespace(profile="covey", app_id="cli_x", review=False, python="", login_from="", work="")
        synced = {"ok": True, "error": "", "detail": "", "wanted": ["usage", "settings"],
                  "synced": ["usage", "settings"], "unchanged": [], "failed": []}
        out = io.StringIO()
        with mock.patch.object(slash_commands, "sync", return_value=synced) as sync_mock, \
                mock.patch.object(app_check, "survey", return_value=({"version": "1.0.2"}, [], [])), \
                mock.patch.object(app_check, "playwright_python", side_effect=AssertionError("browser not needed")), \
                redirect_stdout(out):
            code = app_check.apply(args)
        self.assertEqual(code, app_check.NOTHING)
        sync_mock.assert_called_once_with("covey")
        self.assertIn("斜杠命令已注册：/usage、/settings", out.getvalue())

    def test_check_reports_missing_slash_commands_in_json(self):
        args = SimpleNamespace(profile="covey", app_id="cli_x", review=False, json=True)
        out = io.StringIO()
        missing_specs = [app_manifest.SLASH_COMMANDS[0]]
        with mock.patch.object(app_check, "survey", return_value=({"version": "1.0.2"}, [], [])), \
                mock.patch.object(slash_commands, "missing", return_value=(missing_specs, "")), \
                redirect_stdout(out):
            code = app_check.check(args)
        self.assertEqual(code, app_check.SOMETHING)
        report = json.loads(out.getvalue())
        self.assertEqual(report["offer"], [])
        self.assertEqual(report["slash_missing"], ["usage"])


if __name__ == "__main__":
    unittest.main()
