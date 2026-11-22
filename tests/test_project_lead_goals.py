"""The lead answers for the project's goal (docs/projects.md 负责人对照目标跟进 and 分流的依据, COVEY_COLLAB=1; T634 包 D).

- L1: a 目标检查表 the lead keeps (core/project_checklist.py, project_checklist) and project_finish's gate on an item not met
  or a 协作 gap not dealt with: two topics say they are done while the baseline check of the goal is missing, the finish is
  refused naming it, the lead arranges it, and only then may it finish.
- L2: ordinary receipts that come close together wake the lead once, a start, a choice, a question or a gap at once, a
  consult's receipt never; a wake-up turn that read only results the owner was sent and consults' receipts does not retell
  them; a consult's tokens count in its project's budget once.
- M5: project_answer stands on grounds the Bridge checks: the lead's notes (待核对参考), a line voided, done, superseded or
  only for that once, a line with no origin and a made-up one are refused and the lead is told to escalate; the owner's own
  line that still holds, or his own message in the project, answers, and the grounds are on the answer and its row.

With COVEY_COLLAB off none of it changes anything: each part says so here, and the older tests of each part still pass."""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import make_job
from support.records import write_job, write_topic

from covey.app import project_facts, project_lead, project_loop, triage as flow
from covey.core import butler, butler_mcp, butler_tool_specs, collab, collab_records, project_library, project_memory
from covey.core import projects, triage, turn_source
from covey.core.jobs import job_key
from covey.core.state import read_object, write_json
from covey.core.turn_words import RESULTS

from test_project_lead import CHAT, LEAD, LEAD_NAMES, NOW, PID, Case, ToolsCase, butler_topics_token
from test_project_loop import Loop
from test_project_triage import CHOICE, TOKEN, question

THREAD = "b" * 32
COLLAB = {turn_source.SWITCH: "1"}
# A 目标检查表 as project_checklist leaves it in the record (core/project_checklist.py): c1 not met, delivered by THREAD; c2 met
# while it needs c1.
CHECKLIST = {"items": [
    {"id": "c1", "criterion": "导出 2024 年账单", "topic": THREAD, "needs": [], "evidence": "", "gap": "", "state": "open",
     "at": NOW, "job": "lead-1"},
    {"id": "c2", "criterion": "对账一致", "topic": "", "needs": ["c1"], "evidence": "对账报告", "gap": "", "state": "done",
     "at": NOW, "job": "lead-1"}], "closed": {}, "next": "c3", "at": NOW, "job": "lead-1"}
TRIAGE = {triage.ENV: "1"}


def checklist():
    """core/project_checklist.py, imported where a test uses it (scripts/test_map.py prove runs this module on the code
    before it, where the other tests fail on what they check, not on an import)."""
    from covey.core import project_checklist
    return project_checklist


def label_of(state, topic) -> str:
    return "T" + str(json.loads((Path(state) / "topics" / topic / "topic.json").read_text())["topic_number"])


class ChecklistTest(unittest.TestCase):
    """core/project_checklist.py on a record of its own: what an item is, what a change may do, the gaps, what is not met."""

    def setUp(self):
        self.pc = checklist()

    def test_items_get_ids_in_order_and_a_change_replaces_only_what_it_names(self):
        record = {"id": PID}
        touched = self.pc.apply(record, [{"criterion": "导出 2024 年账单"}, {"criterion": "对账一致", "needs": ["c1"]}],
                                          job="j1", now=NOW)
        self.assertEqual(touched, ["c1", "c2"])
        self.assertEqual([(item["id"], item["state"], item["needs"], item["job"]) for item in self.pc.items(record)],
                         [("c1", "open", [], "j1"), ("c2", "open", ["c1"], "j1")])
        self.pc.apply(record, [{"id": "c1", "state": "done", "evidence": "提交 abc123"}], job="j2", now=NOW + 1)
        first, second = self.pc.items(record)
        self.assertEqual((first["state"], first["evidence"], first["criterion"], first["job"], second["state"]),
                         ("done", "提交 abc123", "导出 2024 年账单", "j2", "open"))
        self.assertEqual(record["checklist"]["next"], "c3")
        self.assertTrue(self.pc.kept(record))
        self.assertFalse(self.pc.kept({"id": PID}))

    def test_what_does_not_fit_is_refused_and_nothing_changes(self):
        record = {"id": PID}
        self.pc.apply(record, [{"criterion": "导出"}], now=NOW)
        before = copy.deepcopy(record)
        for rows, words in (([{"id": "c1", "state": "done"}], "要写 evidence"),
                            ([{"id": "c1", "state": "blocked"}], "要写卡在哪"),
                            ([{"id": "c1", "state": "dropped"}], "为什么不做了"),
                            ([{"id": "c9", "gap": "x"}], "没有条目 c9"),
                            ([{"criterion": "对账", "needs": ["c7"]}], "c7 不在检查表里"),
                            ([{"id": "c1", "needs": ["c1"]}], "不能依赖自己"),
                            ([{"gap": "没写标准"}], "要写 criterion"),
                            ([{"id": "c1", "state": "finished"}], "state 要是"),
                            ([{"criterion": f"第 {n} 条"} for n in range(self.pc.MAX_ITEMS)], "最多 20 条"),
                            ([{"criterion": "好的一条"}, {"id": "c1", "state": "done"}], "要写 evidence")):
            with self.subTest(words=words), self.assertRaisesRegex(ValueError, words):
                self.pc.apply(record, rows, now=NOW + 1)
            self.assertEqual(record, before)  # The good row of a refused call is not written either.

    def test_a_gap_is_a_collab_gap_receipt_until_it_is_closed_with_how(self):
        receipts = [{"id": "0001-aa", "kind": collab.RECEIPT_GAP, "thread": THREAD, "text": "缺原版基线数据", "at": NOW},
                    {"id": "0002-bb", "kind": "thread_end", "text": "T41 做完了", "at": NOW},
                    {"id": "0003-cc", "kind": collab.RECEIPT_GAP, "thread": THREAD, "text": "两份结果冲突", "at": NOW + 1}]
        record = {"id": PID}
        gaps = self.pc.gaps(record, receipts)
        self.assertEqual([gap["text"] for gap in gaps], ["缺原版基线数据", "两份结果冲突"])
        gap = gaps[0]["id"]
        self.assertRegex(gap, r"^g[0-9a-f]{6}$")
        self.assertEqual(gap, self.pc.gap_id("0001-aa"))
        with self.assertRaisesRegex(ValueError, "要写 how"):
            self.pc.apply(record, close=[{"gap": gap}], receipts=receipts, now=NOW)
        with self.assertRaisesRegex(ValueError, "没有没处理的缺口 g000000"):
            self.pc.apply(record, close=[{"gap": "g000000", "how": "补了"}], receipts=receipts, now=NOW)
        self.assertEqual(self.pc.apply(record, close=[{"gap": gap, "how": "T7 补了基线，提交 d4e5"}], receipts=receipts,
                                                 now=NOW), [gap])
        self.assertEqual([row["text"] for row in self.pc.gaps(record, receipts)], ["两份结果冲突"])
        self.assertEqual(record["checklist"]["closed"][gap]["how"], "T7 补了基线，提交 d4e5")
        items, left = self.pc.unmet(record, receipts)
        self.assertEqual((items, [row["id"] for row in left]), ([], [self.pc.gap_id("0003-cc")]))

    def test_an_item_met_while_what_it_needs_is_not_is_a_conflict_and_what_is_not_met_is_listed(self):
        record = {"id": PID}
        self.pc.apply(record, [{"criterion": "原版基线"},
                                         {"criterion": "对比报告", "needs": ["c1"], "state": "done", "evidence": "报告"},
                                         {"criterion": "旧格式", "state": "dropped", "gap": "主人说不要了"}], now=NOW)
        [(item, waiting)] = self.pc.conflicts(record)
        self.assertEqual((item["id"], waiting), ("c2", ["c1"]))
        self.assertEqual([row["id"] for row in self.pc.unmet(record, [])[0]], ["c1"])  # dropped counts as met.

    def test_a_record_without_one_or_with_bad_rows_reads_what_it_can(self):
        self.assertEqual(self.pc.items({}), [])
        rows = [{"id": "x1", "criterion": "不是我们的 id"}, {"id": "c1"}, "c2", {"id": "c3", "criterion": "好", "state": "weird",
                                                                               "needs": ["c1", 7, "zz"]}]
        [item] = self.pc.items({"checklist": {"items": rows}})
        self.assertEqual((item["id"], item["state"], item["needs"]), ("c3", "open", ["c1"]))


class ChecklistToolTest(ToolsCase):
    """project_checklist and project_finish's gate as the lead calls them, 协作 on."""

    def setUp(self):
        super().setUp()
        mock.patch.dict(os.environ, COLLAB).start()
        self.addCleanup(mock.patch.stopall)

    def member(self, request, title):
        topic = self.tool("project_topic_start", request_id=request, title=title, prompt=title, workspace="project",
                          readonly=True, why="x")["data"]["topic_id"]
        return topic, label_of(self.state, topic)

    def ended(self, request, text="做完了"):
        write_job(self.state, "main-" + butler_topics_token(request), status="done", final_text=text)

    def test_two_topics_say_done_but_the_baseline_check_is_missing_so_the_finish_waits_until_it_is_met(self):
        """L1: both members claim done; the goal also asked for a check against the original baseline, which nobody did."""
        _, first = self.member("a", "导出新版结果")
        _, second = self.member("b", "跑新版对比")
        self.ended("a")
        self.ended("b")
        answer = self.tool("project_checklist", items=[
            {"criterion": "新版结果导出", "topic": first, "state": "done", "evidence": "/absolute/out.csv"},
            {"criterion": "新版对比报告", "topic": second, "state": "done", "evidence": "提交 abc123"},
            {"criterion": "和原版基线对照", "gap": "还没有话题做"}])
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["data"]["unmet"], ["c3"])
        self.assertIn("- c3 · 没满足 · 和原版基线对照 · 还没有话题 · 缺口：还没有话题做", answer["text"])
        refused = self.tool("project_finish", summary="两个话题都做完了")
        self.assertFalse(refused["ok"])
        self.assertEqual((refused["data"]["gate"], refused["data"]["unmet"], refused["data"]["gaps"]), ("checklist", ["c3"], []))
        for words in ("c3「和原版基线对照」没满足", "project_topic_send 让原话题返工", "project_topic_start 开新话题"):
            self.assertIn(words, refused["text"])
        self.assertEqual(self.reload()["state"], projects.ACTIVE)
        # The lead arranges it: a topic for the baseline, named on the item.
        _, third = self.member("c", "跑原版基线")
        self.assertTrue(self.tool("project_checklist", items=[{"id": "c3", "topic": third, "gap": f"{third} 在跑"}])["ok"])
        self.ended("c", "基线跑完了")
        pack = project_lead.state_pack(self.state, self.reload(), "lead-job", full=False, receipts=[])
        self.assertIn(f"⚠️ {third} 已经结束（{RESULTS['done']}），它交付的 c3 还没满足", pack)  # Its claim, to check.
        self.assertFalse(self.tool("project_finish", summary="都做完了")["ok"])  # Ended is not met.
        self.assertTrue(self.tool("project_checklist", items=[{"id": "c3", "state": "done", "evidence": "/absolute/base.md"}])["ok"])
        done = self.tool("project_finish", summary="新版对比做完，含原版基线对照")
        self.assertTrue(done["ok"], done)
        self.assertEqual(self.reload()["state"], projects.DONE)

    def test_an_item_not_met_in_the_record_holds_the_finish(self):
        projects.update(self.state, PID, lambda record: record.update(checklist=CHECKLIST))
        refused = self.tool("project_finish", summary="做完了")
        self.assertFalse(refused["ok"], refused)
        self.assertEqual(refused["data"]["unmet"], ["c1"])  # c2 is met (its own need not being so is the pack's warning).
        self.assertEqual(self.reload()["state"], projects.ACTIVE)

    def test_a_collab_gap_holds_the_finish_until_the_lead_says_how_it_was_dealt_with(self):
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_GAP, "T3 协作里补不上的缺口：缺原版基线数据", thread=THREAD)
        project_lead.take_receipts(self.state, PID, "lead-job")  # Read already: still not dealt with.
        refused = self.tool("project_finish", summary="做完了")
        self.assertFalse(refused["ok"])
        [gap] = refused["data"]["gaps"]
        self.assertIn("协作里还有没处理的缺口", refused["text"])
        self.assertIn("缺原版基线数据", refused["text"])
        pack = project_lead.state_pack(self.state, self.reload(), "lead-job", full=False, receipts=[])
        self.assertIn(project_lead.GAPS_HEAD, pack)
        self.assertIn(f"- {gap} · ", pack)
        self.assertIn("要写 how", self.refused("project_checklist", close_gaps=[{"gap": gap}]))
        closed = self.tool("project_checklist", close_gaps=[{"gap": gap, "how": "主人说这次不用补"}])
        self.assertTrue(closed["ok"], closed)
        self.assertEqual(closed["data"]["gaps"], [])
        self.assertTrue(self.tool("project_finish", summary="做完了")["ok"])

    def test_the_topic_of_an_item_is_one_of_the_projects_and_reading_changes_nothing(self):
        outside = "a" * 32  # An ordinary topic of the owner's, in no project.
        write_topic(self.state, {"topic_id": outside}, topic_id=outside, chat_id=CHAT, harness_id="claude", topic_number=88,
                    root_id="om_root88")
        refused = self.tool("project_checklist", items=[{"criterion": "导出", "topic": "T88"}])
        self.assertFalse(refused["ok"])
        self.assertIn("不是这个专项的话题", refused["text"])
        self.assertNotIn("checklist", self.reload())
        self.assertIn("没有找到话题 T999", self.tool("project_checklist", items=[{"criterion": "导出", "topic": "T999"}])["text"])
        before = self.reload()
        shown = self.tool("project_checklist")
        self.assertTrue(shown["ok"])
        self.assertIn(project_lead.CHECKLIST_EMPTY, shown["text"])
        self.assertEqual(self.reload(), before)

    def test_a_refused_change_writes_nothing_and_says_why(self):
        self.tool("project_checklist", items=[{"criterion": "导出"}])
        before = self.reload()
        answer = self.tool("project_checklist", items=[{"criterion": "对账"}, {"id": "c1", "state": "done"}])
        self.assertFalse(answer["ok"])
        self.assertIn("目标检查表没有改：c1 标 done 要写 evidence", answer["text"])
        self.assertEqual(self.reload()["checklist"], before["checklist"])

    def test_what_the_owner_let_go_is_named_when_the_project_is_finished(self):
        self.tool("project_checklist", items=[{"criterion": "导出", "state": "done", "evidence": "/absolute/x.csv"},
                                              {"criterion": "原版基线", "state": "dropped", "gap": "主人说这次不做"}])
        done = self.tool("project_finish", summary="导出做完")
        self.assertTrue(done["ok"], done)
        self.assertIn("主人说不做的：c2「原版基线」（主人说这次不做）", done["text"])

    def test_a_finished_project_cannot_have_its_checklist_changed_but_it_can_be_read(self):
        self.assertTrue(self.tool("project_finish", summary="做完")["ok"])
        self.assertIn("不能改目标检查表", self.refused("project_checklist", items=[{"criterion": "x"}]))
        self.assertTrue(self.tool("project_checklist")["ok"])

    def test_off_there_is_no_checklist_and_the_finish_is_as_it_was(self):
        os.environ.pop(turn_source.SWITCH)
        off = self.tool("project_checklist", items=[{"criterion": "导出"}])
        self.assertFalse(off["ok"])
        self.assertIn("协作没有开", off["text"])
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_GAP, "缺口", thread=THREAD)
        projects.update(self.state, PID, lambda record: record.update(
            checklist={"items": [{"id": "c1", "criterion": "导出", "state": "open"},
                                 {"id": "c2", "criterion": "基线", "state": "dropped", "gap": "不做"}]}))
        done = self.tool("project_finish", summary="账单迁完")
        self.assertTrue(done["ok"], done)
        self.assertEqual(done["text"], "专项已记为完成：账单迁完")


class PackTest(Case):
    """What the lead's rules and pack say, 协作 on and off."""

    def receipts(self):
        made = [project_lead.add_receipt(self.state, PID, kind, text, thread=THREAD, at=NOW + n) for n, (kind, text) in enumerate((
            ("thread_end", "T41 的任务 #41 做完：导出好了"),
            (collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：一"),
            (collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：二"),
            ("stalled", "专项还有要做的事"),
            (collab.RECEIPT_ANSWERED, "T41 请 T56 协助：已答复：三"),
            (collab.RECEIPT_GAP, "T41 协作里补不上的缺口：缺原版基线"),
            (collab.RECEIPT_ANSWERED, "T41 请 T57 协助：未接手：在等主人回答"),
            ("start", "接手一个已在进行的事")))]
        return made

    def world(self):
        self.thread(THREAD, "导出旧账单", 41, status="done", final_text="做完了")
        entry, _ = project_memory.add(self.state, PID, "先迁 2024 年", "decision", "lead")
        projects.update(self.state, PID, lambda record: record.update(checklist=CHECKLIST))
        write_job(self.state, "om_own1", topic_id=LEAD, chat_id=CHAT, job_id=7, message_id="om_own1", status="done",
                  user_text="先迁 2024 年的，其余下周再说")
        write_job(self.state, f"lead-{PID}-1", topic_id=LEAD, chat_id=CHAT, job_id=8, message_id=f"lead-{PID}-1", status="done",
                  user_text=project_loop.WAKE_TEXT)
        return entry, self.receipts()

    def test_off_the_rules_and_the_pack_are_as_they_were(self):
        _, receipts = self.world()
        record = self.reload()
        pack = project_lead.state_pack(self.state, record, "lead-1", full=True, receipts=receipts)
        rules = project_lead.lead_rules()
        with mock.patch.dict(os.environ, {turn_source.SWITCH: "0"}):
            self.assertEqual(project_lead.state_pack(self.state, record, "lead-1", full=True, receipts=receipts), pack)
            self.assertEqual(project_lead.lead_rules(), rules)
        with mock.patch.dict(os.environ, TRIAGE):
            triaged = project_lead.state_pack(self.state, record, "lead-1", full=True, receipts=receipts)
        for words in ("目标检查表", "〔", "先看：", "没处理的协作缺口", "主人在专项里说过的话", "msg:"):
            self.assertNotIn(words, pack)
            self.assertNotIn(words, triaged)
        self.assertIn("自上次唤醒以来的收件箱：\n" + "\n".join(map(project_lead.receipt_line, receipts)), pack)
        for words in ("project_checklist", "目标检查表", "evidence", "collab_answered"):
            self.assertNotIn(words, rules)

    def test_on_the_pack_shows_the_checklist_the_gaps_the_ids_the_owners_words_and_the_inbox_in_groups(self):
        mock.patch.dict(os.environ, {**COLLAB, **TRIAGE}).start()
        self.addCleanup(mock.patch.stopall)
        entry, receipts = self.world()
        pack = project_lead.state_pack(self.state, self.reload(), "lead-1", full=True, receipts=receipts)
        self.assertIn("目标检查表（2 条：1 条满足或不做了，1 条没满足）：", pack)
        self.assertIn(f"- c1 · 没满足 · 导出 2024 年账单 · T41（{RESULTS['done']}）", pack)
        self.assertIn("- c2 · 满足 · 对账一致 · 还没有话题 · 依赖 c1（没满足） · 证据：对账报告", pack)
        self.assertIn("⚠️ c2 标了满足，但它依赖的 c1 还没满足", pack)
        self.assertIn(f"⚠️ T41 已经结束（{RESULTS['done']}），它交付的 c1 还没满足", pack)
        self.assertIn(project_lead.GAPS_HEAD, pack)
        self.assertIn(f"〔{entry['id']}〕先迁 2024 年", pack)
        self.assertIn(project_lead.OWNER_WORDS_HEAD + "\n- msg:om_own1 · ", pack)
        self.assertIn("先迁 2024 年的，其余下周再说", pack)
        self.assertNotIn(f"msg:lead-{PID}-1", pack)  # A wake-up is no word of the owner's.
        inbox = pack[pack.index("自上次唤醒以来的收件箱："):]
        heads = ["先看：", "话题的交付和结束（1 条", "其他：", "协作咨询的回执（4 条"]
        self.assertEqual([inbox.index(head) for head in heads], sorted(inbox.index(head) for head in heads))
        first = inbox[inbox.index("先看："):inbox.index("话题的交付和结束")]
        self.assertIn("- ⚠️ ", first)
        self.assertIn("collab_gap（T41）", first)
        self.assertIn("start（T41）", first)
        self.assertIn("（它交付的 c1 还没满足）", inbox)
        self.assertIn("另有 1 条更早的", inbox)
        self.assertNotIn("已答复：一", inbox)  # Folded: the newest three are shown.
        self.assertIn("未接手：在等主人回答", inbox)
        rules = project_lead.lead_rules()
        for words in ("project_checklist", "collab_gap", "不要把话题或汇总方的结论换个说法再发一遍", "project_answer 必须写 evidence"):
            self.assertIn(words, rules)
        consult = project_lead.read_only_pack(self.state, self.reload())
        self.assertIn("目标检查表（2 条", consult)
        self.assertIn(project_lead.GAPS_HEAD, consult)

    def test_without_the_triage_the_owners_words_are_not_listed_and_the_rules_ask_no_evidence(self):
        mock.patch.dict(os.environ, COLLAB).start()
        self.addCleanup(mock.patch.stopall)
        _, receipts = self.world()
        pack = project_lead.state_pack(self.state, self.reload(), "lead-1", full=True, receipts=receipts)
        self.assertNotIn("主人在专项里说过的话", pack)
        self.assertIn("目标检查表（2 条", pack)
        self.assertNotIn("project_answer 必须写 evidence", project_lead.lead_rules())
        self.assertIn("project_checklist", project_lead.lead_rules())

    def test_the_new_words_retire_nothing_the_owner_retired(self):
        from test_glossary import RETIRED, strings
        mock.patch.dict(os.environ, {**COLLAB, **TRIAGE}).start()
        self.addCleanup(mock.patch.stopall)
        texts = [*project_lead.COLLAB_RULES, project_lead.EVIDENCE_RULE, project_lead.CHECKLIST_EMPTY, project_lead.GAPS_HEAD,
                 project_lead.OWNER_WORDS_HEAD, project_loop.CHOICE_CHECKLIST,
                 *strings(butler_tool_specs.lead_tools({**COLLAB, **TRIAGE}))]
        self.assertEqual([text[:40] for text in texts if RETIRED.search(text)], [])


class BatchTest(Loop):
    """L2: what wakes the lead, 协作 on (COVEY_PROJECT_AUTOWAKE=1, so every ordinary receipt may)."""

    def setUp(self):
        super().setUp()
        self.autowake()
        mock.patch.dict(os.environ, COLLAB).start()

    def reset(self):
        shutil.rmtree(project_lead.inbox_dir(self.state, PID), ignore_errors=True)
        self.queued.clear()

    def test_topics_that_end_together_wake_the_lead_once(self):
        self.receipt(at=NOW)
        self.receipt(text="T42 做完了", at=NOW + 5)
        self.loop.tick(NOW + 10)
        self.assertEqual(self.queued, [])
        self.loop.tick(NOW + 5 + 19)
        self.assertEqual(self.queued, [])
        self.loop.tick(NOW + 5 + 20)  # COVEY_PROJECT_BATCH_SECONDS unset: 20.
        self.assertEqual([message for message, _ in self.queued], [f"lead-{PID}-1"])
        self.assertEqual(len(project_lead.take_receipts(self.state, PID, f"lead-{PID}-1")), 2)  # One turn reads both.

    def test_a_steady_trickle_waits_no_longer_than_the_stretch(self):
        for n in range(6):  # One every 15 s: each comes within the 20 s window of the one before.
            self.receipt(text=f"T4{n} 做完了", at=NOW + 15 * n)
            self.loop.tick(NOW + 15 * n + 1)
        self.assertEqual(self.queued, [])
        self.loop.tick(NOW + 20 * 4)  # The newest came 5 s ago; the oldest waited four windows.
        self.assertEqual(len(self.queued), 1)

    def test_a_start_a_choice_a_question_or_a_gap_wakes_at_once(self):
        for kind in ("start", "owner_choice", "question", collab.RECEIPT_GAP):
            with self.subTest(kind=kind):
                self.reset()
                self.receipt(at=NOW)
                self.receipt(kind, "要看的", at=NOW)
                self.loop.tick(NOW + 1)
                self.assertEqual(len(self.queued), 1)

    def test_a_consults_receipt_wakes_nobody_and_does_not_hold_the_others_back(self):
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：好", thread=THREAD, at=NOW)
        self.loop.tick(NOW + 300)
        self.assertEqual(self.queued, [])
        self.receipt(at=NOW + 300)
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_ANSWERED, "T41 请 T56 协助：已答复：好", thread=THREAD, at=NOW + 315)
        self.loop.tick(NOW + 300 + 20)
        self.assertEqual(len(self.queued), 1)

    def test_the_window_can_be_set_and_zero_or_the_switch_off_wakes_at_the_next_look(self):
        for value, seconds in (("60", 60.0), ("0", 0.0), ("2.5", 2.5), ("x", 20.0), ("-1", 20.0), ("nan", 20.0), ("", 20.0)):
            with self.subTest(value=value), mock.patch.dict(os.environ, {project_loop.BATCH_ENV: value}):
                self.assertEqual(project_loop.batch_seconds(), seconds)
        for environ in ({project_loop.BATCH_ENV: "0"}, {turn_source.SWITCH: "0"}):
            with self.subTest(environ=environ), mock.patch.dict(os.environ, environ):
                self.reset()
                self.receipt(at=NOW)
                self.loop.tick(NOW + 1)
                self.assertEqual(len(self.queued), 1)
        with mock.patch.dict(os.environ, {turn_source.SWITCH: "0"}):
            self.assertEqual(project_loop.batch_seconds(), 0.0)


class RetellTest(Case):
    """L2: one result, told once, with consults in the inbox."""

    def wake_reported(self, kind="thread", acted=False):
        wake = f"lead-{PID}-1"
        project_lead.take_receipts(self.state, PID, wake)
        note = {"id": "n1", "at": NOW, "text": "T41 出了报告，T55 也确认了", "report": True, "kind": kind, "job": wake}
        projects.update(self.state, PID, lambda record: record.update(
            style={"report": "verbose"}, notes=[note], **({"acted": [{"job": wake, "what": "send", "at": NOW}]} if acted else {})))
        return project_loop.reported(self.state, LEAD, wake)

    def test_a_wake_that_read_a_result_the_owner_was_sent_and_a_consults_receipt_does_not_retell_them(self):
        project_lead.add_receipt(self.state, PID, "thread_end", "T41 的任务 #41 做完：报告写好了", thread=THREAD, relayed=True)
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：一致", thread=THREAD)
        self.assertFalse(self.wake_reported("thread"))
        self.assertTrue(project_loop.told_already(self.state, PID, f"lead-{PID}-1"))
        self.assertFalse(self.wake_reported("note"))
        self.assertTrue(self.wake_reported("milestone"))  # Its own judgment goes.
        self.assertTrue(self.wake_reported("thread", acted=True))  # Work handed out goes.

    def test_a_wake_that_read_only_consults_receipts_retells_none_of_them(self):
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：一致", thread=THREAD)
        self.assertFalse(self.wake_reported("thread"))

    def test_a_result_the_owner_was_not_sent_beside_a_consults_receipt_is_the_leads_to_tell(self):
        project_lead.add_receipt(self.state, PID, "thread_end", "T41 的任务 #41 做完：报告写好了", thread=THREAD)
        project_lead.add_receipt(self.state, PID, collab.RECEIPT_ANSWERED, "T41 请 T55 协助：已答复：一致", thread=THREAD)
        self.assertTrue(self.wake_reported("thread"))


class ConsultTokensTest(Case):
    """L2: a consult's turn spends its project's budget (package C's handoff 7.1)."""

    def setUp(self):
        super().setUp()
        self.thread(THREAD, "汇总", 41)
        self.outside = "f" * 32
        write_topic(self.state, topic_id=self.outside, chat_id=CHAT, harness_id="claude", topic_number=55)

    def consult(self, integrator, helper, collab_id="c0ffee12", status="done"):
        channel = collab.channel_id(collab_id, helper)
        ask = collab_records.new_ask(collab_id, to=helper, frm=integrator, number=1, text="基线是哪版？", channel=channel, now=NOW)
        record = collab_records.new_record(collab_id, CHAT, root={"message_id": "om_root", "job_key": "om_root", "job_id": 40,
                                                                  "topic": integrator},
                                           integrator=collab_records.participant(integrator, collab.TOPIC),
                                           helpers=[collab_records.participant(helper, collab.TOPIC)], goal_rev=40, source={}, now=NOW)
        collab_records.change(self.state, collab_id, lambda current: {**record, "asks": [ask]})
        write_topic(self.state, topic_id=channel, chat_id=CHAT, harness_id="claude",
                    collab_channel={"collab": collab_id, "helper": helper, "integrator": integrator})
        message = collab.ask_message(ask["id"])
        source = turn_source.make(turn_source.ASK, asserted_by=turn_source.PARTY_TOPIC, origin={"topic": integrator},
                                  collab=collab_id, ask=ask["id"])
        write_job(self.state, job_key(message, 77), topic_id=channel, chat_id=CHAT, job_id=77, message_id=message, status=status,
                  input_tokens=2000, output_tokens=100, turn_source=source, final_text="基线是 v1.8")
        return make_job(job_id=77, chat_id=CHAT, message_id=message, topic_id=channel)

    def after(self, job):
        project_loop.after_runner(self.logs.append, self.state, job)

    def test_a_consults_tokens_count_once_in_its_integrators_project_and_leave_no_receipt(self):
        job = self.consult(THREAD, self.outside)
        self.after(job)
        self.after(job)
        self.assertEqual(self.reload()["tokens_used"], 2100)
        self.assertEqual(project_loop.unread(self.state, PID), [])
        self.assertEqual(project_library.entries(self.state, PID), [])

    def test_an_integrator_in_no_project_charges_the_helpers(self):
        self.after(self.consult(self.outside, THREAD))
        self.assertEqual(self.reload()["tokens_used"], 2100)

    def test_neither_in_a_project_a_turn_not_ended_or_a_record_gone_counts_nothing(self):
        self.after(self.consult(self.outside, "e" * 32))
        self.assertNotIn("tokens_used", self.reload())
        self.after(self.consult(THREAD, self.outside, collab_id="c0ffee13", status="running"))
        self.assertNotIn("tokens_used", self.reload())
        job = self.consult(THREAD, self.outside, collab_id="c0ffee14")
        (self.state / "collab" / "c0ffee14.json").unlink()
        self.after(job)
        self.assertNotIn("tokens_used", self.reload())

    def test_the_budget_counts_them(self):
        with mock.patch.dict(os.environ, {projects.BUDGET_ENV: "2000"}):
            self.after(self.consult(THREAD, self.outside))
            self.assertEqual(project_loop.hold(self.reload(), NOW), "tokens")


class GroundsTest(ToolsCase):
    """M5: project_answer's grounds, 协作 and the triage on; a member topic's choice question held for the lead."""

    def setUp(self):
        super().setUp()
        mock.patch.dict(os.environ, {**COLLAB, **TRIAGE}).start()
        self.addCleanup(mock.patch.stopall)
        self.topic = self.tool("project_topic_start", request_id="m1", title="导出旧账单", prompt="把旧库账单导出", workspace="project",
                               readonly=True, why="脚本在这个仓库")["data"]["topic_id"]
        self.path = self.state / "questions" / (TOKEN + ".json")
        write_json(self.path, question(topic=self.topic, job_key="x-1"), ensure_ascii=False)
        flow.Triage(runtime=SimpleNamespace(log=print), cards=mock.Mock())._route(SimpleNamespace(state_dir=self.state),
                                                                                 read_object(self.path))
        self.label = label_of(self.state, self.topic)
        app = self.env.topics.target(self.state, self.topic, CHAT)[0]
        self.submit = mock.patch.object(app.questions, "submit_answer", side_effect=self.landed).start()

    def landed(self, ctx, chat, token, fields, event_id):
        path = self.state / "questions" / (token + ".json")
        write_json(path, {**read_object(path), "status": "answered", "answers": {"0": {"answers": ["旧版"]}}}, ensure_ascii=False)

    def hold(self, token):
        """Another choice question of the topic, held for the lead."""
        path = self.state / "questions" / (token + ".json")
        write_json(path, question(topic=self.topic, job_key="x-" + token[:4], token=token), ensure_ascii=False)
        flow.Triage(runtime=SimpleNamespace(log=print), cards=mock.Mock())._route(SimpleNamespace(state_dir=self.state),
                                                                                 read_object(path))
        return path

    def answer(self, evidence=None):
        args = {"thread": self.label, "answers": {"0": "旧版"}}
        if evidence is not None:
            args["evidence"] = evidence
        return self.tool("project_answer", **args)

    def owner_answer(self, token="d" * 16, text="主人答：用哪个库版本？→旧版") -> str:
        """A line of the owner's answer to an earlier question card: his, with its origin (level owner), a 当前决定."""
        record = {"token": token, "topic_id": self.topic, "job_id": 3, "questions": CHOICE, "answers": {"0": {"answers": ["旧版"]}}}
        [(entry, _)] = project_memory.note_answers(self.state, PID, record, [{"index": 1, "item": "0", "text": text}])
        return entry["id"]

    def meta(self, entry, **fields):
        project_memory._edit(self.state, PID, lambda rows, meta: meta.__setitem__(entry, {**meta.get(entry, {}), **fields}))

    def still_held(self):
        self.submit.assert_not_called()
        self.assertEqual(triage.state(read_object(self.path)), triage.HELD)

    def test_without_evidence_nothing_is_answered_and_the_question_stays_the_leads(self):
        answer = self.answer()
        self.assertFalse(answer["ok"])
        self.assertEqual(answer["data"]["refused"], "evidence")
        self.assertIn("要写 evidence", answer["text"])
        self.still_held()

    def test_the_leads_own_notes_alone_are_refused_and_it_is_told_to_escalate(self):
        lead, _ = project_memory.add(self.state, PID, "这个专项一律用旧版", "decision", "lead")
        answer = self.answer([lead["id"]])
        self.assertFalse(answer["ok"])
        for words in ("没有替主人答", "待核对参考", "project_escalate"):
            self.assertIn(words, answer["text"])
        self.still_held()

    def test_an_owners_older_line_with_no_origin_is_no_ground_alone(self):
        old, _ = project_memory.add(self.state, PID, "以后都用旧版", "constraint", "owner")  # No origin: level agent.
        answer = self.answer([old["id"]])
        self.assertFalse(answer["ok"])
        self.assertIn("无出处", answer["text"])
        self.still_held()

    def test_a_voided_done_superseded_once_only_or_made_up_line_is_refused(self):
        voided, done, superseded, once, good = (self.owner_answer(token * 16) for token in "12345")
        project_memory.delete(self.state, PID, voided)
        self.meta(done, valid="done")
        self.meta(superseded, valid="superseded", superseded_by=good)
        project_memory.fix(self.state, PID, once, "once", origin={"message_id": "om_fix1"})
        for evidence, words in (([voided], "已作废"), ([done], "进了历史记录"), ([superseded], "进了历史记录"),
                                ([once], "只限当次"), (["0123456789abcdef-9"], "不在这个专项的记忆里"),
                                ([good, "0123456789abcdef-9"], "不在这个专项的记忆里"), ([good, voided], "已作废")):
            with self.subTest(evidence=evidence):
                answer = self.answer(evidence)
                self.assertFalse(answer["ok"])
                self.assertIn(words, answer["text"])
                self.assertIn("project_escalate", answer["text"])
                self.still_held()

    def test_the_owners_line_that_holds_answers_and_the_grounds_are_on_the_answer_and_its_row(self):
        owner = self.owner_answer()
        lead, _ = project_memory.add(self.state, PID, "旧版兼容现有脚本", "fact", "lead")
        answer = self.answer([f"〔{owner}〕", lead["id"]])  # Copied from the pack with its brackets.
        self.assertTrue(answer["ok"], answer)
        note = self.submit.call_args.args[3]["supplement"]
        self.assertTrue(note.startswith("（负责人替主人答的，依据："), note)
        self.assertIn(f"{owner} 你说的·当前决定「主人答：用哪个库版本？→旧版」", note)
        self.assertIn(f"{lead['id']} 它总结的·待核对参考", note)
        row = self.reload()["triage"][-1]
        self.assertTrue(row["text"].startswith("答了（依据 你说的·当前决定、它总结的·待核对参考）："), row["text"])
        self.assertEqual([(item["ref"], item["level"]) for item in row["evidence"]],
                         [(owner, turn_source.LEVEL_OWNER), (lead["id"], turn_source.LEVEL_AGENT)])
        self.assertEqual(project_facts.triage_lines(self.reload())[0][1], TOKEN)  # The 不对 button as before.
        # A 长期约定 of the owner's (his own words, the message they came in kept as its origin) answers alone.
        rule, _ = project_memory.add(self.state, PID, "以后版本都选旧版，兼容现有脚本", "constraint", "owner",
                                     origin={"message_id": "om_rule1"})
        second = self.hold("e" * 16)
        answer = self.answer([rule["id"]])
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(triage.state(read_object(second)), triage.ANSWERED)
        self.assertIn(f"{rule['id']} 你说的·长期约定「以后版本都选旧版", self.submit.call_args.args[3]["supplement"])
        self.assertTrue(self.reload()["triage"][-1]["text"].startswith("答了（依据 你说的·长期约定）："))

    def test_the_owners_own_message_in_the_project_is_a_ground(self):
        write_job(self.state, "om_said1", topic_id=LEAD, chat_id=CHAT, job_id=9, message_id="om_said1", status="done",
                  user_text="这一批都用旧版")
        for message, why in ((f"lead-{PID}-3", "a wake-up"), ("om_other", "another topic's"), ("om_them", "someone else's")):
            topic = self.outside_topic() if why == "another topic's" else LEAD
            write_job(self.state, message, topic_id=topic, chat_id=CHAT, job_id=10, message_id=message, status="done",
                      user_text="用旧版", **({"sender_id": "ou_someone_else"} if why == "someone else's" else {}))
            with self.subTest(why=why):
                answer = self.answer([f"msg:{message}"])
                self.assertFalse(answer["ok"], answer)
                self.assertIn("不是主人在这个专项里说的话", answer["text"])
                self.still_held()
        answer = self.answer(["msg:om_said1"])
        self.assertTrue(answer["ok"], answer)
        self.assertIn("msg:om_said1 主人原话「这一批都用旧版」", self.submit.call_args.args[3]["supplement"])
        self.assertTrue(self.reload()["triage"][-1]["text"].startswith("答了（依据 主人原话）："))

    def outside_topic(self):
        topic = "a" * 32
        write_topic(self.state, {"topic_id": topic}, topic_id=topic, chat_id=CHAT, harness_id="claude", topic_number=77)
        return topic

    def test_off_and_without_evidence_the_answer_is_as_before(self):
        os.environ.pop(turn_source.SWITCH)
        answer = self.answer()
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(self.submit.call_args.args[3]["supplement"], flow.NOTE)
        row = self.reload()["triage"][-1]
        self.assertTrue(row["text"].startswith("答了：" + self.label), row["text"])
        self.assertNotIn("evidence", row)

    def test_off_evidence_given_is_still_checked(self):
        os.environ.pop(turn_source.SWITCH)
        answer = self.answer(["0123456789abcdef-9"])
        self.assertFalse(answer["ok"])
        self.assertIn("不在这个专项的记忆里", answer["text"])
        self.still_held()


class ListingTest(Case):
    """What the lead's MCP server lists, 协作 on and off."""

    def test_off_the_leads_tools_are_as_they_were(self):
        self.assertEqual([tool["name"] for tool in butler_tool_specs.lead_tools({})], LEAD_NAMES)
        self.assertEqual(butler_tool_specs.lead_tools({**TRIAGE})[-2:], butler_tool_specs.TRIAGE_TOOLS)
        self.assertEqual(butler_tool_specs.lead_tools({turn_source.SWITCH: "0", **TRIAGE}), butler_tool_specs.lead_tools(TRIAGE))
        self.assertNotIn("project_checklist", [tool["name"] for tool in butler_mcp.tool_list({butler.LEAD_ENV: PID})])

    def test_on_the_lead_has_project_checklist_and_project_answer_asks_for_evidence(self):
        tools = butler_tool_specs.lead_tools({**COLLAB, **TRIAGE})
        self.assertEqual([tool["name"] for tool in tools], [*LEAD_NAMES, "project_checklist", "project_answer", "project_escalate"])
        answer = next(tool for tool in tools if tool["name"] == "project_answer")
        self.assertEqual(answer["input_schema"]["required"], ["thread", "answers", "evidence"])
        self.assertIn("evidence", answer["input_schema"]["properties"])
        self.assertIn(butler_tool_specs.EVIDENCE_NOTE, answer["description"])
        self.assertNotIn("evidence", butler_tool_specs.TRIAGE_TOOLS[0]["input_schema"]["properties"])  # Not changed in place.
        self.assertEqual([tool["name"] for tool in butler_tool_specs.lead_tools(COLLAB)], [*LEAD_NAMES, "project_checklist"])
        listed = [tool["name"] for tool in butler_mcp.tool_list({butler.LEAD_ENV: PID, **COLLAB})]
        self.assertIn("project_checklist", listed)
        self.assertNotIn("project_checklist", [tool["name"] for tool in butler_tool_specs.listed({**COLLAB, projects.ENV: "1"})])

    def test_a_call_to_project_checklist_on_a_server_without_the_switch_is_refused(self):
        server = butler_mcp.Server({butler.STATE_ENV: str(self.state), butler.JOB_ENV: "k", butler.LEAD_ENV: PID},
                                   submit=mock.Mock())
        answer = server.call({"name": "project_checklist", "arguments": {}})
        self.assertTrue(answer["isError"])
        self.assertIn("没有开 project_checklist", answer["content"][0]["text"])
        server.submit.assert_not_called()

    def test_the_leads_server_is_handed_the_switch_and_the_butlers_is_not(self):
        with mock.patch.dict(os.environ, COLLAB):
            lead = butler.mcp_config(Path("/r"), self.state, "k", sys.executable, lead=PID)
            plain = butler.mcp_config(Path("/r"), self.state, "k", sys.executable)
        self.assertEqual(lead["mcpServers"][butler.MCP_SERVER]["env"][turn_source.SWITCH], "1")
        self.assertNotIn(turn_source.SWITCH, plain["mcpServers"][butler.MCP_SERVER]["env"])
        off = butler.mcp_config(Path("/r"), self.state, "k", sys.executable, lead=PID)
        self.assertNotIn(turn_source.SWITCH, off["mcpServers"][butler.MCP_SERVER]["env"])


if __name__ == "__main__":
    unittest.main()
