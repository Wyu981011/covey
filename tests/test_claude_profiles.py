"""Configured Claude choices must never fall back to a default command or a different gateway."""
from __future__ import annotations

import argparse
import copy
import dataclasses
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest import mock

from support.fake_backends import CLAUDE_JSONL, RUN, SID, codex_context
from covey.app import availability
from covey.backends.claude import models as native_models, profiles, redaction
from covey.app.launch_models import refresh_catalog
from covey.backends.claude.argv import stream_argv
from covey.backends.claude.bridge import ClaudeBackend
from covey.core.harness import RunCallbacks, RunInputs, RunRequest, RunResult


class ClaudeProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / "profiles.json"
        self.profile = {"id": "remote", "name": "Remote gateway", "status": "ready",
                        "command": [sys.executable, str(CLAUDE_JSONL), "success"],
                        "models": [{"id": "opus", "display_name": "Opus", "efforts": ["high", "max"]}]}
        self.write()
        self.ctx = dataclasses.replace(codex_context(self.root, "stream-json"),
            model="profile/remote/opus", effort="high", backend_cmd=["never-run-default"],
            options={"transport": "stream-json", profiles.CONFIG: str(self.path)})
        self.backend = ClaudeBackend()

    def write(self, rows=None):
        self.path.write_text(json.dumps({"version": 1, "profiles": rows if rows is not None else [self.profile]}))

    def test_explicit_catalog_is_visible_without_probing_its_pending_gateway(self):
        self.profile.update(status="pending", reason="等待账号登录")
        self.write()
        with mock.patch("covey.backends.claude.bridge.model_catalog", side_effect=RuntimeError("offline")) as native, \
             mock.patch("subprocess.Popen") as spawn:
            catalog = self.backend.refresh_model_catalog(self.ctx)
        row = catalog[self.ctx.model]
        self.assertEqual(row["catalog_source"], "configured_profile")
        self.assertEqual(row["unavailable_reason"], self.profile["reason"])
        self.assertEqual(row["provider_title"], self.profile["name"])
        self.assertEqual(row["supported_reasoning_levels"], [{"effort": "high"}, {"effort": "max"}])
        self.assertEqual(native.call_args.args[1].backend_cmd, ["never-run-default"])
        spawn.assert_not_called()
        with mock.patch.object(self.backend, "model_catalog") as queried, self.assertRaisesRegex(ValueError, "等待账号登录"):
            self.backend.normalize_model_settings(self.ctx, self.ctx.model, "high")
        queried.assert_not_called()

    def test_native_catalog_and_unconfigured_context_keep_their_behavior(self):
        native = {"native": {"supported_reasoning_levels": []}}
        with mock.patch("covey.backends.claude.bridge.model_catalog", return_value=native):
            self.assertEqual(set(self.backend.model_catalog(self.ctx)), {"native", self.ctx.model})
            plain = dataclasses.replace(self.ctx, model="native", options={})
            self.assertIs(self.backend.model_catalog(plain), native)
        self.assertIs(profiles.resolve(plain), plain)
        with mock.patch("covey.backends.claude.bridge.model_catalog", side_effect=RuntimeError("offline")), \
             self.assertRaisesRegex(RuntimeError, "offline"):
            self.backend.model_catalog(plain)

    def test_device_execution_cannot_replace_a_selected_profile_with_its_default_account(self):
        ctx = dataclasses.replace(self.ctx, device="fixture-device")
        with mock.patch("subprocess.Popen") as spawn:
            with self.assertRaisesRegex(ValueError, "执行设备"):
                self.backend.run(RunRequest(ctx, "prompt"))
            with self.assertRaisesRegex(ValueError, "执行设备"):
                availability.check_or_raise("claude", ctx)
        spawn.assert_not_called()
        self.assertIn("执行设备", profiles.catalog(ctx)[ctx.model]["unavailable_reason"])
        native = dataclasses.replace(ctx, model="opus", options={})
        self.assertIs(profiles.resolve(native), native)

    def test_ready_executes_the_local_protocol_and_returns_a_verified_reply(self):
        saved, processes = [], []
        answer = self.backend.run(RunRequest(self.ctx, "prompt", callbacks=RunCallbacks(
            verified_reply=saved.append, process=processes.append), inputs=RunInputs(threading.Event(), run_id=RUN)))
        self.assertFalse(answer.is_error)
        self.assertEqual(answer.public_reply.backend, "claude")
        self.assertEqual(answer.public_reply.session_id, SID)
        self.assertEqual(answer.public_reply.text, "Complete answer")
        self.assertTrue(any(reply is not None for reply in saved))
        self.assertTrue(processes and all(process.poll() is not None for process in processes))
        self.assertEqual(self.ctx.model, "profile/remote/opus")
        self.assertEqual(self.ctx.backend_cmd, ["never-run-default"])

    def test_local_paths_session_mcp_and_fork_are_preserved_with_native_model_argv(self):
        mcp = {"mcpServers": {"fixture": {"command": "/fake/local/tool"}}}
        ctx = dataclasses.replace(self.ctx, options={**self.ctx.options, "mcp_config": mcp, "fork_session": SID,
                                                   "login_shell": True})
        with mock.patch("covey.backends.claude.runtime.run_stream", return_value=RunResult("ok", SID)) as run:
            self.backend.run(RunRequest(ctx, "prompt"))
        actual = run.call_args.args[1].context
        self.assertEqual((actual.model, actual.backend_cmd), ("opus", self.profile["command"]))
        self.assertEqual((actual.workdir, actual.state_dir, actual.sessions_dir), (ctx.workdir, ctx.state_dir, ctx.sessions_dir))
        self.assertEqual(actual.options["mcp_config"], mcp)
        argv = stream_argv(self.backend, actual)
        self.assertEqual(argv[0], self.profile["command"][0])
        self.assertNotIn("login_shell", actual.options)
        with mock.patch("covey.backends.claude.bridge.model_catalog") as native:
            self.assertIn(self.ctx.model, self.backend.model_catalog(actual))
        native.assert_not_called()
        self.assertEqual(argv[argv.index("--model") + 1], "opus")
        self.assertIn("--fork-session", argv)
        self.assertEqual(argv[argv.index("--resume") + 1], SID)
        with mock.patch("covey.backends.claude.runtime.compact_only", return_value=True) as compact:
            self.assertTrue(self.backend.compact_session(RunRequest(ctx, "", session_id=SID)))
        self.assertEqual(compact.call_args.args[1].context.backend_cmd, self.profile["command"])
        with mock.patch("covey.backends.claude.handoff.summarize", return_value=("summary", "ok")) as summary:
            self.backend.handoff_summary(ctx, SID, "summary", redact=False)
        self.assertEqual(summary.call_args.args[1].model, "opus")
        self.assertEqual(summary.call_args.args[1].backend_cmd, self.profile["command"])
        with mock.patch("covey.backends.claude.rewind.rewind_files", return_value="done") as rewind:
            self.backend.rewind_files(ctx, SID, "prompt-id")
        self.assertEqual(rewind.call_args.args[1].backend_cmd, self.profile["command"])

    def test_pending_removed_and_invalid_profiles_block_every_execution_entry_after_selection(self):
        actions = [lambda: self.backend.run(RunRequest(self.ctx, "prompt")),
                   lambda: self.backend.compact_session(RunRequest(self.ctx, "", session_id=SID)),
                   lambda: self.backend.handoff_summary(self.ctx, SID, "summary", redact=False),
                   lambda: self.backend.rewind_files(self.ctx, SID, "prompt-id"),
                   lambda: availability.check_or_raise("claude", self.ctx)]
        cases = ["pending", "removed", "model_removed", "invalid", "missing"]
        for case in cases:
            self.profile.update(status="ready")
            self.write()
            if case == "pending":
                self.profile.update(status="pending", reason="等待 SSH 授权")
                self.write()
            elif case == "removed":
                self.write([])
            elif case == "model_removed":
                other = copy.deepcopy(self.profile)
                other["models"][0]["id"] = "sonnet"
                self.write([other])
            elif case == "invalid":
                self.path.write_text("{")
            elif case == "missing":
                self.path.unlink()
            for action in actions:
                with self.subTest(case=case, entry=actions.index(action)), \
                     mock.patch("subprocess.Popen") as spawn, mock.patch("subprocess.run") as call, \
                     self.assertRaises(ValueError):
                    action()
                spawn.assert_not_called()
                call.assert_not_called()

    def test_bad_config_never_silently_uses_native_catalog(self):
        for change in ({"command": ["relative-cli"]}, {"id": "bad/id"}, {"status": "typo"},
                       {"reason": "line\nbreak"}, {"models": [{"id": "opus", "display_name": "Opus", "efforts": ["invented"]}]}):
            bad = {**self.profile, **change}
            self.write([bad])
            with self.subTest(change=change), mock.patch("covey.backends.claude.bridge.model_catalog") as native, \
                 self.assertRaisesRegex(ValueError, "配置无效"):
                self.backend.model_catalog(self.ctx)
            native.assert_not_called()
        self.write([self.profile, self.profile])
        with self.assertRaises(ValueError):
            profiles.load(str(self.path))
        with self.assertRaises(ValueError):
            profiles.load("relative.json")

    def test_cli_and_normalization_keep_configured_model_namespace(self):
        parser = argparse.ArgumentParser()
        self.backend.add_cli_args(parser)
        config = self.backend.build_config(parser.parse_args(["--claude-profiles", str(self.path)]))
        self.assertEqual(config.options[profiles.CONFIG], str(self.path))
        self.assertNotIn(profiles.CONFIG, self.backend.build_config(parser.parse_args([])).options)
        with mock.patch.object(self.backend, "model_catalog") as native:
            self.assertEqual(self.backend.normalize_model_settings(self.ctx, self.ctx.model, "max"), (self.ctx.model, "max"))
            with self.assertRaises(ValueError):
                self.backend.normalize_model_settings(self.ctx, self.ctx.model, "low")
        native.assert_not_called()

    def test_gateway_environment_is_not_inherited_from_the_default_account(self):
        env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:1", "ANTHROPIC_API_KEY": "fixture-default",
               "ANTHROPIC_DEFAULT_SONNET_MODEL": "default-sonnet", "HOME": "/fixture/home", "HTTPS_PROXY": "fixture",
               "CLAUDE_CODE_OAUTH_TOKEN": "fixture-oauth", "ANTHROPIC_CUSTOM_HEADERS": "fixture-header",
               "CLAUDE_CODE_USE_BEDROCK": "1"}
        self.assertEqual(profiles.environment(self.ctx, env), {"HOME": "/fixture/home", "HTTPS_PROXY": "fixture"})
        plain = dataclasses.replace(self.ctx, model="opus", options={})
        self.assertIs(profiles.environment(plain, env), env)

    def test_preflight_uses_full_profile_command_and_never_shares_another_profiles_login(self):
        other = {**self.profile, "id": "other", "command": [sys.executable, "other-wrapper"]}
        self.write([self.profile, other])
        other_ctx = dataclasses.replace(self.ctx, model="profile/other/opus")
        with mock.patch.dict(availability._logins, clear=True), \
             mock.patch.object(availability.shutil, "which", return_value=sys.executable), \
             mock.patch.object(availability.subprocess, "run", return_value=SimpleNamespace(stdout='{"loggedIn":true}')) as run:
            availability.check_or_raise("claude", self.ctx)
            availability.check_or_raise("claude", self.ctx)
            availability.check_or_raise("claude", other_ctx)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args_list[0].args[0], [*self.profile["command"], "auth", "status", "--json"])
            self.assertEqual(run.call_args_list[1].args[0], [*other["command"], "auth", "status", "--json"])
            self.profile["status"] = "pending"
            self.write([self.profile, other])
            with self.assertRaises(ValueError):
                availability.check_or_raise("claude", self.ctx)
            self.assertEqual(run.call_count, 2)

    def test_profile_redaction_requires_its_own_endpoint_and_never_falls_back(self):
        env = {"ANTHROPIC_BASE_URL": "http://127.0.0.1:11", "ANTHROPIC_AUTH_TOKEN": "fixture-default"}
        config = {"upstream": "http://127.0.0.1:12"}
        with mock.patch.object(redaction, "gateway_status", return_value="http://127.0.0.1:13") as status:
            self.assertEqual(redaction.resolve_upstream(self.ctx, env, config), "http://127.0.0.1:13")
        self.assertEqual(status.call_args.args[0].backend_cmd, self.profile["command"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", status.call_args.args[1])
        with mock.patch.object(redaction, "gateway_status", return_value=""), self.assertRaises(redaction.Unavailable):
            redaction.resolve_upstream(self.ctx, env, config)
        self.profile["status"] = "pending"
        self.write()
        with mock.patch.object(redaction, "gateway_status") as status, self.assertRaises(ValueError):
            redaction.resolve_upstream(self.ctx, env, config)
        status.assert_not_called()

    def test_gateway_command_changed_after_resolution_is_refused_before_endpoint_discovery(self):
        resolved = profiles.resolve(self.ctx)
        self.profile["command"] = [sys.executable, "different-gateway-wrapper"]
        self.write()
        with mock.patch.object(redaction, "gateway_status") as status, self.assertRaisesRegex(ValueError, "已变化"):
            redaction.resolve_upstream(resolved, {}, {"upstream": ""})
        status.assert_not_called()
        with mock.patch("subprocess.Popen") as spawn, self.assertRaisesRegex(ValueError, "已变化"):
            self.backend.run(RunRequest(resolved, "prompt"))
        spawn.assert_not_called()

    def test_native_timeout_keeps_last_good_models_for_one_hour_without_hiding_profiles(self):
        self.profile.update(status="pending", reason="等待登录")
        self.write()
        process = mock.Mock()
        process.close.return_value = True
        process.initialize.return_value = {"models": [{"value": "opus", "displayName": "Opus",
            "supportsEffort": True, "supportedEffortLevels": ["high", "max"]}]}
        app = SimpleNamespace(backend=self.backend, spec=SimpleNamespace(name="claude"))
        with mock.patch.object(native_models, "ClaudeProcess", return_value=process), \
             mock.patch.object(native_models.time, "time", return_value=10000):
            self.assertEqual(set(refresh_catalog(app, self.ctx)), {"opus", self.ctx.model})
        path = self.ctx.state_dir / "native-models" / native_models.NATIVE_FILE
        self.assertEqual(json.loads(path.read_text())["at"], 10000)
        # A new bridge process has no in-memory native directory, but the same default command still has it on disk.
        with mock.patch.dict(native_models._CACHE, clear=True), \
             mock.patch("covey.backends.claude.bridge.model_catalog", side_effect=RuntimeError("timeout")):
            for now in (10001, 13599):
                with mock.patch.object(native_models.time, "time", return_value=now):
                    rows = refresh_catalog(app, self.ctx)
                    self.assertEqual(set(rows), {"opus", self.ctx.model})
                    self.assertEqual(rows["opus"]["levels"], ["high", "max"])
                    self.assertEqual(rows[self.ctx.model]["unavailable_reason"], "等待登录")
            self.assertEqual(json.loads(path.read_text())["at"], 10000)  # Repeated failures never renew native freshness.
            with mock.patch.object(native_models.time, "time", return_value=13601):
                self.assertEqual(set(refresh_catalog(app, self.ctx)), {self.ctx.model})
            changed = dataclasses.replace(self.ctx, backend_cmd=["never-run-other-default"])
            with mock.patch.object(native_models.time, "time", return_value=10001):
                self.assertEqual(set(self.backend.refresh_model_catalog(changed)), {self.ctx.model})

    def test_unconfigured_native_probes_do_not_create_the_profile_fallback_cache(self):
        plain = dataclasses.replace(self.ctx, model="opus", options={})
        process = mock.Mock()
        process.close.return_value = True
        process.initialize.return_value = {"models": [{"value": "opus"}]}
        with mock.patch.object(native_models, "ClaudeProcess", return_value=process):
            self.backend.refresh_model_catalog(plain)
        self.assertFalse((plain.state_dir / "native-models" / native_models.NATIVE_FILE).exists())
