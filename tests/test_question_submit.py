"""提交回答, the question form's one way to send (T631): what was picked or written and 补充说明 together. With 补充说明
written, a question left unanswered is 不回答此题, so a 补充说明 alone skips every question (the old 只发补充说明 and 先问一句);
beside it only 不处理, a bordered button. 以后这类按推荐走 was taken out (app/answers.py with_note, cards/question_cards.py
_send_row)."""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from support.cards import text_of, walk_dicts
from support.world import TopicFixture

from covey.app.answers import NOTE_EMPTY, SKIPPED, UNANSWERED_NOTE, given, with_note
from covey.app.card_actions import ACTIONS, moved_card_text
from covey.cards.question_cards import (ASK_KIND, SET_ASIDE_KIND, SET_ASIDE_LABEL, SKIP_ALL_KIND, SUBMIT_LABEL, how_to_answer,
                                        question_card, question_element)
from covey.core.jobs import find_job_record, upsert_job_record

WORDS = "B 是什么意思？会动线上吗"
GONE = ("只发补充说明", "先问一句", "以后这类按推荐走")


def checkpoint_question(**fields):
    """A checkpoint's question of task #5 in topic ``t``*64, as the golden samples draw it."""
    return {"token": "c" * 16, "job_id": 5, "topic_id": "t" * 64, "chat_id": "oc_chat", "status": "pending",
            "blocking": True, "request_id": "checkpoint-om_ask", "created_at": 1,
            "questions": [{"id": "fmt", "header": "格式", "question": "用哪种格式输出？",
                           "options": [{"label": "表格"}, {"label": "列表"}]},
                          {"id": "note", "header": "补充", "question": "还有别的要求吗？"}], **fields}


def send_row(form):
    """The form's buttons that are no option (cards/question_cards.py _send_row): 提交回答, then 不处理 when offered."""
    return [e for e in walk_dicts(form) if e.get("tag") == "button" and not str(e.get("name") or "").startswith("pick_")]


class SendRowTest(unittest.TestCase):
    def test_an_open_form_has_submit_and_set_aside_side_by_side(self):
        for name, record in {"several questions": checkpoint_question(),
                             "one with option buttons": checkpoint_question(questions=checkpoint_question()["questions"][:1])}.items():
            with self.subTest(name):
                form = question_element(record)
                submit, aside = send_row(form)
                self.assertEqual((submit["text"]["content"], submit["type"], submit["form_action_type"], submit["name"]),
                                 (SUBMIT_LABEL, "primary_filled", "submit", "submit"))
                # 不处理 is a button like 提交回答 (it was a borderless text button), as wide, and sends no field.
                self.assertEqual((aside["text"]["content"], aside["type"], aside["width"], aside["name"]),
                                 (SET_ASIDE_LABEL, "default", "fill", "set_aside"))
                self.assertNotIn("form_action_type", aside)
                self.assertEqual(aside["behaviors"][0]["value"], {"kind": SET_ASIDE_KIND, "topic_id": "t" * 64, "token": "c" * 16})
                [row] = [e for e in form["elements"] if e.get("tag") == "column_set" and e.get("flex_mode") == "none"]
                self.assertEqual([c["weight"] for c in row["columns"]], [1, 1])
                for word in GONE:
                    self.assertNotIn(word, text_of(question_card(record, "T70")))

    def test_submit_alone_where_set_aside_is_not_offered(self):
        from covey.core import butler
        for name, record in {"Claude's own question": checkpoint_question(native_live_question=True),
                             "Codex's paused question": checkpoint_question(native_paused_question=True)}.items():
            with self.subTest(name):
                form = question_element(record)
                [submit] = send_row(form)
                self.assertEqual((submit["text"]["content"], submit["width"]), (SUBMIT_LABEL, "fill"))
                self.assertIn(submit, form["elements"])  # Not in a row of its own.
        with mock.patch.object(butler, "is_butler_topic", return_value=True):
            self.assertEqual([b["name"] for b in send_row(question_element(checkpoint_question()))], ["submit"])

    def test_how_to_answer_says_a_supplement_alone_skips_the_questions(self):
        several = how_to_answer(checkpoint_question())
        self.assertIn("写了补充说明，没答的题记为不回答此题，不表示同意", several)
        self.assertIn("没写补充说明时，每题都处理后才能提交，提交了任务才继续。", several)
        single = how_to_answer(checkpoint_question(questions=checkpoint_question()["questions"][:1]))
        self.assertIn(f"有疑问）：只写“补充说明”，点“{SUBMIT_LABEL}”", single)
        for word in GONE[:2]:
            self.assertNotIn(f"“{word}”", several + single)

    def test_no_standing_button_whatever_the_old_switch_says(self):
        record = checkpoint_question(questions=[{"id": "go", "question": "合并吗？", "options": [
            {"label": "合并（推荐）"}, {"label": "先不合并"}]}])
        with mock.patch.dict(os.environ, {"COVEY_STANDING_ANSWERS": "1", "LARK_BRIDGE_STANDING_ANSWERS": "1"}):
            card = question_card(record, "T70")
        self.assertNotIn("以后这类按推荐走", text_of(card))
        self.assertNotIn("bridge_question_standing", json.dumps(card))


class WithNoteTest(unittest.TestCase):
    QUESTIONS = checkpoint_question()["questions"]

    def test_a_supplement_skips_what_was_left_unanswered(self):
        self.assertEqual(with_note(self.QUESTIONS, {"supplement": WORDS}),
                         {"supplement": WORDS, "skip_0": True, "skip_1": True})
        self.assertEqual(with_note(self.QUESTIONS, {"supplement": WORDS, "option_0": "1"}),
                         {"supplement": WORDS, "option_0": "1", "skip_1": True})
        both = {"supplement": WORDS, "option_0": "0", "answer_1": "没有"}
        self.assertEqual(with_note(self.QUESTIONS, both), both)

    def test_without_one_the_fields_are_left_for_form_answers_to_ask_for_every_question(self):
        for fields in ({"option_0": "0"}, {}, {"supplement": "  "}, {"option_0": "", "answer_1": " "}):
            with self.subTest(fields):
                self.assertEqual(with_note(self.QUESTIONS, fields), fields)

    def test_what_counts_as_given(self):
        for fields in ({"answer_0": "写的"}, {"option_0": "0"}, {"option_0": ["1"]}, {"option_0": "skip"}, {"skip_0": True},
                       {"skip_0": "true"}):
            with self.subTest(fields):
                self.assertTrue(given(fields, 0))
        for fields in ({}, {"answer_0": " "}, {"option_0": ""}, {"option_0": []}, {"skip_0": False}, {"answer_1": "别的题"}):
            with self.subTest(fields):
                self.assertFalse(given(fields, 0))


class SubmitTest(TopicFixture, unittest.TestCase):
    """A checkpoint's question whose turn ended (task #N waiting_user), answered from its card."""

    def setUp(self):
        super().setUp()
        self.receive("om_ask", "整理数据")
        self.asking = self.app.runtime.jobs.queue.get_nowait()
        self.app.runtime.jobs.unregister(self.asking)  # Its turn ended: it waits for the answer, no task runs.
        self.ctx_topic = self.topic("om_ask")
        checkpoint = self.root / "asking-checkpoint.json"
        checkpoint.write_text(json.dumps({"phase": "等你定格式", "requires_user": True}, ensure_ascii=False))
        upsert_job_record(self.ctx_topic.state_dir, self.asking.message_id, status="waiting_user",
                          checkpoint_path=str(checkpoint), job_id=self.asking.job_id,
                          topic_id=self.asking.topic_id, chat_id="oc_chat", backend="claude")
        self.record = checkpoint_question(job_id=self.asking.job_id, topic_id=self.asking.topic_id,
                                          question_message_id="om_qcard", card_id="card_q")
        self.path = self.ctx_topic.state_dir / "questions" / (self.record["token"] + ".json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.record, ensure_ascii=False))
        self.app.questions.paint_question_state = mock.Mock()
        self.app.questions.show_answer_notice = mock.Mock()
        self.app.cards.repaint_browse_card = mock.Mock(return_value=True)

    def click(self, form, kind="bridge_question", event="ev-submit", message="om_qcard"):
        return self.app.interaction.interaction_action(self.ctx_topic, {
            "chat_id": "oc_chat", "event_id": event, "message_id": message, "operator_id": "ou_user",
            "action_value": {"kind": kind, "topic_id": self.record["topic_id"], "token": self.record["token"]},
            "form_value": form})

    def follow_up(self):
        return [job for job in self.app.runtime.jobs.queue.queue if job.message_id == "answer-" + self.record["token"]]

    def saved(self):
        return json.loads(self.path.read_text())

    def test_a_supplement_alone_is_sent_with_every_question_skipped(self):
        self.click({"supplement": WORDS})
        [job] = self.follow_up()
        saved = self.saved()
        self.assertEqual((saved["status"], saved["supplement"]), ("answered", WORDS))
        self.assertEqual(saved["answers"], {"fmt": {"answers": [SKIPPED]}, "note": {"answers": [SKIPPED]}})
        # The model reads it as feedback, a question or a new request about the questions, not as consent.
        self.assertIn("用户" + UNANSWERED_NOTE + "\n" + WORDS, job.prompt_text)
        self.assertIn("是疑问就先解释", UNANSWERED_NOTE)
        self.assertEqual(job.title, "补充：" + WORDS[:27] if len(WORDS) > 27 else "补充：" + WORDS)
        asking = find_job_record(self.ctx_topic.state_dir, self.asking.message_id)
        self.assertEqual((asking["status"], asking["resumed_by"]), ("continued", job.message_id))

    def test_answers_and_a_supplement_go_together(self):
        self.click({"option_0": "1", "supplement": "表格太宽"})
        [job] = self.follow_up()
        saved = self.saved()
        self.assertEqual(saved["answers"], {"fmt": {"answers": ["列表"]}, "note": {"answers": [SKIPPED]}})
        self.assertIn("用户补充说明：\n表格太宽", job.prompt_text)  # Something was answered: no UNANSWERED_NOTE.
        self.assertNotIn(UNANSWERED_NOTE, job.prompt_text)

    def test_without_a_supplement_every_question_is_still_asked_for(self):
        for form, words in (({}, "还有 2 题没回答"), ({"supplement": " "}, "还有 2 题没回答"),
                            ({"option_0": "0"}, "还有 1 题没回答：还有别的要求吗？（不想回答可选“不回答此题”，或在补充说明里写一句再点“提交回答”）")):
            with self.subTest(form):
                self.click(form)
                self.assertIn(words, self.app.questions.show_answer_notice.call_args.args[3])
                self.assertEqual((self.saved()["status"], self.follow_up()), ("pending", []))

    def test_an_old_cards_skip_and_ask_send_the_supplement_alone(self):
        for kind in (SKIP_ALL_KIND, ASK_KIND):
            self.assertIn(kind, ACTIONS)
        # Empty: refused on the card, redrawn with 提交回答 alone; nothing saved.
        self.click({"supplement": ""}, kind=ASK_KIND)
        card = self.app.cards.repaint_browse_card.call_args.args[4]
        self.assertIn("⚠️ " + NOTE_EMPTY, text_of(card))
        self.assertNotIn("先问一句", text_of(card).replace(NOTE_EMPTY, ""))
        self.assertEqual(self.saved()["status"], "pending")
        # What was picked does not count: the owner meant to ask, not to answer.
        self.click({"supplement": WORDS, "option_0": "0"}, kind=ASK_KIND, event="ev-ask")
        [job] = self.follow_up()
        self.assertEqual(self.saved()["answers"], {"fmt": {"answers": [SKIPPED]}, "note": {"answers": [SKIPPED]}})
        self.assertIn(UNANSWERED_NOTE, job.prompt_text)


class StandingRetiredTest(unittest.TestCase):
    def test_its_old_buttons_get_a_notice_and_do_nothing(self):
        for kind in ("bridge_question_standing", "bridge_standing_save", "bridge_standing_edit", "bridge_standing_cancel"):
            with self.subTest(kind):
                self.assertNotIn(kind, ACTIONS)
                self.assertIn("“以后这类按推荐走”已下线", moved_card_text({"action_value": {"kind": kind, "token": "e" * 24}}))
        self.assertEqual(moved_card_text({"action_value": {"kind": "bridge_question"}}), "")


if __name__ == "__main__":
    unittest.main()
