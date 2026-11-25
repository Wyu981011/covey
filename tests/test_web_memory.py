"""The web page's 记忆 tab (app/web_memory.py, data contract v37; T748): the ``memory`` item the page reads (全局 and each workspace's
principles and knowledge entries, the room they use, which the next turn carries, the candidates, the next turn's block) and the
``memory_edit`` operation (add, edit, 常驻, delete, 记下 and 不用) through the stores the 设置 card uses; and its push (app/web_sync.py
push_memory): alone in its request, again only when a file of the memory changed, before the ack of the page's change."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from test_web_sync import WebCase
from covey.app import memory_candidates, web_memory
from covey.app.web_ops import Ops
from covey.core import knowledge, memory, principles
from covey.core.state import write_json
from covey.core.workspaces import config_path


class StateCase(TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {"COVEY_MEMORY": "1", "COVEY_KNOWLEDGE": "1", "COVEY_MEMORY_LEARN": ""}))
        self.state = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for name in ("project", "docs"):
            (self.state / name).mkdir()
        write_json(config_path(self.state), {"default": "project", "workspaces": {
            "project": str(self.state / "project"), "docs": str(self.state / "docs")}})

    def edit(self, **payload):
        return web_memory.edit(self.state, payload)

    def group(self, data, workspace=""):
        return next(g for g in data["groups"] if g["workspace"] == workspace)


class ViewTests(StateCase):
    def test_groups_by_scope_with_room_carried_and_the_next_turns_block(self):
        a, _ = principles.save(self.state, principles.OWNER, "回复先给结论再给细节")
        b, _ = principles.save(self.state, principles.OWNER, "数字都要有出处")
        principles.pin(self.state, b["id"], True)
        principles.save(self.state, principles.WORKSPACE, "这个仓库的提交说明写英文", workspace="docs")
        k, _ = knowledge.save(self.state, knowledge.OWNER, "decision", "周报每周一早上发", why="主人定的")
        data = web_memory.view(self.state)
        self.assertEqual((data["on"], data["knowledge"], data["learn"], data["default"]), (True, True, False, "project"))
        self.assertEqual(data["workspaces"], ["project", "docs"])
        self.assertEqual(data["limits"][memory.GLOBAL], memory.LIMITS[memory.GLOBAL])
        self.assertEqual([g["title"] for g in data["groups"]], ["全局", "工作区 docs"])  # project has no entries: not a group.
        rows = self.group(data)["entries"]
        self.assertEqual(rows[0]["key"], f"principle:{b['id']}")  # 常驻 first.
        self.assertTrue(rows[0]["pinned"] and rows[0]["pinnable"] and rows[0]["editable"] and rows[0]["carried"])
        know = next(r for r in rows if r["kind"] == "knowledge")
        self.assertEqual((know["key"], know["knowledge_kind"], know["why"], know["pinnable"]), (f"knowledge:{k['id']}", "decision", "主人定的", False))
        self.assertEqual({r["by"] for r in rows}, {memory.OWNER})
        self.assertGreater(self.group(data)["used"], 0)
        self.assertEqual(self.group(data)["left"], 0)
        self.assertIn(a["text"], data["previews"]["project"]["text"])
        self.assertIn("这个仓库的提交说明写英文", data["previews"]["docs"]["text"])
        self.assertNotIn("这个仓库的提交说明写英文", data["previews"]["project"]["text"])
        self.assertEqual(data["candidates"], [])

    def test_knowledge_off_lists_principles_only_and_a_full_scope_says_what_is_left_out(self):
        knowledge.save(self.state, knowledge.OWNER, "fact", "一条知识")
        for n in range(30):
            principles.save(self.state, principles.OWNER, f"第 {n} 条很长的原则：" + "要" * 60)
        with mock.patch.dict(os.environ, {"COVEY_KNOWLEDGE": "0"}):
            data = web_memory.view(self.state)
        group = self.group(data)
        self.assertFalse(data["knowledge"])
        self.assertEqual({r["kind"] for r in group["entries"]}, {"principle"})
        self.assertGreater(group["left"], 0)
        self.assertEqual(sum(1 for r in group["entries"] if not r["carried"]), group["left"])

    def test_open_candidates_are_listed_with_learning_on(self):
        write_json(memory_candidates.path(self.state), {"schema": 1, "rows": [
            {"id": "c0123abcd", "text": "以后先跑测试再提交", "workspace": "", "slot": "s", "at": 100.0, "state": "open", "carried": True},
            {"id": "c0123abce", "text": "不用了的那条", "workspace": "", "slot": "s", "at": 99.0, "state": "declined"}], "declined": []})
        with mock.patch.dict(os.environ, {"COVEY_MEMORY_LEARN": "1"}):
            data = web_memory.view(self.state)
        self.assertEqual([c["key"] for c in data["candidates"]], ["candidate:c0123abcd"])
        self.assertTrue(data["candidates"][0]["carried"])
        drafts = [r for r in self.group(data)["entries"] if r["kind"] == "candidate"]
        self.assertEqual([(r["by"], r["editable"]) for r in drafts], [(memory.LEAD, False)])  # 它总结的, carried as a draft.


class EditTests(StateCase):
    def test_add_principles_and_entries_to_global_and_a_workspace(self):
        self.assertTrue(self.edit(action="add", what="principle", scope="global", text="先给结论").startswith("已记下"))
        self.assertTrue(self.edit(action="add", what="principle", scope="global", text="先给结论。").startswith("已有说同样意思的一条"))
        self.edit(action="add", what="principle", scope="workspace", workspace="docs", text="提交说明写英文")
        self.edit(action="add", what="knowledge", scope="workspace", workspace="docs", text="发版走 deploy 脚本", knowledge_kind="practice")
        self.assertEqual([r["text"] for r in principles.entries(self.state)], ["先给结论", "提交说明写英文"])
        self.assertEqual(principles.entries(self.state)[0]["source"], {"via": "web"})
        entry = knowledge.entries(self.state)[0]
        self.assertEqual((entry["workspace"], entry["kind"], entry["source"]), ("docs", "practice", {"via": "web"}))
        with self.assertRaisesRegex(ValueError, "要选记在哪个工作区"):
            self.edit(action="add", what="principle", scope="workspace", text="x")
        with self.assertRaisesRegex(ValueError, "最多 200 字"):
            self.edit(action="add", what="principle", scope="global", text="长" * 201)

    def test_a_full_group_is_refused_in_the_owners_words(self):
        for n in range(principles.GROUP_LIMIT):
            principles.save(self.state, principles.OWNER, f"原则 {n}")
        with self.assertRaises(ValueError) as caught:
            self.edit(action="add", what="principle", scope="global", text="再来一条")
        self.assertIn("先删掉用不着的再记", str(caught.exception))
        self.assertNotIn("principle_delete", str(caught.exception))

    def test_edit_saves_only_over_what_the_page_saw(self):
        item, _ = principles.save(self.state, principles.OWNER, "回复先给结论")
        key = f"principle:{item['id']}"
        self.assertTrue(self.edit(action="edit", key=key, text="回复先给结论，再列依据", base="回复先给结论").startswith("已保存"))
        saved = principles.entries(self.state)[0]
        self.assertEqual((saved["text"], saved["at"]), ("回复先给结论，再列依据", item["at"]))
        self.assertTrue(saved["edited"])
        with self.assertRaisesRegex(ValueError, "刚在别处改过"):
            self.edit(action="edit", key=key, text="别的", base="回复先给结论")
        with self.assertRaisesRegex(ValueError, "正文是空的"):
            self.edit(action="edit", key=key, text="  ")
        k, _ = knowledge.save(self.state, knowledge.OWNER, "fact", "测试机在 3 楼")
        self.assertEqual(self.edit(action="edit", key=f"knowledge:{k['id']}", text="测试机在 3 楼", base="测试机在 3 楼"), "没有变化")
        self.assertTrue(self.edit(action="edit", key=f"knowledge:{k['id']}", text="测试机搬到 5 楼", base="测试机在 3 楼").startswith("已保存"))
        now = knowledge.entries(self.state)
        self.assertEqual([e["text"] for e in now], ["测试机搬到 5 楼"])  # Replaced: a new id, the old one superseded.
        with self.assertRaisesRegex(ValueError, "已经不在了"):
            self.edit(action="edit", key=f"knowledge:{k['id']}", text="再改")

    def test_pin_unpin_delete_and_void(self):
        item, _ = principles.save(self.state, principles.OWNER, "数字要有出处")
        key = f"principle:{item['id']}"
        self.assertTrue(self.edit(action="pin", key=key).startswith("已标常驻"))
        self.assertTrue(principles.entries(self.state)[0]["pinned"])
        self.assertTrue(self.edit(action="unpin", key=key).startswith("已取消常驻"))
        self.assertNotIn("pinned", principles.entries(self.state)[0])
        self.assertTrue(self.edit(action="delete", key=key).startswith("已删除"))
        self.assertEqual(principles.entries(self.state), [])
        with self.assertRaisesRegex(ValueError, "已经不在了"):
            self.edit(action="delete", key=key)
        k, _ = knowledge.save(self.state, knowledge.OWNER, "fact", "一条事实")
        with self.assertRaisesRegex(ValueError, "只有原则能标常驻"):
            self.edit(action="pin", key=f"knowledge:{k['id']}")
        self.assertTrue(self.edit(action="delete", key=f"knowledge:{k['id']}").startswith("已作废"))
        self.assertEqual(knowledge.find(self.state, k["id"])["state"], knowledge.DROPPED)
        with self.assertRaisesRegex(ValueError, "不认识这条记忆"):
            self.edit(action="delete", key="principle:../../x")
        with self.assertRaisesRegex(ValueError, "不认识的记忆操作"):
            self.edit(action="rm", key=key)

    def test_candidates_kept_become_principles_and_dropped_ones_are_declined(self):
        rows = [{"id": "c0123abcd", "text": "以后先跑测试再提交", "workspace": "docs", "slot": "s", "at": 100.0, "state": "open"},
                {"id": "c0123abce", "text": "别再用英文回复", "workspace": "", "slot": "s", "at": 99.0, "state": "open"}]
        write_json(memory_candidates.path(self.state), {"schema": 1, "rows": rows, "declined": []})
        self.assertTrue(self.edit(action="keep", key="candidate:c0123abcd").startswith("已记下"))
        self.assertEqual([(r["workspace"], r["text"]) for r in principles.entries(self.state)], [("docs", "以后先跑测试再提交")])
        self.assertTrue(self.edit(action="drop", key="candidate:c0123abce").startswith("不用了"))
        with self.assertRaisesRegex(ValueError, "处理过了"):
            self.edit(action="keep", key="candidate:c0123abce")
        with self.assertRaisesRegex(ValueError, "候选不能改"):
            self.edit(action="edit", key="candidate:c0123abcd", text="x")


class OpTests(StateCase):
    def ops(self, owner=True):
        runtime = SimpleNamespace(owner_open_id="ou_owner", access=SimpleNamespace(is_owner=lambda open_id: owner))
        return SimpleNamespace(runtime=runtime)

    def test_the_operation_is_the_owners_only_and_needs_the_memory_on(self):
        payload = {"action": "add", "what": "principle", "scope": "global", "text": "先给结论"}
        self.assertTrue(Ops.memory_edit(self.ops(), self.state, "oc_chat", {}, payload).startswith("已记下"))
        with self.assertRaisesRegex(ValueError, "只有主人"):
            Ops.memory_edit(self.ops(owner=False), self.state, "oc_chat", {}, payload)
        with mock.patch.dict(os.environ, {"COVEY_MEMORY": "0"}), self.assertRaisesRegex(ValueError, "记忆没开"):
            Ops.memory_edit(self.ops(), self.state, "oc_chat", {}, payload)


class MemoryPushTest(WebCase):
    """The ``settings`` item ``memory`` in a request of its own: pushed when a file of the memory changed, ``{on: false}`` when off."""

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.dict(os.environ, {"COVEY_MEMORY": "1", "COVEY_KNOWLEDGE": "0"}))

    def pushed(self):
        return [each for batch in self.web.upserts for each in batch["items"] if each["key"] == "memory"]

    def test_pushed_alone_when_the_memory_changed_and_off_says_so(self):
        principles.save(self.state, principles.OWNER, "先给结论")
        self.assertEqual(self.sync.push_memory(), 1)
        self.assertEqual([(each["type"], each["key"]) for batch in self.web.upserts for each in batch["items"]], [("settings", "memory")])
        self.assertEqual(self.sync.push_memory(), 0)  # Nothing changed.
        self.assertEqual(self.sync.push_memory(full=True), 0)  # The same rev is not sent again.
        principles.save(self.state, principles.OWNER, "数字要有出处")
        self.assertEqual(self.sync.push_memory(), 1)
        self.assertEqual({e["text"] for e in self.pushed()[-1]["data"]["groups"][0]["entries"]}, {"数字要有出处", "先给结论"})
        with mock.patch.dict(os.environ, {"COVEY_MEMORY": "0"}):
            self.assertEqual(self.sync.push_memory(), 1)  # The page had the tab: it is told the memory is off.
            self.assertEqual(self.sync.push_memory(full=True), 0)
        self.assertEqual(self.pushed()[-1]["data"], {"on": False})

    def test_never_on_never_pushed(self):
        with mock.patch.dict(os.environ, {"COVEY_MEMORY": "0"}):
            self.assertEqual(self.sync.push_memory(full=True), 0)
        self.assertEqual(self.pushed(), [])

    def test_a_change_from_the_page_is_made_and_pushed_before_the_ack(self):
        self.sync.push_memory()
        self.web.op("memory_edit", 1, "op-m1", action="add", what="principle", scope="global", text="先给结论")
        with mock.patch.object(self.runtime, "access", SimpleNamespace(owner_chat=lambda: "oc_chat", is_owner=lambda open_id: True)):
            self.assertEqual(self.sync.inbox_once(), 1)
        self.assertEqual([r["text"] for r in principles.entries(self.state)], ["先给结论"])
        self.assertEqual(self.web.acks[-1]["state"], "done")
        self.assertEqual([e["text"] for e in self.pushed()[-1]["data"]["groups"][0]["entries"]], ["先给结论"])
