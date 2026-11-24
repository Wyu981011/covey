"""整理记忆 (COVEY_MEMORY_LEARN=1, app/memory_tidy.py, core/project_memory.py settle and unsettle, cards/digest.py
memory_elements, app/digest.py memory_click): a project's lines put away as done, superseded or unused and put back by 撤销, the
rules the model distilled carried as 它总结的 until 确认长期 makes them the owner's, the carried candidates nobody used let go,
and the evening digest's part with its buttons."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import make_context

from covey.app import memory_candidates, memory_tidy
from covey.app.track_standby import Failed
from covey.cards.digest import MEMORY_KIND, digest_card, digest_text, memory_elements
from covey.core import memory, memory_usage, project_memory, projects
from covey.core.state import write_json

ON = {memory.ENV: "1", memory.LEARN_ENV: "1", projects.ENV: "1", projects.MEMORY_ENV: "1"}
PID, CHAT = "a1b2c3d4e5f6", "oc_owner_dm"
DAY = 86400
NOW = 1_800_000_000.0


def envelope(value) -> str:
    return json.dumps({"result": json.dumps(value, ensure_ascii=False)})


def buttons(card):
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("tag") == "button":
                found.append(node["behaviors"][0]["value"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(card)
    return found


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.dict(os.environ, ON)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = make_context(Path(tmp.name))
        self.state = self.ctx.state_dir
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="网关", goal="把网关发出去", project_id=PID, now=NOW))
        self.logs = []
        self.asked = []

    def line(self, text, source="owner_answer", kind="decision", at=NOW):
        entry, _ = project_memory.add(self.state, PID, text, kind, source, now=at)
        return entry["id"]

    def tidy(self, answer=None, error=None):
        def ask(system, data, **kwargs):
            self.asked.append(json.loads(data))
            if error is not None:
                raise error
            return envelope(answer or {})
        return memory_tidy.MemoryTidy(mock.Mock(log=self.logs.append), mock.Mock(apps={}), ask=ask)

    def parts(self):
        found = {}
        for row in project_memory.stored(self.state, PID):
            if not row["deleted"]:
                found[row["text"]] = memory.describe(row)
        return found


class SettleTest(Case):
    def test_a_settled_line_is_history_and_unsettle_puts_it_back(self):
        one = self.line("现在部署吗→部署")
        settled = project_memory.settle(self.state, PID, [{"id": one, "valid": "done"}, {"id": "nope", "valid": "done"}])
        self.assertEqual(settled, [(one, {})])
        self.assertEqual(self.parts()["现在部署吗→部署"]["layer"], memory.HISTORY)
        self.assertEqual(project_memory.unsettle(self.state, PID, settled), [one])
        self.assertEqual(self.parts()["现在部署吗→部署"]["part"], memory.DECISION)

    def test_superseded_keeps_who_replaced_it(self):
        old, new = self.line("用 A 方案"), self.line("改用 B 方案")
        project_memory.settle(self.state, PID, [{"id": old, "valid": "superseded", "superseded_by": new}])
        facts = self.parts()["用 A 方案"]
        self.assertEqual((facts["valid"], facts["superseded_by"]), ("superseded", new))


class RunTest(Case):
    def test_done_superseded_and_a_rule_from_several_decisions(self):
        deploy = self.line("主人答：现在部署吗？→部署（推荐）")
        a1 = self.line("主人答：镜像先发预发吗？→先发预发（推荐）")
        a2 = self.line("主人答：这次也先发预发吗？→先发预发")
        old = self.line("主人答：用哪个配置？→A")
        new = self.line("主人答：用哪个配置？→B")
        self.line("用中文回复", source="owner", kind="constraint")  # His 长期约定: never put away.
        run = self.tidy({"done": [deploy], "superseded": [{"id": old, "by": new}],
                         "rules": [{"text": "发网关镜像都先发预发", "from": [a1, a2]}, {"text": "只有一条依据", "from": [a1]}]}
                        ).run(self.ctx, CHAT, NOW, now=NOW)
        parts = self.parts()
        self.assertEqual(parts["主人答：现在部署吗？→部署（推荐）"]["valid"], "done")
        self.assertEqual(parts["主人答：用哪个配置？→A"]["valid"], "superseded")
        self.assertEqual(parts["发网关镜像都先发预发"]["part"], memory.REFERENCE)  # 它总结的, carried at once.
        self.assertNotIn("只有一条依据", parts)
        self.assertEqual(parts["用中文回复"]["part"], memory.RULE)
        self.assertEqual([line["part"] for line in self.asked[0]["lines"]], ["当前决定"] * 5)
        self.assertEqual(self.asked[0]["rules"], ["用中文回复"])
        view = memory_tidy.view_of(run)
        self.assertEqual(view["away"], {"idle": 0, "done": 1, "superseded": 1})
        self.assertEqual([rule["text"] for rule in view["rules"]], ["发网关镜像都先发预发"])

    def test_a_line_nobody_used_for_long_goes_without_the_model_and_one_used_stays(self):
        stale = self.line("主人答：旧问题→旧回答", at=NOW - 40 * DAY)
        used = self.line("主人答：常用的问题→常用的回答", at=NOW - 40 * DAY)
        memory_usage.note(self.state, [f"project:{PID}:{used}"], now=NOW - 2 * DAY)
        run = self.tidy().run(self.ctx, CHAT, NOW, now=NOW)
        self.assertEqual(self.asked, [])  # Fewer than MIN_LINES left: no model.
        self.assertEqual(self.parts()["主人答：旧问题→旧回答"]["valid"], "done")
        self.assertEqual(self.parts()["主人答：常用的问题→常用的回答"]["valid"], "active")
        self.assertEqual(memory_tidy.view_of(run)["away"]["idle"], 1)
        self.assertEqual(stale, run["projects"][0]["settled"][0][0])

    def test_a_slot_is_tidied_once_and_a_failed_model_leaves_the_lines(self):
        for i in range(4):
            self.line(f"主人答：问题 {i}→回答 {i}")
        tidy = self.tidy(error=Failed("timeout"))
        self.assertEqual(tidy.view(self.ctx, CHAT, NOW, now=NOW), {})  # Nothing put away.
        self.assertEqual(len(self.asked), 1)
        tidy.view(self.ctx, CHAT, NOW, now=NOW)
        self.assertEqual(len(self.asked), 1)
        self.assertTrue(all(facts["valid"] == "active" for facts in self.parts().values()))

    def test_undo_puts_back_what_it_put_away_and_confirm_makes_a_rule_his(self):
        ids = [self.line(f"主人答：发布前先跑冒烟吗？第 {i} 次→跑") for i in range(3)]
        tidy = self.tidy({"done": [ids[0]], "rules": [{"text": "发布前先跑冒烟", "from": ids[1:]}]})
        run = tidy.run(self.ctx, CHAT, NOW, now=NOW)
        rule = run["projects"][0]["rules"][0]
        tidy.decide(self.ctx, run["id"], "confirm", project=PID, entry=rule["entry"], message_id="om_card")
        self.assertEqual(self.parts()["发布前先跑冒烟"]["part"], memory.RULE)  # 你说的 now.
        again = tidy.decide(self.ctx, run["id"], "wrong", project=PID, entry=rule["entry"])
        self.assertEqual(again["projects"][0]["rules"][0]["state"], memory_tidy.CONFIRMED)  # Decided once.
        undone = tidy.decide(self.ctx, run["id"], "undo")
        self.assertTrue(undone["undone"])
        self.assertEqual(self.parts()["主人答：发布前先跑冒烟吗？第 0 次→跑"]["valid"], "active")

    def test_a_carried_candidate_nobody_used_is_let_go_and_undo_opens_it_again(self):
        write_json(memory_candidates.path(self.state), {"schema_version": 1, "rows": [
            {"id": "c0a1b2c3d", "text": "汇报先给结论", "workspace": "", "slot": NOW - 40 * DAY, "at": NOW - 40 * DAY,
             "state": "open", "carried": True, "source": "repeat"},
            {"id": "c0a1b2c3e", "text": "回复用中文", "workspace": "", "slot": NOW - 40 * DAY, "at": NOW - 40 * DAY,
             "state": "open", "carried": True, "source": "repeat"}], "declined": [], "ran": []})
        memory_usage.note(self.state, ["candidate:c0a1b2c3e"], now=NOW - DAY)
        tidy = self.tidy()
        run = tidy.run(self.ctx, CHAT, NOW, now=NOW)
        self.assertEqual(run["expired"], ["c0a1b2c3d"])
        self.assertEqual(memory_candidates.carried(self.state, "")[0][0]["id"], "c0a1b2c3e")
        tidy.decide(self.ctx, run["id"], "undo")
        self.assertEqual(len(memory_candidates.carried(self.state, "")[0]), 2)


class CardTest(Case):
    VIEW = {"run": "t0a1b2c3d", "away": {"idle": 1, "done": 8, "superseded": 3}, "expired": 2, "undone": False,
            "rules": [{"project": PID, "name": "网关", "entry": "e1", "text": "发网关镜像都先发预发", "state": "open"}]}

    def test_the_part_says_what_went_away_and_has_its_buttons(self):
        elements = memory_elements({"memory_tidy": self.VIEW})
        text = json.dumps(elements, ensure_ascii=False)
        self.assertIn("收起 12 条：办完的 8 条、被新回答替代的 3 条、很久没用的 1 条", text)
        self.assertIn("2 条候选很久没用，不再带", text)
        self.assertIn("专项「网关」 · 新约定，已先照着做（它总结的）", text)
        self.assertEqual([(value["op"], value.get("entry")) for value in buttons(elements)],
                         [("undo", None), ("confirm", "e1"), ("wrong", "e1")])
        self.assertTrue(all(value["kind"] == MEMORY_KIND and value["run"] == "t0a1b2c3d" for value in buttons(elements)))

    def test_decided_and_undone_are_grey_lines_and_none_without_the_part(self):
        view = {**self.VIEW, "undone": True, "rules": [{**self.VIEW["rules"][0], "state": "confirmed"}]}
        text = json.dumps(memory_elements({"memory_tidy": view}), ensure_ascii=False)
        self.assertIn("已撤销，都放回去了", text)
        self.assertIn("已确认，以后算你说的", text)
        self.assertEqual(buttons(memory_elements({"memory_tidy": view})), [])
        self.assertEqual(memory_elements({}), [])

    def test_the_digest_card_and_its_markdown_carry_it(self):
        view = {"slot": NOW, "since": NOW - DAY, "waiting": [], "running": [], "done": [], "memory_tidy": self.VIEW}
        self.assertIn("整理记忆", json.dumps(digest_card(view), ensure_ascii=False))
        self.assertIn("发网关镜像都先发预发", digest_text(view))


class ClickTest(Case):
    def test_the_owners_click_is_decided_after_the_ack_and_others_are_ignored(self):
        from covey.app.digest import Digest
        digest = Digest(mock.Mock(log=self.logs.append), mock.Mock(), mock.Mock())
        digest.memory_tidy = mock.Mock()
        event = {"message_id": "om_card"}
        with mock.patch("covey.app.digest.after_ack", side_effect=lambda work: work()), \
                mock.patch.object(digest, "memory_decided") as decided:
            self.assertEqual(digest.claim(self.ctx, event, {"kind": MEMORY_KIND, "run": "t0a1b2c3d", "op": "undo"}, True),
                             "digest_memory")
            self.assertEqual(digest.claim(self.ctx, event, {"kind": MEMORY_KIND, "run": "bad", "op": "undo"}, True),
                             "digest_memory_ignored")
            self.assertEqual(digest.claim(self.ctx, event, {"kind": MEMORY_KIND, "run": "t0a1b2c3d", "op": "undo"}, False),
                             "owner_only")
        decided.assert_called_once_with(self.ctx, "om_card", "t0a1b2c3d", "undo", "", "")


if __name__ == "__main__":
    unittest.main()
