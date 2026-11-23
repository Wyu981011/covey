"""A read hung on the network disk holds up its own thread, never every route of the Bridge (T680).

2026-11-23 a click on a question card and a message to the butler both waited minutes before their route, and were let
go in the same tenth of a second: the topic.json read of one topic (an NFS open that hung in D state) was made under
``core/locks.py`` LOCK and ``core/topics.py`` _LOCK, which every route takes (the workspace list, the topic's model
snapshot, the butler's topic.json, a new alias). The 专项卡 asks ``topic_number`` of each of its topics every second.

``Threads.hang`` makes reads of one file hang as that open did, until the test lets them go; ``Threads.finishes`` runs a
route on its own thread and says whether it ended in time.
"""
from __future__ import annotations

import contextlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support import make_context
from support.butler import BUTLER, CHAT, switch_on
from support.world import UnifiedCase
from covey.app import project_facts
from covey.core import topics, workspaces
from covey.core.jobs import upsert_job_record
from covey.core.locks import LOCK
from covey.core.topics import context_for_topic, remember_topic_message, topic_file, topic_label, topic_number
from covey.feishu import message_request

PATIENCE = 5.0  # Seconds a route may take here before it counts as held up (it takes milliseconds).


class Threads:
    """Mixin: the threads a test leaves waiting (on a hung read, on a lock a stuck holder has) are let go and joined at
    its cleanup, before its temporary directory goes. ``let_go_first`` is called at the end of setUp."""

    def let_go_first(self):
        self.gates, self.threads = [], []
        self.addCleanup(self.let_go)

    def let_go(self):
        for gate in self.gates:
            gate.set()
        for thread in self.threads:
            thread.join(PATIENCE)

    def in_thread(self, call, name="hung-reader"):
        """``call`` on a thread of its own."""
        thread = threading.Thread(target=call, daemon=True, name=name)
        self.threads.append(thread)
        thread.start()
        return thread

    def hang(self, path):
        """Reads of ``path`` (Path.read_text, what topic.json's readers call) hang, as the open of 2026-11-23 did, until
        the test ends or ``release``. Its ``entered`` is set once a thread waits in one; ``reads`` counts them."""
        hung = SimpleNamespace(path=Path(path), gate=threading.Event(), entered=threading.Event(), reads=0)
        hung.release = hung.gate.set
        self.gates.append(hung.gate)
        original = Path.read_text

        def read_text(path_, *args, **kwargs):
            if Path(path_) == hung.path:
                hung.reads += 1
                hung.entered.set()
                hung.gate.wait(60)
            return original(path_, *args, **kwargs)

        patch = mock.patch.object(Path, "read_text", read_text)
        patch.start()
        self.addCleanup(patch.stop)
        return hung

    def finishes(self, call, timeout=PATIENCE):
        """(whether ``call`` ended within ``timeout`` on its own thread, what it returned). One that did not goes on once
        the test lets go of what holds it up; what it raised is raised here."""
        done, result = threading.Event(), {}

        def run():
            try:
                result["value"] = call()
            except BaseException as exc:  # noqa: BLE001 - raised on the test's thread
                result["error"] = exc
            finally:
                done.set()

        self.in_thread(run, name="route-under-test")
        ended = done.wait(timeout)
        if "error" in result:
            raise result["error"]
        return ended, result.get("value")

    def holding(self, *locks):
        """Another thread holds ``locks`` until the test ends: a holder stuck on the network disk."""
        taken, gate = threading.Event(), threading.Event()
        self.gates.append(gate)

        def hold():
            with contextlib.ExitStack() as stack:
                for lock in locks:
                    stack.enter_context(lock)
                taken.set()
                gate.wait(60)

        self.in_thread(hold, name="stuck-holder")
        self.assertTrue(taken.wait(PATIENCE))


def free(lock) -> bool:
    """Whether another thread can take ``lock`` now (it is let go again at once)."""
    taken = []

    def take():
        if lock.acquire(timeout=1.0):
            taken.append(True)
            lock.release()

    thread = threading.Thread(target=take, daemon=True)
    thread.start()
    thread.join(PATIENCE)
    return bool(taken)


class RouteCase(Threads, UnifiedCase):
    """The Bridge with the butler on in its private chat CHAT, two topics A and B (A as a project's member would be),
    the card ``om_card_b`` of B, and no T number known yet (a Bridge that has just started)."""

    def setUp(self):
        switch_on(self)
        self.addCleanup(message_request.configure_top_level, None)
        super().setUp()
        self.app.runtime.state_dir = self.state = self.ctx.state_dir
        cards = iter(range(100))
        for app in self.app.apps.values():
            app.cards.create_streaming_reply = mock.Mock(
                side_effect=lambda *a, **k: SimpleNamespace(message_id=f"om_card{next(cards)}", card_id="c"))
            app.cards.set_task_element = mock.Mock(return_value=True)
        patch = mock.patch.object(topics, "_numbers", {}, create=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.a = self.open("om_a")
        self.b = self.open("om_b")
        remember_topic_message(self.state, self.b, CHAT, "om_card_b")
        topics._numbers.clear()
        self.let_go_first()

    def open(self, root) -> str:
        """A topic of its own (a 话题区), opened at ``root``: its id."""
        _, target = self.app.topics.route(self.ctx, {"chat_id": CHAT, "message_id": root, "root_id": root})
        return target.topic_id

    def send(self, mid, content="task"):
        """The owner's message ``mid`` at the top level of CHAT: the butler's."""
        event = {"chat_id": CHAT, "chat_type": "p2p", "sender_id": "owner", "message_id": mid, "root_id": "",
                 "content": content}
        with mock.patch("covey.app.app.enrich_incoming_event") as enrich:
            enrich.return_value = SimpleNamespace(text=content, display_text=content, event=event)
            self.app.handle_event(event, self.ctx)

    def click_b(self):
        """The route of a click on B's card (app/card_routing.py: what comes before ``route``)."""
        routed = self.app.topics.route_or_refuse(self.ctx, {"chat_id": CHAT, "message_id": "om_card_b",
                                                            "event_id": "ev_b"})
        return routed[1].topic_id

    def queued(self, mid):
        job = self.app.runtime.jobs.find(0, mid)
        return job.topic_id if job is not None else None

    def done(self, mid):
        """The turn of message ``mid`` ended well and left the registry: the next message is a turn of its own."""
        job = self.app.runtime.jobs.find(0, mid)
        upsert_job_record(self.state, job.message_id, status="done", topic_id=job.topic_id, chat_id=CHAT,
                          job_id=job.job_id)
        self.app.runtime.jobs.unregister(job)


class HungTopicTest(RouteCase):
    """The incident: one topic's topic.json read hangs, its number asked for as the 专项卡 asks it each second."""

    def hang_a(self, ask):
        """A's topic.json hung, and ``ask`` (about A) waiting in it on a thread of its own."""
        hung = self.hang(topic_file(self.state, self.a))
        self.in_thread(ask)
        self.assertTrue(hung.entered.wait(PATIENCE))
        return hung

    def test_a_click_on_another_topics_card_routes_while_one_topics_number_hangs(self):
        self.hang_a(lambda: topic_number(self.state, self.a))
        ended, topic = self.finishes(self.click_b)
        self.assertTrue(ended, "a click on B's card waited for A's hung read")
        self.assertEqual(topic, self.b)

    def test_a_message_to_the_butler_is_queued_while_a_project_card_reads_a_hung_member(self):
        self.send("om_1")  # The butler's topic.json is there, as on a Bridge that has run.
        self.done("om_1")
        self.hang_a(lambda: project_facts.member_view(self.state, self.a, time.time()))
        ended, _ = self.finishes(lambda: self.send("om_2"))
        self.assertTrue(ended, "the butler's message waited for a member's hung read in the 专项卡")
        self.assertEqual(self.queued("om_2"), BUTLER)

    def test_the_locks_stay_free_while_a_topic_number_read_hangs(self):
        self.hang_a(lambda: topic_label(self.state, self.a))
        self.assertTrue(free(LOCK), "topic_number holds LOCK across its read")
        self.assertTrue(free(topics._LOCK), "topic_number holds _LOCK across its read")

    def test_the_hung_topic_still_gets_its_number_once_the_read_comes_back(self):
        number = json.loads(topic_file(self.state, self.a).read_text())["topic_number"]
        hung = self.hang(topic_file(self.state, self.a))
        got = []
        thread = self.in_thread(lambda: got.append(topic_label(self.state, self.a)))
        self.assertTrue(hung.entered.wait(PATIENCE))
        hung.release()
        thread.join(PATIENCE)
        self.assertEqual(got, [f"T{number}"])


class StuckHolderTest(RouteCase):
    """Another thread holds LOCK and _LOCK, stuck on the network disk: a route in a topic that is there takes neither."""

    def test_a_click_on_a_known_card_routes(self):
        self.holding(LOCK, topics._LOCK)
        ended, topic = self.finishes(self.click_b)
        self.assertTrue(ended, "a click on a known card waited for LOCK or _LOCK")
        self.assertEqual(topic, self.b)

    def test_a_message_to_the_butler_reaches_its_route(self):
        self.send("om_1")
        routed = []
        for app in self.app.apps.values():  # After the route: the submission, which registers its job under LOCK.
            app.handle_event = mock.Mock(side_effect=lambda event, target, **kwargs: routed.append(target.topic_id))
        self.holding(LOCK, topics._LOCK)
        ended, _ = self.finishes(lambda: self.send("om_2"))
        self.assertTrue(ended, "the butler's message waited for LOCK or _LOCK before its route")
        self.assertEqual(routed, [BUTLER])

    def test_an_alias_is_written_under_its_own_lock(self):
        self.holding(LOCK, topics._LOCK)
        ended, _ = self.finishes(lambda: remember_topic_message(self.state, self.b, CHAT, "om_new_card"))
        self.assertTrue(ended, "remembering a card's alias waited for _LOCK")
        self.assertEqual(topics.message_topic(self.state, CHAT, "om_new_card"), self.b)

    def test_the_workspace_list_and_a_topics_model_snapshot_are_read_without_lock(self):
        app, target = self.app.topics.route(self.ctx, {"chat_id": CHAT, "message_id": "om_card_b"})
        self.holding(LOCK)
        ended, config = self.finishes(lambda: workspaces.load_config(self.state, self.ctx.default_workdir))
        self.assertTrue(ended, "load_config waited for LOCK")
        self.assertIn(config["default"], config["workspaces"])
        ended, configured = self.finishes(lambda: app.models.configured_context(target))
        self.assertTrue(ended, "configured_context waited for LOCK")
        self.assertEqual(configured.topic_id, self.b)


class FewerReadsTest(RouteCase):
    """What a route no longer reads: a T number known, the workspace list in a topic that is there."""

    def test_a_known_number_is_not_read_again(self):
        number = topic_number(self.state, self.a)
        hung = self.hang(topic_file(self.state, self.a))
        hung.release()  # Counted only.
        for _ in range(3):
            self.assertEqual(topic_number(self.state, self.a), number)
        self.assertEqual(hung.reads, 0)

    def test_a_route_in_a_topic_that_is_there_reads_no_workspace_list(self):
        hung = self.hang(workspaces.config_path(self.state))
        hung.release()  # Counted only.
        self.assertEqual(self.click_b(), self.b)
        self.assertEqual(hung.reads, 0)
        self.open("om_new")  # A new topic still starts in the default workspace.
        self.assertGreater(hung.reads, 0)


class ContextTest(Threads, unittest.TestCase):
    """context_for_topic on its own: the lookup without a lock, the writes under _LOCK as before."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.ctx = make_context(self.root, options={"harness_id": "claude"})
        patch = mock.patch.object(topics, "_numbers", {}, create=True)
        patch.start()
        self.addCleanup(patch.stop)
        self.let_go_first()

    def topic(self, event, **kwargs):
        return context_for_topic(self.ctx, {"chat_id": "oc_chat", **event}, lambda _: self.root, **kwargs)

    def test_concurrent_first_messages_of_one_topic_make_it_once(self):
        found, start = [], threading.Barrier(8)

        def first():
            start.wait()
            found.append(self.topic({"message_id": "om_root"}).topic_id)

        threads = [threading.Thread(target=first) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(PATIENCE)
        self.assertEqual(len(set(found)), 1)
        self.assertEqual(json.loads((self.ctx.state_dir / "topics" / "counter.json").read_text()), {"next": 2})
        self.assertEqual(topic_number(self.ctx.state_dir, found[0]), 1)

    def test_a_new_topic_starts_where_default_says_and_one_there_never_asks(self):
        elsewhere = self.root / "elsewhere"
        asked = []

        def default():
            asked.append(True)
            return make_context(self.root, options={"harness_id": "claude"}, workspace_name="other", workdir=elsewhere)

        made = self.topic({"message_id": "om_root"}, default=default)
        self.assertEqual((made.workspace_name, made.workdir, len(asked)), ("other", elsewhere, 1))
        again = self.topic({"message_id": "om_card", "root_id": "om_root", "thread_id": "omt"}, default=default)
        self.assertEqual((again.topic_id, again.workspace_name, len(asked)), (made.topic_id, "other", 1))
        self.assertEqual(topics.message_topic(self.ctx.state_dir, "oc_chat", "om_card"), made.topic_id)

    def test_a_topic_that_is_there_is_found_without_writing_or_locking(self):
        made = self.topic({"message_id": "om_root"})
        self.holding(LOCK, topics._LOCK)
        with mock.patch.object(topics, "write_private_text") as write:
            ended, found = self.finishes(lambda: self.topic({"message_id": "om_root"}))
        self.assertTrue(ended, "finding a topic that is there waited for _LOCK")
        self.assertEqual(found.topic_id, made.topic_id)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
