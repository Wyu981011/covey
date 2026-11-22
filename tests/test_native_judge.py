"""The small model's questions where no Claude Code is enabled (T664): one question to a Harness's own CLI and nothing else
(core/one_shot.py, backends/codex/judge.py, backends/agy/judge.py, core/agy_home.py), and where app/track_judge.py puts
each question (``tools``, ``ask``, ``judge``): the gateway when it is set, Claude Code while it is enabled, else Codex, else
Antigravity. Fake CLIs stand in for codex and agy; nothing here reaches a model."""
from __future__ import annotations

import json
import os
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import exec_tempdir

from covey.app import track_judge
from covey.backends.agy import judge as agy_judge
from covey.backends.agy.bridge import READ_ONLY_SETTINGS, AntigravityBackend
from covey.backends.codex import judge as codex_judge
from covey.backends.codex.bridge import CodexBackend
from covey.core import agy_home, one_shot
from covey.core.harness import AskFailed, HarnessCapabilities, backend_capabilities, for_device
from covey.core.track_route import LiveJob, Message, Quote

NOW = 1_800_000_000.0
QUESTION = "顺便把第二个对比表也加上内存占用那一列"

# One fake for both CLIs. It records its argv, working directory, standard input and HOME/CODEX_HOME (and what that home
# holds) to FAKE_RECORD, then prints FAKE_ROWS (JSON lines); FAKE_MODE: "hang" (a child started first, pids in FAKE_PIDS,
# then the rows, then it lingers), "exit" (status 3, FAKE_STDERR on stderr).
FAKE = """#!{python}
import json, os, subprocess, sys, time
stdin = sys.stdin.read()
home = os.environ.get("CODEX_HOME") or os.environ.get("HOME") or ""
listing = sorted(os.listdir(home)) if home and os.path.isdir(home) else []
gemini = os.path.join(home, ".gemini", "antigravity-cli")
linked = sorted(os.listdir(gemini)) if os.path.isdir(gemini) else []
config = open(os.path.join(home, "config.toml")).read() if os.path.isfile(os.path.join(home, "config.toml")) else None
with open(os.environ["FAKE_RECORD"], "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd(), "stdin": stdin, "home": home, "listing": listing,
                        "linked": linked, "config": config}}) + "\\n")
mode = os.environ.get("FAKE_MODE", "")
if mode == "hang":
    child = subprocess.Popen(["sleep", "30"])
    open(os.environ["FAKE_PIDS"], "w").write(f"{{os.getpid()}} {{child.pid}}")
for row in json.loads(os.environ.get("FAKE_ROWS") or "[]"):
    print(json.dumps(row, ensure_ascii=False), flush=True)
if mode == "hang":
    time.sleep(30)
if mode == "exit":
    sys.stderr.write(os.environ.get("FAKE_STDERR", "boom"))
    sys.exit(3)
"""

CODEX_ROWS = [{"type": "thread.started", "thread_id": "t1"}, {"type": "turn.started"},
              {"type": "item.completed", "item": {"id": "i0", "type": "reasoning", "text": "想一下"}},
              {"type": "item.completed", "item": {"id": "i1", "type": "agent_message",
                                                  "text": '{"route":"merge","target":1,"confidence":0.9}'}},
              {"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}]
AGY_ROWS = [{"event": "init", "conversation_id": "c1", "init": {"tools": []}},
            {"event": "result", "result": {"conversation_id": "c1", "status": "SUCCESS",
                                           "response": '{"route":"new","target":null,"confidence":0.8}\n'}}]


def alive(pid) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat") as handle:
            return handle.read().split(") ", 1)[1][0] != "Z"
    except OSError:
        return True


class Case(unittest.TestCase):
    def setUp(self):
        self._tmp = exec_tempdir()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.script = self.root / "fake-cli"
        self.script.write_text(FAKE.format(python=sys.executable))
        self.script.chmod(0o755)
        self.record, self.pids = self.root / "record.jsonl", self.root / "pids"
        self.home = self.root / "home"
        self.home.mkdir()
        self.state = self.root / "state"
        env = {key: value for key, value in os.environ.items()
               if not key.startswith(("FAKE_", "COVEY_JUDGE", "LARK_BRIDGE_JUDGE", "COVEY_TRACK_JUDGE", "GEMINI_",
                                      "AGY_", "CODEX_HOME"))}
        patch = mock.patch.dict(os.environ, {**env, "HOME": str(self.home), "FAKE_RECORD": str(self.record),
                                             "FAKE_PIDS": str(self.pids), "COVEY_TRACK_JUDGE_WARM": "0"}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)

    def rows(self, rows, **env):
        patch = mock.patch.dict(os.environ, {"FAKE_ROWS": json.dumps(rows, ensure_ascii=False), **env})
        patch.start()
        self.addCleanup(patch.stop)

    def recorded(self):
        return [json.loads(line) for line in self.record.read_text().splitlines()] if self.record.exists() else []

    def ctx(self, name):
        return SimpleNamespace(backend_cmd=[str(self.script)], state_dir=self.state, options={"harness_id": name},
                               device=None)


class OneShotTest(Case):
    def run_lines(self, limit=10.0, done=lambda row: row.get("type") == "turn.completed", **kwargs):
        return one_shot.run_lines([str(self.script), "-"], "问题的正文", env=dict(os.environ), cwd=str(self.root),
                                  limit=limit, done=done, **kwargs)

    def test_the_rows_up_to_the_answer_and_the_question_only_on_standard_input(self):
        self.rows(CODEX_ROWS)
        rows = self.run_lines()
        self.assertEqual([row["type"] for row in rows][-2:], ["item.completed", "turn.completed"])
        record = self.recorded()[0]
        self.assertEqual(record["stdin"], "问题的正文")
        self.assertNotIn("问题的正文", " ".join(record["argv"]))

    def test_past_the_limit_the_whole_group_is_killed(self):
        self.rows([], FAKE_MODE="hang")
        started = time.monotonic()
        with self.assertRaises(AskFailed) as caught:
            self.run_lines(limit=1.5)
        self.assertEqual(caught.exception.reason, "timeout")
        self.assertLess(time.monotonic() - started, 8)
        deadline = time.monotonic() + 5
        pids = [int(pid) for pid in self.pids.read_text().split()] if self.pids.exists() else []
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(pids)
        self.assertFalse([pid for pid in pids if alive(pid)], "the CLI or its child outlived the limit")

    def test_the_group_is_killed_once_the_answer_is_in(self):
        self.rows(CODEX_ROWS, FAKE_MODE="hang")  # Prints its answer, then lingers with a child, as Codex does.
        started = time.monotonic()
        rows = self.run_lines(limit=20)
        self.assertLess(time.monotonic() - started, 10)
        self.assertEqual(rows[-1]["type"], "turn.completed")
        pids = [int(pid) for pid in self.pids.read_text().split()]  # Written before the answer.
        deadline = time.monotonic() + 5
        while any(alive(pid) for pid in pids) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertEqual(len(pids), 2)
        self.assertFalse([pid for pid in pids if alive(pid)], "the CLI or its child outlived its answer")

    def test_an_error_exit_says_its_code_and_last_stderr_line_with_secrets_hidden_never_the_question(self):
        self.rows([], FAKE_MODE="exit", FAKE_STDERR="first line\nhttps://accounts.example/o/oauth2/x\n"
                                                    "failed: password=hunter-fake-0000\n")
        with self.assertRaises(AskFailed) as caught:
            self.run_lines(skip=("oauth2",))
        self.assertEqual(caught.exception.reason, "exit_nonzero")
        self.assertTrue(caught.exception.detail.startswith("code=3 failed:"), caught.exception.detail)
        self.assertNotIn("hunter-fake", caught.exception.detail)
        self.assertNotIn("问题", caught.exception.detail)

    def test_a_cli_that_does_not_start_is_spawn_failed(self):
        with self.assertRaises(AskFailed) as caught:
            one_shot.run_lines([str(self.root / "missing")], "q", env=dict(os.environ), cwd=str(self.root), limit=5,
                               done=lambda row: True)
        self.assertEqual(caught.exception.reason, "spawn_failed")

    def test_output_that_ends_without_the_answer_is_left_to_the_caller(self):
        self.rows([{"type": "thread.started"}])
        self.assertEqual(self.run_lines(), [{"type": "thread.started"}])


class CodexJudgeTest(Case):
    def catalog(self, models):
        codex = self.home / ".codex"
        codex.mkdir(exist_ok=True)
        (codex / "models_cache.json").write_text(json.dumps({"models": [
            {"slug": slug, "visibility": "list", "description": text,
             "supported_reasoning_levels": [{"effort": effort} for effort in efforts]}
            for slug, text, efforts in models]}))

    def test_one_question_is_an_ephemeral_read_only_exec_with_its_words_on_standard_input(self):
        self.rows(CODEX_ROWS)
        text = codex_judge.ask_once(self.ctx("codex"), "只回一行 JSON", QUESTION, limit=10)
        self.assertEqual(json.loads(text), {"route": "merge", "target": 1, "confidence": 0.9})
        record = self.recorded()[0]
        argv = record["argv"]
        self.assertEqual(argv[:2], ["exec", "--ephemeral"])  # No session written.
        self.assertEqual(argv[argv.index("-s") + 1], "read-only")
        self.assertIn("--json", argv)
        self.assertEqual(argv[-1], "-")
        self.assertEqual(record["stdin"], QUESTION)
        self.assertNotIn(QUESTION, " ".join(argv))
        self.assertIn("developer_instructions=" + json.dumps("只回一行 JSON"), argv)
        flags = {argv[i + 1] for i, part in enumerate(argv) if part == "-c"}
        for flag in ("features.shell_tool=false", "features.multi_agent=false", "features.apps=false",
                     "features.plugins=false", "features.hooks=false", "features.memories=false", 'web_search="disabled"'):
            self.assertIn(flag, flags)
        self.assertEqual(Path(record["cwd"]), self.state / "codex-judge")
        self.assertTrue(record["home"].startswith(str(self.state / "tmp" / "codex-judge-")))
        self.assertFalse(Path(record["home"]).exists())  # Its own CODEX_HOME went with the question.

    def test_its_home_has_the_login_but_no_mcp_server_rule_hook_memory_or_global_instructions(self):
        real = self.home / ".codex"
        real.mkdir()
        for name in ("auth.json", "AGENTS.md", "history.jsonl", "hooks.json", "memories_1.sqlite"):
            (real / name).write_text("x")
        for name in ("rules", "skills", "plugins", "sessions"):
            (real / name).mkdir()
        (real / "config.toml").write_text('model = "gpt-x"\n[mcp_servers.owner]\ncommand = "owner-server"\n')
        self.rows(CODEX_ROWS)
        codex_judge.ask_once(self.ctx("codex"), "s", "{}", limit=10)
        record = self.recorded()[0]
        self.assertIn("auth.json", record["listing"])
        for name in ("AGENTS.md", "history.jsonl", "hooks.json", "memories_1.sqlite", "rules", "skills", "plugins"):
            self.assertNotIn(name, record["listing"])
        from covey.backends.codex import consult
        if consult.tomllib is not None:
            self.assertNotIn("mcp_servers", record["config"] or "")
            self.assertIn('model = "gpt-x"', record["config"])

    def test_the_answer_is_the_last_agent_message_and_a_failed_turn_or_none_is_a_reason(self):
        self.assertEqual(codex_judge.answer_of(CODEX_ROWS), '{"route":"merge","target":1,"confidence":0.9}')
        with self.assertRaises(AskFailed) as caught:
            codex_judge.answer_of([{"type": "turn.failed", "error": {"code": "rate_limited", "message": "x"}}])
        self.assertEqual((caught.exception.reason, caught.exception.detail), ("model_error", "rate_limited"))
        with self.assertRaises(AskFailed) as caught:
            codex_judge.answer_of([{"type": "turn.completed"}])
        self.assertEqual(caught.exception.reason, "bad_output")

    def test_the_model_a_light_one_from_the_catalog_the_owners_default_for_a_heavy_one_or_the_variable(self):
        self.catalog([("gpt-big", "Our most capable model.", ("low", "medium", "high")),
                      ("gpt-luna", "Fast and affordable model for easier tasks.", ("low", "medium")),
                      ("gpt-gemini-like", "A model.", ("minimal", "low"))])
        env = {"HOME": str(self.home)}
        self.assertEqual(codex_judge.choose(env, heavy=False, environ={}), ("gpt-luna", "low"))
        self.assertEqual(codex_judge.choose(env, heavy=True, environ={}), ("", "medium"))
        self.assertEqual(codex_judge.choose(env, heavy=False, environ={codex_judge.MODEL_ENV: "gpt-big"}),
                         ("gpt-big", "low"))
        self.assertEqual(codex_judge.choose(env, heavy=False, environ={codex_judge.MODEL_ENV: "not-listed"}),
                         ("gpt-luna", "low"))  # A model the account does not list is not asked for.
        self.catalog([("gpt-big", "Our most capable model.", ("low", "medium"))])
        self.assertEqual(codex_judge.choose(env, heavy=False, environ={}), ("", "low"))  # None light: the default's.

    def test_a_turn_that_never_completes_is_a_timeout(self):
        self.rows(CODEX_ROWS[:2], FAKE_MODE="hang")
        with self.assertRaises(AskFailed) as caught:
            codex_judge.ask_once(self.ctx("codex"), "s", "{}", limit=1.5)
        self.assertEqual(caught.exception.reason, "timeout")


class AgyJudgeTest(Case):
    def sign_in(self):
        folder = self.home / ".gemini" / "antigravity-cli"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / agy_home.TOKEN).write_text("fake-token")
        for name in ("conversations", "brain", "log"):
            (folder / name).mkdir(exist_ok=True)
        (folder / "bin").mkdir(exist_ok=True)
        config = self.home / ".gemini" / "config"
        config.mkdir(exist_ok=True)
        (config / "mcp_config.json").write_text(json.dumps({"mcpServers": {"owner": {"command": "x"}}}))

    def ask(self, heavy=False, limit=10):
        backend = SimpleNamespace(model_catalog=lambda ctx: {
            "gemini-4-neon": {"display_name": "Gemini 4 Neon", "supported_reasoning_levels": [{"effort": "low"}]},
            "gemini-3.8-flash": {"display_name": "Gemini 3.8 Flash",
                                 "supported_reasoning_levels": [{"effort": "low"}, {"effort": "high"}]}})
        return agy_judge.ask_once(backend, self.ctx("agy"), "只回一行 JSON", QUESTION, heavy=heavy, limit=limit,
                                  settings=READ_ONLY_SETTINGS)

    def test_without_a_sign_in_nothing_starts(self):
        with self.assertRaises(AskFailed) as caught:
            self.ask()
        self.assertEqual(caught.exception.reason, "not_signed_in")
        self.assertEqual(self.recorded(), [])

    def test_one_question_in_a_scratch_home_with_the_deny_rules_and_its_words_on_standard_input(self):
        self.sign_in()
        self.rows(AGY_ROWS)
        self.assertEqual(json.loads(self.ask()), {"route": "new", "target": None, "confidence": 0.8})
        record = self.recorded()[0]
        argv = record["argv"]
        self.assertEqual(argv[argv.index("--output-format") + 1], "stream-json")
        self.assertEqual(argv[argv.index("--input-format") + 1], "stream-json")
        self.assertIn("--disable-slash-commands", argv)
        self.assertNotIn("--dangerously-skip-permissions", argv)  # A step that asks is skipped.
        self.assertEqual(json.loads(argv[argv.index("--settings") + 1]), READ_ONLY_SETTINGS)
        self.assertEqual(argv[argv.index("--model") + 1:argv.index("--model") + 4], ["gemini-3.8-flash", "--effort", "low"])
        self.assertNotIn(QUESTION, " ".join(argv))
        line = json.loads(record["stdin"])
        self.assertEqual(line["event"], "user")
        self.assertTrue(line["message"]["content"].startswith("只回一行 JSON\n\n"))
        self.assertIn(QUESTION, line["message"]["content"])
        home = Path(record["home"])
        self.assertEqual(home.parent, self.state / "tmp")
        self.assertFalse(home.exists())  # The scratch home, the conversation in it, went with the question.
        self.assertIn(agy_home.TOKEN, record["linked"])
        for name in ("conversations", "brain", "log"):
            self.assertNotIn(name, record["linked"])
        self.assertEqual(record["listing"], [".gemini"])  # No config/: none of the owner's MCP servers or rules.
        self.assertTrue((self.home / ".gemini" / "config" / "mcp_config.json").exists())  # The owner's untouched.

    def test_a_heavy_question_runs_on_agys_own_default_and_the_variable_names_one(self):
        self.sign_in()
        self.rows(AGY_ROWS)
        self.ask(heavy=True)
        self.assertNotIn("--model", self.recorded()[-1]["argv"])
        with mock.patch.dict(os.environ, {agy_judge.MODEL_ENV: "gemini-4-neon-low"}):
            self.ask()
        argv = self.recorded()[-1]["argv"]
        self.assertEqual(argv[argv.index("--model") + 1], "gemini-4-neon-low")
        self.assertNotIn("--effort", argv)

    def test_a_light_model_is_a_word_of_its_name_never_inside_another(self):
        catalog = {"gemini-4-neon": {"display_name": "Gemini 4 Neon"},
                   "gemini-3.8-flash": {"display_name": "Gemini 3.8 Flash"}}
        self.assertEqual(agy_judge.choose(catalog, heavy=False, environ={})[0], "gemini-3.8-flash")  # Not "gemini" ⊃ "mini".
        self.assertEqual(agy_judge.choose({"gemini-4-neon": {}}, heavy=False, environ={}), ("", ""))

    def test_an_error_result_or_no_result_is_a_reason(self):
        self.assertEqual(agy_judge.answer_of(AGY_ROWS), '{"route":"new","target":null,"confidence":0.8}\n')
        with self.assertRaises(AskFailed) as caught:
            agy_judge.answer_of([{"event": "result", "result": {"status": "ERROR", "error": "quota"}}])
        self.assertEqual(caught.exception.reason, "model_error")
        with self.assertRaises(AskFailed) as caught:
            agy_judge.answer_of([{"event": "init"}])
        self.assertEqual(caught.exception.reason, "bad_output")

    def test_signed_in_by_the_token_or_an_api_key(self):
        self.assertFalse(agy_home.signed_in({"HOME": str(self.home)}))
        self.assertTrue(agy_home.signed_in({"HOME": str(self.home), "GEMINI_API_KEY": "fake"}))
        self.sign_in()
        self.assertTrue(agy_home.signed_in({"HOME": str(self.home)}))


class CapabilityTest(unittest.TestCase):
    def test_codex_and_agy_answer_one_question_on_this_machine_only(self):
        ctx = SimpleNamespace(device=None, options={})
        for backend in (CodexBackend(), AntigravityBackend()):
            with self.subTest(backend=type(backend).__name__):
                capabilities = backend_capabilities(backend, ctx)
                self.assertTrue(capabilities.ask_once and capabilities.bridge_tools)
        self.assertFalse(for_device(HarnessCapabilities(ask_once=True), SimpleNamespace(device="box")).ask_once)


class RoutingTest(unittest.TestCase):
    """app/track_judge.py: where a question goes and how its answer comes back."""

    @staticmethod
    def app(name, *, ask_once=False, answer='{"route":"merge","target":1,"confidence":0.9}'):
        calls = []

        def ask(ctx, system, data, *, heavy=False, limit, cwd=None):
            calls.append({"system": system, "data": data, "heavy": heavy, "limit": limit, "cwd": cwd})
            if isinstance(answer, AskFailed):
                raise answer
            return answer
        backend = SimpleNamespace(capabilities=lambda ctx: HarnessCapabilities(ask_once=ask_once), ask_once=ask,
                                  calls=calls)
        context = SimpleNamespace(backend_cmd=[name], state_dir=Path("/absolute/state"), options={"harness_id": name},
                                  device=None)
        return SimpleNamespace(harness=SimpleNamespace(backend=backend, context=context), backend=backend)

    def setUp(self):
        patch = mock.patch.dict(os.environ, {"COVEY_TRACK_JUDGE_WARM": "0"})
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("COVEY_JUDGE_GATEWAY", "LARK_BRIDGE_JUDGE_GATEWAY", "COVEY_TRACK_JUDGE", "COVEY_TRACK_JUDGE_MS"):
            os.environ.pop(name, None)

    def test_claude_code_first_then_codex_then_antigravity_and_never_one_that_cannot_answer_alone(self):
        claude, codex, agy, pi = self.app("claude"), self.app("codex", ask_once=True), self.app("agy", ask_once=True), \
            self.app("pi")
        for apps, want in (({"claude": claude, "codex": codex, "agy": agy}, claude),
                           ({"codex": codex, "agy": agy}, codex), ({"agy": agy, "pi": pi}, agy)):
            with self.subTest(apps=sorted(apps)):
                self.assertEqual(track_judge.tools(apps), (want.harness.backend, want.harness.context))
        self.assertEqual(track_judge.tools({"pi": pi}), (None, None))
        self.assertEqual(track_judge.tools({}), (None, None))
        self.assertFalse(track_judge.available({"pi": pi}, environ={}))
        self.assertTrue(track_judge.available({"codex": codex}, environ={}))
        self.assertTrue(track_judge.available({}, environ={"COVEY_JUDGE_GATEWAY": "gw:model"}))

    def test_a_native_harness_gets_the_question_and_its_answer_comes_back_as_an_envelope(self):
        codex = self.app("codex", ask_once=True)
        backend, ctx = track_judge.tools({"codex": codex})
        raw = track_judge.ask("系统", "{}", backend=backend, ctx=ctx, limit=30, cwd="/absolute/state/judge", environ={})
        self.assertEqual(track_judge.answer_text(raw, "claude"), '{"route":"merge","target":1,"confidence":0.9}')
        self.assertEqual(backend.calls[-1], {"system": "系统", "data": "{}", "heavy": False, "limit": 30,
                                             "cwd": "/absolute/state/judge"})
        track_judge.ask("系统", "{}", backend=backend, ctx=ctx, limit=30, cwd="/c", model="sonnet", environ={})
        self.assertTrue(backend.calls[-1]["heavy"])  # 整理专项's model: the Harness's own default.
        failing = self.app("agy", ask_once=True, answer=AskFailed("not_signed_in"))
        backend, ctx = track_judge.tools({"agy": failing})
        with self.assertRaises(track_judge.Failed) as caught:
            track_judge.ask("系统", "{}", backend=backend, ctx=ctx, limit=30, cwd="/c", environ={})
        self.assertEqual(caught.exception.reason, "not_signed_in")
        with self.assertRaises(track_judge.Failed) as caught:
            track_judge.ask("系统", "{}", backend=None, ctx=None, limit=30, cwd="/c", environ={})
        self.assertEqual(caught.exception.reason, "no_backend")

    def test_the_gateway_set_comes_first(self):
        codex = self.app("codex", ask_once=True)
        backend, ctx = track_judge.tools({"codex": codex})
        with mock.patch.object(track_judge.judge_gateway, "ask", return_value='{"result":"x"}') as gateway:
            track_judge.ask("s", "{}", backend=backend, ctx=ctx, limit=5, cwd="/c",
                            environ={"COVEY_JUDGE_GATEWAY": "gw:model"})
        gateway.assert_called_once()
        self.assertEqual(backend.calls, [])

    def test_the_router_asks_codex_with_its_own_limit_logs_where_and_warms_no_claude_code(self):
        codex = self.app("codex", ask_once=True)
        backend, ctx = track_judge.tools({"codex": codex})
        live = (LiveJob(1, "j1", "running", "整理对比表", NOW - 300, NOW - 200),)
        lines = []
        verdict = track_judge.judge(Message(QUESTION, live, Quote(), now=NOW), backend=backend, ctx=ctx,
                                    log=lines.append, environ={})
        self.assertEqual((verdict.route, verdict.target), ("merge", 1))
        self.assertEqual(backend.calls[-1]["limit"], track_judge.NATIVE_MS / 1000)
        self.assertEqual(Path(backend.calls[-1]["cwd"]), Path("/absolute/state/track-judge"))
        self.assertTrue(lines[-1].startswith("track judge route=merge target=1") and lines[-1].endswith("via=codex"))
        self.assertNotIn(QUESTION, "\n".join(lines))
        with mock.patch.object(track_judge.track_standby, "warm") as warm:
            self.assertFalse(track_judge.warm(backend, ctx, environ={}))
        warm.assert_not_called()
        verdict = track_judge.judge(Message(QUESTION, live, Quote(), now=NOW), redacted=True, backend=backend, ctx=ctx,
                                    log=lines.append, environ={})
        self.assertEqual((verdict.route, verdict.why, len(backend.calls)), ("new", "redacted", 1))  # Nothing sent.

    def test_a_native_failure_is_new_with_its_reason(self):
        codex = self.app("codex", ask_once=True, answer=AskFailed("timeout"))
        backend, ctx = track_judge.tools({"codex": codex})
        live = (LiveJob(1, "j1", "running", "整理对比表", NOW - 300, NOW - 200),)
        lines = []
        verdict = track_judge.judge(Message(QUESTION, live, Quote(), now=NOW), backend=backend, ctx=ctx,
                                    log=lines.append, environ={})
        self.assertEqual((verdict.route, verdict.why), ("new", "timeout"))
        self.assertIn("track judge failed reason=timeout", lines[-1])
        self.assertTrue(lines[-1].endswith("via=codex"))

    def test_the_native_limit_is_its_own_unless_the_variable_says(self):
        self.assertEqual(track_judge.limit_ms({}, native=True), track_judge.NATIVE_MS)
        self.assertEqual(track_judge.limit_ms({}), track_judge.DEFAULT_MS)
        self.assertEqual(track_judge.limit_ms({"COVEY_TRACK_JUDGE_MS": "6000"}, native=True), 6000)


if __name__ == "__main__":
    unittest.main()
