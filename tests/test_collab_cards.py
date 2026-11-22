"""协作卡 (cards/collab_card.py, app/collab_cards.py, docs/architecture.md 多参与者协作 · 两端): the card drawn from the record's
view, sent in the integrator's thread, redrawn when the record says something new, and its 停止这次协作 that acts through
``Collaboration.stop`` once; nothing at all with COVEY_COLLAB off."""
from __future__ import annotations

import json
import os
import threading
import time
from unittest import mock

from support.fake_lark import FakeCardKit
from test_collab_flow import Case

from covey.app import collab_cards, collab_channel
from covey.app.card_actions import ACTIONS
from covey.cards import collab_card as view
from covey.cards.card_cost import CARD_COST_BUDGET, card_cost
from covey.cards.elements import CARD_BYTES, CARD_NODES, element_count, json_size, walk
from covey.core import collab, turn_source
from covey.core import collab_records as records
from covey.core.jobs import upsert_job_record

CREATED = {"code": 0, "data": {"card_id": "card-1"}}


def texts(built) -> str:
    return "\n".join(str(item.get("content") or (item.get("text") or {}).get("content") or "")
                     for _, _, item in walk(built["body"]["elements"]))


def buttons(built) -> list:
    return [item for _, _, item in walk(built["body"]["elements"]) if item.get("tag") == "button"]


def ask(number=1, frm="a" * 16, to="b" * 16, state=collab.REPLIED, **fields):
    base = {"id": f"c1-{to[:4]}-{number}", "from": frm, "to": to, "number": number, "text": "方案定的是哪个？",
            "state": state, "words": collab.ASK_WORDS[state], "reason": "", "evidence": {}, "reply": {}, "late": False}
    return {**base, **fields}


def sample(state=collab.OPEN, asks=None, replies=()):
    return {"id": "c1", "chat_id": "chat", "state": state, "stopped_by": "", "deadline": 1.0,
            "integrator": {"key": "a" * 16, "role": "topic", "project": "", "label": "T3", "named": False},
            "helpers": [{"key": "b" * 16, "role": "topic", "project": "", "label": "T5", "named": True},
                        {"key": "c" * 16, "role": "lead", "project": "p", "label": "负责人（迁移）", "named": False}],
            "asks": asks if asks is not None else [ask(state=collab.QUEUED)], "replies": list(replies)}


class BuildTest(Case):
    def test_it_names_the_integrator_the_participants_each_speaker_state_question_answer_and_evidence(self):
        at = time.mktime((2026, 11, 22, 14, 3, 0, 0, 0, -1))
        answered = ask(state=collab.READ, reply={"text": "定的是方案 B", "evidence": {"level": collab.FORKED, "job_id": 12, "at": at}})
        pending = ask(to="c" * 16, state=collab.TAKEN, number=1)
        built = view.collab_card(sample(asks=[answered, pending]))
        text = texts(built)
        self.assertEqual(built["header"]["title"]["content"], "🤝 协作 · 由 T3 汇总")
        self.assertIn("汇总方", text)
        self.assertIn("T5", text)
        self.assertIn("负责人（迁移）", text)
        self.assertIn("咨询", text)
        self.assertIn(collab.ASK_WORDS[collab.READ], text)  # The logical speaker line: T3 → T5 · 咨询 · 已被汇总方读取.
        self.assertIn(collab.ASK_WORDS[collab.TAKEN], text)
        self.assertIn("→", text)
        self.assertIn("定的是方案 B", text)
        self.assertIn(collab.EVIDENCE_WORDS[collab.FORKED], text)
        self.assertIn("任务 &#35;12", text)  # literal(): the # as its entity, drawn as #.
        self.assertIn("核查于 14:03", text)
        self.assertEqual(built["header"]["text_tag_list"][0]["text"]["content"], "在做")

    def test_the_owner_names_win_over_the_labels_and_a_clarification_says_so(self):
        built = view.collab_card(sample(asks=[ask(number=2, state=collab.QUEUED)]), names={"a" * 16: "管家"})
        text = texts(built)
        self.assertEqual(built["header"]["title"]["content"], "🤝 协作 · 由 管家 汇总")
        self.assertIn("澄清", text)
        self.assertNotIn("咨询 ·", text)

    def test_why_an_ask_was_not_taken_failed_expired_or_cancelled_is_on_the_card_and_a_late_answer_is_said_to_be_kept_only(self):
        for state, reason in ((collab.NOT_TAKEN, "对方在等主人回答问题"), (collab.FAILED, "对方这一轮没有完成"),
                              (collab.EXPIRED, "排队超过 10 分钟"), (collab.CANCELLED, "主人停了这件事")):
            with self.subTest(state):
                text = texts(view.collab_card(sample(asks=[ask(state=state, reason=reason)])))
                self.assertIn(reason, text)
                self.assertIn(collab.ASK_WORDS[state], text)
        text = texts(view.collab_card(sample(state=collab.CANCELLED, asks=[
            ask(state=collab.CANCELLED, reason="主人停了这件事", late=True)])))
        self.assertIn(view.LATE_NOTE, text)
        self.assertEqual(view.collab_card(sample(state=collab.CANCELLED))["header"]["text_tag_list"][0]["text"]["content"], "已停止")

    def test_the_stop_button_is_there_only_while_something_waits_or_runs_and_carries_the_id_and_the_kind(self):
        for state, asks, replies, shown in (
                (collab.OPEN, [ask(state=collab.QUEUED)], (), True),
                (collab.OPEN, [ask(state=collab.TAKEN)], (), True),
                (collab.OPEN, [ask(state=collab.READ)], [{"number": 1, "state": "queued"}], True),
                (collab.OPEN, [ask(state=collab.READ)], [{"number": 1, "state": "done"}], False),
                (collab.OPEN, [ask(state=collab.NOT_TAKEN, reason="x")], (), False),
                (collab.DONE, [ask(state=collab.READ)], (), False),
                (collab.CANCELLED, [ask(state=collab.CANCELLED)], (), False)):
            with self.subTest(state=state, asks=[a["state"] for a in asks], replies=replies):
                found = buttons(view.collab_card(sample(state=state, asks=asks, replies=replies)))
                self.assertEqual(len(found), int(shown))
        [button] = buttons(view.collab_card(sample()))
        self.assertEqual(button["behaviors"][0]["value"], {"kind": view.KIND, "collab": "c1"})
        self.assertEqual(button["text"]["content"], view.STOP_LABEL)
        self.assertIn(view.KIND, ACTIONS)
        self.assertFalse(ACTIONS[view.KIND].bot_only)  # It starts no task.

    def test_a_full_collaboration_with_long_words_stays_within_what_cardkit_takes(self):
        long = "很长的话" * 600
        asks = [ask(number=n, to=to * 16, text=long, state=collab.REPLIED, reply={"text": long, "evidence": {
            "level": collab.RECORD, "job_id": 99, "at": time.time()}}, late=True, reason=long)
                for to in "bc" for n in (1, 2)]
        built = view.collab_card(sample(asks=asks))
        self.assertLess(card_cost(built), CARD_COST_BUDGET)
        self.assertLessEqual(element_count(built), CARD_NODES)
        self.assertLessEqual(json_size(built), CARD_BYTES)
        self.assertNotIn(long, texts(built))

    def test_markdown_in_the_words_is_shown_as_written(self):
        text = texts(view.collab_card(sample(asks=[ask(text="**加粗** <at id=all></at>", state=collab.QUEUED)])))
        self.assertNotIn("<at", text)


class CardCase(Case):
    def setUp(self):
        super().setUp()
        del self.app.messenger.create_and_send_card  # The real one, over the fake CardKit below.
        self.fake = FakeCardKit(return_value=CREATED, sent=("om_collab_card", False)).start(self)
        self.helper, self.integrator = self.topic("om_h"), self.topic("om_i")

    def begin(self, **fields):
        self.end(self.root_turn(self.integrator, [{"to": self.label(self.helper), "question": "方案定的是哪个？"}], **fields))
        return self.record()

    def card(self):
        """The card JSON of the last write: a create, or a whole replace."""
        last = self.fake.calls[-1]
        return last.created if last.method == "POST" else last.card

    def click(self, cid, operator="owner", event_id="ev1", message="om_collab_card"):
        self.app.handle_card_action_event({"event_id": event_id, "operator_id": operator, "chat_id": "chat",
                                           "message_id": message, "action_value": {"kind": view.KIND, "collab": cid}},
                                          self.ctx)
        return [line.split("outcome=")[1].split()[0] for line in self.logs if line.startswith("card action ")][-1]


class SendTest(CardCase):
    def test_starting_sends_the_card_in_the_integrators_thread_and_no_line_says_the_same_again(self):
        record = self.begin()
        [create] = [call for call in self.fake.calls if call.method == "POST"]
        self.assertEqual(create.created["header"]["title"]["content"], f"🤝 协作 · 由 {self.label(self.integrator)} 汇总")
        self.assertIn(self.label(self.helper), texts(create.created))
        sent = self.fake.send.call_args
        self.assertEqual(sent.kwargs["reply_to_message_id"], "om_i")  # The thread of the integrator.
        self.assertEqual((record["card"]["card_id"], record["card"]["message_id"]), ("card-1", "om_collab_card"))
        self.assertFalse([text for text in self.said() if text.startswith("🤝 协作")])  # Not said twice.
        self.assertEqual(len(buttons(create.created)), 1)

    def test_a_card_that_did_not_go_out_leaves_the_line_and_is_sent_as_the_same_card_next_time(self):
        self.fake.send.return_value = ("", False)
        record = self.begin()
        self.assertEqual(record["card"]["card_id"], "card-1")  # Kept before the send.
        self.assertNotIn("message_id", record["card"])
        self.assertTrue([text for text in self.said() if text.startswith("🤝 协作")])  # The line, as before.
        creates = len([call for call in self.fake.calls if call.method == "POST"])
        self.fake.send.return_value = ("om_collab_card", False)
        self.assertTrue(self.flow.cards.refresh(self.ctx, record["id"]))
        self.assertEqual(len([call for call in self.fake.calls if call.method == "POST"]), creates)  # Not created again.
        self.assertEqual(self.record()["card"]["message_id"], "om_collab_card")

    def test_nothing_is_sent_with_the_switch_off(self):
        with mock.patch.dict(os.environ, {turn_source.SWITCH: ""}):
            self.end(self.root_turn(self.integrator, [{"to": self.label(self.helper), "question": "?"}]))
            self.assertFalse(self.flow.cards.refresh(self.ctx, "anything"))
            self.assertIsNone(self.flow.cards.claim(self.ctx, {"chat_id": "chat"}, {"kind": view.KIND, "collab": "x"}, True))
        self.assertEqual(records.records(self.state), [])
        self.assertEqual(self.fake.api.call_count, 0)
        self.assertEqual(self.fake.send.call_count, 0)


class UpdateTest(CardCase):
    def test_a_changed_record_writes_the_whole_card_with_a_new_sequence_and_an_unchanged_one_writes_nothing(self):
        record = self.begin()
        cid = record["id"]
        self.assertTrue(self.flow.cards.refresh(self.ctx, cid))
        writes = len(self.fake.calls)
        self.assertTrue(self.flow.cards.refresh(self.ctx, cid))
        self.assertEqual(len(self.fake.calls), writes)  # The same drawing: no write.
        [job] = self.queued()
        upsert_job_record(self.state, job.message_id, **{collab_channel.EVIDENCE: {
            "level": collab.FORKED, "job_id": 7, "at": time.time()}})
        self.answer(job, "定的是方案 B")
        puts = [call for call in self.fake.calls if call.method == "PUT"]
        self.assertTrue(puts)
        sequences = [call.data["sequence"] for call in puts]
        self.assertEqual(sequences, sorted(set(sequences)))  # Never back, never twice (rule 3).
        self.assertEqual(self.record()["card"]["sequence"], sequences[-1])
        self.assertIn("定的是方案 B", texts(puts[-1].card))
        self.assertIn(collab.EVIDENCE_WORDS[collab.FORKED], texts(puts[-1].card))

    def test_stopping_draws_the_card_without_its_button_and_its_cancelled_asks(self):
        cid = self.begin()["id"]
        self.flow.stop(self.ctx, cid, by="web")  # The page's stop: the same record, the card follows.
        built = self.card()
        self.assertEqual(buttons(built), [])
        self.assertIn(collab.ASK_WORDS[collab.CANCELLED], texts(built))
        self.assertIn("已停止", json.dumps(built, ensure_ascii=False))

    def test_a_late_answer_after_a_stop_is_said_kept_only_on_the_card(self):
        cid = self.begin()["id"]
        [job] = self.queued()
        self.app.runtime.unregister_reply_job(job)
        self.flow.stop(self.ctx, cid, by="web")
        self.answer(job, "迟到的答复")
        self.assertIn(view.LATE_NOTE, texts(self.card()))

    def test_the_card_is_sent_and_written_outside_the_records_lock(self):
        cid = collab.collab_id("om_root", self.integrator, [self.helper])
        held = []

        def free():
            """Whether another thread can take the collaboration's record lock now."""
            thread = threading.Thread(target=lambda: records.change(self.state, cid, lambda current: None))
            thread.start()
            thread.join(2)
            return not thread.is_alive()

        def api(profile, method, path, data, **kwargs):
            held.append(free())
            return CREATED

        def send(*args, **kwargs):
            held.append(free())
            return ("om_collab_card", False)
        self.fake.api.side_effect = api
        self.fake.send.side_effect = send
        self.assertEqual(self.begin()["id"], cid)
        [job] = self.queued()
        self.answer(job, "方案 B")
        self.assertGreaterEqual(len(held), 3)  # The create, the send, a whole-card write.
        self.assertTrue(all(held), held)


class ClickTest(CardCase):
    def test_the_owners_click_stops_once_and_a_second_click_only_draws_the_card_again(self):
        cid = self.begin()["id"]
        with mock.patch.object(self.flow, "stop", wraps=self.flow.stop) as stop:
            self.assertEqual(self.click(cid), "collab_stop")
            self.assertEqual(self.record()["state"], collab.CANCELLED)
            self.assertEqual(self.record()["stopped_by"], "card")
            self.assertEqual(self.click(cid, event_id="ev2"), "collab_ended")
            stop.assert_called_once()
            self.assertEqual(stop.call_args.kwargs["by"], "card")
        self.assertEqual(buttons(self.card()), [])
        puts = len([call for call in self.fake.calls if call.method == "PUT"])
        self.assertEqual(self.click(cid, event_id="ev3"), "collab_ended")
        self.assertEqual(len([call for call in self.fake.calls if call.method == "PUT"]), puts)  # Drawn the same: no write.

    def test_a_stop_the_page_made_first_is_not_run_again_by_the_card(self):
        cid = self.begin()["id"]
        self.flow.stop(self.ctx, cid, by="web")
        with mock.patch.object(self.flow, "stop") as stop:
            self.assertEqual(self.click(cid), "collab_ended")
        stop.assert_not_called()
        self.assertEqual(self.record()["stopped_by"], "web")  # Whoever came first stays.

    def test_someone_who_is_not_the_owner_does_not_stop_it(self):
        cid = self.begin()["id"]
        with mock.patch.object(self.flow, "stop") as stop:
            self.assertEqual(self.click(cid, operator="stranger"), "not_owner")
            self.assertEqual(self.flow.cards.claim(self.ctx, {"chat_id": "chat"}, {"kind": view.KIND, "collab": cid}, False),
                             collab_cards.OWNER_ONLY)
        stop.assert_not_called()
        self.assertEqual(self.record()["state"], collab.OPEN)

    def test_a_collaboration_of_another_chat_or_none_is_not_stopped(self):
        cid = self.begin()["id"]
        with mock.patch.object(self.flow, "stop") as stop:
            self.assertEqual(self.flow.cards.claim(self.ctx, {"chat_id": "elsewhere"}, {"kind": view.KIND, "collab": cid}, True),
                             "collab_unknown")
            self.assertEqual(self.flow.cards.claim(self.ctx, {"chat_id": "chat"}, {"kind": view.KIND, "collab": "nope"}, True),
                             "collab_unknown")
        stop.assert_not_called()
