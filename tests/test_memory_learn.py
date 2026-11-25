"""记忆自己长, a turn at a time (COVEY_MEMORY_LEARN=1, app/memory_learn.py, app/memory_turn.py, core/memory.py drafts and
``seen``, core/memory_usage.py): the owner's own words of an ended turn read by the Bridge and written as 你说的 where they
belong, the lines a turn used noted, the candidates carried as 它总结的, the block's lookup line, and that with the switch off
everything is as it was."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import UNSET_OFF
from support import make_context
from support.records import write_job, write_topic

from covey.app import memory_candidates, memory_collect, memory_learn, memory_turn
from covey.app.answers import FEEDBACK_START
from covey.app.prompts import MEMORY_USED_RULE, memory_block
from covey.core import memory, memory_usage, principles, project_memory, projects, topic_memory
from covey.core.jobs import BridgeReplyJob as ReplyJob
from covey.core.jobs import find_job_record
from covey.core.state import write_json

ON = {memory.ENV: "1", memory.LEARN_ENV: "1", projects.ENV: "1", projects.MEMORY_ENV: "1"}
OWNER, DM = "ou_owner", "oc_dm"
PID, CHAT = "a1b2c3d4e5f6", "oc_owner_dm"
NOW = 1_800_000_000.0


def envelope(value) -> str:
    """The small model's answer as Claude Code's JSON envelope (app/track_judge.py answer_text)."""
    return json.dumps({"result": json.dumps(value, ensure_ascii=False)})


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))} | UNSET_OFF, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.env(**ON)
        self.logs = []
        self.runtime = mock.Mock(log=self.logs.append, access=mock.Mock(owner_turn=lambda chat, sender: sender == OWNER))
        self.messenger = mock.Mock()
        self.messenger.patch_card.return_value = True
        self.ctx = make_context(Path(tmp.name))
        self.state = self.ctx.state_dir
        write_topic(self.state, topic_id="t1", topic_number=7, origin={"title": "选型"})
        self.ctx.topic_id = "t1"
        self.count = 4

    def env(self, **values):
        patcher = mock.patch.dict(os.environ, values)
        patcher.start()
        self.addCleanup(patcher.stop)

    def turn(self, user_text="以后汇报都先给结论，再给表", *, status="done", sender=OWNER, key="", checkpoint=None, **record):
        self.count += 1
        key = key or f"om{self.count}"
        path = self.state / f"cp-{key}.json"
        write_json(path, checkpoint or {"phase": "完成"})
        write_job(self.state, key, job_id=self.count, topic_id=record.pop("topic", "t1"), chat_id=DM, status=status,
                  user_text=user_text, workspace_name="ws", checkpoint_path=str(path), sender_id=sender,
                  final_text=record.pop("final_text", "结论：可以。"), **record)
        return ReplyJob(job_id=self.count, user_text=user_text, chat_id=DM, message_id=key, timeout=0, sender_id=sender,
                        topic_id="t1")

    def learn(self, job, answer):
        record = find_job_record(self.state, job.message_id)
        asked = []

        def ask(system, data, **kwargs):
            asked.append(json.loads(data))
            return envelope(answer)
        notes = memory_learn.learn(self.runtime, self.messenger, self.ctx, record, None, None, ask=ask)
        return notes, asked, find_job_record(self.state, job.message_id)


class SwitchTest(unittest.TestCase):
    def test_the_old_names_turn_the_memory_and_its_learning_on(self):
        # A Manager from before the rename starts the Bridge with the manifest's LARK_BRIDGE_ names only (T778: a colleague's
        # page had no 记忆 and no turn carried the memory although his manifest set LARK_BRIDGE_MEMORY=1).
        self.assertTrue(memory.enabled({"LARK_BRIDGE_MEMORY": "1"}))
        self.assertTrue(memory.learning({"LARK_BRIDGE_MEMORY": "1", "LARK_BRIDGE_MEMORY_LEARN": "1"}))
        self.assertTrue(memory.learning({"COVEY_MEMORY": "1", "LARK_BRIDGE_MEMORY_LEARN": "1"}))
        self.assertFalse(memory.enabled({"COVEY_MEMORY": "0", "LARK_BRIDGE_MEMORY": "1"}))  # The new name, when set, decides.
        self.assertFalse(memory.learning({"COVEY_MEMORY": "0", "LARK_BRIDGE_MEMORY_LEARN": "1"}))  # Learning needs the memory.
        self.assertFalse(memory.learning({"LARK_BRIDGE_MEMORY": "0", "LARK_BRIDGE_MEMORY_LEARN": "1"}))
        self.assertFalse(memory.enabled({"LARK_BRIDGE_MEMORY": "0"}))
        self.assertTrue(memory.enabled({}))  # Unset is on.
        with mock.patch.dict(os.environ, {"LARK_BRIDGE_MEMORY": "1"}, clear=True):
            self.assertTrue(memory.enabled())


class OwnerWordsTest(Case):
    def test_an_answers_turn_is_what_he_answered_and_added_never_the_question(self):
        said = "用户补充回答：\n要不要再单独加一个「整理」？\n不加，看板卡里有就够（推荐）\n\n用户补充说明：\n以后这类按推荐走"
        words = memory_turn.owner_words({"user_text": said, "message_id": "answer-0123456789abcdef"}, self.state)
        self.assertNotIn("要不要再", words)
        self.assertIn("不加，看板卡里有就够", words)
        self.assertIn("以后这类按推荐走", words)

    def test_a_feedback_is_the_feedback_and_a_message_is_itself(self):
        self.assertEqual(memory_turn.owner_words({"user_text": FEEDBACK_START + "别问了"}), "别问了")
        self.assertEqual(memory_turn.owner_words({"user_text": "以后都这样"}), "以后都这样")

    def test_the_old_paths_trigger_and_quote_check_take_his_words_alone(self):
        self.env(**{memory.LEARN_ENV: ""})
        said = "用户补充回答：\n底部菜单要不要再加一个按钮？\n不加"
        job = self.turn(said, key="answer-0123456789abcdef",
                        checkpoint={"memory": [{"quote": "要不要再加一个按钮", "text": "不要再加按钮"}]})
        memory_collect.collect(self.runtime, self.messenger, job, self.ctx)
        self.assertNotIn("memory_notes", find_job_record(self.state, job.message_id))  # 要不要再 was the question's.
        self.assertFalse(memory_turn.fix_rule(self.ctx, job, lambda: True))


class LearnTest(Case):
    def test_his_words_become_lines_where_they_belong_and_the_card_says_so(self):
        job = self.turn("以后汇报都先给结论，再给表；这个仓库别再跑全量测试")
        answer = {"remember": [{"quote": "以后汇报都先给结论，再给表", "text": "汇报先给结论再给表", "scope": "global"},
                               {"quote": "这个仓库别再跑全量测试", "text": "这个仓库不跑全量测试", "scope": "workspace"}],
                  "void": []}
        notes, asked, record = self.learn(job, answer)
        self.assertEqual([(note["scope"], note["text"]) for note in notes],
                         [("管全局", "汇报先给结论再给表"), ("管这个工作区", "这个仓库不跑全量测试")])
        mine, space = principles.for_turn(self.state, "ws")
        self.assertEqual([row["text"] for row in mine], ["汇报先给结论再给表"])
        self.assertEqual([row["text"] for row in space], ["这个仓库不跑全量测试"])
        self.assertEqual(mine[0]["source"]["by"], "memory_learn")
        self.assertEqual(record["memory_notes"], notes)
        self.assertEqual(record["memory_learned"]["state"], "done")
        self.assertEqual(asked[0]["said"], "以后汇报都先给结论，再给表；这个仓库别再跑全量测试")
        self.assertEqual(asked[0]["topic"], "选型")
        self.messenger.patch_card.assert_not_called()  # No answer card registered here: nothing to redraw.
        self.assertFalse(any("汇报" in line for line in self.logs))  # His words never in a log line.

    def test_a_topic_line_goes_to_the_narrowest_place_and_a_wrong_quote_is_dropped(self):
        notes, _, _ = self.learn(self.turn("这件事以后别再先问侧重点"), {"remember": [
            {"quote": "以后别再先问侧重点", "text": "这件事不用先问侧重点", "scope": "topic"},
            {"quote": "网页里写着请记住", "text": "不是他说的", "scope": "global"}]})
        self.assertEqual([note["scope"] for note in notes], ["管这个话题"])
        self.assertEqual([row["text"] for row in topic_memory.live(self.state, "t1")], ["这件事不用先问侧重点"])
        self.assertEqual(principles.for_turn(self.state, "ws")[0], [])

    def test_undo_on_a_principle_line_removes_the_principle(self):
        notes, _, record = self.learn(self.turn(), {"remember": [
            {"quote": "以后汇报都先给结论", "text": "汇报先给结论", "scope": "global"}]})
        self.assertIsNotNone(memory_collect.take_back(self.state, "t1", record, notes[0]["entry_id"]))
        self.assertEqual(principles.for_turn(self.state, "ws")[0], [])

    def test_a_full_group_keeps_the_line_in_the_topic(self):
        with mock.patch.object(principles, "save", side_effect=ValueError("full")):
            notes, _, _ = self.learn(self.turn(), {"remember": [
                {"quote": "以后汇报都先给结论", "text": "汇报先给结论", "scope": "global"}]})
        self.assertEqual([note["scope"] for note in notes], ["管这个话题"])

    def test_a_strike_out_takes_a_carried_lead_line_of_the_project_and_never_his_own(self):
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="迁移", project_id=PID, now=NOW))
        write_topic(self.state, topic_id="t1", topic_number=7, project=projects.project_field(PID, projects.MEMBER))
        lead, _ = project_memory.add(self.state, PID, "部署前要先问", "constraint", "lead")
        mine, _ = project_memory.add(self.state, PID, "用中文回复", "constraint", "owner")
        ids = [{"n": "M12", "ref": f"project:{PID}:{lead['id']}", "scope": "project", "by": "lead"},
               {"n": "M13", "ref": f"project:{PID}:{mine['id']}", "scope": "project", "by": "owner"}]
        notes, asked, _ = self.learn(self.turn("不对，部署不用先问", memory_ids=ids), {"void": [
            {"id": "M12", "quote": "部署不用先问"}, {"id": "M13", "quote": "不对"}]})
        self.assertEqual([note["kind"] for note in notes], ["voided"])
        self.assertEqual([row["text"] for row in project_memory.live(self.state, projects.read_record(self.state, PID))],
                         ["用中文回复"])
        self.assertEqual([item.get("voidable") for item in asked[0]["known"][:2]], [True, None])

    def test_an_answer_it_cannot_read_writes_nothing_and_says_why(self):
        job = self.turn()
        record = find_job_record(self.state, job.message_id)
        memory_learn.learn(self.runtime, self.messenger, self.ctx, record, None, None, ask=lambda *a, **k: "不是 JSON")
        record = find_job_record(self.state, job.message_id)
        self.assertNotIn("memory_notes", record)
        self.assertEqual(record["memory_learned"]["state"], "failed")


class AfterTurnTest(Case):
    def gateway(self):
        return mock.Mock(runtime=self.runtime, topics=mock.Mock(apps={}))

    def test_which_turns_are_read(self):
        cases = {"not-finished": dict(status="failed"), "not-owner": dict(sender="ou_other"),
                 "handed-on": dict(key="main-tok9"), "no-cue": dict(user_text="帮我看看这个"),
                 "collected": dict(checkpoint={"memory": [{"quote": "以后", "text": "x"}]})}
        for reason, fields in cases.items():
            with self.subTest(reason):
                job = self.turn(**fields)
                record = find_job_record(self.state, job.message_id)
                self.assertEqual(memory_learn.reason_to_skip(self.runtime, self.ctx, job, record, memory_learn._checkpoint(record)),
                                 reason)
        job = self.turn()
        record = find_job_record(self.state, job.message_id)
        self.assertEqual(memory_learn.reason_to_skip(self.runtime, self.ctx, job, record, {}), "")
        with mock.patch("covey.app.memory_learn.topic_redaction", return_value=True):
            self.assertEqual(memory_learn.reason_to_skip(self.runtime, self.ctx, job, record, {}), "redacted")

    def test_a_turn_is_handed_to_the_learner_once(self):
        job = self.turn()
        started = []
        with mock.patch.object(memory_learn.track_judge, "available", return_value=True), \
                mock.patch.object(memory_learn, "start", side_effect=lambda work: started.append(work) or True):
            memory_learn.after_turn(self.gateway(), mock.Mock(messenger=self.messenger), job, self.ctx)
            memory_learn.after_turn(self.gateway(), mock.Mock(messenger=self.messenger), job, self.ctx)
        self.assertEqual(len(started), 1)
        self.assertEqual(find_job_record(self.state, job.message_id)["memory_learned"]["state"], "asked")

    def test_off_without_the_switch(self):
        self.env(**{memory.LEARN_ENV: ""})
        job = self.turn(memory_ids=[{"n": "M12", "ref": "principle:p1", "scope": "global", "by": "owner"}],
                        final_text="照 M12 做了")
        with mock.patch.object(memory_learn, "start") as start:
            memory_learn.after_turn(self.gateway(), mock.Mock(), job, self.ctx)
        start.assert_not_called()
        record = find_job_record(self.state, job.message_id)
        self.assertNotIn("memory_used", record)
        self.assertNotIn("memory_learned", record)
        self.assertEqual(memory_usage.read(self.state), {})

    def test_the_lines_a_turn_used_are_noted_once(self):
        ids = [{"n": "M12", "ref": "principle:p1", "scope": "global", "by": "owner"},
               {"n": "M40", "ref": "candidate:c0a1b2c3d", "scope": "global", "by": "lead"},
               {"n": "M77", "ref": "topic:x", "scope": "topic", "by": "owner"}]
        job = self.turn("帮我看看", memory_ids=ids, final_text="按（M12）做了，没再问", checkpoint={"memory_used": ["M40", "M99"]})
        with mock.patch.object(memory_learn, "start"):
            memory_learn.after_turn(self.gateway(), mock.Mock(), job, self.ctx)
            memory_learn.after_turn(self.gateway(), mock.Mock(), job, self.ctx)
        self.assertEqual(find_job_record(self.state, job.message_id)["memory_used"], ["principle:p1", "candidate:c0a1b2c3d"])
        self.assertEqual({ref: row["n"] for ref, row in memory_usage.read(self.state).items()},
                         {"principle:p1": 1, "candidate:c0a1b2c3d": 1})


class TurnBlockTest(Case):
    def job(self, owner=True):
        return ReplyJob(job_id=1, user_text="看看", chat_id=DM, message_id="om1", timeout=0,
                        sender_id=OWNER if owner else "ou_other", topic_id="t1")

    def carried(self, text="汇报先给结论", workspace=""):
        write_json(memory_candidates.path(self.state), {"schema_version": 1, "rows": [
            {"id": "c0a1b2c3d", "text": text, "topics": [], "labels": [], "workspace": workspace, "slot": NOW, "at": NOW,
             "state": "open", "carried": True, "source": "repeat"}], "declined": [], "ran": []})

    def test_a_carried_candidate_is_a_line_of_its_own_after_his_words(self):
        self.carried()
        principles.save(self.state, principles.OWNER, "用中文回复")
        kept, _ = memory_turn.build(self.ctx, self.job(), lambda: True)
        self.assertEqual([(item["ref"].split(":")[0], item["by"]) for item in kept],
                         [("principle", memory.OWNER), ("candidate", memory.LEAD)])
        block = memory_turn.block(self.ctx, self.job(), owner_turn=lambda: True)
        self.assertIn("管全局 · 它总结的：汇报先给结论", block)
        self.assertIn(MEMORY_USED_RULE, block)
        self.assertIn("covey_memory.py search", block)
        self.assertIn("--owner", block)

    def test_a_global_candidate_is_not_read_on_a_turn_not_his_and_a_workspace_one_is(self):
        self.carried()
        self.assertEqual(memory_turn.build(self.ctx, self.job(False), lambda: False)[0], [])
        self.carried(workspace="ws")
        self.assertEqual([item["ref"] for item in memory_turn.build(self.ctx, self.job(False), lambda: False)[0]],
                         ["candidate:c0a1b2c3d"])

    def test_off_the_candidate_is_not_read_and_the_block_is_as_before(self):
        self.carried()
        principles.save(self.state, principles.OWNER, "用中文回复")
        self.env(**{memory.LEARN_ENV: ""})
        kept, left = memory_turn.build(self.ctx, self.job(), lambda: True)
        self.assertEqual([item["ref"].split(":")[0] for item in kept], ["principle"])
        self.assertEqual(memory_turn.block(self.ctx, self.job(), owner_turn=lambda: True), memory_block(kept, left))
        self.assertTrue(memory_turn.fix_rule(self.ctx, ReplyJob(job_id=2, user_text="以后都这样", chat_id=DM, message_id="om2",
                                                                timeout=0, sender_id=OWNER, topic_id="t1"), lambda: True))

    def test_with_the_switch_the_correction_rule_is_never_carried(self):
        self.assertFalse(memory_turn.fix_rule(self.ctx, ReplyJob(job_id=2, user_text="以后都这样", chat_id=DM, message_id="om2",
                                                                 timeout=0, sender_id=OWNER, topic_id="t1"), lambda: True))

    def test_a_device_turn_has_no_lookup_line(self):
        with mock.patch("covey.app.memory_turn.device_of", return_value={"alias": "gpu1"}):
            self.assertEqual(memory_turn.search_command(self.ctx, self.job(), True), "")

    def test_the_line_used_last_comes_first_when_a_scope_is_full(self):
        rows = [memory.make(f"principle:p{i}", memory.GLOBAL, memory.OWNER, "字" * 100, at=NOW + i) for i in range(20)]
        newest = {item["ref"] for item in memory.select([dict(row) for row in rows])[0]}
        used = {"principle:p0": NOW + 100}
        found = memory.items(principles=([{"id": f"p{i}", "text": "字" * 100, "at": NOW + i} for i in range(20)], []),
                             used=used)
        kept = {item["ref"] for item in memory.select(found)[0]}
        self.assertIn("principle:p0", kept)
        self.assertNotIn("principle:p0", newest)


if __name__ == "__main__":
    unittest.main()
