"""话题转交管家 (app/butler_asks.py, docs/architecture.md 话题转交管家): the owner's own turn of a topic carries the rule, a
turn that wrote ``ask_butler`` is handed to the butler once (a message at the top level, then a queued butler turn with
the turn source ``handover``), and what cannot be handed on is said in the topic."""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.records import write_topic

from covey.app import butler_asks as asks
from covey.app import prompts
from covey.core import butler, projects, turn_source
from covey.core.jobs import upsert_job_record
from covey.core.state import read_object
from covey.core.topics import message_topic

CHAT, OWNER, TOPIC = "oc_owner", "ou_owner", "a1" * 16


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        self.enterContext(mock.patch.dict(os.environ, {projects.ENV: "1"}))
        self.enterContext(mock.patch.object(butler, "enabled", return_value=True))
        write_topic(self.state, topic_id=TOPIC, chat_id=CHAT, topic_number=12, title="迁移订单库")
        self.logs = []
        self.access = SimpleNamespace(owner_turn=lambda chat, sender: sender in ("", OWNER) and chat == CHAT,
                                      agent_chat=lambda chat, group=None: chat == CHAT,
                                      spaces=SimpleNamespace(personal_groups=()))
        base = SimpleNamespace(profile="prof", state_dir=self.state)
        root = butler.butler_topic_id(CHAT)
        self.enqueue = mock.Mock(side_effect=lambda ctx, text, chat, message, **kwargs: SimpleNamespace(message_id=message))
        self.butler_app = SimpleNamespace(
            harness=SimpleNamespace(context=base),
            submission=SimpleNamespace(
                event_context=lambda context, event: SimpleNamespace(
                    topic_id=root, history_path=self.state / "topics" / root / "history.jsonl"),
                enqueue_chat_job=self.enqueue))
        self.app_for = mock.Mock(return_value=self.butler_app)
        self.send_text = mock.Mock(return_value="om_handed")
        self.send_message = mock.Mock(return_value="om_note")
        self.gateway = SimpleNamespace(
            runtime=SimpleNamespace(access=self.access, log=self.logs.append, owner_open_id=OWNER),
            topics=SimpleNamespace(apps={"claude": SimpleNamespace(harness=SimpleNamespace(context=base))}, default="claude"),
            butler=SimpleNamespace(app_for=self.app_for, keep_topic=lambda ctx, app, chat: "claude-butler"),
            messenger=SimpleNamespace(send_text=self.send_text, send_message=self.send_message),
            voice=SimpleNamespace(safe_key=lambda key: key, key=lambda *parts: "-".join(map(str, parts))))
        self.ctx = SimpleNamespace(state_dir=self.state, profile="prof")
        self.enterContext(mock.patch.object(asks, "context_for_job", return_value=SimpleNamespace(
            profile="prof", reply_to_message_id="om_thread")))

    def turn(self, key="om_turn1", ask=None, **fields):
        """A finished turn of the topic whose checkpoint has ``ask`` as its ask_butler; the job the Bridge has of it."""
        checkpoint = self.state / f"{key}.cp.json"
        checkpoint.write_text(json.dumps({"phase": "完成", **({asks.FIELD: ask} if ask is not None else {})}, ensure_ascii=False))
        upsert_job_record(self.state, key, **{"status": "done", "verified_reply_authorized": True, "job_id": 7,
                                              "topic_id": TOPIC, "chat_id": CHAT, "message_id": key, "sender_id": OWNER,
                                              "user_text": "开个专项推进这件事", "checkpoint_path": str(checkpoint), **fields})
        return SimpleNamespace(message_id=key, job_id=7, topic_id=TOPIC, chat_id=CHAT)


class RuleTest(Case):
    def offered(self, message_id="om_1", sender=OWNER, topic=TOPIC, chat=CHAT, **fields):
        job = {"message_id": message_id, "chat_id": chat, "sender_id": sender, "topic_id": topic, **fields}
        return asks.offered(self.access, self.state, job)

    def test_the_owners_own_turn_of_a_topic_carries_the_rule(self):
        self.assertTrue(self.offered())
        self.assertTrue(self.offered("web-op1"))  # His words from the web page.
        self.assertTrue(self.offered(sender=""))  # A record without a sender, in his private chat.

    def test_hand_ons_wake_ups_answers_retries_and_other_peoples_turns_do_not(self):
        for message in ("main-abc", "lead-p1-3", "revisit-a1a1-1-0", "answer-q1"):
            self.assertFalse(self.offered(message), message)
        self.assertFalse(self.offered(sender="ou_colleague"))
        self.assertFalse(self.offered(chat="oc_somewhere"))  # No butler in that chat.
        self.assertFalse(self.offered(auto_retry=1))  # An automatic retry (app/auto_retry.py COUNTS).
        self.assertFalse(self.offered(policy_retry={"of": "k"}))
        ask = turn_source.make(turn_source.ASK, asserted_by="topic", collab="c1")
        self.assertFalse(self.offered(turn_source=ask))  # A 协作 turn.

    def test_the_butlers_family_and_a_proxy_topic_do_not(self):
        self.assertFalse(self.offered(topic=butler.butler_topic_id(CHAT)))
        self.assertFalse(self.offered(topic=projects.lead_topic_id(CHAT, "p1p1p1")))
        write_topic(self.state, topic_id="b2" * 16, chat_id=CHAT, proxy={"contact": "x"})
        self.assertFalse(self.offered(topic="b2" * 16))

    def test_off_without_projects_or_the_butler(self):
        with mock.patch.dict(os.environ, {projects.ENV: ""}):
            self.assertFalse(self.offered())
        with mock.patch.object(butler, "enabled", return_value=False):
            self.assertFalse(self.offered())

    def test_the_rule_is_put_after_the_checkpoint_file_of_the_owners_turn_only(self):
        from covey.app.runs import Runs

        runs = SimpleNamespace(runtime=SimpleNamespace(access=self.access))
        ctx = SimpleNamespace(state_dir=self.state, topic_id=TOPIC)
        job = SimpleNamespace(topic_id="", chat_id=CHAT, message_id="om_1", sender_id=OWNER)
        self.assertEqual(Runs._ask_note(runs, ctx, job), "\n\n" + asks.RULE)  # The context's topic when the job has none.
        self.assertEqual(Runs._ask_note(runs, ctx, SimpleNamespace(**{**vars(job), "message_id": "main-tok"})), "")

    def test_the_butlers_rule_reads_the_handed_message(self):
        self.assertIn(prompts.ASKED_RULE, prompts.project_rules())
        self.assertIn(asks.HEAD.format(label="T12"), prompts.ASKED_RULE)
        with mock.patch.dict(os.environ, {projects.ENV: ""}):
            self.assertEqual(prompts.project_rules(), ())

    def test_the_checkpoint_field_is_read_as_written_and_cut(self):
        self.assertEqual(asks.wanted({asks.FIELD: "开专项「X」"}), {"ask": "开专项「X」", "why": ""})
        self.assertEqual(asks.wanted({asks.FIELD: {"ask": "  开专项\n「X」 ", "why": "话题开不了"}}),
                         {"ask": "开专项 「X」", "why": "话题开不了"})
        self.assertEqual(len(asks.wanted({asks.FIELD: {"ask": "长" * 900}})["ask"]), asks.ASK_CHARS)
        for raw in (None, "", {"why": "x"}, ["开专项"], {"ask": "  "}):
            self.assertIsNone(asks.wanted({asks.FIELD: raw}), raw)
        self.assertIsNone(asks.wanted({}))


class HandOnTest(Case):
    ASK = {"ask": "开专项「迁移订单库」，按启动包推进，把 T12 收进去", "why": "话题开不了专项"}
    TEXT = "↪ T12 转给管家\n你在 T12 说：开个专项推进这件事\nT12 的理解：开专项「迁移订单库」，按启动包推进，把 T12 收进去"

    def test_a_turn_with_an_ask_is_a_message_at_the_top_level_and_a_queued_handover_turn_of_the_butler(self):
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        (profile, chat, text, key), _ = self.send_text.call_args
        self.assertEqual((profile, chat, text), ("prof", CHAT, self.TEXT))
        (target, shown, chat, message), kwargs = self.enqueue.call_args
        self.assertEqual((shown, chat, message, kwargs["prompt_content"], kwargs["sender_id"]),
                         (self.TEXT, CHAT, "om_handed", self.TEXT, OWNER))
        source = kwargs["source"]
        self.assertEqual((source["kind"], source["asserted_by"], source["recorded_by"], source["level"]),
                         (turn_source.HANDOVER, "owner", "bridge", "owner"))
        self.assertEqual(source["origin"], {"topic": TOPIC, "message_id": "om_turn1", "chat": CHAT})
        self.assertEqual(turn_source.refusal({"turn_source": source}), "")  # This release runs it.
        self.assertFalse(turn_source.behavior({"turn_source": source}).steers)  # Queued, never a 补充.
        self.assertEqual(message_topic(self.state, CHAT, "om_handed"), butler.butler_topic_id(CHAT))
        self.assertIn("om_handed", target.history_path.read_text(encoding="utf-8"))
        record = read_object(asks.record_path(self.state, "om_turn1"))
        self.assertEqual((record["state"], record["message_id"], record["butler_job"], record["why"]),
                         ("sent", "om_handed", "om_handed", "话题开不了专项"))
        self.send_message.assert_not_called()

    def test_the_owners_words_come_from_the_topics_history_by_the_message_id(self):
        from covey.core.history_storage import append_history
        from covey.core.topics import topic_file

        history = topic_file(self.state, TOPIC).parent / "history.jsonl"
        append_history(history, "user", "把这个开成专项吧\n附件：", {"message_id": "om_turn1"})
        append_history(history, "assistant", "好，交给管家", {"message_id": "om_turn1"})
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        self.assertIn("你在 T12 说：把这个开成专项吧", self.send_text.call_args.args[2])

    def test_a_turn_read_twice_and_a_later_turn_with_the_same_words_hand_on_once(self):
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        asks.collect(self.gateway, self.turn("om_turn2", ask=self.ASK), self.ctx)  # Its checkpoint copied.
        self.assertEqual(self.send_text.call_count, 1)
        self.assertEqual(self.enqueue.call_count, 1)
        self.assertTrue(any("same words" in line for line in self.logs))
        asks.collect(self.gateway, self.turn("om_turn3", ask={"ask": "另开一个话题查 Y"}), self.ctx)
        self.assertEqual(self.send_text.call_count, 2)

    def test_what_is_not_handed_on(self):
        cases = {"om_failed": {"status": "failed"}, "om_unauthorized": {"verified_reply_authorized": False},
                 "main-tok": {}, "om_colleague": {"sender_id": "ou_colleague"}, "answer-q1": {}}
        for key, fields in cases.items():
            asks.collect(self.gateway, self.turn(key, ask=self.ASK, **fields), self.ctx)
        asks.collect(self.gateway, self.turn("om_none"), self.ctx)  # No ask_butler.
        self.send_text.assert_not_called()
        self.enqueue.assert_not_called()
        self.send_message.assert_not_called()
        self.assertEqual(sum("butler ask ignored" in line for line in self.logs), 5)

    def test_an_automatic_retrys_ask_is_not_handed_on_and_its_thread_says_so(self):
        asks.collect(self.gateway, self.turn("om_retry", ask=self.ASK, auto_retry=1, retry_of="om_turn0"), self.ctx)
        self.send_text.assert_not_called()
        (profile, chat, text, key), kwargs = self.send_message.call_args
        self.assertIn("这一轮是自动重试", text)
        self.assertEqual(kwargs["reply_to_message_id"], "om_thread")

    def test_no_butler_to_take_it_is_said_in_the_topic_and_a_later_turn_may_hand_it_on(self):
        self.app_for.return_value = None
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        self.send_text.assert_not_called()
        (profile, chat, text, key), kwargs = self.send_message.call_args
        self.assertEqual((chat, kwargs["reply_to_message_id"]), (CHAT, "om_thread"))
        self.assertIn("没能交给管家：管家现在没有开", text)
        self.assertEqual(read_object(asks.record_path(self.state, "om_turn1"))["state"], "no_butler")
        self.app_for.return_value = self.butler_app  # The owner turned the butler on and asked again.
        asks.collect(self.gateway, self.turn("om_turn2", ask=self.ASK), self.ctx)
        self.assertEqual(self.send_text.call_count, 1)

    def test_a_message_that_did_not_go_out_is_not_sent_again_and_is_said(self):
        self.send_text.return_value = ""
        for ambiguous, word in ((False, "failed"), (True, "uncertain")):
            with self.subTest(word=word), mock.patch("covey.feishu.transport.last_failure",
                                                     return_value=SimpleNamespace(ambiguous=ambiguous)):
                key = f"om_{word}"
                asks.collect(self.gateway, self.turn(key, ask={"ask": f"开专项 {word}"}), self.ctx)
                asks.collect(self.gateway, self.turn(key, ask={"ask": f"开专项 {word}"}), self.ctx)
                self.assertEqual(read_object(asks.record_path(self.state, key))["state"], word)
        self.assertEqual(self.send_text.call_count, 2)  # Once each, never again.
        self.enqueue.assert_not_called()
        texts = [call.args[2] for call in self.send_message.call_args_list]
        self.assertIn("消息没发出去", texts[0])
        self.assertIn("可能没发出去：私聊里没看到“↪ T12 转给管家”", texts[1])

    def test_a_butler_turn_that_was_not_queued_is_said_and_not_handed_again(self):
        self.enqueue.side_effect = None
        self.enqueue.return_value = None
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        self.assertEqual(read_object(asks.record_path(self.state, "om_turn1"))["state"], "not_queued")
        self.assertIn("管家的这一轮没排上", self.send_message.call_args.args[2])
        asks.collect(self.gateway, self.turn("om_turn2", ask=self.ASK), self.ctx)  # The message is there: not sent twice.
        self.assertEqual(self.send_text.call_count, 1)

    def test_nothing_at_all_with_the_switch_off(self):
        with mock.patch.dict(os.environ, {projects.ENV: ""}):
            asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        self.send_text.assert_not_called()
        self.assertFalse((self.state / asks.FOLDER).exists())

    def test_a_later_turn_may_hand_on_the_same_words_after_the_days(self):
        asks.collect(self.gateway, self.turn(ask=self.ASK), self.ctx)
        with mock.patch.object(asks.time, "time", return_value=time.time() + (asks.SAME_DAYS + 1) * 86400):
            asks.collect(self.gateway, self.turn("om_turn2", ask=self.ASK), self.ctx)
        self.assertEqual(self.send_text.call_count, 2)


if __name__ == "__main__":
    unittest.main()
