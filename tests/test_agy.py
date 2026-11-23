"""Antigravity (agy) over its headless stream-json: argv, events, verified completion and failure codes."""
import dataclasses
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from support import FIXTURES
from covey.app.unified import UnifiedBridgeApp
from covey.backends.agy.bridge import (AntigravityEventAdapter, NOT_LOGGED_IN, models_from_listing, tool_inputs)
from covey.core.harness import RunCallbacks, RunInputs, RunRequest
from covey.core.steer import SteerNotReady, SteerRefused

RUN = "33333333-3333-4333-8333-333333333333"
SID = "055a398f-db14-4c5f-abbb-1bf03f8120a7"
FAKE = FIXTURES / "harness/agy_stream.py"


class AntigravityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        clean = {k: v for k, v in os.environ.items() if not k.startswith("FAKE_AGY")}
        patcher = mock.patch.dict(os.environ, {**clean, "HOME": str(self.root),
                                               "FAKE_AGY_RECORD": str(self.root / "record.json")}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.app = UnifiedBridgeApp(script_path=Path(__file__).resolve().parents[1] / "bin/covey_bridge.py")
        self.app.build_context(self.app.build_parser().parse_args(
            ["--workdir", str(self.root), "--state-dir", str(self.root / "state"), "--profile", "unit"]))
        self.backend = self.app.apps["agy"].backend
        self.ctx = dataclasses.replace(self.app.harnesses["agy"].context, backend_cmd=[sys.executable, "-I", str(FAKE)],
                                       model="gemini-3.8-pro-high", effort="high")

    def run_agy(self, scenario, session=None, cancel=None, ctx=None):
        os.environ["FAKE_AGY_SCENARIO"] = scenario
        events, replies, sessions = [], [], []
        result = self.backend.run(RunRequest(ctx or self.ctx, "做个任务", session_id=session, callbacks=RunCallbacks(
            event=lambda kind, data, control: events.append((kind, data)), session=sessions.append,
            verified_reply=replies.append), inputs=RunInputs(cancel or threading.Event(), run_id=RUN)))
        path = self.root / "record.json"
        record = json.loads(path.read_text()) if path.exists() else {}
        for leftover in (path, path.with_name("record.json.all")):
            if leftover.exists():
                leftover.unlink()
        return result, events, [r for r in replies if r is not None], sessions, record

    def test_completed_turn_is_verified_and_its_events_are_public_only(self):
        result, events, replies, sessions, record = self.run_agy("ok")
        self.assertFalse(result.is_error, result.text)
        self.assertEqual((result.text, result.session_id, sessions), ("完成", SID, [SID]))
        self.assertTrue(result.outcome.resume_allowed)
        self.assertEqual(replies[-1].backend, "agy")
        self.assertEqual(replies[-1].fingerprint, result.outcome.reply_fingerprint)
        published = json.dumps(events, ensure_ascii=False)
        for private in ("PRIVATE_OUTPUT", "PRIVATE_SUBAGENT"):
            self.assertNotIn(private, published)
        tools = [d for k, d in events if k == "tool"]
        self.assertEqual([(t["name"], t["status"]) for t in tools], [("bash", "running"), ("bash", "done")])
        self.assertEqual(tools[0]["detail"], "ls")
        self.assertIn(("progress_note", "先看一下目录"), [(k, d.get("text")) for k, d in events])
        self.assertEqual([k for k, _d in events].count("model_output"), 1)
        usage = [d for k, d in events if k == "token_usage"]
        self.assertEqual(len(usage), 2)  # One a model request, the result's sum not added again.
        self.assertEqual((usage[-1]["output_tokens"], usage[-1]["input_tokens"], usage[-1]["cache_read_tokens"]),
                         (132, 15436 + 11130, 11130))
        self.assertEqual((usage[-1]["measured_output_tokens"], usage[-1]["generation_seconds"]), (132, 5.0))
        self.assertEqual(events[-1][0], "trace_finished")
        self.assertEqual(json.loads(record["stdin"]), {"event": "user", "message": {"content": "做个任务"}})
        self.assertEqual(record["argv"], ["--output-format", "stream-json", "--input-format", "stream-json",
                                          "--disable-slash-commands", "--dangerously-skip-permissions",
                                          "--model", "gemini-3.8-pro-high", "--effort", "high"])
        self.assertEqual(Path(record["cwd"]).resolve(), Path(self.ctx.workdir).resolve())

    def test_the_answer_is_what_the_model_wrote_after_its_last_tool_subagent_or_system_message(self):
        # agy's result.response joins the progress lines and the waits before the answer (T588 #5298, #5309).
        result, events, replies, *_rest = self.run_agy("waits")
        self.assertFalse(result.is_error, result.text)
        self.assertEqual((result.text, replies[-1].text), ("完成", "完成"))
        notes = [d.get("text") for k, d in events if k == "progress_note"]
        self.assertIn("正在等待子 Agent。\n", notes)
        self.assertIn(("agent", "done"), [(d["name"], d["status"]) for k, d in events if k == "tool" and d["id"] == "step-3"])

    def test_an_answer_that_is_not_the_end_of_the_response_falls_back_to_the_response(self):
        from covey.backends.agy.bridge import StreamRows
        rows = StreamRows(None, AntigravityEventAdapter(lambda *a: None), None)
        rows.sid, rows.result = SID, {"response": "全文"}
        rows.kinds, rows.texts = {0: "agent_response"}, {0: "别的"}
        self.assertEqual(rows.reply(), "全文")
        rows.texts = {}
        self.assertEqual(rows.reply(), "全文")

    def test_the_butlers_turn_gets_the_bridge_tools_through_a_home_of_its_own(self):
        """T614: agy reads MCP servers from ~/.gemini/config/mcp_config.json alone. The butler's turn runs with a home
        of its own: every entry a link to the real one but that file, which adds the Bridge's server (eager tools, a
        wait above the server's own 120 seconds) to the owner's; the real file is left alone and the home goes."""
        from covey.core.butler import mcp_config
        real = self.root / ".gemini" / "config"
        real.mkdir(parents=True)
        owner = {"mcpServers": {"mine": {"command": "my-server", "args": ["--x"]}}}
        (real / "mcp_config.json").write_text(json.dumps(owner))
        (real / "config.json").write_text("{}")
        (self.root / ".gemini" / "antigravity-cli").mkdir()
        (self.root / ".gitconfig").write_text("[user]\n")
        config = mcp_config(Path(__file__).resolve().parents[1], self.root / "state", "om_1-1", sys.executable)
        ctx = dataclasses.replace(self.ctx, options={**self.ctx.options, "mcp_config": config})
        result, _events, _replies, _sessions, record = self.run_agy("ok", ctx=ctx)
        self.assertFalse(result.is_error, result.text)
        home = Path(record["home"])
        self.assertNotEqual(home, self.root)
        self.assertEqual(home.parent, self.root / "state" / "tmp")
        self.assertFalse(home.exists())  # Removed with the turn, its links never followed.
        self.assertEqual(json.loads((real / "mcp_config.json").read_text()), owner)
        self.assertTrue((real / "config.json").exists() and (self.root / ".gitconfig").exists())
        servers = record["mcp"]["mcpServers"]
        self.assertEqual(servers["mine"], owner["mcpServers"]["mine"])
        bridge = servers["bridge"]
        self.assertEqual((bridge["command"], bridge["args"], bridge["env"]),
                         (config["mcpServers"]["bridge"]["command"], config["mcpServers"]["bridge"]["args"],
                          config["mcpServers"]["bridge"]["env"]))
        self.assertEqual(bridge["timeoutSeconds"], 150)
        self.assertIn("topic_start", bridge["tools"])
        self.assertTrue(all(tool == {"eager": True} for tool in bridge["tools"].values()))

    def test_a_private_home_links_everything_but_the_mcp_file_and_says_when_the_owners_file_is_not_json(self):
        from covey.backends.agy.home import PrivateHome
        real = self.root / ".gemini" / "config"
        real.mkdir(parents=True)
        (real / "mcp_config.json").write_text('{"mcpServers": {"mine": {"command": "x"},},}  // agy takes this')
        (self.root / ".gemini" / "antigravity-cli").mkdir()
        server = {"command": sys.executable, "args": ["-c", "pass"]}  # Answers nothing: its tools are not eager.
        home = PrivateHome(self.root / "state", self.root, {"mcpServers": {"bridge": server}}, dict(os.environ))
        with home as path:
            self.assertTrue((path / ".gemini" / "antigravity-cli").is_symlink())
            self.assertTrue((path / ".gemini" / "config").is_dir() and not (path / ".gemini" / "config").is_symlink())
            self.assertTrue((path / ".gitconfig").is_symlink() or not (self.root / ".gitconfig").exists())
            data = json.loads((path / ".gemini" / "config" / "mcp_config.json").read_text())
            self.assertEqual(list(data["mcpServers"]), ["bridge"])
            self.assertNotIn("tools", data["mcpServers"]["bridge"])
            self.assertIn("not plain JSON", home.note)
        self.assertFalse(path.exists())
        self.assertTrue((self.root / ".gemini" / "antigravity-cli").is_dir())
        (real / "mcp_config.json").write_text("")  # As agy leaves it with no server: nothing to say.
        home = PrivateHome(self.root / "state", self.root, {"mcpServers": {"bridge": server}}, dict(os.environ))
        with home:
            self.assertEqual(home.note, "")

    def test_any_other_turn_keeps_the_real_home(self):
        _result, _events, _replies, _sessions, record = self.run_agy("ok")
        self.assertEqual(Path(record["home"]), self.root)

    def test_agys_own_default_model_and_budget_pass_no_flag(self):
        result, *_rest, record = self.run_agy("ok", ctx=dataclasses.replace(self.ctx, model="", effort=""))
        self.assertFalse(result.is_error, result.text)
        self.assertNotIn("--model", record["argv"])
        self.assertNotIn("--effort", record["argv"])

    def test_without_skip_permissions_agy_asks_for_none(self):
        _result, *_rest, record = self.run_agy("ok", ctx=dataclasses.replace(self.ctx, skip_permissions=False))
        self.assertNotIn("--dangerously-skip-permissions", record["argv"])

    def test_resume_passes_the_conversation_and_rejects_another(self):
        result, *_rest, record = self.run_agy("ok", session=SID)
        self.assertFalse(result.is_error, result.text)
        self.assertEqual(record["argv"][record["argv"].index("--conversation") + 1], SID)
        result, _events, replies, _sessions, _record = self.run_agy("mismatch", session=SID)
        self.assertTrue(result.is_error)
        self.assertEqual(result.outcome.error_code, "protocol_error")
        self.assertEqual(replies, [])

    def test_failures_map_to_bridge_codes_without_native_text(self):
        for scenario, code in (("logged-out", "authentication_error"), ("garbage", "protocol_error"),
                               ("busy", "rate_limited"), ("error", "root_failed"),
                               ("exit-after-result", "root_failed"), ("unavailable", "server_fault"),
                               ("quota-window", "rate_limited"), ("quota", "quota_exhausted")):
            with self.subTest(scenario=scenario):
                result, events, replies, _sessions, _record = self.run_agy(scenario)
                self.assertTrue(result.is_error)
                self.assertEqual(result.outcome.error_code, code)
                self.assertFalse(result.outcome.resume_allowed)
                self.assertNotIn("PRIVATE_DETAIL", result.text)
                self.assertEqual(replies, [])
                if scenario == "logged-out":
                    self.assertEqual(result.text, NOT_LOGGED_IN)
                    failure = [d for k, d in events if k == "backend_failure"][-1]
                    self.assertFalse([line for line in failure["stderr"] if "oauth2" in line])

    def test_a_limit_and_a_passing_fault_are_told_from_what_no_retry_gets_past(self):
        """agy's ``result.error`` read for app/auto_retry.py: a limit or a quota that resets by itself (retried), a
        passing server fault (retried), and a login, a spent quota or anything else (never)."""
        from covey.backends.agy.bridge import error_code
        cases = {
            "rate_limited": ("429 Too Many Requests", "RESOURCE_EXHAUSTED (code 429): rate limit exceeded",
                             "Quota exceeded for quota metric 'Generate Content API requests per minute'",
                             "Your quota will reset after 4h12m. You have exhausted your capacity on this model."),
            "server_fault": ("UNAVAILABLE (code 503): The model is overloaded.", "INTERNAL (code 500): oops",
                             "DEADLINE_EXCEEDED (code 504)", "stream error: stream ID 7; INTERNAL_ERROR",
                             'Post "https://example.invalid/v1": read: connection reset by peer',
                             "The model API is currently overloaded and may experience intermittent errors.",
                             "unexpected EOF", "context deadline exceeded",
                             "There was a network issue connecting to the server, please try again."),
            "quota_exhausted": ("you are out of credits", "Quota exhausted for this account", "usage limit reached"),
            "authentication_error": ("You are not logged into Antigravity.", "401 Unauthorized",
                                     "authentication failed or timed out"),
            "": ("PRIVATE_DETAIL internal", "PERMISSION_DENIED (code 403): Your location is not eligible",
                 "INVALID_ARGUMENT (code 400): bad request", "model not found", "tool run_command failed", "",
                 # A safety block is never a limit or a fault, whatever else it says.
                 "INTERNAL (code 500): response blocked by SAFETY", "429: content violates the usage policy",
                 "UNAVAILABLE: PROHIBITED_CONTENT"),
        }
        cases["rate_limited"] += ("model gemini-3.1-pro is out of quota until 2026-11-23T08:00:00Z",)
        for code, errors in cases.items():
            for error in errors:
                with self.subTest(error=error):
                    self.assertEqual(error_code(error), code)

    def test_a_stopped_turn_is_never_a_limit_or_a_fault(self):
        """The stop's own end (agy cut off mid-stream) says cancelled, never what app/auto_retry.py would retry."""
        from types import SimpleNamespace
        from covey.backends.agy.bridge import stream_outcome
        stopped, running = threading.Event(), threading.Event()
        stopped.set()
        for error in ("UNAVAILABLE (code 503): stream closed", "429 Too Many Requests"):
            with self.subTest(error=error):
                rows = SimpleNamespace(result={"status": "ERROR", "error": error}, invalid=False, sid=SID)
                self.assertEqual(stream_outcome(rows, 1, stopped), ("cancelled", "cancelled"))
                self.assertIn(stream_outcome(rows, 1, running)[1], ("server_fault", "rate_limited"))
        # A login that failed is still said as one.
        rows = SimpleNamespace(result={"status": "ERROR", "error": "401 Unauthorized"}, invalid=False, sid=SID)
        self.assertEqual(stream_outcome(rows, 1, stopped), ("failed", "authentication_error"))

    def test_stop_ends_the_process_and_is_not_resumable(self):
        cancel = threading.Event()
        threading.Timer(1.0, cancel.set).start()
        started = time.monotonic()
        result, *_rest = self.run_agy("slow", cancel=cancel)
        self.assertLess(time.monotonic() - started, 20)
        self.assertEqual(result.outcome.status, "cancelled")
        self.assertFalse(result.outcome.resume_allowed)

    def test_a_supplement_stops_the_turn_and_the_conversation_goes_on_with_it(self):
        os.environ["FAKE_AGY_SCENARIO"] = "steer"
        events, replies, controls, tools = [], [], [], threading.Event()

        def event(kind, data, control):
            events.append((kind, data))
            if kind == "tool" and data.get("status") == "running":
                tools.set()
        done = {}
        request = RunRequest(self.ctx, "做个任务", callbacks=RunCallbacks(
            event=event, control=controls.append, verified_reply=replies.append),
            inputs=RunInputs(threading.Event(), run_id=RUN))
        worker = threading.Thread(target=lambda: done.update(result=self.backend.run(request)))
        worker.start()
        self.assertTrue(tools.wait(20))
        control = controls[0]
        control.steer("改成 B", "ev-1")
        worker.join(30)
        result = done["result"]
        self.assertFalse(result.is_error, result.text)
        self.assertEqual((result.text, result.session_id), ("完成", SID))
        runs = [json.loads(line) for line in (self.root / "record.json.all").read_text().splitlines()]
        self.assertEqual(len(runs), 2)
        self.assertNotIn("--conversation", runs[0]["argv"])
        self.assertEqual(runs[1]["argv"][runs[1]["argv"].index("--conversation") + 1], SID)
        message = json.loads(runs[1]["stdin"])["message"]["content"]
        self.assertTrue(message.startswith("用户补充（你刚才的执行被这条补充打断了") and message.endswith("改成 B"), message)
        self.assertIn(("steer_read", {"event_id": "ev-1"}), events)
        steps = {}
        for kind, data in events:
            if kind == "tool":
                steps[data["id"]] = data["status"]
        # The stopped command ends failed; the next process's steps have keys of their own.
        self.assertEqual(steps, {"step-2": "failed", "step-1-2": "done"})
        self.assertEqual([k for k, _d in events].count("trace_finished"), 1)
        child = int((self.root / "record.json.child").read_text())
        self.assertFalse(Path(f"/proc/{child}").exists() and "python" in Path(f"/proc/{child}/cmdline").read_text())
        self.assertIsNone(controls[-1])  # The controls are dropped when the turn ends.
        with self.assertRaises(SteerRefused):
            control.steer("太晚了", "ev-2")

    def test_a_supplement_before_agy_said_its_conversation_waits(self):
        from covey.backends.agy.bridge import AgyControl
        control = AgyControl(lambda *a: None)
        with self.assertRaises(SteerNotReady):
            control.steer("x", "ev")
        with self.assertRaises(SteerRefused):
            control.steer("  ", "ev")

    def test_an_unknown_budget_never_starts_agy(self):
        with self.assertRaises(ValueError):
            self.backend.run(RunRequest(dataclasses.replace(self.ctx, effort="ultra"), "x"))
        self.assertFalse((self.root / "record.json").exists())

    def test_catalog_lists_agy_models_and_refuses_without_a_login(self):
        os.environ["FAKE_AGY_SCENARIO"] = "ok"
        catalog = self.backend.refresh_model_catalog(self.ctx)
        self.assertEqual(catalog, {
            "gemini-4-neon": {"display_name": "Gemini 4 Neon", "default_reasoning_level": "high",
                              "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]},
            "gemini-pro-orchestrator": {"display_name": "Orchestrator (Carbon)", "supported_reasoning_levels": []},
            "gemini-3.8-flash": {"display_name": "Gemini 3.8 Flash", "default_reasoning_level": "medium",
                                 "supported_reasoning_levels": [{"effort": "medium"}]}})
        os.environ["FAKE_AGY_SCENARIO"] = "logged-out"
        with self.assertRaisesRegex(ValueError, "还没有登录"):
            self.backend.refresh_model_catalog(self.ctx)
        self.assertEqual(models_from_listing("Fetching available models...\nModels\n"), {})

    def test_the_saved_catalog_keeps_budgets_agy_refuses_from_it(self):
        from covey.app.launch_models import refresh_catalog
        os.environ["FAKE_AGY_SCENARIO"] = "ok"
        refresh_catalog(self.app.apps["agy"], self.ctx)
        with self.assertRaisesRegex(ValueError, "不支持所选推理档位"):
            self.backend.run(RunRequest(dataclasses.replace(self.ctx, model="gemini-4-neon", effort="medium"), "x"))
        self.assertFalse((self.root / "record.json").exists())
        _result, *_rest, record = self.run_agy("ok", ctx=dataclasses.replace(
            self.ctx, model="gemini-pro-orchestrator", effort="high"))
        self.assertNotIn("--effort", record["argv"])  # agy refuses a budget for a model without any.
        _result, *_rest, record = self.run_agy("ok", ctx=dataclasses.replace(self.ctx, model="gemini-4-neon"))
        self.assertEqual(record["argv"][-4:], ["--model", "gemini-4-neon", "--effort", "high"])

    def test_tool_parameters_read_like_the_other_harnesses(self):
        self.assertEqual(tool_inputs({"CommandLine": "ls", "Cwd": "/x"}), {"command": "ls"})
        self.assertEqual(tool_inputs({"AbsolutePath": "/a.py", "StartLine": 3}), {"path": "/a.py"})
        adapter = AntigravityEventAdapter(lambda kind, data: None)
        adapter.accept({"event": "step_update", "step_update": {
            "step_index": 4, "state": "ACTIVE", "step_type": "tool", "tool_name": "read_url_content",
            "tool_info": {"parameters": {"Url": "https://example.invalid/doc?token=PRIVATE#part"}}}}, 1.0)
        self.assertEqual(adapter.tools["step-4"]["detail"], "https://example.invalid/doc")
        self.assertEqual(adapter.tools["step-4"]["name"], "webfetch")


class AgyTurnHookTests(unittest.TestCase):
    """T674: an extension's ``agy_turn`` hook gives a turn its environment and, after a process that failed on a spent
    quota, a limit or a sign-in, another one in which the same conversation goes on (several Google accounts, each a
    HOME of its own, are the extension's). Without the hook, or when it has none, a turn runs and fails as before."""

    def setUp(self):
        AntigravityTests.setUp(self)
        self.failures = []
        # Each process's record, kept past run_agy (which removes record.json's): ``runs`` reads and removes them.
        self.record = self.root / "hook-record.json"
        os.environ["FAKE_AGY_RECORD"] = str(self.record)

    run_agy = AntigravityTests.run_agy

    def runs(self):
        path = self.record.with_name(self.record.name + ".all")
        found = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        if path.exists():
            path.unlink()
        return found

    def hook(self, *spent, note="主号的 Gemini 额度用完了，换副号接着做", raises=False, cancel=None):
        """A hook whose turn starts with ``FAKE_AGY_SPENT=spent[0]`` (the fake agy's failure, '' none) and HOME
        <root>/acct-0, each switch going on with the next one; None once they are used up."""
        import contextlib
        from types import SimpleNamespace

        def env_of(env, index):
            home = self.root / f"acct-{index}"
            home.mkdir(exist_ok=True)
            return {**env, "HOME": str(home), "FAKE_AGY_SPENT": spent[index]}

        @contextlib.contextmanager
        def turn(ctx, env, *, run_id=""):
            self.assertEqual(run_id, RUN)
            left = list(range(1, len(spent)))

            def switch(failure):
                self.failures.append(failure)
                if raises:
                    raise RuntimeError("the hook broke")
                if cancel is not None:
                    cancel.set()
                return (env_of(env, left.pop(0)), note) if left else None
            yield env_of(env, 0), switch
        return SimpleNamespace(turn=turn)

    def hooked(self, hook, scenario="ok", **kwargs):
        from covey.core import extensions
        with mock.patch.object(extensions, "hook", return_value=hook) as asked:
            found = self.run_agy(scenario, **kwargs)
        asked.assert_called_with("agy_turn")
        return found

    def test_a_spent_quota_goes_on_in_the_hooks_next_environment_in_the_same_conversation(self):
        from covey.backends.agy.bridge import SWITCH_RESUMED
        result, events, replies, sessions, _record = self.hooked(self.hook("after-steps", ""))
        self.assertFalse(result.is_error, result.text)
        self.assertEqual((result.text, result.session_id, sessions), ("完成", SID, [SID]))
        self.assertEqual(replies[-1].fingerprint, result.outcome.reply_fingerprint)
        first, second = self.runs()
        self.assertEqual((first["spent"], first["home"]), ("after-steps", str(self.root / "acct-0")))
        self.assertEqual((second["spent"], second["home"]), ("", str(self.root / "acct-1")))
        self.assertNotIn("--conversation", first["argv"])
        self.assertEqual(second["argv"][second["argv"].index("--conversation") + 1], SID)
        self.assertEqual(json.loads(second["stdin"])["message"]["content"], SWITCH_RESUMED)
        failure, = self.failures
        self.assertEqual((failure["code"], failure["conversation"], failure["model"]),
                         ("quota_exhausted", SID, "gemini-3.8-pro-high"))
        self.assertIn("exhausted your quota", failure["error"])
        notes = [data for kind, data in events if kind == "progress_note" and data["id"].startswith("agy-switch-")]
        self.assertEqual([note["text"] for note in notes], ["主号的 Gemini 额度用完了，换副号接着做"])
        steps = {}
        for kind, data in events:
            if kind == "tool":
                steps[data["id"]] = data["status"]
        self.assertEqual(steps, {"step-2": "done", "step-1-2": "done"})  # The next process's steps have keys of their own.
        self.assertEqual([kind for kind, _data in events].count("backend_failure"), 0)
        self.assertEqual([kind for kind, _data in events].count("trace_finished"), 1)

    def test_words_agy_never_took_in_go_again_and_taken_ones_are_gone_on_from(self):
        from covey.backends.agy.bridge import SWITCH_RESUMED
        cases = (("before-init", None, False, "做个任务"), ("before-init", SID, True, "做个任务"),
                 ("after-input", None, True, SWITCH_RESUMED), ("logged-out", None, False, "做个任务"))
        for spent, session, resumes, words in cases:
            with self.subTest(spent=spent, session=session):
                self.failures.clear()
                result, _events, _replies, sessions, _record = self.hooked(self.hook(spent, ""), session=session)
                self.assertFalse(result.is_error, result.text)
                self.assertEqual(sessions, [SID])  # Said once, by the process that began it.
                first, second = self.runs()
                self.assertEqual("--conversation" in second["argv"], resumes)
                self.assertEqual(json.loads(second["stdin"])["message"]["content"], words)
                if spent == "before-init":
                    self.assertEqual((second["argv"], second["stdin"]), (first["argv"], first["stdin"]))
                self.assertEqual(self.failures[0]["code"],
                                 {"before-init": "rate_limited", "after-input": "quota_exhausted",
                                  "logged-out": "authentication_error"}[spent])

    def test_without_the_hook_or_another_environment_the_turn_fails_as_before(self):
        from covey.core import extensions
        with mock.patch.object(extensions, "hook", return_value=None):
            result, *_rest = self.run_agy("ok")
        self.assertFalse(result.is_error)
        self.assertEqual(Path(self.runs()[0]["home"]), self.root)  # The environment as it is.
        for raises in (False, True):
            with self.subTest(raises=raises), self.assertLogs("covey.backends.agy.bridge", "WARNING") as logs:
                result, events, replies, _sessions, _record = self.hooked(self.hook("after-steps", raises=raises))
                if not raises:
                    logging.getLogger("covey.backends.agy.bridge").warning("none")  # assertLogs wants one.
                self.assertEqual(any("agy_turn switch failed" in line for line in logs.output), raises)
                self.assertTrue(result.is_error)
                self.assertEqual(result.outcome.error_code, "quota_exhausted")
                self.assertEqual((len(self.runs()), replies), (1, []))
                self.assertFalse([data for kind, data in events if kind == "progress_note"
                                  and data["id"].startswith("agy-switch-")])
                self.assertEqual([kind for kind, _data in events].count("backend_failure"), 1)

    def test_a_turn_goes_on_elsewhere_at_most_max_switches_times(self):
        from covey.backends.agy.bridge import MAX_SWITCHES
        result, *_rest = self.hooked(self.hook(*["after-steps"] * (MAX_SWITCHES + 2)))
        self.assertEqual(result.outcome.error_code, "quota_exhausted")
        self.assertEqual((len(self.runs()), len(self.failures)), (MAX_SWITCHES + 1, MAX_SWITCHES))

    def test_other_failures_a_stop_and_a_device_never_ask_the_hook(self):
        from covey.backends.agy import bridge
        result, *_rest = self.hooked(self.hook("", ""), scenario="error")
        self.assertEqual((result.outcome.error_code, len(self.runs()), self.failures), ("root_failed", 1, []))
        cancel = threading.Event()
        result, *_rest = self.hooked(self.hook("after-steps", "", cancel=cancel), cancel=cancel)
        self.assertTrue(result.is_error)
        self.assertEqual((len(self.runs()), len(self.failures)), (1, 1))  # Stopped while the hook looked: no next one.
        hook = mock.Mock()
        with mock.patch.object(bridge, "device_of", return_value="box"), \
                mock.patch.object(bridge.extensions, "hook", return_value=hook):
            with bridge.extension_turn(self.ctx, {"HOME": "/x"}) as found:
                self.assertEqual(found, ({"HOME": "/x"}, None))
        hook.turn.assert_not_called()

    def test_the_butlers_home_is_made_again_over_the_next_environments_home(self):
        from covey.core.butler import mcp_config
        for index in (0, 1):
            cli = self.root / f"acct-{index}" / ".gemini" / "antigravity-cli"
            cli.mkdir(parents=True)
            (cli.parent / "config").mkdir()
        config = mcp_config(Path(__file__).resolve().parents[1], self.root / "state", "om_1-1", sys.executable)
        ctx = dataclasses.replace(self.ctx, options={**self.ctx.options, "mcp_config": config})
        result, *_rest = self.hooked(self.hook("after-steps", ""), ctx=ctx)
        self.assertFalse(result.is_error, result.text)
        first, second = self.runs()
        for index, run in enumerate((first, second)):
            self.assertEqual(Path(run["home"]).parent, self.root / "state" / "tmp")
            self.assertFalse(Path(run["home"]).exists())  # Each removed: the first when the turn moved on.
            self.assertEqual(run["cli"], str((self.root / f"acct-{index}" / ".gemini" / "antigravity-cli").resolve()))
            self.assertIn("bridge", run["mcp"]["mcpServers"])
        self.assertNotEqual(first["home"], second["home"])


if __name__ == "__main__":
    unittest.main()
