"""The butler and a project's lead off Claude Code (T664): which Harness the butler runs on when its settings name none
(app/butler_harness.py), the lead's app before and after its topic.json (app/project_loop.py lead_app, app/projects.py
step_lead), the lead held to reading on every Harness that takes the Bridge's tools (core/harness.py LEAD: Claude Code's
tools, Codex's read-only sandbox with the Bridge's tools approved, Antigravity's deny rules), refused on one that does not
(app/tool_limits.py refusal), and the small model's callers going where app/track_judge.py tools puts them."""
from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import make_context

from covey.app import butler_harness, project_loop, tidy_facts, tool_limits, track_judge
from covey.backends.agy.bridge import READ_ONLY_SETTINGS, AntigravityBackend
from covey.backends.codex import appserver
from covey.backends.codex.bridge import CodexBackend
from covey.core import butler_settings
from covey.core.harness import (CONSULT, LEAD, LOOK, READ, TOOL_LIMIT, HarnessCapabilities, backend_capabilities)
from covey.core.redaction import TOPIC_KEY as REDACTION_KEY

BRIDGE_TOOLS = {"mcpServers": {"bridge": {"command": "python3", "args": ["mcp.py"], "env": {"K": "v"}}}}


def app(name, *, tools=True, ask_once=False, workdir="/absolute/work"):
    backend = SimpleNamespace(capabilities=lambda ctx: HarnessCapabilities(bridge_tools=tools, ask_once=ask_once))
    context = SimpleNamespace(default_workdir=Path(workdir), state_dir=Path("/absolute/state"), device=None,
                              options={"harness_id": name}, backend_cmd=[name])
    return SimpleNamespace(backend=backend, harness=SimpleNamespace(backend=backend, context=context))


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        (self.root / "work").mkdir()


class ChoiceTest(Case):
    def test_none_named_claude_code_while_it_can_else_codex_else_antigravity(self):
        claude, codex, agy = app("claude"), app("codex"), app("agy")
        for apps, want in (({"claude": claude, "codex": codex, "agy": agy}, "claude"),
                           ({"codex": codex, "agy": agy, "pi": app("pi", tools=False)}, "codex"),
                           ({"agy": agy, "dsh": app("dsh", tools=False)}, "agy"),
                           ({"claude": app("claude", tools=False), "agy": agy}, "agy"),
                           ({"pi": app("pi", tools=False)}, "claude"), ({}, "claude")):
            with self.subTest(apps=sorted(apps)):
                self.assertEqual(butler_harness.default_name(apps), want)
                name, chosen = butler_harness.chosen(self.state, apps)
                self.assertEqual(name, want)
                self.assertIs(chosen, apps.get(want) if apps.get(want) and butler_harness.takes_tools(apps[want]) else None)

    def test_codex_and_antigravity_come_before_pi_and_deepseek_without_claude_code(self):
        """T700: Pi and DeepSeek Harness take the Bridge's tools too; a butler with no Harness named still falls back to
        Codex, then Antigravity, and to them only where neither is enabled."""
        pi, dsh, agy = app("pi"), app("dsh"), app("agy")
        for apps, want in (({"dsh": dsh, "pi": pi, "agy": agy}, "agy"), ({"pi": pi, "codex": app("codex")}, "codex"),
                           ({"pi": pi, "dsh": dsh}, "dsh"), ({"pi": pi}, "pi")):
            with self.subTest(apps=sorted(apps)):
                self.assertEqual(butler_harness.default_name(apps), want)

    def test_the_settings_choice_stands_even_where_it_cannot_run(self):
        butler_settings.update(self.state, harness="claude")
        self.assertEqual(butler_harness.chosen(self.state, {"codex": app("codex")}), ("claude", None))
        butler_settings.update(self.state, harness="agy")
        agy = app("agy")
        self.assertEqual(butler_harness.chosen(self.state, {"claude": app("claude"), "agy": agy}), ("agy", agy))

    def test_the_cards_draw_the_harness_it_runs_on_and_nothing_is_saved(self):
        settings = butler_settings.load(self.state)
        self.assertEqual(settings.harness, "")
        drawn = butler_harness.drawn(settings, {"codex": app("codex")})
        self.assertEqual((drawn.harness, drawn.butler_harness), ("codex", "codex"))
        self.assertFalse(butler_settings.path(self.state).exists())
        named = dataclasses.replace(settings, harness="agy")
        self.assertIs(butler_harness.drawn(named, {"codex": app("codex")}), named)

    def test_what_its_topic_json_will_say_before_its_first_message(self):
        butler_settings.update(self.state, harness="codex", model="gpt-x", effort="low", redaction=True)
        data = butler_harness.unwritten_topic(self.state, {"codex": app("codex", workdir=str(self.root / "work"))})
        self.assertEqual(data, {"harness_id": "codex", "model": "gpt-x", "effort": "low", "workspace_name": "work",
                                "workdir": str((self.root / "work").resolve()), REDACTION_KEY: True})
        self.assertEqual(butler_harness.unwritten_topic(self.state, {"pi": app("pi", tools=False)}), {})

    def test_a_model_saved_with_no_harness_named_is_claude_codes_and_a_fallback_runs_its_own_default(self):
        butler_settings.update(self.state, model="claude-opus-x", effort="max")
        settings = butler_settings.load(self.state)
        self.assertEqual(butler_harness.model_of(settings, "claude"), ("claude-opus-x", "max"))
        self.assertEqual(butler_harness.model_of(settings, "codex"), ("", ""))
        self.assertEqual(butler_harness.unwritten_topic(self.state, {"agy": app("agy")})["model"], "")
        drawn = butler_harness.drawn(settings, {"codex": app("codex")})
        self.assertEqual((drawn.harness, drawn.model, drawn.effort), ("codex", "", ""))
        drawn = butler_harness.drawn(settings, {"claude": app("claude"), "codex": app("codex")})
        self.assertEqual((drawn.harness, drawn.model, drawn.effort), ("claude", "claude-opus-x", "max"))
        named = dataclasses.replace(settings, harness="codex", model="gpt-x")
        self.assertEqual(butler_harness.model_of(named, "codex"), ("gpt-x", "max"))


class LeadAppTest(Case):
    def env(self, apps):
        return SimpleNamespace(topics=SimpleNamespace(apps=apps))

    def test_the_leads_own_harness_else_the_one_the_butler_runs_on_now(self):
        claude, codex = app("claude"), app("codex")
        env = self.env({"claude": claude, "codex": codex})
        self.assertIs(project_loop.lead_app(env, self.state, {"harness_id": "codex"}), codex)
        self.assertIs(project_loop.lead_app(env, self.state, {}), claude)
        self.assertIs(project_loop.lead_app(self.env({"codex": codex}), self.state, {}), codex)  # Not "claude" by default.
        self.assertIsNone(project_loop.lead_app(self.env({"codex": codex}), self.state, {"harness_id": "claude"}))


class LeadLimitTest(Case):
    """LEAD on each Harness: reading, searching and the Bridge's tools; nothing changed."""

    def ctx(self, **options):
        return make_context(self.root, options=options)

    def test_codex_runs_a_lead_read_only_with_its_bridge_tools_approved(self):
        params, _ = appserver.thread_params(self.ctx(**{TOOL_LIMIT: LEAD, "mcp_config": BRIDGE_TOOLS}), None)
        self.assertEqual(params["sandbox"], "read-only")
        self.assertEqual(params["approvalPolicy"], "never")
        config = params["config"]
        self.assertTrue(config["mcp_servers.bridge.enabled"])  # Not a CONSULT: the Bridge's tools stay.
        self.assertEqual(config["mcp_servers.bridge.default_tools_approval_mode"], "approve")
        self.assertEqual(config["mcp_servers.bridge.args"], ["mcp.py"])
        sent = {}
        rpc = SimpleNamespace(thread_id="thread-1", request=lambda method, params, timeout=None: sent.update(params)
                              or {"turn": {"id": "turn-1"}})
        appserver.start_turn(rpc, SimpleNamespace(inputs=SimpleNamespace(attachments=())),
                             self.ctx(**{TOOL_LIMIT: LEAD}), "hi", None)
        self.assertEqual(sent["sandboxPolicy"], {"type": "readOnly"})
        flags = appserver.server_flags(self.ctx(**{TOOL_LIMIT: LEAD}))
        self.assertEqual(flags, [part for flag in appserver.consult.READING_FLAGS for part in ("-c", flag)])

    def test_the_butlers_codex_turn_is_as_before(self):
        params, _ = appserver.thread_params(self.ctx(mcp_config=BRIDGE_TOOLS), None)
        self.assertNotEqual(params["sandbox"], "read-only")
        self.assertNotIn("mcp_servers.bridge.default_tools_approval_mode", params["config"])
        self.assertEqual(appserver.server_flags(self.ctx()), ["-c", "features.default_mode_request_user_input=true"])

    def test_a_resumed_codex_lead_runs_in_a_home_without_the_owners_rules_and_hooks(self):
        backend = CodexBackend()
        for session_id, homes in (("thread-1", 1), (None, 0)):  # A new thread is recorded in the owner's home.
            with self.subTest(session_id=session_id):
                seen = []
                request = SimpleNamespace(session_id=session_id, check_cancelled=lambda: None,
                                          context=self.ctx(**{TOOL_LIMIT: LEAD, "mcp_config": BRIDGE_TOOLS}))
                with mock.patch.object(backend, "_run", side_effect=lambda request, ctx, env: seen.append(env) or "done"), \
                        mock.patch("covey.backends.codex.bridge.ReadingHome") as home:
                    home.return_value.__enter__.return_value = {"CODEX_HOME": "/absolute/reading"}
                    self.assertEqual(backend.run(request), "done")
                self.assertEqual(home.call_count, homes)
                self.assertEqual(seen[0] == {"CODEX_HOME": "/absolute/reading"}, bool(homes))

    def test_antigravity_holds_a_lead_by_deny_rules_for_this_run_alone(self):
        backend = AntigravityBackend()
        ctx = self.ctx(**{TOOL_LIMIT: LEAD, "mcp_config": BRIDGE_TOOLS})
        argv = backend.argv(ctx, None)
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), READ_ONLY_SETTINGS)
        self.assertIn("--dangerously-skip-permissions", argv)  # A deny rule wins over it (agy 1.5.14, docs/projects.md).
        self.assertNotIn("--settings", backend.argv(self.ctx(mcp_config=BRIDGE_TOOLS), None))  # The butler's.
        self.assertIn("只读", backend.prompt_runtime_note(ctx))
        self.assertNotIn("只读", backend.prompt_runtime_note(self.ctx()))
        self.assertEqual(READ_ONLY_SETTINGS, {"permissions": {"deny": ["write_file(*)", "command(*)", "read_url(*)"]}})

    def test_a_harness_without_the_bridge_tools_does_not_run_a_lead(self):
        ctx = self.ctx(**{TOOL_LIMIT: LEAD})
        refused = tool_limits.refusal(ctx, HarnessCapabilities(read_only=True), "Pi")
        self.assertIn("Pi 不能当专项负责人", refused)
        self.assertEqual(tool_limits.refusal(ctx, HarnessCapabilities(bridge_tools=True), "Antigravity"), "")
        for backend in (CodexBackend(), AntigravityBackend()):
            self.assertEqual(tool_limits.refusal(ctx, backend_capabilities(backend, ctx), "x"), "")

    def test_the_other_limits_are_as_they_were(self):
        for limit in (READ, LOOK, CONSULT):
            with self.subTest(limit=limit):
                self.assertNotIn("负责人", tool_limits.refusal(self.ctx(**{TOOL_LIMIT: limit}), HarnessCapabilities(), "x"))


class JudgeCallersTest(Case):
    """Each caller of the small model takes what app/track_judge.py tools picks: no "claude" of its own."""

    def apps(self):
        return {"codex": app("codex", ask_once=True), "pi": app("pi", tools=False)}

    def test_tidy_and_the_patrol_and_the_memory_candidates_and_the_stuck_check_ask_codex_without_claude_code(self):
        apps = self.apps()
        want = (apps["codex"].harness.backend, apps["codex"].harness.context)
        self.assertEqual(tidy_facts.judge_tools(SimpleNamespace(topics=SimpleNamespace(apps=apps))), want)
        self.assertEqual(track_judge.tools(apps), want)
        from covey.app import stuck_check
        check = stuck_check.StuckCheck.__new__(stuck_check.StuckCheck)
        check.harness = SimpleNamespace(spec=SimpleNamespace(name="pi"))
        check.topics = SimpleNamespace(apps=apps)
        self.assertEqual(check.judge(SimpleNamespace()), want)

    def test_the_butlers_tracks_never_ask_the_butlers_own_harness_as_claude_code(self):
        from covey.app import butler_tracks
        tracks = butler_tracks.Tracks.__new__(butler_tracks.Tracks)
        apps = {"claude": app("claude"), **self.apps()}
        tracks.main = SimpleNamespace(topics=SimpleNamespace(apps=apps))
        self.assertEqual(tracks.judge_tools(), (apps["claude"].harness.backend, apps["claude"].harness.context))
        tracks.main = SimpleNamespace(topics=SimpleNamespace(apps=self.apps()))
        self.assertEqual(tracks.judge_tools()[1].options["harness_id"], "codex")


if __name__ == "__main__":
    unittest.main()
