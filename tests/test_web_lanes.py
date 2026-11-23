"""网页工作台同步的快看与全量 (app/web_sync.py, app/web_collect.py, core/store.py; T673, 2026-11-23): what runs, asks or just ended reaches
the page within seconds whatever the full pass is doing. Live on 2026-11-23 the owner answered T646's question at 09:07:52 and the page
still said 1 件事要你处理 minutes later: the one push thread built 25 quiet topics before the hot ones every step, a read stuck on the network
disk (an open of T646's topic.json, of jobs/.journal under the index's lock) held it 60 s at a time, and each time it started over with
every cache empty and a new full pass (120 s of reads, up to 82 thousand file calls a step).

- A read of the pass that hangs holds up no quick look: the pass has its own thread, the quick look posts on its own.
- A read of the pass older than what the page has of its topic is never sent after it.
- The caches drop their oldest when full, never all at once; a collector made again after a stuck read keeps them.
- A quick look gives its step up when another thread holds an index's lock (core/store.py bounded), and leaves no thread behind for it.
- A job or question this process writes wakes the quick look at once (core/store.py listen).
- A project is built again only when it changed; a T number is read once."""
from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from support.records import write_job, write_topic

from covey.app import web_collect as app_collect, web_sync as app_web, web_turns
from covey.app.web_collect import Collector
from covey.core import board_read, project_memory, store, web_sync
from covey.core.history_storage import append_history
from covey.core.state import read_object, write_json
from covey.core.store import directory_store
from test_web_sync import CHAT, OTHER, PID, T0, TOKEN, TOPIC, WebCase

QUIET = "e" * 32


def wait_for(condition, seconds=5.0):
    """Whether ``condition()`` came true within ``seconds``."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.02)
    return bool(condition())


class LanesCase(WebCase):
    def run_threads(self):
        """The feature's threads, started as the Bridge starts them; stopped and joined at cleanup."""
        threads = [threading.Thread(target=target, args=(None,), name=name, daemon=True) for name, target in self.sync.threads()]
        for thread in threads:
            thread.start()

        def stop():
            self.runtime.shutdown.set()
            for thread in threads:
                thread.join(5)
        self.addCleanup(stop)
        return threads

    def states(self, topic=TOPIC):
        return [item["data"]["state"] for item in self.web.items("topic") if item["key"] == topic]


class SlowPassTest(LanesCase):
    def test_a_read_of_the_pass_that_hangs_holds_up_no_quick_look(self):
        """Live 09:07-09:10: the push thread was stuck in a pass's read and the owner's answer reached the page minutes late."""
        self.topic(QUIET, number=20, title="安静的话题")
        self.topic(status="running", lines=(("user", "做一下"),))
        entered, release = threading.Event(), threading.Event()
        real = Collector.topic_items

        def topic_items(collector, state, chat, topic, records, now):
            if topic == QUIET and not release.is_set():
                entered.set()
                release.wait(20)  # An NFS open that does not return.
            return real(collector, state, chat, topic, records, now)
        with mock.patch.object(Collector, "topic_items", topic_items):
            self.run_threads()
            self.addCleanup(release.set)  # Before the threads are stopped (the last cleanup added runs first): the hung read returns.
            self.assertTrue(entered.wait(15), self.logs)
            self.assertTrue(wait_for(lambda: "在做" in self.states(), 10), (self.states(), self.logs))
            write_job(self.state, f"k-{TOPIC[:4]}", status="done")
            self.assertTrue(wait_for(lambda: self.states()[-1:] == ["做完"], 10), (self.states(), self.logs))
            self.assertFalse(release.is_set())  # All the while the pass's read hung.
            self.assertNotIn(QUIET, {item["key"] for item in self.web.items("topic")})

    def test_a_pass_step_left_behind_says_where_it_was_and_leaves_its_topic_out(self):
        """Live 08:38 and 09:07 a stuck step was logged with no topic: where it was is in the line now."""
        self.topic(QUIET, number=20, title="安静的话题")
        hang = threading.Event()
        self.addCleanup(hang.set)
        real = Collector.topic_items

        def topic_items(collector, state, chat, topic, records, now):
            if topic == QUIET and not hang.is_set():
                hang.wait(10)
            return real(collector, state, chat, topic, records, now)

        def step():
            put = self.sync.pass_once()
            if any("leaves topic" in line for line in self.logs):
                self.runtime.shutdown.set()
            return put
        guard = threading.Timer(8, self.runtime.shutdown.set)
        guard.start()
        self.addCleanup(guard.cancel)
        with mock.patch.object(Collector, "topic_items", topic_items), mock.patch.object(app_web, "STUCK_SECONDS", 0.3):
            self.sync.loop("pass", step, lambda: 0.01, self.sync.start_over_pass, lambda: self.sync.passer.moved,
                           where=lambda: self.sync.passer.doing)
        self.assertTrue(any("web sync pass stuck" in line and f"at: topic {QUIET[:12]}" in line for line in self.logs), self.logs)
        self.assertTrue(any(f"web sync pass leaves topic {QUIET[:12]}" in line for line in self.logs), self.logs)

    def test_a_quick_look_is_left_behind_sooner_than_the_pass(self):
        self.assertLess(app_web.HOT_STUCK_SECONDS, app_web.STUCK_SECONDS)


class FreshTest(LanesCase):
    def test_a_read_of_the_pass_older_than_the_quick_look_s_is_not_sent(self):
        """The pass read the topic while its question waited; the owner answered and a quick look pushed 在做: the pass's 等你 never goes."""
        self.topic(status="waiting_user")
        self.question()
        self.sync.pass_once(T0)  # No quick look yet: the pass reads the topic itself, 等你, into the backlog.
        self.assertIn(("topic", TOPIC), self.sync.backlog)
        row = read_object(self.state / "questions" / f"{TOKEN}.json")
        write_json(self.state / "questions" / f"{TOKEN}.json", {**row, "status": "answered", "answers": {"q1": {"answers": ["A"]}}})
        write_job(self.state, f"k-{TOPIC[:4]}", status="running")
        self.sync.push_hot(T0 + 1)
        self.sync.push_hot(T0 + 2)
        self.assertEqual(self.states(), ["在做"])
        self.assertEqual([item["data"]["state"] for item in self.web.items("question")], ["answered"])
        self.assertEqual(self.sync.backlog, {})

    def test_an_item_of_an_older_read_left_in_the_backlog_is_dropped(self):
        self.topic(status="running")
        stale = web_sync.item("question", "tok-stale-0001", {"topic_key": TOPIC, "state": "open"})
        self.sync.backlog[("question", "tok-stale-0001")] = (stale, TOPIC, self.sync.shared.next_seq())
        self.sync.push_hot(T0)  # A quick look reads TOPIC now, after that read.
        self.assertNotIn("tok-stale-0001", {item["key"] for item in self.web.items("question")})
        self.assertEqual(self.sync.backlog, {})

    def test_a_topic_a_quick_look_built_after_the_pass_ended_is_not_deleted(self):
        self.topic()
        self.sync.push_once(T0)
        with self.sync.backlog_lock:
            self.sync.deletions.append((self.sync.shared.next_seq(), [{"type": "topic", "key": TOPIC}]))
        self.sync.collector.touch(TOPIC)  # Written to again: the quick look reads it after the pass that missed it.
        self.sync.push_hot(T0 + 1)
        self.assertFalse([row for batch in self.web.upserts for row in batch["deleted"] if row["key"] == TOPIC])


class CacheTest(LanesCase):
    def test_ended_turns_read_once_stay_read_however_many_a_pass_builds(self):
        """512 ended turns' extras were cleared at once, every 26 topics of a pass: each pass read the trace files again."""
        collector = Collector(self.env)
        jobs = [{"message_id": f"om_{n}", "job_id": n, "updated_at": "2026-11-23T09:00:00+08:00"} for n in range(600)]
        with mock.patch.object(web_turns, "extras", return_value={"usage": {"total": 1}}) as read:
            for job in jobs:
                collector.ended_extras(self.state, job)
            for job in jobs:
                collector.ended_extras(self.state, job)
        self.assertEqual(read.call_count, 600)

    def test_histories_read_once_stay_read_for_a_pass_of_hundreds_of_topics(self):
        topics = [f"{n:032x}" for n in range(300)]
        for topic in topics:
            append_history(self.state / "topics" / topic / "history.jsonl", "user", "你好", {"message_id": "m1"})
        collector = Collector(self.env)
        with mock.patch.object(app_collect, "history_lines", wraps=app_collect.history_lines) as read:
            for topic in topics:
                collector.rows(self.state, topic)
            for topic in topics:
                collector.rows(self.state, topic)
        self.assertEqual(read.call_count, 300)

    def test_a_full_cache_drops_its_oldest_quarter_and_a_hit_is_kept(self):
        from covey.app.web_collect import Shared
        shared = Shared()
        for n in range(8):
            shared.keep(shared.extra, n, {"n": n}, 8)
        self.assertEqual(shared.recall(shared.extra, 0), {"n": 0})  # Now the newest.
        shared.keep(shared.extra, 8, {"n": 8}, 8)
        self.assertEqual(sorted(shared.extra), [0, 3, 4, 5, 6, 7, 8])
        self.assertIsNone(shared.recall(shared.extra, 1))

    def test_starting_over_after_a_stuck_read_keeps_what_was_read(self):
        """Live: each stuck read made a new collector with every cache empty and a new full pass of cold reads (120 s)."""
        self.topic()
        self.sync.push_once(T0)
        self.sync.start_over()
        # Renamed: the pass builds again only a topic whose inputs changed (T678), and its ended turn is as it was.
        write_topic(self.state, topic_id=TOPIC, chat_id=CHAT, harness_id="claude", topic_number=7, origin={"title": "整理账单（二）"},
                    workspace_name="ws1")
        with mock.patch.object(web_turns, "extras", wraps=web_turns.extras) as extras, \
                mock.patch.object(web_turns, "ended_figures", wraps=web_turns.ended_figures) as figures, \
                mock.patch.object(Collector, "topic_items", autospec=True, side_effect=Collector.topic_items) as built:
            self.sync.push_once(T0 + 1)  # The new pass builds the topic again.
        self.assertIn(TOPIC, [call.args[3] for call in built.call_args_list])
        self.assertEqual((extras.call_count, figures.call_count), (0, 0))


class BusyIndexTest(LanesCase):
    def hold(self, folder="jobs"):
        """The index of ``folder`` held by another thread (one stuck in an NFS open of its journal, live 09:21-09:23)."""
        held, release = threading.Event(), threading.Event()
        lock = directory_store(self.state / folder).lock

        def run():
            with lock:
                held.set()
                release.wait(10)
        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        self.assertTrue(held.wait(5))
        self.addCleanup(lambda: (release.set(), thread.join(5)))
        return release

    def test_a_quick_look_gives_its_step_up_and_goes_on_once_the_index_is_free(self):
        self.topic(status="running")
        release = self.hold()
        with mock.patch.object(app_web, "HOT_WAIT", 0.2):
            began = time.monotonic()
            self.assertEqual(self.sync.push_hot(T0), 0)
            self.assertLess(time.monotonic() - began, 3)
            self.assertEqual(self.sync.push_hot(T0 + 1), 0)
        self.assertEqual(sum("web sync push waits" in line for line in self.logs), 1)
        release.set()
        self.assertGreater(self.sync.push_hot(T0 + 2), 0)
        self.assertTrue(any("web sync push goes on" in line for line in self.logs))
        self.assertEqual(self.states(), ["在做"])

    def test_bounded_raises_busy_and_outside_it_a_query_waits(self):
        write_job(self.state, "k-1", topic_id=TOPIC, chat_id=CHAT, job_id=1, status="done")
        jobs = directory_store(self.state / "jobs")
        jobs.query()
        release = self.hold()
        with store.bounded(0.1), self.assertRaises(store.Busy):
            jobs.query(topic_id=TOPIC)
        threading.Timer(0.3, release.set).start()
        began = time.monotonic()
        self.assertEqual(len(jobs.query(topic_id=TOPIC)), 1)  # Not bounded: waits for the lock, as every other reader does.
        self.assertGreater(time.monotonic() - began, 0.2)


class WakeTest(LanesCase):
    def test_a_job_this_process_writes_wakes_the_quick_look(self):
        """The owner's answer on a card is written by this process: the page has it at once, not at the next tick."""
        config = read_object(self.state / "web.json")
        write_json(self.state / "web.json", {**config, "push_seconds": 30})
        self.topic(status="running", lines=(("user", "做一下"),))
        self.run_threads()
        self.assertTrue(wait_for(lambda: "在做" in self.states(), 10), self.logs)
        time.sleep(0.3)  # The quick look waits its 30 seconds now.
        write_job(self.state, f"k-{TOPIC[:4]}", status="done")
        self.assertTrue(wait_for(lambda: self.states()[-1:] == ["做完"], 10), (self.states(), self.logs))

    def test_listeners_hear_the_journaled_folders_only(self):
        heard = []

        def listener(folder, name):
            heard.append((folder, name))
        store.listen(listener)
        self.addCleanup(store.unlisten, listener)
        write_job(self.state, "k-1", topic_id=TOPIC, chat_id=CHAT, job_id=1, status="done")
        (self.state / "elsewhere").mkdir()
        write_json(self.state / "elsewhere" / "x.json", {})
        self.assertEqual([folder for folder, _ in heard], ["jobs"])

    def test_a_failing_listener_fails_no_write(self):
        def listener(folder, name):
            raise RuntimeError("boom")
        store.listen(listener)
        self.addCleanup(store.unlisten, listener)
        write_job(self.state, "k-1", topic_id=TOPIC, chat_id=CHAT, job_id=1, status="done")
        self.assertEqual(read_object(self.state / "jobs" / "k-1.json").get("status"), "done")


class ProjectRowsTest(LanesCase):
    def test_a_project_that_did_not_change_is_not_read_again(self):
        self.thread(OTHER, "对账", 8, status="done")
        project_memory.add(self.state, PID, "用新库", "decision", "owner", now=T0)
        self.sync.push_once(T0)
        with mock.patch.object(project_memory, "entries", wraps=project_memory.entries) as read:
            self.sync.push_once(T0 + 1)  # No pass due: a quick look alone, every second.
            self.assertEqual(read.call_count, 0)
            project_memory.add(self.state, PID, "对账一致才算完", "constraint", "lead", now=T0 + 2)
            self.sync.push_once(T0 + 3)
            self.assertEqual(read.call_count, 1)
        texts = [row["text"] for row in self.web.items("project")[-1]["data"]["memory"]]
        self.assertEqual(texts, ["用新库", "对账一致才算完"])

    def test_a_topic_s_number_is_read_once(self):
        self.thread(OTHER, "对账", 8, status="done")
        collector = Collector(self.env)
        with mock.patch.object(board_read, "topic_label", wraps=board_read.topic_label) as read:
            self.assertEqual([collector.topic_number(self.state, OTHER) for _ in range(5)], [8] * 5)
        self.assertEqual(read.call_count, 1)


class FailingTopicTest(LanesCase):
    def raising(self, bad):
        real = Collector.topic_items

        def topic_items(collector, state, chat, topic, records, now):
            if topic in bad:
                raise TypeError("a record of a shape the build does not know")
            return real(collector, state, chat, topic, records, now)
        return mock.patch.object(Collector, "topic_items", topic_items)

    def test_a_hot_topic_whose_build_raises_holds_up_no_other(self):
        """One topic's build that raised failed the whole step: none of the others went out either."""
        self.topic(status="running", lines=(("user", "做一下"),))
        self.topic(OTHER, number=8, title="写周报", status="running", lines=(("user", "写吧"),))
        with self.raising({TOPIC}):
            self.sync.push_once(T0)
            self.sync.push_once(T0 + 1)
        self.assertEqual(self.states(OTHER), ["在做"])
        self.assertEqual(self.states(TOPIC), [])
        self.assertEqual(sum(f"web sync topic {TOPIC[:12]} not built: TypeError" in line for line in self.logs), 1)
        self.sync.push_once(T0 + 2)
        self.assertEqual(self.states(TOPIC), ["在做"])

    def test_a_topic_whose_build_raises_in_a_pass_is_not_deleted(self):
        self.topic()
        self.topic(OTHER, number=8, title="写周报")
        self.sync.push_once(T0)
        with self.raising({TOPIC}):
            self.sync.push_once(T0 + web_sync.FULL_SECONDS + 1)  # The next pass: its build raises.
        self.assertFalse([row for batch in self.web.upserts for row in batch["deleted"] if row["key"] == TOPIC])

    def test_a_quick_look_given_up_keeps_what_it_was_asked_to_build(self):
        self.topic()
        self.sync.push_once(T0)
        write_topic(self.state, topic_id=TOPIC, chat_id=CHAT, harness_id="claude", topic_number=7, origin={"title": "改了名"},
                    workspace_name="ws1")
        self.sync.collector.touch(TOPIC)  # The page acted on it: the next quick look builds it whatever the indexes say.
        release = BusyIndexTest.hold(self)
        with mock.patch.object(app_web, "HOT_WAIT", 0.2):
            self.assertEqual(self.sync.push_hot(T0 + 1), 0)  # Given up: it must still be asked of the next look.
        release.set()
        self.sync.push_hot(T0 + 2)
        titles = [item["data"]["title"] for item in self.web.items("topic") if item["key"] == TOPIC]
        self.assertEqual(titles[-1], "改了名")

    def test_a_topic_the_pass_left_to_a_stuck_read_is_not_deleted_when_the_read_ends(self):
        self.topic()
        self.topic(OTHER, number=8, title="写周报")
        self.topic(QUIET, number=20, title="安静的话题")
        self.sync.push_once(T0)

        class Read:
            alive = True

            def is_alive(self):
                return self.alive
        read = Read()
        self.sync.shared.stuck[TOPIC] = read
        real = board_read.topic_jobs

        def topic_jobs(state, chat):
            found = real(state, chat)
            return {key: found[key] for key in sorted(found, key=lambda key: key != TOPIC)}
        with mock.patch.object(app_collect, "PASS_SLICE", 1), mock.patch.object(board_read, "topic_jobs", topic_jobs):
            self.sync.pass_once(T0 + web_sync.FULL_SECONDS + 1)  # Takes TOPIC off its list while its read is stuck, builds one more.
            self.assertTrue(self.sync.passer.pass_left)
            read.alive = False  # The read returns before the pass ends.
            while self.sync.passer.pass_left:
                self.sync.pass_once(T0 + web_sync.FULL_SECONDS + 2)
        self.assertTrue(self.sync.passer.pass_done)
        self.assertFalse([row for _, rows in self.sync.deletions for row in rows if row["key"] == TOPIC])

class OwnerChatTest(LanesCase):
    """2026-11-23 15:26-15:49 (T673): the client's NFSv4 state recovery could not start (dmesg kthread_run: -4) and opens hung for
    minutes; the web page's three threads each opened owner-chat.json every step and all three were caught stuck in that open."""

    def access(self):
        from covey.app.access import Access
        return Access(SimpleNamespace(state_dir=self.state, owner_open_id="ou_owner", log=self.logs.append))

    def test_the_owner_chat_is_read_once_until_its_file_changes(self):
        from covey.app import access as app_access
        write_json(self.state / "owner-chat.json", {"owner": "ou_owner", "chat_id": CHAT})
        access = self.access()
        with mock.patch.object(app_access, "read_object", wraps=app_access.read_object) as read:
            self.assertEqual({access.owner_chat() for _ in range(50)}, {CHAT})
            self.assertEqual(read.call_count, 1)
            write_json(self.state / "owner-chat.json", {"owner": "ou_owner", "chat_id": "oc_another0123"})
            self.assertEqual(access.owner_chat(), "oc_another0123")  # Another process wrote it: a new inode.
            self.assertEqual(read.call_count, 2)
            access.remember_owner_chat(CHAT)  # This process writes it: kept as written, not read again.
            self.assertEqual(access.owner_chat(), CHAT)
            self.assertEqual(read.call_count, 2)


class InboxQuietTest(LanesCase):
    def test_an_empty_poll_reads_no_settings_or_tidy_file(self):
        with mock.patch.object(app_web.WebSync, "push_settings") as settings, mock.patch.object(app_web.WebSync, "push_tidy") as tidy:
            self.assertEqual(self.sync.inbox_once(), 0)
        self.assertEqual((settings.call_count, tidy.call_count), (0, 0))

    def test_a_settings_read_that_hangs_holds_up_no_poll(self):
        """15:28 and 15:31: the inbox was left behind twice, stuck 60 s in what each poll read after its request."""
        hang = threading.Event()
        self.addCleanup(hang.set)
        done = threading.Event()
        with mock.patch.object(app_web.WebSync, "push_settings", side_effect=lambda *args, **kwargs: hang.wait(10)), \
                mock.patch.object(app_web.WebSync, "push_tidy", side_effect=lambda *args, **kwargs: hang.wait(10)):
            threading.Thread(target=lambda: (self.sync.inbox_once(), done.set()), daemon=True).start()
            self.assertTrue(done.wait(3))

    def test_the_config_is_read_again_only_when_its_file_changed_and_the_loops_read_none(self):
        client = self.sync.client
        self.assertEqual(client.known("push_seconds", 7.0), 7.0)  # Before any read: the default, no file touched.
        with mock.patch.object(web_sync, "load_config", wraps=web_sync.load_config) as load:
            first = client.settings()
            client.loaded = 0.0  # Its check is due.
            self.assertIs(client.settings(), first)
            self.assertEqual(load.call_count, 1)
            config = read_object(self.state / "web.json")
            write_json(self.state / "web.json", {**config, "push_seconds": 2})
            client.loaded = 0.0
            self.assertEqual(client.settings().push_seconds, 2.0)
            self.assertEqual(load.call_count, 2)
            self.assertEqual(client.known("push_seconds", 7.0), 2.0)
            self.assertEqual(load.call_count, 2)


if __name__ == "__main__":
    unittest.main()
