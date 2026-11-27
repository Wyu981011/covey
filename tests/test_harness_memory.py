"""What the Harnesses remember on their own, offered for import (core/harness_memory.py, app/memory_harvest.py queue): the
three adapters read Claude Code's auto memory, Codex's summary and task groups and Antigravity's rules file and knowledge
items, read only, entry by entry with a stable fingerprint; the repo map names a bucket's repository and marks a frozen one
old; the web's page orders and flags them; the night offers only what a changed file says anew; a ticked one is imported."""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from support.records import state_dir

from covey.app import memory_harvest
from covey.core import harness_memory as hm, memstore

CLAUDE_FILE = """---
name: reply-in-chinese
description: "Write the final reply in Chinese"
metadata:
  type: feedback
---

English replies made the owner skip question cards.
"""
CODEX_SUMMARY = """# Memory summary

## User Profile

- 主人用中文交流，结论先行。

## User preferences

- 不要重新询问已选路线。
- 汇报要带证据
  和命令输出。

## General Tips

- 搜索前先限定目录。

## What's in Memory

- /absolute/repo: 2026-11-23 task notes
"""
CODEX_MEMORY = """# Task Group: gateway capacity plan

scope: read-only planning
applies_to: cwd=/absolute/work/gateway; reuse_rule=snapshots need fresh checks

## Task 1: plan

### keywords

- AIDP, 1017

## User preferences

- 只读盘点，新占卡要另行授权。 [Task 1]

## Reusable knowledge

- 网关支持同模型名多后端。 [Task 1]

# Task Group: old repo cleanup

applies_to: cwd=/absolute/work/old-repo

## Failures and how to do differently

- 先查 pgrep 再快进主检出。 [Task 2]
"""
GEMINI = """# 全局规则

这份规则对每次运行都生效。

## 搜索

- 只搜具体仓库，不要整个工作区递归。
- 命令要设超时。

## 汇报

结论先行，再给证据。
"""


class Case(unittest.TestCase):
    def setUp(self):
        self.state = state_dir(self)
        self.home = state_dir(self)
        memstore._cache.clear()
        home = self.home
        claude = home / ".claude" / "projects"
        self.covey_bucket = hm._dashed("/absolute/work/covey")
        for bucket, files in ((self.covey_bucket, {"reply-in-chinese.md": CLAUDE_FILE, "MEMORY.md": "- [x](x.md)\n"}),
                              (hm._dashed("/absolute/work/old-repo"), {"no-cp.md": "---\nname: no-cp\ntype: project\n---\n不要 cp -al。\n"})):
            (claude / bucket / "memory").mkdir(parents=True)
            for name, text in files.items():
                (claude / bucket / "memory" / name).write_text(text)
        (claude / "-empty" / "memory").mkdir(parents=True)
        codex = home / ".codex" / "memories"
        codex.mkdir(parents=True)
        (codex / "memory_summary.md").write_text(CODEX_SUMMARY)
        (codex / "MEMORY.md").write_text(CODEX_MEMORY)
        (codex / "raw_memories.md").write_text("- 原始的不导\n")
        gemini = home / ".gemini"
        (gemini / "config").mkdir(parents=True)
        (gemini / "config" / "GEMINI.md").write_text(GEMINI)
        (gemini / "antigravity" / "knowledge" / "ki1").mkdir(parents=True)
        (gemini / "antigravity" / "knowledge" / "ki1" / "metadata.json").write_text(
            json.dumps({"title": "部署检查", "summary": "部署前看预检输出"}, ensure_ascii=False))
        Path(self.state, "repos.json").write_text(json.dumps({"repos": [
            {"name": "covey", "path": "/absolute/work/covey"},
            {"name": "gateway", "path": "/absolute/work/gateway"},
            {"name": "old-repo", "path": "/absolute/work/old-repo", "status": "frozen"}]}))

    def scan(self):
        return hm.scan(self.state, self.home)


class ScanTest(Case):
    def test_each_harness_is_read_entry_by_entry_with_its_bucket_and_repository(self):
        items = self.scan()
        found = {(item.harness, item.text): item for item in items}
        texts = {text for _, text in found}
        self.assertEqual({item.harness for item in items}, set(hm.HARNESSES))
        claude = found[("claude_code", "Write the final reply in Chinese English replies made the owner skip question cards.")]
        # Its title the description's, not the file's slug of a name (T870 Wave 3.5, P1-5).
        self.assertEqual((claude.title, claude.type, claude.repo), ("Write the final reply in Chinese", "feedback", "covey"))
        self.assertEqual(found[("claude_code", "不要 cp -al。")].title, "不要 cp -al")  # No description: the body's, not "no-cp".
        self.assertIn("主人用中文交流，结论先行。", texts)
        self.assertIn("汇报要带证据 和命令输出。", texts)  # A continuation line joins its item.
        self.assertIn("搜索前先限定目录。", texts)
        self.assertNotIn("/absolute/repo: 2026-11-23 task notes", texts)  # The index of what is in memory is not an entry.
        self.assertNotIn("原始的不导", texts)
        self.assertNotIn("AIDP, 1017", texts)
        gateway = found[("codex", "只读盘点，新占卡要另行授权。")]
        self.assertEqual((gateway.type, gateway.bucket, gateway.repo), ("feedback", "/absolute/work/gateway", "gateway"))
        self.assertEqual(found[("codex", "先查 pgrep 再快进主检出。")].repo, "old-repo")
        self.assertIn(("antigravity", "只搜具体仓库，不要整个工作区递归。"), found)
        self.assertEqual(found[("antigravity", "结论先行，再给证据。")].title, "汇报")
        self.assertEqual(found[("antigravity", "部署检查 部署前看预检输出")].type, "knowledge")
        self.assertFalse(any(item.file.endswith("MEMORY.md") and item.harness == "claude_code" for item in items))
        self.assertEqual([item.fingerprint for item in self.scan()], [item.fingerprint for item in items])  # Stable.
        self.assertEqual(len({item.fingerprint for item in items}), len(items))

    def test_a_claude_folder_of_no_repository_is_named_short(self):
        """T870 Wave 3.5 (P1-5): the page grouped them under ``-mnt-bn-…-xuke-code-covey`` (the folder's dashed name)."""
        Repo = type("Repo", (), {})
        one = Repo()
        one.path, one.name = "/absolute/work/covey", "covey"
        self.assertEqual(hm.short_bucket(hm._dashed("/absolute/work/misc-tasks"), [one]), "misc-tasks")
        self.assertEqual(hm.short_bucket(hm._dashed("/absolute/work"), [one]), "work")
        self.assertEqual(hm.short_bucket("-somewhere-else-tool", [one]), "tool")
        self.assertEqual(hm.short_bucket("/absolute/work/gateway", [one]), "/absolute/work/gateway")
        bucket = self.home / ".claude" / "projects" / hm._dashed("/absolute/work/misc-tasks") / "memory"
        bucket.mkdir(parents=True)
        (bucket / "note.md").write_text("---\nname: tidy-note\ndescription: 杂活放 misc-tasks\ntype: project\n---\n杂活目录。\n")
        page = hm.page(self.state, self.home, 0, items=self.scan())
        row = next(row for row in page["items"] if row["text"].startswith("杂活放"))
        self.assertEqual((row["bucket"], row["title"]), ("misc-tasks", "杂活放 misc-tasks"))

    def test_the_page_orders_flags_and_names_what_is_there_already(self):
        items = self.scan()
        old = next(item for item in items if item.repo == "old-repo")
        memstore.add(self.state, kind="rule", scope="global", text="搜索前先限定目录。")
        hm.ignore(self.state, [items[0].fingerprint], items=items)
        page = hm.page(self.state, self.home, 0, items=items)
        self.assertEqual(page["page"], 0)
        rows = {row["fingerprint"]: row for row in page["items"]}
        self.assertEqual(page["items"][-1]["state"], "ignored")
        self.assertTrue(rows[old.fingerprint]["old_repo"])
        tip = next(row for row in page["items"] if row["text"] == "搜索前先限定目录。")
        self.assertTrue(tip["dup_of"].startswith("global:"))
        self.assertEqual(rows[items[1].fingerprint]["file_tail"].count("/"), 1)
        self.assertNotIn("file", rows[items[1].fingerprint])
        self.assertEqual({row["suggest"]["kind"] for row in page["items"] if row["type"] == "feedback"}, {"rule"})
        self.assertEqual({row["suggest"]["kind"] for row in page["items"] if row["type"] == "reference"}, {"note"})
        self.assertEqual(hm.summary(self.state, items), {"total": len(items), "new": len(items) - 1, "pages": 1})
        self.assertEqual(hm.page(self.state, self.home, 1, items=items)["items"], [])

    def test_ticked_ones_are_imported_as_the_owners_and_marked(self):
        items = self.scan()
        chosen = [item for item in items if item.repo == "gateway" or item.repo == "old-repo"]
        made = hm.take(self.state, self.home, [item.fingerprint for item in chosen], items=items, token="u-imp")
        self.assertEqual(len(made), len(chosen))
        self.assertTrue(all(entry.by == "import" and entry.said == "owner" and entry.scope == "global" for entry in made))
        self.assertEqual({entry.repos for entry in made}, {("gateway",), ()})  # A frozen repository is not named.
        self.assertEqual({entry.origin["harness"] for entry in made}, {"codex", "claude_code"})
        records = memstore.imports(self.state)["items"]
        self.assertEqual({records[item.fingerprint]["state"] for item in chosen}, {"imported"})
        self.assertEqual(sorted(memstore.undo(self.state, "u-imp")), sorted(entry.ref for entry in made))


class NightTest(Case):
    def test_the_first_night_notes_and_later_ones_offer_only_what_a_changed_file_says_anew(self):
        self.assertEqual(memory_harvest.queue(self.state, self.home, log=lambda line: None), 0)
        self.assertEqual(memstore.review_items(self.state), [])
        self.assertEqual(memory_harvest.queue(self.state, self.home, log=lambda line: None), 0)
        summary = self.home / ".codex" / "memories" / "memory_summary.md"
        summary.write_text(CODEX_SUMMARY.replace("## General Tips", "## General Tips\n\n- 改完先跑相关测试。"))
        stamp = time.time() + 5
        os.utime(summary, (stamp, stamp))
        self.assertEqual(memory_harvest.queue(self.state, self.home, log=lambda line: None), 1)
        (item,) = memstore.review_items(self.state)
        self.assertEqual((item["type"], item["text"], item["suggest"]["kind"]), ("import", "改完先跑相关测试。", "note"))
        self.assertEqual(memory_harvest.queue(self.state, self.home, log=lambda line: None), 0)

    def test_a_broken_home_is_logged_not_raised(self):
        lines = []
        with mock.patch.object(hm, "fresh", side_effect=OSError("gone")):
            self.assertEqual(memory_harvest.queue(self.state, self.home, log=lines.append), 0)
        self.assertEqual(lines, ["memory import failed: OSError"])

    def test_two_hundred_files_are_read_whole_and_quickly(self):
        folder = self.home / ".claude" / "projects" / "-absolute-many" / "memory"
        folder.mkdir(parents=True)
        for index in range(220):
            (folder / f"n{index}.md").write_text(f"---\nname: n{index}\ntype: user\n---\n第 {index} 条偏好\n")
        started = time.monotonic()
        items = self.scan()
        self.assertGreaterEqual(len([item for item in items if item.bucket == "-absolute-many"]), 220)
        self.assertLess(time.monotonic() - started, 10)


if __name__ == "__main__":
    unittest.main()
