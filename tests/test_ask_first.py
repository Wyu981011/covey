"""先问一句 on a 代发草稿 card (T604 #13): the owner asks the topic that drafted it something first. It reaches the topic the
way its messages do (its next turn, or into the task it runs), the card stays open and the draft unsent (app/owner_send.py
ask). On a question card it was folded into 提交回答 (T631): a 补充说明 alone is sent with every question 不回答此题, and a
card sent before still sends its 先问一句 so (test_question_submit)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.cards import walk_dicts
from support.world import TopicFixture

from covey.app.answers import ASK_PREFIX, ask_id
from covey.app.owner_send import ASK_EMPTY as DRAFT_ASK_EMPTY, ASK_GONE, ASK_START as DRAFT_ASK_START, OwnerSend
from covey.cards.owner_send import ASK, ASK_FIELD, owner_send_card
from covey.core import owner_send as drafts
from covey.core.jobs import find_job_record, upsert_job_record

WORDS = "B 是什么意思？会动线上吗"


class AcknowledgeTest(TopicFixture, unittest.TestCase):
    """A turn queued while a task waits for its answer goes on from it (TaskControls.acknowledge_waiting_answer); a
    先问一句's turn does not: the question it asks about still waits."""

    def test_an_ask_turn_leaves_the_waiting_task_as_it_is(self):
        self.receive("om_wait", "整理数据")
        waiting = self.app.runtime.jobs.queue.get_nowait()
        ctx = self.topic("om_wait")
        checkpoint = self.root / "cp.json"
        checkpoint.write_text('{"requires_user": true}')
        upsert_job_record(ctx.state_dir, waiting.message_id, status="waiting_user", checkpoint_path=str(checkpoint),
                          job_id=waiting.job_id, topic_id=waiting.topic_id, chat_id="oc_chat", backend="claude")
        ask = SimpleNamespace(message_id=ASK_PREFIX + "0" * 16, chat_id="oc_chat", job_id=9, recovery_context=None)
        self.assertIsNone(self.app.controls.acknowledge_waiting_answer(ctx, ask))
        self.assertEqual(find_job_record(ctx.state_dir, waiting.message_id)["status"], "waiting_user")
        self.assertIsNone(ask.recovery_context)
        other = SimpleNamespace(message_id="om_next", chat_id="oc_chat", job_id=10, recovery_context=None)
        self.app.controls.acknowledge_waiting_answer(ctx, other)
        self.assertEqual(find_job_record(ctx.state_dir, waiting.message_id)["status"], "continued")
        self.assertEqual(other.recovery_context, {"requires_user": True})


class AskDraftTest(unittest.TestCase):
    """先问一句 on a 代发草稿 card: the line under the draft's box goes to the topic that drafted it; the draft stays as it
    is, unsent, and its card is not redrawn (what the owner changed in the box stays)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        self.ctx = SimpleNamespace(state_dir=self.state, profile="bot")
        self.topic_app = SimpleNamespace(questions=SimpleNamespace(queue_ask=mock.Mock(return_value=SimpleNamespace(job_id=12))))
        self.target = SimpleNamespace(topic_id="t" * 64)
        self.topics = SimpleNamespace(target=mock.Mock(return_value=(self.topic_app, self.target, {})))
        self.messenger = SimpleNamespace(send_message=mock.Mock(return_value="om_line"))
        self.proxy = SimpleNamespace(topics=self.topics, messenger=self.messenger,
                                     voice=SimpleNamespace(key=lambda *parts: "-".join(parts)),
                                     runtime=SimpleNamespace(log=lambda line: None))
        self.owner = OwnerSend(self.proxy)
        self.owner.publish = mock.Mock(return_value=True)
        self.checkpoint = self.state / "drafting.json"
        self.checkpoint.write_text('{"phase": "草稿写好了"}')
        upsert_job_record(self.state, "om_job1", status="done", checkpoint_path=str(self.checkpoint), job_id=9,
                          topic_id="t" * 64, chat_id="oc_owner")
        self.record = {"id": "d" * 32, "ref": "zs", "status": "drafted", "job_key": "om_job1", "job_id": 9,
                       "topic_id": "t" * 64, "chat_id": "oc_owner", "reply_to": "om_thread", "to": {"email": "z@example.com"},
                       "text": "AK 开好了", "why": "交付", "recipient": {"name": "张三", "open_id": "ou_zs"},
                       "to_label": "张三", "card_id": "card_d", "message_id": "om_draft", "view": {"state": "drafted"},
                       "history": [["drafted", 1, ""]]}
        drafts.write(self.state, self.record)

    def click(self, words=WORDS, owner=True, event="ev-draft"):
        value = {"kind": ASK, "draft": self.record["id"]}
        return self.owner.click(self.ctx, {"message_id": "om_draft", "operator_id": "ou_me", "event_id": event,
                                           "action_value": value, "form_value": {ASK_FIELD: words, "text": "改过的正文"}},
                                value, owner)

    def test_the_card_offers_it_while_the_draft_waits(self):
        card = owner_send_card(self.record, {"state": "drafted"})
        buttons = [e for e in walk_dicts(card) if e.get("tag") == "button"]
        self.assertEqual([b["name"] for b in buttons], ["owner_send_go", "owner_send_drop", "owner_send_ask"])
        self.assertEqual((buttons[2]["form_action_type"], buttons[2]["behaviors"][0]["value"]),
                         ("submit", {"kind": ASK, "draft": self.record["id"]}))
        self.assertTrue([e for e in walk_dicts(card) if e.get("tag") == "input" and e.get("name") == ASK_FIELD])
        for state in ("sent", "declined", "sending", "choose", "superseded"):
            with self.subTest(state):
                self.assertNotIn("owner_send_ask", json.dumps(owner_send_card({**self.record, "status": state},
                                                                              {"state": state})))

    def test_the_question_goes_to_the_drafting_topic_and_the_draft_stays(self):
        self.assertEqual(self.click(), "owner_send_ask")
        self.topics.target.assert_called_once_with(self.state, "t" * 64, "oc_owner")
        call = self.topic_app.questions.queue_ask.call_args
        target, chat, shown, text, mid = call.args
        self.assertEqual((target, chat, shown, mid), (self.target, "oc_owner", WORDS, ask_id(self.record["id"], "ev-draft")))
        self.assertEqual(text, f"{DRAFT_ASK_START}\n草稿 zs，发给 张三。\n他问：\n{WORDS}")
        self.assertNotIn("AK 开好了", text)  # Not the text, which may hold a key.
        self.assertEqual((call.kwargs["title"], call.kwargs["sender"]), ("先问一句：" + WORDS, "ou_me"))
        self.assertEqual(call.kwargs["prior"], {"phase": "草稿写好了"})
        saved = drafts.read(self.state, self.record["id"])
        self.assertEqual((saved["status"], saved["text"]), ("drafted", "AK 开好了"))
        self.owner.publish.assert_not_called()  # Not redrawn: the box keeps what the owner changed.
        self.messenger.send_message.assert_not_called()

    def test_nothing_asked_is_said_in_the_topic(self):
        self.assertEqual(self.click(words="  "), "owner_send_ask_empty")
        self.assertEqual(self.messenger.send_message.call_args.args[2], DRAFT_ASK_EMPTY)
        self.assertEqual(self.messenger.send_message.call_args.kwargs["reply_to_message_id"], "om_thread")
        self.topics.target.return_value = None  # The topic gone, or on a Harness no longer here.
        self.assertEqual(self.click(event="ev-2"), "owner_send_ask")
        self.assertEqual(self.messenger.send_message.call_args.args[2], ASK_GONE)
        self.topic_app.questions.queue_ask.assert_not_called()

    def test_only_the_owner_and_only_while_it_waits(self):
        self.assertEqual(self.click(owner=False), "owner_only")
        drafts.write(self.state, {**self.record, "status": "sent"})
        self.assertEqual(self.click(), "owner_send_stale")
        self.topic_app.questions.queue_ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
