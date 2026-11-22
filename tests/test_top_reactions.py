"""引用卡片接着说 (docs/usage.md): a message quoted from outside its topic's thread (a reply quoting a relay card or a
question card's copy at the chat's top level, 引用直达) has its turn's cards in that thread, so the message's own reactions
say how the turn stands (app/butler_reactions.py top_message): OnIt, 排队中 while it waits, DONE or CrossMark at its end,
nothing for a stop or a question; DONE once it went into the running task or with an answer; a retry and a resume put
OnIt back. A message in the topic's thread, a topic's first message and the butler's turns are as before."""
from __future__ import annotations

import dataclasses
import json
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from support import make_job
from support.world import QuestionFixture, TopicFixture

from covey.app import butler_reactions, butler_reply
from covey.app.butler_reactions import DONE, FAILED, GOT, ON_IT, QUEUED
from covey.app.runner_spawn import dump_job, load_job
from covey.core.butler import butler_topic_id
from covey.core.deliveries import delivery_path, read_delivery
from covey.core.jobs import context_for_job, find_job_record
from covey.core.steer import SteerRefused
from covey.core.topics import remember_topic_message, route_message

CHAT = "oc_chat"


class Reactions:
    """What the fixture's messenger was asked (support/world.py TopicFixture mocks react, unreact and reaction_ids)."""

    def reactions(self):
        """(message, emoji) of each reaction put on, in order."""
        return [call.args[1:] for call in self.app.messenger.react.call_args_list]

    def listed(self):
        """(message, emoji) of each listing of the bot's reactions, to take them off."""
        return [call.args[1:] for call in self.app.messenger.reaction_ids.call_args_list]

    def holding(self, *emojis):
        """The bot's reactions as Feishu lists them: one of each of ``emojis`` on any message."""
        self.app.messenger.reaction_ids.side_effect = lambda profile, message, emoji: (
            [f"r-{emoji}"] if emoji in emojis else [])

    def forget(self):
        for name in ("react", "unreact", "reaction_ids"):
            getattr(self.app.messenger, name).reset_mock()


class QuotedCase(Reactions, TopicFixture, unittest.TestCase):
    """A topic rooted at om_root that answered once, and its relay at the chat's top level (om_relay, routed to it)."""

    def setUp(self):
        super().setUp()
        self.receive("om_root", "第一项任务")
        first = self.work()
        self.topic_id = first.topic_id
        self.ctx_topic = self.topic("om_root")
        remember_topic_message(self.ctx.state_dir, self.topic_id, CHAT, "om_relay")
        route_message(self.ctx.state_dir, CHAT, "om_relay", self.topic_id)
        self.forget()

    def quote(self, message, text="接着做"):
        """``message`` at the chat's top level quoting the relay: 引用直达 into the topic."""
        self.app.handle_event({"chat_id": CHAT, "sender_id": "ou_user", "message_id": message, "content": text,
                               "root_id": "om_relay", "parent_id": "om_relay"}, self.ctx, fetch_message_details=False)

    def queued(self, message):
        return next(job for job in self.app.runtime.jobs.queue.queue if job.message_id == message)

    def running(self, message="om_run"):
        """A turn of the topic that started (a message in its thread), still registered."""
        self.receive(message, "跑着", root="om_root", thread="omt_root")
        job = self.queued(message)
        self.app.runtime.jobs.queue.queue.remove(job)
        job.execution_started = True
        self.forget()
        return job


class TopMessageTest(QuotedCase):
    def event(self, **fields):
        return {"chat_id": CHAT, "message_id": "om_q", **fields}

    def test_a_message_outside_the_topics_thread(self):
        top = butler_reactions.top_message
        self.assertEqual(self.ctx_topic.reply_to_message_id, "om_root")
        # At the chat's top level: quoting a relay (or a copy, a 派发卡, a hook), or the root itself.
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_relay", parent_id="om_relay")), "om_q")
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_root", parent_id="om_root")), "om_q")
        # In another thread (the butler's card in the thread under the owner's question).
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_other", parent_id="om_card", thread_id="omt_2")),
                         "om_q")
        # In a group the same (a personal group's relays are at its top level too): whoever sent it.
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_relay", parent_id="om_relay", chat_type="group",
                                                        sender_id="ou_member")), "om_q")

    def test_none_where_the_card_is_or_nothing_is_said(self):
        top = butler_reactions.top_message
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_root", parent_id="om_x", thread_id="omt_1")), "")
        self.assertEqual(top(self.ctx_topic, self.event(thread_id="omt_1")), "")  # A thread, its root not said.
        self.assertEqual(top(self.ctx_topic, {"chat_id": CHAT, "message_id": "om_root"}), "")  # The topic's first.
        self.assertEqual(top(self.ctx_topic, self.event(message_id="web-1", root_id="om_relay")), "")
        self.assertEqual(top(dataclasses.replace(self.ctx_topic, reply_to_message_id=""), self.event(root_id="om_relay")),
                         "")
        butler = dataclasses.replace(self.ctx_topic, topic_id=butler_topic_id(CHAT))
        self.assertEqual(top(butler, self.event(root_id="om_relay")), "")  # The butler's: placement.marked.
        path = self.ctx_topic.history_path.parent / "topic.json"
        path.write_text(json.dumps({**json.loads(path.read_text()), "proxy": {"contact": "c1"}}))
        self.assertEqual(top(self.ctx_topic, self.event(root_id="om_relay")), "")  # A 代答 topic's.
        self.assertEqual(top(None, self.event(root_id="om_relay")), "")  # Never raises.


class QuotedTurnTest(QuotedCase):
    def test_on_it_as_it_is_queued_then_done_its_card_in_the_topics_thread(self):
        self.quote("om_quote")
        job = self.queued("om_quote")
        self.assertEqual((job.topic_id, job.reply_to_message_id, job.top_message), (self.topic_id, "om_root", "om_quote"))
        self.assertEqual(self.reactions(), [("om_quote", ON_IT)])
        self.assertEqual(find_job_record(self.ctx.state_dir, "om_quote")["top_message"], "om_quote")
        self.app.process_reply_job(job, self.ctx)
        self.assertEqual(find_job_record(self.ctx.state_dir, "om_quote")["status"], "done")
        # Its start looked for 排队中 (none), its end took OnIt off and said DONE, never Get.
        self.assertEqual(self.listed(), [("om_quote", QUEUED)])
        self.assertEqual(self.reactions(), [("om_quote", ON_IT), ("om_quote", ON_IT), ("om_quote", DONE)])
        self.app.messenger.unreact.assert_called_once_with(self.ctx.profile, "om_quote", "reaction-1")

    def test_a_message_in_the_thread_and_a_topics_first_message_get_none(self):
        self.receive("om_in", "串里接着说", root="om_root", thread="omt_root")
        job = self.work()
        self.assertEqual((job.message_id, job.top_message), ("om_in", ""))
        self.receive("om_new", "另一件事")  # A topic of its own: its card goes under it.
        job = self.work()
        self.assertEqual((job.message_id, job.top_message), ("om_new", ""))
        self.assertEqual(self.reactions(), [])
        self.assertEqual(self.listed(), [])
        self.assertNotIn("top_message", find_job_record(self.ctx.state_dir, "om_in"))

    def test_behind_a_running_task_it_waits_then_is_on_it_when_it_starts(self):
        running = self.running()
        self.quote("om_wait")  # The Harness takes no supplements: it waits behind #running.
        job = self.queued("om_wait")
        self.assertEqual(self.reactions(), [("om_wait", QUEUED)])
        self.app.runtime.unregister_reply_job(running)
        self.holding(QUEUED)
        self.app.process_reply_job(job, self.ctx)
        self.assertEqual(self.reactions(), [("om_wait", QUEUED), ("om_wait", ON_IT), ("om_wait", ON_IT),
                                            ("om_wait", DONE)])
        self.assertIn(mock.call(self.ctx.profile, "om_wait", f"r-{QUEUED}"), self.app.messenger.unreact.call_args_list)

    def test_one_that_starts_meanwhile_gets_on_it_and_one_stopped_meanwhile_nothing(self):
        job = make_job(job_id=9, message_id="om_late", top_message="om_late")
        job.execution_started = True  # Its task runner took it before 排队中 could go on.
        self.assertTrue(butler_reactions.top_queued(self.app.messenger, "p", job, mock.Mock(), waits=True))
        stopped = make_job(job_id=10, message_id="om_gone", top_message="om_gone")
        stopped.cancelled_before_start = True
        self.assertFalse(butler_reactions.top_queued(self.app.messenger, "p", stopped, mock.Mock(), waits=True))
        self.assertEqual(self.reactions(), [("om_late", ON_IT)])

    def test_a_failure_says_crossmark_a_stop_nothing(self):
        self.backend.run = mock.Mock(side_effect=RuntimeError("boom"))
        self.quote("om_fail")
        self.app.process_reply_job(self.queued("om_fail"), self.ctx)
        self.assertEqual(find_job_record(self.ctx.state_dir, "om_fail")["status"], "failed")
        self.assertEqual(self.reactions()[-1], ("om_fail", FAILED))
        self.forget()
        self.quote("om_stop")
        job = self.queued("om_stop")
        job.cancel_event.set()  # Stopped as it starts: its OnIt only comes off.
        self.app.process_reply_job(job, self.ctx)
        self.assertEqual(find_job_record(self.ctx.state_dir, "om_stop")["status"], "cancelled")
        self.assertEqual(self.reactions(), [("om_stop", ON_IT), ("om_stop", ON_IT)])
        self.app.messenger.unreact.assert_called_once_with(self.ctx.profile, "om_stop", "reaction-1")

    def test_one_that_could_not_be_queued_says_crossmark(self):
        with mock.patch.object(self.app.models, "prepare_submission_context", side_effect=ValueError("no model")):
            self.quote("om_nomodel")
        self.assertTrue(self.app.runtime.jobs.queue.empty())
        self.assertEqual(self.reactions(), [("om_nomodel", FAILED)])  # Why is said in the topic's thread.

    def test_each_end_as_the_butlers_but_never_get(self):
        job = make_job(job_id=7, message_id="om_q", topic_id=self.topic_id, top_message="om_q")
        with mock.patch.object(butler_reply, "routes", return_value=["T5"]):
            for status, outcome, emoji in (("done", None, DONE), ("failed", None, FAILED),
                                           ("cancelled", SimpleNamespace(policy_event={"kind": "refusal"}), FAILED),
                                           ("cancelled", None, ""), ("waiting_user", None, "")):
                react = mock.Mock(return_value=True)
                delivery = SimpleNamespace(job=job, ctx=self.ctx_topic, reacted=False, react=react, runtime=mock.Mock(),
                                           turn=SimpleNamespace(status=status, outcome=outcome))
                butler_reply.react_end(delivery)
                self.assertEqual(react.call_args.args, (job, emoji), status)
                self.assertNotEqual(react.call_args.args[1], GOT)
        bare = make_job(job_id=8, message_id="om_in", topic_id=self.topic_id)  # In the thread: none.
        react = mock.Mock()
        butler_reply.react_end(SimpleNamespace(job=bare, ctx=self.ctx_topic, reacted=False, react=react,
                                               runtime=mock.Mock(), turn=SimpleNamespace(status="done", outcome=None)))
        react.assert_not_called()

    def test_stopped_or_recalled_while_queued_it_is_left_with_nothing(self):
        running = self.running()
        self.quote("om_wait")
        job = self.queued("om_wait")
        self.holding(QUEUED, ON_IT)
        self.app.controls.cancel_reply_job_from_card(self.ctx_topic, {"job_id": str(job.job_id),
                                                                      "message_id": job.message_id}, CHAT, "click")
        self.assertTrue(job.cancelled_before_start)
        self.assertEqual(self.listed()[-2:], [("om_wait", QUEUED), ("om_wait", ON_IT)])
        self.assertEqual({call.args[2] for call in self.app.messenger.unreact.call_args_list}, {f"r-{QUEUED}", f"r-{ON_IT}"})
        self.app.runtime.unregister_reply_job(running)

    def test_its_task_runner_and_its_record_keep_it_an_older_ones_have_none(self):
        self.quote("om_quote")
        job = self.queued("om_quote")
        dumped = json.loads(json.dumps(dump_job(job), ensure_ascii=False))
        self.assertEqual(dumped["extras"]["top_message"], "om_quote")
        self.assertEqual(load_job(dumped).top_message, "om_quote")
        # A release before it handed or recorded none: no reactions anywhere.
        dumped["extras"].pop("top_message")
        old = load_job(dumped)
        self.assertEqual(old.top_message, "")
        self.forget()
        self.assertFalse(butler_reactions.begin(self.app.messenger, self.ctx.state_dir, "p", old, mock.Mock()))
        butler_reactions.unqueue(self.app.messenger, self.ctx.state_dir, "p", old, mock.Mock())
        self.app.controls.top_stopped(self.ctx_topic, {"job_id": 3, "message_id": "om_quote", "status": "failed"})
        self.assertEqual((self.reactions(), self.listed()), ([], []))
        self.assertNotIn("top_message", dump_job(make_job(message_id="om_x"))["extras"])
        self.assertEqual(butler_reactions.top_of({"top_message": "answer-1"}), "")

    def test_the_butlers_quiet_turns_react_as_before(self):
        quiet = make_job(job_id=7, message_id="om_1", topic_id=butler_topic_id(CHAT), reaction_message="om_owner")
        self.assertFalse(butler_reactions.begin(self.app.messenger, self.ctx.state_dir, "p", quiet, mock.Mock()))
        butler_reactions.finish(self.app.messenger, "p", quiet, DONE, mock.Mock())
        self.assertEqual(self.listed(), [])  # The switch of 多路并行 is off: no 排队中 to look for.
        self.assertEqual(self.reactions(), [("om_owner", ON_IT), ("om_owner", DONE)])


class QuotedSteerTest(QuotedCase):
    """The topic's task runs and takes supplements (COVEY_TOPIC_STEER, on by default): the quote goes into it."""

    def setUp(self):
        super().setUp()
        self.backend.declare(steering=True, steer_reads=True)
        self.run_job = self.running()
        self.control = SimpleNamespace(steer=mock.Mock(return_value=None), supports_steer=True)
        self.run_job.backend_control = self.control
        self.run_job.timings["backend_requested"] = 0
        self.app.harness.context = self.ctx
        self.app.cards.create_streaming_reply = mock.Mock(side_effect=lambda ctx, job, content, **kw: SimpleNamespace(
            card_id="card-" + job.message_id, message_id="msg-" + job.message_id, sequence=1, disabled=False))
        for name in ("close_streaming_reply", "replace_record_card", "update_job_streaming_reply", "update_card_activity",
                     "set_task_element"):
            setattr(self.app.cards, name, mock.Mock(return_value=True))

    def synchronous(self):
        return mock.patch("covey.app.steering.background.start", side_effect=lambda _, fn, *a: fn(*a))

    def delivery(self, message):
        return read_delivery(delivery_path(self.ctx_topic.state_dir, self.topic_id, "queued-steer-" + message))

    def test_into_the_running_task_it_says_done_once(self):
        self.quote("om_more", "顺便看下日志")
        self.control.steer.assert_called_once()
        self.assertEqual(self.delivery("om_more")["requeue"]["top"], "om_more")
        self.assertEqual(self.reactions(), [("om_more", DONE)])  # No OnIt, no 排队中 first.

    def test_held_for_a_task_not_ready_it_waits_then_says_done_when_sent(self):
        self.run_job.backend_control = None  # Started, its backend not up yet: held.
        self.quote("om_more")
        self.assertEqual(self.delivery("om_more")["status"], "held")
        self.assertEqual(self.reactions(), [("om_more", QUEUED)])
        self.holding(QUEUED)
        with self.synchronous():
            self.app.steering.settle_steer(self.ctx_topic, self.run_job, "queued-steer-om_more", status="sent", error="")
        self.assertEqual(self.reactions()[-1], ("om_more", DONE))
        self.assertIn(mock.call(self.ctx.profile, "om_more", f"r-{QUEUED}"), self.app.messenger.unreact.call_args_list)

    def test_held_until_its_task_ended_it_becomes_a_turn_of_its_own_with_its_reactions(self):
        self.run_job.backend_control = None
        self.quote("om_more")
        self.forget()
        with self.synchronous():
            self.app.steering.settle_held_at_end(context_for_job(self.ctx, self.run_job), self.run_job)
        again = next(job for job in self.app.runtime.jobs.topic_jobs(self.topic_id, CHAT) if job is not self.run_job)
        self.assertTrue(again.message_id.startswith("requeue-"))
        self.assertEqual(again.top_message, "om_more")
        # 排队中 off as it settled, then the turn of its own waits behind the task still registered.
        self.assertEqual(self.listed()[0], ("om_more", QUEUED))
        self.assertIn(("om_more", QUEUED), self.reactions())

    def test_refused_it_stays_queued_and_waits(self):
        self.control.steer.side_effect = SteerRefused("任务正在收尾")
        self.quote("om_late")
        self.assertEqual(self.delivery("om_late")["status"], "refused")
        self.assertFalse(self.queued("om_late").cancelled_before_start)
        self.assertEqual(self.reactions(), [("om_late", QUEUED)])

    def test_uncertain_it_says_nothing_until_it_is_confirmed(self):
        self.control.steer.side_effect = RuntimeError("connection lost")
        self.quote("om_unsure")
        self.assertEqual(self.delivery("om_unsure")["status"], "uncertain")
        self.assertEqual(self.reactions(), [])  # It may have gone in: never run again, never said done.

    def test_sent_by_a_click_on_its_queued_card_its_wait_becomes_done(self):
        with mock.patch.dict(os.environ, {"COVEY_TOPIC_STEER": "0"}):
            self.quote("om_queued")
        queued = self.queued("om_queued")
        self.assertEqual(self.reactions(), [("om_queued", QUEUED)])
        self.holding(QUEUED)
        self.assertTrue(self.app.steering.steer_queued_job(self.ctx_topic, CHAT, queued, "click-1"))
        self.assertEqual(self.reactions()[-1], ("om_queued", DONE))
        self.assertIn(mock.call(self.ctx.profile, "om_queued", f"r-{QUEUED}"), self.app.messenger.unreact.call_args_list)

    def test_one_its_task_never_read_runs_on_its_own_and_its_done_comes_off(self):
        self.quote("om_more")
        self.holding(DONE)
        with self.synchronous():
            self.app.steering.end_unread_steers(context_for_job(self.ctx, self.run_job), self.run_job)
        again = next(job for job in self.app.runtime.jobs.topic_jobs(self.topic_id, CHAT) if job is not self.run_job)
        self.assertEqual(again.top_message, "om_more")
        self.assertIn(("om_more", DONE), self.listed())
        self.assertIn(mock.call(self.ctx.profile, "om_more", f"r-{DONE}"), self.app.messenger.unreact.call_args_list)

    def test_a_message_in_the_thread_as_before_done_from_its_arrival(self):
        self.receive("om_in", "等一下", root="om_root", thread="omt_root")
        self.assertEqual(self.reactions(), [("om_in", DONE)])  # Steering.acknowledge_arrival, as ever.


class QuotedRetryTest(QuotedCase):
    def failed(self):
        self.backend.run = mock.Mock(side_effect=RuntimeError("boom"))
        self.quote("om_quote")
        self.app.process_reply_job(self.queued("om_quote"), self.ctx)
        self.backend.run = mock.Mock(side_effect=lambda request: SimpleNamespace())
        self.forget()
        return find_job_record(self.ctx.state_dir, "om_quote")

    def test_a_retry_takes_the_end_off_and_is_on_it_again(self):
        record = self.failed()
        self.assertEqual(record["top_message"], "om_quote")
        self.holding(FAILED)
        self.app.controls.requeue(self.ctx_topic, CHAT, "click-1", record)
        job = self.queued("click-1")
        self.assertEqual(job.top_message, "om_quote")
        self.assertEqual(find_job_record(self.ctx.state_dir, "click-1")["top_message"], "om_quote")
        self.assertEqual(self.listed(), [("om_quote", DONE), ("om_quote", FAILED)])
        self.assertIn(mock.call(self.ctx.profile, "om_quote", f"r-{FAILED}"), self.app.messenger.unreact.call_args_list)
        self.assertEqual(self.reactions(), [("om_quote", ON_IT)])

    def test_interrupted_it_loses_on_it_failed_before_it_ran_it_says_crossmark(self):
        record = {**self.failed(), "status": "interrupted"}
        self.app.cards.replace_record_card = mock.Mock(return_value=True)
        self.holding(QUEUED, ON_IT)
        self.assertTrue(self.app.controls.show_recovery_card(self.ctx_topic, record))
        self.assertEqual(self.listed(), [("om_quote", QUEUED), ("om_quote", ON_IT)])
        self.assertEqual(self.reactions(), [])
        self.forget()
        self.app.controls.show_recovery_card(self.ctx_topic, {**record, "status": "failed"})
        self.assertEqual(self.reactions(), [("om_quote", FAILED)])

    def test_interrupted_with_its_question_form_waiting_it_loses_on_it_too(self):
        record = {**self.failed(), "status": "interrupted"}
        with mock.patch.object(self.app.questions, "has_native_questions", return_value=True):
            self.app.controls.report_unfinished(self.ctx_topic, record, "中断了", "k", keep_question_forms=True)
        self.assertEqual(self.listed(), [("om_quote", QUEUED), ("om_quote", ON_IT)])


class QuotedAnswerTest(Reactions, QuestionFixture, unittest.TestCase):
    """The question card's copy at the chat's top level (om_copy, routed to the topic) quoted with a typed answer."""

    def setUp(self):
        super().setUp()
        self.backend.declare(questions=True, steering=True)
        route_message(self.ctx.state_dir, CHAT, "om_copy", self.job.topic_id)
        self.app.messenger.publish_card = mock.Mock(return_value=True)
        self.forget()

    def answer(self, message, text="全部"):
        self.app.handle_event({"chat_id": CHAT, "sender_id": "ou_user", "message_id": message, "content": text,
                               "root_id": "om_copy", "parent_id": "om_copy"}, self.ctx, fetch_message_details=False)

    def second_question(self):
        self.record["questions"].append({"id": "order", "question": "顺序？", "options": []})
        self.path.write_text(json.dumps(self.record))

    def test_the_running_task_takes_it_and_it_says_done(self):
        self.answer("om_ans")
        self.assertEqual(self.rpc.answer.call_args.args[1]["scope"]["answers"][0], "全部")
        self.assertEqual(json.loads(self.path.read_text())["status"], "answered")
        self.assertEqual(self.reactions(), [("om_ans", DONE)])

    def test_its_task_gone_it_is_a_continuation_with_its_reactions(self):
        self.job.backend_control = None
        self.answer("om_ans")
        continuation = self.app.runtime.jobs.queue.get_nowait()
        self.assertEqual((continuation.message_id, continuation.top_message), ("answer-" + self.token, "om_ans"))
        self.assertEqual(self.reactions(), [("om_ans", QUEUED)])  # Its asking task is still registered before it.

    def test_a_note_for_several_questions_waits_then_goes_with_the_answer(self):
        self.second_question()
        self.answer("om_note", "另外看日志")
        note, = self.app.questions.notes.held_notes(self.ctx_topic, CHAT, "held")
        self.assertTrue(note["top"])
        self.assertEqual(self.reactions(), [("om_note", QUEUED)])
        self.holding(QUEUED)
        self.app.questions.submit_answer(self.ctx_topic, CHAT, self.token, {"option_0": "0", "answer_1": "先检查"}, "c1")
        self.assertIn("另外看日志", json.dumps(self.rpc.answer.call_args.args[1], ensure_ascii=False))
        self.assertEqual(self.reactions()[-1], ("om_note", DONE))
        self.assertIn(mock.call(self.ctx.profile, "om_note", f"r-{QUEUED}"), self.app.messenger.unreact.call_args_list)

    def test_a_note_withdrawn_leaves_nothing_one_kept_for_the_next_round_runs_with_its_reactions(self):
        self.second_question()
        self.answer("om_note", "另外看日志")
        note, = self.app.questions.notes.held_notes(self.ctx_topic, CHAT, "held")
        self.holding(QUEUED)
        self.app.questions.note_action(self.ctx_topic, CHAT, {"token": note["token"], "verb": "withdraw"}, "c1")
        self.assertIn(mock.call(self.ctx.profile, "om_note", f"r-{QUEUED}"), self.app.messenger.unreact.call_args_list)
        self.answer("om_next", "再看看配置")
        kept, = self.app.questions.notes.held_notes(self.ctx_topic, CHAT, "held")
        self.app.questions.notes.change_note(self.ctx_topic, kept["token"], {"held"}, status="next_round")
        self.app.questions.notes.queue_notes(self.ctx_topic, CHAT, self.app.questions.notes.held_notes(
            self.ctx_topic, CHAT, "next_round"))
        job = self.app.runtime.jobs.queue.get_nowait()
        self.assertEqual((job.message_id, job.top_message), ("note-" + kept["token"], "om_next"))

    def test_refused_it_says_crossmark(self):
        self.path.write_text(json.dumps({**self.record, "display_pending": True}))
        self.answer("om_ans")
        self.rpc.answer.assert_not_called()
        self.assertEqual(self.reactions(), [("om_ans", FAILED)])

    def test_an_answer_in_the_thread_gets_none(self):
        self.receive("om_in", "全部", root="om_question", thread="omt_q")
        self.rpc.answer.assert_called_once()
        self.assertEqual(self.reactions(), [])


if __name__ == "__main__":
    unittest.main()
