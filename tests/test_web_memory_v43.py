"""The memory center's keys (data contract v43, app/web_memory.py Center, app/web_sync.py push_memory_center): every memory:*
key built from the one store has the fields and the types of its golden sample (tests/golden/web_memory_v43.json), key by key;
the change sentinel is the one file stat'ed; a key whose rev did not change is not sent again, and what a turn did with an
entry never moves one; a key gone is taken back (SyncDeleted); the old ``memory`` key (v37) still goes alone; and the 17
actions of a ``memory_edit`` with ``v: 43`` (app/web_ops.py) each change the store as the receipt says, with the operation's
id as the undo token. Package M2's functions (core/memory_review.py decide/decide_all/health, app/memory_turn.py preview)
are taken when they have the agreed signatures: stand-ins of the same signatures show it."""
from __future__ import annotations

import json
import os
import pathlib
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.records import state_dir, write_job, write_topic
from test_web_sync import WebCase

from covey.app import memory_turn, web_memory
from covey.app.web_ops import Ops
from covey.core import harness_memory, memory_review, memory_usage, memstore, principles, projects, web_sync

GOLDEN = json.loads((Path(__file__).resolve().parents[1] / "tests" / "golden" / "web_memory_v43.json").read_text(encoding="utf-8"))
CHAT = "oc_owner_dm"
PID = "demo01"
TID = "t001"
NOW = time.time()
# The optional fields the contract (web/shared/api.interface.ts) allows beside the golden's, per shape (a list's element).
EXTRA = {"entry": {"project_key", "topic_key", "topic_number", "why", "repos", "device", "verified_at", "over_cap",
                   "superseded_by", "edited", "in_progress"},
         "origin": {"topic_key", "topic_number", "quote", "message_id", "question", "file", "harness"},
         "review": {"quote", "from", "conflict_with", "items", "flags"},
         "import": {"repo", "dup_of", "old_repo"}}


def kind_of(value) -> str:
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, (int, float)):
        return "number"
    return {str: "str", list: "list", dict: "dict", type(None): "null"}[type(value)]


def schema(samples) -> dict:
    """The shape the golden ``samples`` of one place have: their type; of dicts each field's schema (from every sample that has
    it) and the fields every sample has (required); of lists their elements' schema. A map (``revs``, ``health``) is open."""
    samples = list(samples)
    kinds = {kind_of(value) for value in samples}
    kind = "number" if kinds == {"number"} else kinds.pop() if len(kinds) == 1 else "any"
    out = {"kind": kind}
    if kind == "dict":
        names = [name for sample in samples for name in sample]
        out["fields"] = {name: schema([sample[name] for sample in samples if name in sample]) for name in dict.fromkeys(names)}
        out["required"] = set.intersection(*(set(sample) for sample in samples))
        values = [value for sample in samples for value in sample.values()]
        out["values"] = schema(values) if values and len({kind_of(v) for v in values}) == 1 else {"kind": "any"}
    elif kind == "list":
        out["items"] = schema([item for sample in samples for item in sample]) if any(samples) else None
    return out


OPEN = ("revs", "health")  # Maps: any key, the golden's values' type.


def check(test, shape, ours, where, seen, extra_of):
    """``ours`` has ``shape``: the same type; a dict every required field and no field the contract does not know, each field
    checked; a list each element. ``seen`` collects the paths of the golden fields our data had (the coverage check)."""
    if shape["kind"] == "any":
        return
    test.assertEqual(kind_of(ours), shape["kind"], where)
    if shape["kind"] == "dict":
        is_open = where.rsplit(".", 1)[-1] in OPEN
        if not is_open:
            for name in shape["required"] - extra_of(where):  # What the contract makes optional the golden may still show.
                test.assertIn(name, ours, f"{where}.{name}")
        for name, value in ours.items():
            field = shape["values"] if is_open else shape["fields"].get(name)
            if field is None:
                test.assertIn(name, extra_of(where), f"{where}.{name} is not in the contract")
                continue
            path = f"{where}.{name}" if not is_open else where
            seen.add(f"{where}.{name}" if not is_open else where)
            check(test, field, value, path, seen, extra_of)
    elif shape["kind"] == "list" and shape["items"] is not None:
        for value in ours:
            check(test, shape["items"], value, f"{where}[]", seen, extra_of)


def golden_paths(shape, where, out) -> set:
    """Every path of a field the golden samples have (an open map's own path only)."""
    if shape["kind"] == "dict":
        is_open = where.rsplit(".", 1)[-1] in OPEN
        for name, field in shape["fields"].items():
            if is_open:
                out.add(where)
                continue
            out.add(f"{where}.{name}")
            golden_paths(field, f"{where}.{name}", out)
    elif shape["kind"] == "list" and shape.get("items"):
        golden_paths(shape["items"], f"{where}[]", out)
    return out


def extra_fields(path) -> set:
    tail = path.rsplit(".", 1)[-1]
    if tail in ("entries[]", "items[]") and ".memory:import" not in path and "review[]" not in path:
        return EXTRA["entry"]
    if tail == "origin":
        return EXTRA["origin"]
    if tail == "review[]":
        return EXTRA["review"]
    if tail == "items[]" and ".memory:import" in path:
        return EXTRA["import"]
    if tail == "items[]" and "review[]" in path:
        return EXTRA["entry"]
    if tail == "topics[]":
        return {"topic_number", "project_key"}
    if tail == "log[]":
        return {"because", "undo_token"}
    if tail == "because":
        return {"topic_number", "quote"}
    if tail == "from":
        return {"topic_key", "topic_number"}
    if tail == "suggest":
        return {"project_key"}
    return set()


def own_home(test, home):
    """This process's user's Harness folders made ``home``'s (core/harness_memory.py roots reads CLAUDE_CONFIG_DIR, CODEX_HOME)."""
    test.enterContext(mock.patch.dict(os.environ, {"CLAUDE_CONFIG_DIR": str(home / ".claude"), "CODEX_HOME": str(home / ".codex"),
                                                   "HOME": str(home)}))
    test.enterContext(mock.patch.object(pathlib.Path, "home", return_value=home))


class Case(unittest.TestCase):
    def setUp(self):
        self.enterContext(mock.patch.dict(os.environ, {"COVEY_MEMORY": "1", "COVEY_KNOWLEDGE": "0", "COVEY_MEMORY_LEARN": ""}))
        self.state = state_dir(self)
        self.home = self.state / "home"
        memstore._cache.clear()
        self.addCleanup(memstore._cache.clear)
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="演示专项", project_id=PID, now=NOW))

    def seed(self):
        """A store with every part the golden samples show: 全局 rules and notes (two saying the same), a topic's rule and note,
        a project's decision, 待审核 of each kind the golden has, the log, the imports in each state."""
        s = self.state
        self.rule = memstore.add(s, kind="rule", scope="global", text="提交代码之前先跑相关测试，失败就不提交。", title="提交前先跑测试",
                                 why="曾经把没跑过的改动合进了主干", origin={"topic_number": 12, "quote": "提交代码之前先跑相关测试"},
                                 token="u-0001", now=NOW - 100)
        self.note = memstore.add(s, kind="note", scope="global", text="演示环境的网页服务监听在 8080 端口。", title="部署机用的端口",
                                 said="summary", by="learn", verified_at=NOW - 90 * 86400, now=NOW - 90 * 86400)
        data = json.loads(memstore.global_path(s).read_text())  # The same words twice (体检 dup): written as an older store would.
        twin = dict(data["entries"][0], id="g9z9z9", code="")
        data["entries"].append(twin)
        memstore.global_path(s).write_text(json.dumps(data, ensure_ascii=False))
        write_topic(s, topic_id=TID, chat_id=CHAT, topic_number=12, title="演示话题", project={"id": PID, "role": "member"})
        self.trule = memstore.add(s, kind="rule", scope="topic", owner_key=TID, text="这个话题里不要修改 demo-repo，只读它的代码。",
                                  title="这个话题只读 demo-repo", repos=("demo-repo",), now=NOW - 50,
                                  origin={"topic_number": 12, "quote": "这个话题里不要修改 demo-repo，"})
        memstore.edit(s, self.trule.ref, why="主人说的")
        self.tnote = memstore.add(s, kind="note", scope="topic", owner_key=TID, text="日志里的超时来自上游接口，和本地代码无关。",
                                  title="排查结论", now=NOW - 40)
        for n in range(6):  # Past the topic's room: the last ones are listed by title only.
            memstore.add(s, kind="rule", scope="topic", owner_key=TID, text=f"第 {n} 条话题规矩" + "很长" * 60, now=NOW - 30 + n)
        self.decision = memstore.add_decision(s, scope="project", owner_key=PID, question="记忆中心先上线什么？", answer="只读页",
                                              said="summary", by="lead", origin={"topic_number": 12, "quote": "记忆中心第一版先只做查看"},
                                              now=NOW - 20)
        self.learn, _ = memstore.review_put(s, {"type": "learn", "title": "回复先说结论", "text": "回复时先给结论，再展开原因。",
                                                "quote": "你先说结论吧", "origin": {"topic_key": TID, "topic_number": 12},
                                                "suggest": {"kind": "rule", "scope": "global"}, "flags": ["repeat"]})
        self.conflict, _ = memstore.review_put(s, {"type": "conflict", "title": "部署端口改为 9090", "text": "演示环境的网页服务改到 9090 端口。",
                                                   "suggest": {"kind": "note", "scope": "global"}, "conflict_with": self.note.ref,
                                                   "flags": ["dynamic"], "origin": {"topic_key": "t002", "topic_number": 15}})
        self.tidy, _ = memstore.review_put(s, {"type": "tidy", "title": "两条相近的规矩", "text": "这两条意思重复，可以合并。",
                                               "suggest": {"kind": "rule", "scope": "global"}, "items": [self.rule.ref, "global:g9z9z9"]})
        self.project_item, _ = memstore.review_put(s, {"type": "lead", "title": "专项要先写测试", "text": "专项里改代码前先写测试。",
                                                       "suggest": {"kind": "rule", "scope": "project", "project_key": PID}})
        memstore.log_change(s, who="owner", action="accept", refs=[self.rule.ref], title="提交前先跑测试",
                            because={"topic_number": 12, "quote": "提交之前先跑测试"}, token="u-0002", now=NOW - 10)
        bucket = self.home / ".claude" / "projects" / "-absolute-demo-repo" / "memory"
        bucket.mkdir(parents=True)
        for name, text in (("a.md", "测试要用真实数据库。"), ("b.md", "提交代码之前先跑相关测试，失败就不提交。"), ("c.md", "旧仓库的构建命令。")):
            (bucket / name).write_text(f"---\nname: {name}\nmetadata:\n  type: feedback\n---\n\n{text}\n")
        (s / "repos.json").write_text(json.dumps({"repos": [{"name": "demo-repo", "path": "/absolute/demo-repo", "status": "frozen"}]}))
        items = harness_memory.scan(s, self.home)
        by_name = {Path(item.file).name: item.fingerprint for item in items}
        memstore.imports_set(s, [by_name["b.md"]], "imported", entry_ref=self.rule.ref)
        memstore.imports_set(s, [by_name["c.md"]], "ignored")
        self.fps = by_name
        write_job(s, "k-t001", topic_id=TID, chat_id=CHAT, job_id=12, status="done", updated_at=NOW - 5)

    def build(self, now=None):
        return web_memory.Center(self.state, home=self.home).build(now=now or NOW)


class GoldenShapeTest(Case):
    def test_every_key_has_the_golden_fields_and_types_and_covers_them(self):
        self.seed()
        built = self.build()
        golden = GOLDEN["keys"]
        names = {"memory:p:demo01": f"memory:p:{PID}"}
        self.assertEqual({web_sync.MEMORY_KEY_RE.match(key) is not None for key in built}, {True})
        for key in golden:
            self.assertIn(names.get(key, key), built)
        seen, wanted = set(), set()
        for key, sample in golden.items():
            shape = schema([sample])
            golden_paths(shape, key, wanted)
            with self.subTest(key=key):
                check(self, shape, built[names.get(key, key)], key, seen, extra_fields)
        # The notes a preview finds relevant are package M2's search (app/memory_turn.py preview): PackageM2Test checks their shape.
        # A topic's line keeps no quote of where it came from (core/memstore.py topic_add): its origin is the topic itself.
        wanted = {path for path in wanted if ".notes[]" not in path and path != "memory:topics.topics[].entries[].origin.quote"}
        self.assertEqual(sorted(wanted - seen), [], "golden fields our data never had")
        index = built["memory:index"]
        self.assertEqual(index["revs"]["memory:global"], web_sync.rev(built["memory:global"]))
        self.assertEqual(set(index["revs"]), set(built))
        self.assertEqual(index["counts"]["pending"], 4)
        self.assertTrue({"dup", "conflict", "stale", "over_cap"} <= set(index["health"]), index["health"])
        for key, data in built.items():
            self.assertLessEqual(len(json.dumps(data, ensure_ascii=False).encode()), web_memory.KEY_BYTES, key)

    def test_entries_carry_no_use_counts_and_a_turns_use_moves_no_key(self):
        self.seed()
        before = self.build()
        memory_usage.carried(self.state, [self.rule.ref, self.note.ref, self.trule.ref])
        memory_usage.signal(self.state, [self.rule.ref], "memory_used")
        after = self.build()
        for key in before:
            if key != "memory:index":
                self.assertEqual(web_sync.rev(before[key]), web_sync.rev(after[key]), key)
        same = [{k: v if k != "revs" else {n: r for n, r in v.items() if n != "memory:index"} for k, v in data["memory:index"].items()
                 if k != "health"} for data in (before, after)]
        self.assertEqual(same[0], same[1])  # Only 体检's 很久没用 reads the use: an entry used again is not idle.
        self.assertEqual({k: v for k, v in before["memory:index"]["health"].items() if k != "idle"},
                         {k: v for k, v in after["memory:index"]["health"].items() if k != "idle"})
        text = json.dumps(after["memory:global"], ensure_ascii=False)
        for word in ('"e"', '"t"', '"h"', '"n"', '"last"', "usage"):
            self.assertNotIn(word + ":", text)

    def test_the_global_key_past_its_size_loses_log_rows_never_review(self):
        self.seed()
        for n in range(400):
            memstore.log_change(self.state, who="owner", action="edit", refs=[self.rule.ref], title="改" * 40, token=f"u-{n}", now=NOW)
        with mock.patch.object(web_memory, "KEY_BYTES", 6000), mock.patch.object(web_memory, "LOG_SHOWN", 400):
            data = self.build()["memory:global"]
            self.assertLessEqual(len(json.dumps(data, ensure_ascii=False).encode()), 6000 + 4000)
        self.assertEqual(len(data["review"]), 4)
        self.assertLess(len(data["log"]), 400)

    def test_titles_are_short_and_at_most_the_table(self):
        self.seed()
        with mock.patch.object(web_memory, "TITLES", 3):
            titles = self.build()["memory:index"]["titles"]
        self.assertEqual(len(titles), 3)
        for code, title, key in titles:
            self.assertTrue(memstore.is_code(code))
            self.assertLessEqual(len(title), 40)
            self.assertIsNotNone(memstore.find(self.state, key))

    def test_rules_past_the_room_are_flagged_not_dropped(self):
        self.seed()
        topic = self.build()["memory:topics"]["topics"][0]
        rules = [e for e in topic["entries"] if e["kind"] == "rule" and e["status"] == "active"]
        self.assertEqual(len(rules), 7)
        over = [e for e in rules if e.get("over_cap")]
        self.assertTrue(over)
        self.assertTrue(all(not e["carried_next"] for e in over))
        self.assertTrue(all(e["carried_next"] for e in rules if not e.get("over_cap")))
        self.assertEqual(topic["entries"][0]["topic_number"], 12)

    def test_topics_older_than_thirty_days_are_not_read(self):
        self.seed()
        built = self.build(now=NOW + 40 * 86400)
        self.assertEqual(built["memory:topics"], {"topics": []})


class StampTest(Case):
    def test_stamps_stat_the_one_sentinel_and_walk_nothing(self):
        self.seed()
        web_memory.stamps(self.state)
        statted = []
        real = pathlib.Path.stat

        def stat(path, *args, **kwargs):
            statted.append(str(path))
            return real(path, *args, **kwargs)

        def walk(*args, **kwargs):
            raise AssertionError("stamps walked a directory")

        with mock.patch.object(pathlib.Path, "stat", stat), mock.patch.object(pathlib.Path, "iterdir", walk), \
                mock.patch.object(pathlib.Path, "glob", walk), mock.patch.object(os, "scandir", walk), \
                mock.patch.object(os, "listdir", walk):
            first = web_memory.stamps(self.state)
        self.assertEqual(statted, [str(memstore.rev_path(self.state))])
        self.assertEqual(web_memory.stamps(self.state), first)
        memstore.archive(self.state, self.note.ref)
        self.assertNotEqual(web_memory.stamps(self.state), first)

    def test_an_older_stores_write_moves_the_sentinel_once_it_was_planted(self):
        self.assertEqual(memstore.rev_path(self.state).exists(), False)
        first = web_memory.stamps(self.state)
        self.assertTrue(memstore.rev_path(self.state).exists())
        principles.save(self.state, principles.OWNER, "先给结论")  # core/memory_rev.py touch(create=False)
        self.assertNotEqual(web_memory.stamps(self.state), first)


class ActionsTest(Case):
    """The 17 actions, each through app/web_ops.py as the page sends them, with the operation's id as the undo token."""

    def setUp(self):
        super().setUp()
        self.seed()
        runtime = SimpleNamespace(owner_open_id="ou_owner", access=SimpleNamespace(is_owner=lambda open_id: True), log=lambda line: None)
        self.ops = SimpleNamespace(runtime=runtime)
        own_home(self, self.home)

    def run_op(self, op_id, action, keys=(), **payload):
        row = {"op_id": op_id, "kind": "memory_edit"}
        return Ops.memory_edit(self.ops, self.state, CHAT, row, {"v": 43, "action": action, "keys": list(keys), **payload})

    def logged(self, token):
        return [row for row in memstore.log_read(self.state, limit=500) if row.get("undo_token") == token]

    def test_add_edit_move_promote_archive_restore_void(self):
        said = self.run_op("op-1", "add", title="先只读后编辑", text="第一版先做只读页", kind="decision", scope="project", project_key=PID)
        self.assertTrue(said.startswith("已记下"), said)
        decision = next(e for e in memstore.decisions(self.state, "project", PID) if e.title == "先只读后编辑")
        self.assertEqual((decision.by, decision.said), ("web", "owner"))
        self.assertTrue(self.logged("w-op-1"))
        self.assertTrue(self.run_op("op-2", "add", title="一条", text="提交前先跑测试", kind="rule", scope="global").startswith("已记下"))
        self.assertTrue(self.run_op("op-2b", "add", title="一条", text="提交前先跑测试", kind="rule", scope="global").startswith("已有"))
        rule = memstore.find(self.state, self.rule.ref)
        with self.assertRaisesRegex(ValueError, "刚在别处改过"):
            self.run_op("op-3", "edit", [rule.ref], text="新的话", base="nope")
        self.assertTrue(self.run_op("op-3", "edit", [rule.ref], text="提交前先跑全部相关测试", kind="rule", base=memstore.rev_of(rule)).startswith("已保存"))
        self.assertEqual(memstore.find(self.state, rule.ref).text, "提交前先跑全部相关测试")
        self.assertEqual(self.run_op("op-3b", "edit", [rule.ref], text="提交前先跑全部相关测试"), "没有变化")
        moved = self.run_op("op-4", "move", [self.trule.ref], scope="project", project_key=PID,
                            base=memstore.rev_of(memstore.find(self.state, self.trule.ref)))
        self.assertTrue(moved.startswith("已换范围"), moved)
        self.assertEqual(memstore.find(self.state, self.trule.ref).status, "archived")
        promoted = self.run_op("op-5", "promote", [self.tnote.ref], scope="project", project_key=PID, repos=["demo-repo"])
        self.assertTrue(promoted.startswith("已提到"), promoted)
        new = memstore.find(self.state, memstore.find(self.state, self.tnote.ref).superseded_by)
        self.assertEqual((new.scope, new.repos), ("project", ("demo-repo",)))
        self.assertTrue(self.run_op("op-6", "archive", [self.note.ref]).startswith("已归档"))
        self.assertEqual(self.run_op("op-6b", "archive", [self.note.ref]), "这条已经归档了")
        self.assertTrue(self.run_op("op-7", "restore", [self.note.ref]).startswith("已放回"))
        self.assertTrue(self.run_op("op-8", "void", [decision.ref], why="决定已作废").startswith("已作废"))
        self.assertEqual(memstore.find(self.state, decision.ref).status, "void")
        with self.assertRaisesRegex(ValueError, "已经不在了"):
            self.run_op("op-9", "archive", ["global:gnothere"])

    def test_accept_reject_and_their_all_forms(self):
        said = self.run_op("op-a", "accept", [self.learn], kind="rule", scope="global", title="回复先给结论")
        self.assertEqual(said, "已采纳")
        made = next(e for e in memstore.entries(self.state, scope="global") if e.title == "回复先给结论")
        self.assertEqual((made.kind, made.said, made.by), ("rule", "owner", "learn"))
        self.assertEqual(memstore.review_items(self.state, states=("accepted",))[0]["key"], self.learn)
        self.assertEqual(self.run_op("op-r", "reject", [self.project_item]), "不要了")
        with self.assertRaisesRegex(ValueError, "已经处理过了"):
            self.run_op("op-r2", "reject", [self.project_item])
        self.assertEqual(self.run_op("op-all", "accept_all", [self.tidy]), "全部采纳 1 条")
        self.assertEqual(memstore.find(self.state, "global:g9z9z9").status, "archived")  # A tidy group put away.
        self.assertEqual(self.run_op("op-none", "reject_all", []), "全部不要 1 条")  # The conflict, the last one open.
        self.assertEqual(memstore.review_items(self.state), [])
        with self.assertRaisesRegex(ValueError, "没有要处理的待审核"):
            self.run_op("op-none2", "accept_all", [])

    def test_keep_left_right_both(self):
        self.assertEqual(self.run_op("op-l", "keep_left", [self.note.ref, self.conflict]), "留了原来的")
        self.assertEqual(memstore.find(self.state, self.note.ref).text, "演示环境的网页服务监听在 8080 端口。")
        memstore.review_set(self.state, self.conflict, "open")
        self.assertEqual(self.run_op("op-rt", "keep_right", [self.note.ref, self.conflict]), "换成了新的")
        self.assertEqual(memstore.find(self.state, self.note.ref).text, "演示环境的网页服务改到 9090 端口。")
        other, _ = memstore.review_put(self.state, {"type": "conflict", "title": "备用端口", "text": "演示环境另开了 7070 端口。",
                                                    "suggest": {"kind": "note", "scope": "global"}, "conflict_with": self.note.ref})
        before = len(memstore.entries(self.state, scope="global"))
        self.assertEqual(self.run_op("op-b", "keep_both", [self.note.ref, other]), "两条都留了")
        self.assertEqual(len(memstore.entries(self.state, scope="global")), before + 1)

    def test_import_ignore_and_undo(self):
        said = self.run_op("op-i", "import", [self.fps["a.md"]], kind="rule", scope="global")
        self.assertEqual(said, "已导入 1 条")
        made = next(e for e in memstore.entries(self.state, scope="global") if e.text == "测试要用真实数据库。")
        self.assertEqual((made.by, made.said), ("import", "owner"))
        self.assertEqual(memstore.imports(self.state)["items"][self.fps["a.md"]]["state"], "imported")
        self.assertIn("留在原工具", self.run_op("op-g", "ignore", [self.fps["c.md"]]))
        with self.assertRaisesRegex(ValueError, "找不到"):
            self.run_op("op-i2", "import", ["fp-not-there"])
        self.assertTrue(self.run_op("op-u", "undo", undo_token="w-op-i").startswith("已撤销"))
        self.assertEqual(memstore.find(self.state, made.ref).status, "void")
        with self.assertRaisesRegex(ValueError, "撤销过了"):
            self.run_op("op-u2", "undo", undo_token="w-op-i")

    def test_undo_of_a_decision_of_review_opens_it_again(self):
        self.run_op("op-a", "accept", [self.learn], kind="rule", scope="global")
        self.run_op("op-r", "reject", [self.project_item])
        self.assertIn("回到待审核", self.run_op("op-u", "undo", undo_token="w-op-a"))
        self.assertIn(self.learn, [item["key"] for item in memstore.review_items(self.state)])
        self.assertIn("回到待审核", self.run_op("op-u2", "undo", undo_token="w-op-r"))
        self.assertIn(self.project_item, [item["key"] for item in memstore.review_items(self.state)])

    def test_every_golden_action_is_known_and_the_old_payload_still_goes_the_old_way(self):
        self.assertEqual(set(web_memory.ACTIONS_V43), {edit["action"] for edit in GOLDEN["edits"]})
        old = Ops.memory_edit(self.ops, self.state, CHAT, {"op_id": "op-old"},
                              {"action": "add", "what": "principle", "scope": "global", "text": "先给结论"})
        self.assertTrue(old.startswith("已记下"))
        self.assertEqual([r["text"] for r in principles.entries(self.state)], ["先给结论"])
        with self.assertRaisesRegex(ValueError, "不认识的记忆操作"):
            self.run_op("op-x", "pin", [self.rule.ref])

    def test_the_log_gives_the_page_the_undo_token_of_its_operation(self):
        self.run_op("op-6", "archive", [self.note.ref])
        log = self.build()["memory:global"]["log"]
        row = next(item for item in log if item.get("undo_token") == "w-op-6")
        self.assertIn(self.note.ref, row["refs"])
        self.run_op("op-u", "undo", undo_token="w-op-6")
        log = self.build()["memory:global"]["log"]
        self.assertFalse([item for item in log if item.get("undo_token") == "w-op-6"])  # Taken back: no 撤销 any more.


class PackageM2Test(Case):
    """M2's functions of the agreed signatures are the ones taken; A0's shapes are not."""

    def test_review_decisions_go_through_m2_with_the_owners_edits_on_the_item(self):
        self.seed()
        calls = []

        def decide(state_dir, key, action, *, who="owner", token="", now=None):
            calls.append((key, action, who, token, next(i for i in memstore.review_items(state_dir) if i["key"] == key)["title"]))
            memstore.review_set(state_dir, key, "accepted")
            return {"refs": ["global:gm2"]}

        def decide_all(state_dir, action, *, keys=None, who="owner", token="", now=None):
            calls.append(("all", action, tuple(keys or ())))
            return {"refs": []}

        with mock.patch.object(memory_review, "decide", decide, create=True), \
                mock.patch.object(memory_review, "decide_all", decide_all, create=True):
            found = web_memory.review_decide(self.state, [self.learn], "accept", edits={"title": "改过的标题"}, token="w-1")
            web_memory.review_decide(self.state, [], "reject_all", token="w-2")
        self.assertEqual(found["refs"], ["global:gm2"])
        self.assertEqual(calls[0], (self.learn, "accept", "owner", "w-1", "改过的标题"))
        self.assertEqual(calls[1][:2], ("all", "reject_all"))
        self.assertEqual(set(calls[1][2]), {self.conflict, self.tidy, self.project_item})

    def test_health_and_previews_come_from_m2_when_it_has_them(self):
        self.seed()

        def health(state_dir, *, now=None):
            return {"vague": ["global:g1"], "dup": []}

        def preview(state_dir, topic_key="", *, project_key="", title="", query="", repos=()):
            return {"topic_key": topic_key, "title": title, "chars": 9, "rules": [], "decisions": [], "notes": [{"code": "N1234", "sim": 0.5}],
                    "listed": []}

        with mock.patch.object(memory_review, "health", health, create=True), mock.patch.object(memory_turn, "preview", preview, create=True):
            built = self.build()
        self.assertEqual(built["memory:index"]["health"], {"vague": ["global:g1"]})
        rows = built["memory:previews"]["previews"]
        self.assertEqual([(r["topic_key"], r["chars"]) for r in rows], [(TID, 9), ("new", 9)])
        check(self, schema([GOLDEN["keys"]["memory:previews"]]), built["memory:previews"], "memory:previews", set(), extra_fields)
        self.assertEqual(rows[-1]["title"], "新的普通话题")

    def test_without_m2_the_baseline_previews_carry_rules_and_open_decisions(self):
        self.seed()
        rows = self.build()["memory:previews"]["previews"]
        self.assertEqual([r["topic_key"] for r in rows], [TID, "new"])
        topic, new = rows
        self.assertIn(memstore.find(self.state, self.rule.ref).code, topic["rules"])
        self.assertIn(memstore.find(self.state, self.decision.ref).code, topic["decisions"])
        self.assertEqual(new["decisions"], [])
        self.assertEqual(topic["notes"], [])


class CenterPushTest(WebCase):
    """push_memory_center: the data keys, then memory:index; nothing again while the revs are the same; a key gone taken back;
    the old ``memory`` key in its own request as before; off says so and takes the rest back."""

    def setUp(self):
        super().setUp()
        self.enterContext(mock.patch.dict(os.environ, {"COVEY_MEMORY": "1", "COVEY_KNOWLEDGE": "0"}))
        memstore._cache.clear()
        own_home(self, self.state / "home")

    def keys_sent(self):
        return [each["key"] for batch in self.web.upserts for each in batch["items"]]

    def deleted(self):
        return [row for batch in self.web.upserts for row in batch["deleted"]]

    def test_the_index_goes_last_and_an_unchanged_rev_is_not_sent_again(self):
        memstore.add(self.state, kind="rule", scope="global", text="提交前先跑测试")
        sent = self.sync.push_memory_center()
        keys = self.keys_sent()
        self.assertEqual(keys[-1], "memory:index")
        self.assertEqual(sent, len(keys))
        self.assertEqual({key for key in keys if not key.startswith("memory:p:")},
                         {"memory:index", "memory:global", "memory:topics", "memory:previews"})
        self.assertEqual(self.sync.push_memory_center(), 0)  # The sentinel did not move.
        self.assertEqual(self.sync.push_memory_center(force=True), 0)  # Built again: the same revs.
        memory_usage.carried(self.state, [e.ref for e in memstore.entries(self.state)])
        self.assertEqual(self.sync.push_memory_center(force=True), 0)  # A turn's use moves no key.
        memstore.add(self.state, kind="note", scope="global", text="测试机在 3 楼")
        self.assertEqual(self.sync.push_memory_center(), 2)  # memory:global and memory:index.
        self.assertEqual(self.keys_sent()[-2:], ["memory:global", "memory:index"])

    def test_a_project_cancelled_is_taken_back(self):
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="演示专项", project_id=PID, now=NOW))
        memstore.add(self.state, kind="rule", scope="project", owner_key=PID, text="专项里先写测试")
        self.sync.push_memory_center()
        self.assertIn(f"memory:p:{PID}", self.keys_sent())
        projects.set_state(self.state, PID, projects.CANCELLED)
        memstore.touch_rev(self.state)
        self.sync.push_memory_center()
        self.assertIn({"type": "settings", "key": f"memory:p:{PID}"}, self.deleted())
        self.assertNotIn(("settings", f"memory:p:{PID}"), self.sync.sent)

    def test_fewer_import_pages_take_the_last_back(self):
        bucket = self.state / "home" / ".claude" / "projects" / "-absolute-x" / "memory"
        bucket.mkdir(parents=True)
        for n in range(3):
            (bucket / f"{n}.md").write_text(f"第 {n} 条要记住的话\n")
        with mock.patch.object(harness_memory, "PAGE", 2):
            self.sync.push_memory_center()
            self.assertIn("memory:import:1", self.keys_sent())
            (bucket / "2.md").unlink()
            self.sync.memory_center.scanned = None  # The next scan is due.
            memstore.touch_rev(self.state)
            self.sync.push_memory_center()
        self.assertIn({"type": "settings", "key": "memory:import:1"}, self.deleted())

    def test_the_old_memory_key_still_goes_alone_and_off_takes_the_center_back(self):
        principles.save(self.state, principles.OWNER, "先给结论")
        self.assertEqual(self.sync.push_memory(), 1)
        self.assertEqual([[each["key"] for each in batch["items"]] for batch in self.web.upserts], [["memory"]])
        self.sync.push_memory_center()
        self.assertTrue(all(key == "memory" or key.startswith("memory:") for key in self.keys_sent()))
        with mock.patch.dict(os.environ, {"COVEY_MEMORY": "0"}):
            self.sync.push_memory_center()
            index = [each for batch in self.web.upserts for each in batch["items"] if each["key"] == "memory:index"][-1]
            self.assertFalse(index["data"]["on"])
            self.assertEqual({row["key"] for row in self.deleted() if not row["key"].startswith("memory:p:")},
                             {"memory:global", "memory:topics", "memory:previews"})
            self.assertEqual(self.sync.push_memory_center(full=True), 0)

    def test_never_on_never_pushed(self):
        with mock.patch.dict(os.environ, {"COVEY_MEMORY": "0"}):
            self.assertEqual(self.sync.push_memory_center(full=True), 0)
        self.assertEqual(self.web.upserts, [])

    def test_a_refused_post_waits_longer_each_time(self):
        memstore.add(self.state, kind="rule", scope="global", text="提交前先跑测试")
        with mock.patch.object(self.sync.client, "request", side_effect=web_sync_error()):
            self.assertEqual(self.sync.push_memory_center(), 0)
            self.assertEqual(self.sync.push_memory_center(full=True), 0)  # Within the wait: not even built.
        self.assertEqual(self.sync.center_failed, 1)
        self.assertGreater(self.sync.center_wait, time.monotonic())
        self.assertEqual(self.sync.push_memory_center(force=True) > 0, True)  # The page's own change goes at once.

    def test_a_change_from_the_page_is_pushed_before_the_ack(self):
        self.sync.push_memory_center()
        self.web.outbox.append({"seq": 1, "op_id": "op-m1", "kind": "memory_edit", "topic_key": "", "project_key": "", "payload": {
            "v": 43, "action": "add", "keys": [], "title": "先给结论", "text": "回复先给结论", "kind": "rule", "scope": "global"}})
        with mock.patch.object(self.runtime, "access", SimpleNamespace(owner_chat=lambda: "oc_chat", is_owner=lambda open_id: True)):
            self.assertEqual(self.sync.inbox_once(), 1)
        self.assertEqual(self.web.acks[-1]["state"], "done")
        glob = [each for batch in self.web.upserts for each in batch["items"] if each["key"] == "memory:global"][-1]
        self.assertEqual([e["title"] for e in glob["data"]["entries"]], ["先给结论"])
        self.assertEqual(glob["data"]["log"][0]["undo_token"], "w-op-m1")


def web_sync_error():
    from covey.app.web_push_client import WebError
    return WebError("refused")


if __name__ == "__main__":
    unittest.main()
