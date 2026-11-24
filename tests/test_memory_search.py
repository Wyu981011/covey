"""按需查记忆 (COVEY_MEMORY_LEARN=1, core/memory_search.py, bin/covey_memory.py): what a turn's block could not carry, found by
its words, with the same rules of who may read what as the block."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import REPO
from support.records import write_topic

from covey.core import memory_search, principles, project_memory, projects, topic_memory
from covey.core.state import write_json

PID, CHAT = "a1b2c3d4e5f6", "oc_owner_dm"
NOW = 1_800_000_000.0


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))}, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="网关", project_id=PID, now=NOW))
        write_topic(self.state, topic_id="t1", topic_number=7, workspace_name="ws",
                    project=projects.project_field(PID, projects.MEMBER))

    def texts(self, query, **options):
        return [row["text"] for row in memory_search.search(self.state, query, "t1", **options)]


class SearchTest(Case):
    def test_it_finds_a_decision_put_away_and_an_answered_question_once(self):
        done, _ = project_memory.add(self.state, PID, "主人答：镜像要不要先发预发？→先发预发", "decision", "owner_answer")
        project_memory.settle(self.state, PID, [{"id": done["id"], "valid": "done"}])
        project_memory.add(self.state, PID, "主人答：要不要现在合入？→现在合入", "decision", "owner_answer")
        folder = project_memory.memory_path(self.state, PID).parent / project_memory.ANSWERS_DIR
        write_json(folder / "0123456789abcdef.json", {"questions": [
            {"id": "q1", "question": "对外 README 要不要点名竞品？"}, {"id": "q2", "question": "镜像要不要先发预发？"}],
            "answers": {"q1": {"answers": ["只按类别写，不点名"]}, "q2": {"answers": ["先发预发"]}}, "noted_at": NOW})
        rows = memory_search.search(self.state, "镜像先发预发", "t1")
        self.assertEqual([(row["kind"], row["state"], row["extra"]) for row in rows],
                         [("当前决定", "历史", "做完了")])  # The kept question with a line still there: listed once.
        self.assertEqual(self.texts("README 点名竞品"), ["问：对外 README 要不要点名竞品？ → 答：只按类别写，不点名"])

    def test_a_common_word_alone_finds_little(self):
        for i in range(6):
            project_memory.add(self.state, PID, f"主人答：要不要做第 {i} 件事？→要", "decision", "owner_answer")
        project_memory.add(self.state, PID, "主人答：要不要点名竞品？→不点名", "decision", "owner_answer")
        self.assertEqual(self.texts("要不要点名竞品", limit=1), ["主人答：要不要点名竞品？→不点名"])

    def test_who_may_read_what_is_the_blocks(self):
        principles.save(self.state, principles.OWNER, "汇报先给结论")
        principles.save(self.state, principles.WORKSPACE, "这个仓库不跑全量", workspace="ws")
        topic_memory.add(self.state, "t1", "这件事不用先问", redacted=True)
        self.assertEqual(self.texts("汇报先给结论"), [])  # 全局: the owner's own turn only.
        self.assertEqual(self.texts("汇报先给结论", owner=True), ["汇报先给结论"])
        self.assertEqual(self.texts("全量"), ["这个仓库不跑全量"])
        self.assertEqual(self.texts("先问"), [])  # From a topic with redaction on.
        self.assertEqual(self.texts("先问", redacted=True), ["这件事不用先问"])
        write_topic(self.state, topic_id="t1", topic_number=7, proxy={"chat_id": "oc_x"})
        self.assertEqual(self.texts("全量"), [])  # A 代答 topic reads nothing.

    def test_the_entry_prints_lines_and_json(self):
        project_memory.add(self.state, PID, "主人答：要不要现在合入？→现在合入", "decision", "owner_answer")
        argv = [sys.executable, "-B", str(REPO / "bin" / "covey_memory.py"), "search", "--state", str(self.state),
                "--topic", "t1", "现在合入"]
        out = subprocess.run(argv, capture_output=True, text=True, timeout=60, cwd=self.state)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertRegex(out.stdout, r"^- \[专项 · 当前决定 · 你说的 · \d\d-\d\d\] 主人答：要不要现在合入？→现在合入")
        out = subprocess.run([*argv, "--json"], capture_output=True, text=True, timeout=60, cwd=self.state)
        self.assertEqual(json.loads(out.stdout)[0]["kind"], "当前决定")
        out = subprocess.run([*argv[:-1], "完全无关"], capture_output=True, text=True, timeout=60, cwd=self.state)
        self.assertIn("没有查到", out.stdout)


if __name__ == "__main__":
    unittest.main()
