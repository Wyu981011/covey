"""What Codex and Claude Code noted of the owner on their own, offered as candidates (COVEY_MEMORY_LEARN=1,
app/memory_harvest.py, app/memory_candidates.py add, carried, expire and reopen): read once a slot, only what changed, never
carried before a click, and none of a Harness's own files written."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import UNSET_OFF
from covey.app import memory_candidates, memory_harvest
from covey.app.track_standby import Failed
from covey.backends.claude.sessions import encode_project_dir
from covey.core import memory, principles
from covey.core.state import write_json
from covey.core.workspaces import config_path

NOW = 1_800_000_000.0
SUMMARY = "v1\n\n## User Profile\n\n他用中文。\n\n## User preferences\n\n- 先给结论，再给表\n\n## Projects\n\n- 别的项目细节\n"


def envelope(value) -> str:
    return json.dumps({"result": json.dumps(value, ensure_ascii=False)})


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.state, self.codex, self.claude, work = root / "state", root / "codex", root / "claude", root / "work"
        self.state.mkdir()
        work.mkdir()
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))} | UNSET_OFF, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env = {"CODEX_HOME": str(self.codex), "CLAUDE_CONFIG_DIR": str(self.claude)}
        (self.codex / "memories").mkdir(parents=True)
        (self.codex / "memories" / "memory_summary.md").write_text(SUMMARY)
        write_json(config_path(self.state), {"default": "ws", "workspaces": {"ws": str(work), "gpu": "gpu1:/home/me/p"}})
        self.memory_dir = self.claude / "projects" / encode_project_dir(work) / "memory"
        self.memory_dir.mkdir(parents=True)
        (self.memory_dir / "MEMORY.md").write_text("- [x](feedback_x.md)\n")
        (self.memory_dir / "feedback_x.md").write_text("---\nname: x\nmetadata:\n  type: feedback\n---\n\n改完先跑检查再合并\n")
        (self.memory_dir / "project_y.md").write_text("---\nname: y\nmetadata:\n  type: project\n---\n\n某个项目的进度\n")
        self.asked = []

    def harvest(self, answer, slot=NOW, error=None):
        def ask(system, data, **kwargs):
            self.asked.append(json.loads(data))
            if error is not None:
                raise error
            return envelope(answer)
        return memory_harvest.harvest(self.state, slot, backend=None, ctx=None, log=lambda line: None, ask=ask, env=self.env,
                                      now=slot)


class SourcesTest(Case):
    def test_codexs_sections_on_the_user_and_claudes_user_and_feedback_files(self):
        notes = memory_harvest.codex_notes(self.env)
        self.assertIn("先给结论，再给表", notes)
        self.assertNotIn("别的项目细节", notes)
        found = memory_harvest.claude_notes(self.state, self.env)
        self.assertEqual([row["workspace"] for row in found], ["ws"])
        self.assertIn("改完先跑检查再合并", found[0]["text"])


class HarvestTest(Case):
    def test_its_rules_become_candidates_of_their_source_never_carried(self):
        added = self.harvest({"rules": [{"text": "汇报先给结论再给表", "workspace": "", "from": "codex"},
                                        {"text": "改完先跑检查再合并", "workspace": "ws", "from": "claude"},
                                        {"text": "不认识的工作区", "workspace": "nope", "from": "claude"}]})
        self.assertEqual([(row["source"], row["workspace"]) for row in added], [("codex", ""), ("claude", "ws"), ("claude", "")])
        self.assertTrue(all(not row.get("carried") for row in added))
        self.assertEqual(memory_candidates.carried(self.state, "ws"), ([], []))
        self.assertEqual({row["from"] for row in self.asked[0]["sources"]}, {"codex", "claude"})
        self.assertEqual((self.memory_dir / "feedback_x.md").read_text().count("改完先跑检查再合并"), 1)  # Not written.

    def test_the_prompt_has_covey_glossary_and_a_person_is_never_a_负责人(self):
        for words in ("user、owner、用户", "主人", "「负责人」在 Covey 里专指", "回复负责人"):
            self.assertIn(words, memory_harvest.SYSTEM)
        added = self.harvest({"rules": [{"text": "回复负责人必须用中文", "workspace": "", "from": "codex"},
                                        {"text": "需要负责人拍板的决定要列出选项", "workspace": "", "from": "codex"},
                                        {"text": "负责人汇报进度时要简短", "workspace": "", "from": "claude"}]})
        self.assertEqual([row["text"] for row in added], ["回复主人必须用中文", "需要主人拍板的决定要列出选项",
                                                         "负责人汇报进度时要简短"])  # A lead Agent stays one.
        self.assertEqual(memory_harvest.terms("问负责人之前先查文档，向负责人汇报，负责人确认后再合并"),
                         "问主人之前先查文档，向主人汇报，主人确认后再合并")

    def test_a_slot_is_read_once_and_an_unchanged_source_is_not_sent_again(self):
        self.harvest({"rules": []})
        self.harvest({"rules": []})
        self.assertEqual(len(self.asked), 1)
        self.harvest({"rules": []}, slot=NOW + 86400)
        self.assertEqual(len(self.asked), 1)  # Nothing changed since.
        (self.memory_dir / "feedback_z.md").write_text("---\nmetadata:\n  type: user\n---\n\n他喜欢短的回答\n")
        self.harvest({"rules": []}, slot=NOW + 2 * 86400)
        self.assertEqual([row["from"] for row in self.asked[1]["sources"]], ["claude"])

    def test_a_failure_is_tried_the_next_day_and_what_a_principle_says_already_is_not_offered(self):
        principles.save(self.state, principles.OWNER, "汇报先给结论再给表")
        self.assertEqual(self.harvest({}, error=Failed("timeout")), [])
        self.assertEqual(self.harvest({"rules": [{"text": "汇报先给结论再给表", "from": "codex"}]}, slot=NOW + 86400), [])
        self.assertEqual(len(self.asked), 2)  # Its sources were not marked seen by the failed read.


class CandidatesTest(Case):
    def test_rows_offered_with_the_switch_are_carried_and_kept_until_decided(self):
        with mock.patch.dict(os.environ, {memory.ENV: "1", memory.LEARN_ENV: "1"}):
            memory_candidates.offer(self.state, "oc", NOW, lambda: [{"text": "汇报先给结论", "topics": ["a", "b"],
                                                                      "labels": ["T1", "T2"], "workspace": ""}], now=NOW)
        rows = memory_candidates.load(self.state)["rows"]
        self.assertEqual((rows[0]["carried"], rows[0]["source"]), (True, memory_candidates.REPEAT))
        later = NOW + 30 * 86400
        self.assertEqual(len(memory_candidates.kept_rows(rows, later)), 1)  # Open and carried: past KEPT_DAYS too.
        memory_candidates.decide(self.state, rows[0]["id"], "drop", now=later)
        self.assertEqual(memory_candidates.kept_rows(memory_candidates.load(self.state)["rows"], later), [])

    def test_without_the_switch_a_row_is_as_before(self):
        with mock.patch.dict(os.environ, {memory.ENV: "1"}):
            memory_candidates.offer(self.state, "oc", NOW, lambda: [{"text": "汇报先给结论", "topics": ["a", "b"],
                                                                      "labels": [], "workspace": ""}], now=NOW)
        row = memory_candidates.load(self.state)["rows"][0]
        self.assertNotIn("carried", row)
        self.assertNotIn("source", row)


if __name__ == "__main__":
    unittest.main()
