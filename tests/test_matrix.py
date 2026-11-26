"""入口 × Harness × 界面 (AGENTS.md 收敛期): every way into Covey on every core Harness, and where its turns show.

The entries are the rows: the butler (管家, the private chat's top level), a project's lead (负责人), a topic (话题: the
launch card, 换配置, the butler's topic_start) and a topic opened on the web page (网页). The columns are core/roster.py
CORE_HARNESSES. The surfaces are the Feishu cards (core/placement.py by role, the relay of a web topic to the private chat)
and the web page (app/web_collect.py). One subTest a cell, each asked the same way of every Harness; what a backend does in
detail stays in its own tests (test_claude, test_codex, test_agy, test_dsh, test_butler_harness, test_lead_harness).

A cell left out is what the owner kept finding by hand: the butler only on Claude Code (T614), a lead that could not choose
its Harness (T664), the butler on Antigravity without topic_start (T750, T754), a topic opened on the web page whose outcome
never came back to the private chat (T762). A Harness added to the roster fails ``test_every_core_harness_says_how_its_cells_are_seen`` until ``SEEN`` says how its backend takes the Bridge's
tools and holds a lead to reading. A cell that does not hold on a Harness on purpose is in ``GAPS`` with why; it fails here
when it starts to hold, so the list stays true.
"""
from __future__ import annotations

import json
import os
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from support import UNSET_OFF
from support import make_context
from support.records import write_job, write_topic
from support.world import UnifiedCase
from test_web_sync import T0, WebCase

from covey.app import butler_harness, lead_harness, relay_targets, tool_limits, web_launch
from covey.app.butler_model_choice import resolve
from covey.app.launch_models import available_models
from covey.backends.agy import home as agy_home
from covey.backends.agy.bridge import READ_ONLY_SETTINGS, AntigravityBackend
from covey.backends.claude import argv as claude_argv
from covey.backends.claude.bridge import ClaudeBackend
from covey.backends.codex import appserver
from covey.backends.dsh import bridge as dsh_bridge
from covey.core import butler, butler_mcp, butler_settings, placement, projects
from covey.core.butler import butler_topic_id
from covey.core.butler_tool_specs import HANDING
from covey.core.harness import LEAD, READ, TOOL_LIMIT, backend_capabilities
from covey.core.history_storage import append_history
from covey.core.menu_choice import butler_harnesses, harness_of
from covey.core.redaction import TOPIC_KEY as REDACTION_KEY
from covey.core.roster import CORE_HARNESSES
from covey.core.state import write_json

BRIDGE = {"mcpServers": {"bridge": {"command": "python3", "args": ["mcp.py"], "env": {"K": "v"}}}}
# The Bridge's tools with every switch that adds one on: the most a Harness with a budget (Antigravity) has to fit.
BUTLER_ENV = {"COVEY_PROJECTS": "1", "COVEY_KNOWLEDGE": "1", "COVEY_HISTORY_CMD": "/absolute/history",
              "COVEY_PROJECT_TIDY": "suggest", "COVEY_BUTLER_RULES": "1"}
LEAD_ENV = {"COVEY_PROJECT_LEAD": "p1", "COVEY_PROJECT_TRIAGE": "1", "COVEY_COLLAB": "1", "COVEY_PROJECT_AUTOWAKE": "1"}


def names(tools) -> set:
    return {tool["name"] for tool in tools}


def claude_tools(ctx, tools) -> set:
    argv = claude_argv.stream_argv(ClaudeBackend(), ctx)
    config = json.loads(argv[argv.index("--mcp-config") + 1]) if "--mcp-config" in argv else {}
    return names(tools) if "bridge" in config.get("mcpServers", {}) else set()


def claude_lead(ctx) -> bool:
    argv = claude_argv.stream_argv(ClaudeBackend(), ctx)
    return argv[argv.index("--tools") + 1] == ",".join(claude_argv.READ_TOOLS) and "--mcp-config" in argv


def codex_tools(ctx, tools) -> set:
    params, _ = appserver.thread_params(ctx, None)
    return names(tools) if params["config"].get("mcp_servers.bridge.enabled") is True else set()


def codex_lead(ctx) -> bool:
    params, _ = appserver.thread_params(ctx, None)
    return params["sandbox"] == "read-only" and params["config"].get("mcp_servers.bridge.enabled") is True


def dsh_tools(ctx, tools) -> set:
    rows = dsh_bridge.mcp_rows(ctx.options.get("mcp_config"))
    return names(tools) if any(row["id"] == "mcp-bridge" for row in rows) else set()


def dsh_lead(ctx) -> bool:
    return (dsh_bridge.lead_turn(ctx) and "read-only" in dsh_bridge.LEAD_ARGS
            and "read-only" in dsh_bridge.DshBackend().prompt_runtime_note(ctx))


def agy_tools(ctx, tools) -> set:
    """What agy loads up front of the Bridge's server in the butler's private home: its tool budget is the only one."""
    with mock.patch.object(agy_home, "listed_tools", lambda server, env, timeout=agy_home.LIST_SECONDS: list(tools)):
        servers, _ = agy_home.agy_servers(ctx.options.get("mcp_config"), {})
    return set((servers.get("bridge") or {}).get("tools") or ())


def agy_lead(ctx) -> bool:
    argv = AntigravityBackend().argv(ctx, None)
    return "--settings" in argv and json.loads(argv[argv.index("--settings") + 1]) == READ_ONLY_SETTINGS


# How each core Harness's backend is seen to take the Bridge's tools (the names a turn has at hand, given the server's
# list: all of them, or Antigravity's up-front ones) and to hold a lead's turn to reading with those tools kept.
SEEN = {
    "claude": {"tools": claude_tools, "lead": claude_lead},
    "codex": {"tools": codex_tools, "lead": codex_lead},
    "dsh": {"tools": dsh_tools, "lead": dsh_lead},
    "agy": {"tools": agy_tools, "lead": agy_lead},
}
# Cells that do not hold on a Harness, on purpose or not yet, with why. A cell here that starts to hold fails
# test_the_known_gaps_are_still_gaps: take it off.
GAPS = {
    ("话题 · 群成员只读", "agy"): "agy 没声明 read_only：群成员只读的群里这一轮不启动（app/tool_limits.py refusal）。"
                                  "它给负责人用的 deny 规则（READ_ONLY_SETTINGS）也能守住只读，待接上",
    ("话题 · 群成员只读", "dsh"): "dsh 没声明 read_only：同上；它给负责人用的 --permission-mode read-only 待接上",
    ("话题 · 敏感词脱敏", "codex"): "设计如此：脱敏经 Claude 的词表中转，只有 Claude Code 能脱敏（docs/architecture.md 敏感词脱敏）",
    ("话题 · 敏感词脱敏", "dsh"): "设计如此：同上",
    ("话题 · 敏感词脱敏", "agy"): "设计如此：同上",
}


def held(cell, harness) -> bool:
    return (cell, harness) not in GAPS


def gap_words(cell, harness) -> str:
    """What a failure of the cell says to do."""
    if held(cell, harness):
        return f"{cell} × {harness} 不成立了：修好，或写进 GAPS 并写明原因"
    return f"{cell} × {harness} 已经成立：从 GAPS 去掉"


class HarnessCellsCase(UnifiedCase):
    """The UnifiedBridgeApp with every core Harness, the butler on (agent mode) in the owner's private chat."""

    def setUp(self):
        super().setUp()
        env = {name: value for name, value in os.environ.items() if not name.startswith(("COVEY_", "LARK_BRIDGE_"))}
        patch = mock.patch.dict(os.environ, {**env, **UNSET_OFF}, clear=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.state = self.ctx.state_dir
        self.addCleanup(butler.configure_state, butler.configure_state(self.state))
        write_json(self.state / butler_settings.FILE, {"mode": "agent"})
        butler.forget_mode()
        self.addCleanup(butler.forget_mode)
        self.apps = self.app.apps
        self.choices = available_models(self.app.topics, self.ctx)
        self.chat = "oc_owner_dm"

    def capabilities(self, name):
        app = self.apps[name]
        return backend_capabilities(app.backend, app.harness.context)

    def menu_harnesses(self, choices) -> set:
        return {harness_of(key, entry) for key, entry in choices.items()}


class RowsTest(HarnessCellsCase):
    def test_every_core_harness_says_how_its_cells_are_seen(self):
        self.assertEqual(sorted(SEEN), sorted(CORE_HARNESSES), "a Harness of the roster without its row in SEEN: say how its "
                         "backend takes the Bridge's tools and holds a lead to reading")
        self.assertLessEqual({harness for _, harness in GAPS}, set(CORE_HARNESSES))
        self.assertTrue(all(why.strip() for why in GAPS.values()))

    def test_every_core_harness_is_enabled_in_the_bridge_the_tests_build(self):
        self.assertLessEqual(set(CORE_HARNESSES), set(self.apps))
        self.assertLessEqual(set(CORE_HARNESSES), self.menu_harnesses(self.choices))


class ButlerRowTest(HarnessCellsCase):
    """管家 × Harness."""

    def test_the_butler_runs_on_every_harness_and_alone_falls_back_to_it(self):
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                app = self.apps[name]
                self.assertTrue(butler_harness.takes_tools(app))
                self.assertEqual(butler_harness.default_name({name: app}), name)

    def test_the_settings_card_offers_every_harness_for_the_butler(self):
        offered = set(butler_harnesses(self.choices))
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertIn(name, offered)

    def test_the_butlers_tools_that_hand_work_on_are_at_hand_on_every_harness(self):
        tools = butler_mcp.tool_list(BUTLER_ENV)
        wanted = HANDING & names(tools)
        self.assertTrue({"topic_start", "topic_send", "topic_fork", "project_send"} <= wanted)
        ctx = make_context(self.root, options={"mcp_config": BRIDGE})
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                at_hand = SEEN[name]["tools"](ctx, tools)
                self.assertTrue(at_hand, "the Bridge's server does not reach the model")
                self.assertEqual(sorted(wanted - at_hand), [])


class LeadRowTest(HarnessCellsCase):
    """负责人 × Harness."""

    def test_a_lead_runs_on_every_harness(self):
        ctx = make_context(self.root, options={TOOL_LIMIT: LEAD})
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                app = self.apps[name]
                self.assertTrue(lead_harness.runs_lead(app))
                self.assertEqual(lead_harness.refusal(self.apps, name), "")
                self.assertEqual(tool_limits.refusal(ctx, self.capabilities(name), name), "")

    def test_every_harness_is_a_leads_choice_on_the_cards_and_the_page(self):
        offered = self.menu_harnesses(lead_harness.lead_choices(self.choices))
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertIn(name, offered)

    def test_where_the_butler_redacts_a_new_lead_takes_a_harness_only_if_it_redacts(self):
        """The lead's 脱敏 is the butler's when it is made (app/lead_harness.py binding): a Harness the butler's call names
        that cannot redact gives way to the butler's own, so no lead turn goes out unredacted. (换配置 on the 专项卡 can turn
        the lead's 脱敏 off afterwards, as a topic's: docs/projects.md 负责人用哪个 Harness.)"""
        root = {"harness_id": "claude", "model": "claude-model", REDACTION_KEY: True}
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                found = lead_harness.binding(self.apps, root, call={"harness": name, "model": f"{name}-model"})
                self.assertEqual(found["source"] == "call", self.capabilities(name).redaction)
                found = lead_harness.binding(self.apps, {**root, REDACTION_KEY: False}, call={"harness": name})
                self.assertEqual((found["source"], found["harness_id"]), ("call", name))

    def test_a_leads_turn_is_held_to_reading_with_its_tools_on_every_harness(self):
        tools = butler_mcp.tool_list(LEAD_ENV)
        wanted = HANDING & names(tools)
        self.assertTrue({"project_topic_start", "project_topic_send"} <= wanted)
        ctx = make_context(self.root, options={TOOL_LIMIT: LEAD, "mcp_config": BRIDGE})
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertTrue(SEEN[name]["lead"](ctx))
                self.assertEqual(sorted(wanted - SEEN[name]["tools"](ctx, tools)), [])


class TopicRowTest(HarnessCellsCase):
    """话题 × Harness: the launch card and 换配置 list the menu (app/launch_models.py available_models); the butler's
    topic_start names a Harness (app/butler_model_choice.py resolve)."""

    def test_the_launch_card_and_the_switch_card_list_every_harness(self):
        listed = self.menu_harnesses(self.choices)
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertIn(name, listed)

    def test_the_butlers_topic_start_opens_a_topic_on_every_harness(self):
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                found = resolve(self.app.topics, self.state, self.chat, butler_settings.TopicDefaults(), {"harness": name},
                                self.choices)
                self.assertIsInstance(found, dict, found)
                self.assertEqual(found["harness"], name)

    def test_a_group_members_read_only_turn(self):
        ctx = make_context(self.root, options={TOOL_LIMIT: READ})
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertEqual(tool_limits.refusal(ctx, self.capabilities(name), name) == "", held("话题 · 群成员只读", name),
                                 gap_words("话题 · 群成员只读", name))

    def test_redaction(self):
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertEqual(self.capabilities(name).redaction, held("话题 · 敏感词脱敏", name),
                                 gap_words("话题 · 敏感词脱敏", name))


class WebRowTest(HarnessCellsCase):
    """网页 × Harness: the page's 新话题 (app/web_launch.py catalog) and a topic it opened relaying to the private chat."""

    def test_the_web_page_opens_a_topic_on_every_harness(self):
        env = SimpleNamespace(topics=self.app.topics, runtime=self.app.runtime)
        models = web_launch.catalog(env, self.ctx, self.chat)["models"]
        offered = {model["harness"] for model in models}
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                self.assertIn(name, offered)
                self.assertTrue(all(model["bridge_tools"] for model in models if model["harness"] == name))

    def test_a_topic_opened_on_the_web_page_relays_to_the_private_chat_on_every_harness(self):
        for name in CORE_HARNESSES:
            with self.subTest(harness=name):
                topic = f"web-{name}"
                write_topic(self.state, topic_id=topic, chat_id=self.chat, harness_id=name, topic_number=7,
                            root_id=f"om_root_{name}", origin={"kind": "web", "request": f"web-op-{name}", "title": "页面开的"})
                target = relay_targets.area_target(self.state, topic, self.chat)
                self.assertIsNotNone(target)
                self.assertEqual((target["chat_id"], target["reply_to"], target["kind"]), (self.chat, f"om_root_{name}", "follow"))


class FeishuSurfaceTest(unittest.TestCase):
    """界面 · 飞书: each entry's turn has a place in the private chat (core/placement.py), whatever its Harness."""

    def test_every_entry_says_its_answer_somewhere(self):
        rows = {role: placement.TABLE[(placement.AREA, role)] for role in
                (placement.BUTLER_ROLE, placement.LEAD_ROLE, placement.TOPIC_ROLE, placement.MEMBER_ROLE)}
        for role, row in rows.items():
            with self.subTest(role=role):
                self.assertNotEqual(row.answer, placement.NONE)
        # A topic's outcome and its questions come back to the top level; a project member's go to its lead.
        self.assertEqual((rows["topic"].conclusion, rows["topic"].stop, rows["topic"].question_copy),
                         (placement.TOP, placement.TOP, placement.TOP))
        self.assertEqual(placement.TABLE[(placement.TOPICS, placement.TOPIC_ROLE)].answer, placement.THREAD)


class WebSurfaceTest(WebCase):
    """界面 · 网页: the butler's, the lead's, a topic's and a web-opened topic's turns are pushed to the page on every
    Harness, each a topic item of its kind naming its Harness, with the agent's answer as a turn."""

    def entries(self, name):
        """{topic id: kind} of the four entries written on ``name``, each with one finished turn."""
        butler_id = butler_topic_id(self.chat)
        lead_id = projects.lead_topic_id(self.chat, self.pid)
        write_topic(self.state, topic_id=butler_id, chat_id=self.chat, harness_id=name, main_thread=True,
                    workspace_name="ws1", workdir=str(self.state))
        write_topic(self.state, topic_id=lead_id, chat_id=self.chat, harness_id=name,
                    project=projects.project_field(self.pid, projects.LEAD))
        write_topic(self.state, topic_id="t-topic", chat_id=self.chat, harness_id=name, topic_number=7,
                    origin={"title": "普通话题"}, workspace_name="ws1")
        write_topic(self.state, topic_id="t-web", chat_id=self.chat, harness_id=name, topic_number=8, workspace_name="ws1",
                    root_id="om_web_root", origin={"kind": "web", "request": "web-op-1", "title": "网页开的"})
        found = {butler_id: "butler", lead_id: "lead", "t-topic": "topic", "t-web": "topic"}
        for number, topic in enumerate(found, 1):
            write_job(self.state, f"k-{number}", topic_id=topic, chat_id=self.chat, job_id=number, status="done",
                      model=f"{name}-model", harness_id=name, message_id=f"om_m{number}",
                      timings={"backend_started": time.time() - 60})
            history = self.state / "topics" / topic / "history.jsonl"
            append_history(history, "user", "做件事", {"message_id": f"om_m{number}"})
            append_history(history, "assistant", f"{name} 做完了", {})
        return found

    def check(self, name):
        found = self.entries(name)
        self.sync.push_once(T0)
        by = {(item["type"], item["key"]): item["data"] for item in self.web.items()}
        for topic, kind in found.items():
            with self.subTest(harness=name, topic=topic):
                item = by.get(("topic", topic))
                self.assertIsNotNone(item, "not on the web page")
                self.assertEqual((item["kind"], item["harness"]), (kind, name))
                turns = [data for (kind_, _), data in by.items() if kind_ == "turn" and data.get("topic_key") == topic]
                self.assertIn(f"{name} 做完了", [turn.get("body") for turn in turns])

    def setUp(self):
        super().setUp()
        self.chat, self.pid = "oc_owner_dm", "a1b2c3d4e5f6"


for _name in CORE_HARNESSES:
    setattr(WebSurfaceTest, f"test_the_four_entries_show_on_the_web_page_on_{_name}", lambda self, n=_name: self.check(n))


class KnownGapsTest(HarnessCellsCase):
    def test_the_known_gaps_are_still_gaps(self):
        """The cells GAPS lists are asked above (test_a_group_members_read_only_turn, test_redaction): one that holds now
        fails there; this one keeps GAPS to cells those tests ask."""
        self.assertLessEqual({cell for cell, _ in GAPS}, {"话题 · 群成员只读", "话题 · 敏感词脱敏"})


if __name__ == "__main__":
    unittest.main()
