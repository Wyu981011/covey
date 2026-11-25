"""scripts/question_stats.py: how much the turns asked the owner, the numbers to compare before and after the asking rules
(core/checkpoint.py ASK_RULE, PLAN_RULE) change."""
from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("question_stats_script", REPO / "scripts" / "question_stats.py")
stats = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stats)


def at(day, hour=12):
    return dt.datetime.fromisoformat(f"{day}T{hour:02d}:00:00").timestamp()


def question(qid, header, text, *labels):
    return {"id": qid, "header": header, "question": text, "options": [{"label": label} for label in labels]}


class QuestionStatsTest(unittest.TestCase):
    def setUp(self):
        self.state = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.state)
        (self.state / "questions").mkdir()
        (self.state / "jobs").mkdir()
        (self.state / "questions" / ".locks").mkdir()  # Not a record: never read.

    def card(self, name, day, job_id, questions, answers=None, **fields):
        record = {"token": name, "topic_id": "t1", "job_id": job_id, "created_at": at(day), "questions": questions,
                  "answers": {qid: {"answers": given} for qid, given in (answers or {}).items()}, **fields}
        (self.state / "questions" / f"{name}.json").write_text(json.dumps(record, ensure_ascii=False))

    def job(self, job_id, day, topic="t1"):
        record = {"job_id": job_id, "topic_id": topic, "created_at": f"{day}T04:00:00Z"}
        (self.state / "jobs" / f"j{job_id}.json").write_text(json.dumps(record))

    def run_json(self, *windows):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = stats.main(["--state", str(self.state), *(f"--window={w}" for w in windows), "--json"])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_cards_questions_and_the_recommended_picks_per_window(self):
        for job_id, day in ((1, "2026-11-10"), (2, "2026-11-11"), (3, "2026-11-11"), (4, "2026-11-12"), (5, "2026-11-20")):
            self.job(job_id, day)
        # The topic's first turn asks before it gave its plan; a deploy picked as recommended, a naming left unanswered.
        self.card("a", "2026-11-11", 1, [question("d", "部署", "现在部署到现网吗？", "现在部署（推荐）", "先不"),
                                         question("n", "名字", "新模块叫什么？", "tidy（推荐）", "sorter")],
                  {"d": ["现在部署（推荐）"], "n": ["用户选择不回答此题（不表示同意或授权）"]})
        self.card("b", "2026-11-12", 3, [question("o", "顺序", "先做哪件？", "先 A（推荐）", "先 B")], {"o": ["先 A（推荐）"]},
                  triage={"state": "answered_by_lead"})
        self.card("c", "2026-11-12", 4, [question("x", "清理", "删掉旧目录吗？", "删", "留着")], {"x": ["留着"]})
        self.card("late", "2026-11-20", 5, [question("y", "下一步", "接着做吗？", "做（推荐）")])
        self.card("early", "2026-11-09", 1, [question("z", "发版", "发布吗？", "发（推荐）")], {"z": ["发（推荐）"]})
        found = self.run_json("2026-11-11:2026-11-12", "2026-11-20:2026-11-20")
        first, second = found["windows"]
        self.assertEqual((first["days"], first["turns"], first["cards"], first["cards_per_day"]), (2, 3, 3, 1.5))
        self.assertEqual(first["cards_per_100_turns"], 100.0)
        self.assertEqual((first["questions"], first["offered_recommended"], first["picked_recommended"], first["skipped"]),
                         (4, 3, 2, 1))
        self.assertEqual(first["picked_recommended_pct"], 50.0)
        self.assertEqual((first["lead_answered_cards"], first["first_turn_cards"]), (1, 1))
        self.assertEqual(first["kinds"]["部署"], {"questions": 1, "picked_recommended": 1, "skipped": 0})
        self.assertEqual(first["kinds"]["删除"], {"questions": 1, "picked_recommended": 0, "skipped": 0})
        self.assertEqual(first["kinds"]["其他"], {"questions": 2, "picked_recommended": 1, "skipped": 1})
        self.assertEqual((second["cards"], second["questions"], second["picked_recommended"], second["turns"]), (1, 1, 0, 1))
        self.assertEqual(found["unread"], {"questions": 0, "jobs": 0})

    def test_a_day_without_turns_or_cards_says_so_and_the_text_reads(self):
        found = self.run_json("2026-11-11:2026-11-11")["windows"][0]
        self.assertEqual((found["cards"], found["turns"], found["cards_per_100_turns"], found["picked_recommended_pct"]),
                         (0, 0, None, None))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            stats.main(["--state", str(self.state), "--window", "2026-11-11:2026-11-11", "--daily"])
        self.assertIn("2026-11-11 ~ 2026-11-11（1 天）", out.getvalue())
        self.assertIn("问题卡 0：0.0 张/天，每百轮 — 张", out.getvalue())

    def test_a_record_changed_before_the_windows_is_not_opened(self):
        self.card("old", "2026-11-01", 1, [question("z", "发版", "发布吗？", "发（推荐）")])
        path = self.state / "questions" / "old.json"
        os.utime(path, (at("2026-11-01"), at("2026-11-01")))
        path.chmod(0)  # Opening it would fail: it is skipped by its time alone.
        self.addCleanup(path.chmod, 0o600)
        records, unread = stats.read_records(str(self.state / "questions"), at("2026-11-10", 0), 5)
        self.assertEqual((records, unread), ([], 0))

    def test_a_window_is_two_dates_in_order(self):
        self.assertEqual(stats.window("2026-11-11:2026-11-25"), ("2026-11-11", "2026-11-25"))
        for bad in ("2026-11-25:2026-11-11", "11-11:11-25", "2026-11-11"):
            with self.assertRaises(ValueError, msg=bad):
                stats.window(bad)


if __name__ == "__main__":
    unittest.main()
