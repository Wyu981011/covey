"""网页工作台同步的全量补扫跳过没变的话题 (app/web_collect.py Collector.inputs, unchanged; T678, 2026-11-23). After T673 the pass had a
thread of its own, but each pass still built every topic of the last 30 days again: on the live state directory 598 topics, 44-83 s and
53-277 thousand file calls a warm pass, on the network disk whose opens of files other processes rewrite hang for minutes. Most of those
topics had not changed since the pass before.

- A topic whose inputs (Collector.inputs: its records, the stats of its own files, what the look read of the board, the projects, the
  collaborations, the relays, its 到点回来看 and 代发 drafts, the switches and the model menu) are those of its last build, and whose items
  the page has, is left unbuilt: no file of it is read but those stats. It is seen all the same: never deleted at the pass's end.
- Any one of those inputs changed: built at the next pass. One whose items change by themselves (a task not ended, a question open) is
  built every pass; one whose 产物 still go up is built again at the next pass (their links come with the upload's ledger).
- Whatever its inputs say, a topic is built again at the latest REBUILD_SECONDS after its last build (each topic its own limit, so they
  do not all come due in one pass); a new process, a new day's empty ``sent``, a post the page refused and a quick look that sent another
  reading of it since all build it again."""
from __future__ import annotations

import os
import unittest
from unittest import mock

from support.records import write_job, write_topic

from covey.app import web_collect as app_collect, web_sync as app_web, web_turns
from covey.app.relay_send import RELAYS
from covey.app.web_collect import Collector
from covey.app.web_sync import WebSync
from covey.core import collab_records, http_upstream, owner_send as owner_send_records, project_proposals, projects, revisits, topic_gist
from covey.core.history_storage import append_history
from covey.core.jobs import job_key, topic_job_records
from covey.core.state import write_json
from test_web_collab import THIRD, CollabCase
from test_web_lanes import QUIET, LanesCase
from test_project_lead import LEAD
from test_web_sync import BUTLER, CHAT, OTHER as OTHER_TOPIC, PID, T0, TOPIC

STEP = 100.0  # Seconds between two passes of a test: past FULL_SECONDS, well within any topic's limit.


class SkipCase(LanesCase):
    def full_pass(self, now, sync=None):
        """The topics a whole pass at ``now`` built (each step of it followed by a quick look that sends what it read, as the two
        threads do), the quick looks' builds among them."""
        sync = sync or self.sync
        with mock.patch.object(Collector, "topic_items", autospec=True, side_effect=Collector.topic_items) as items:
            for _ in range(50):
                sync.push_once(now)
                if not sync.passer.pass_left:
                    break
        return [call.args[3] for call in items.call_args_list]

    def deleted(self):
        return [each for batch in self.web.upserts for each in batch["deleted"]]

    def job_of(self, topic=TOPIC):
        return next(iter(topic_job_records(self.state, topic, chat_id=CHAT)))


class SkipTest(SkipCase):
    def test_a_topic_whose_inputs_did_not_change_is_not_built_or_read_again(self):
        self.topic()
        self.assertIn(TOPIC, self.full_pass(T0))
        posted = len(self.web.items())
        with mock.patch.object(app_collect, "history_lines", wraps=app_collect.history_lines) as history, \
                mock.patch.object(web_turns, "extras", wraps=web_turns.extras) as extras, \
                mock.patch.object(web_turns, "artifacts_of", wraps=web_turns.artifacts_of) as artifacts, \
                mock.patch.object(app_collect.board_read, "topic_label", wraps=app_collect.board_read.topic_label) as label:
            built = self.full_pass(T0 + STEP)
        self.assertNotIn(TOPIC, built)
        self.assertEqual((history.call_count, extras.call_count, artifacts.call_count), (0, 0, 0))
        self.assertNotIn(TOPIC, [call.args[1] for call in label.call_args_list])
        self.assertEqual(len(self.web.items()), posted)  # Nothing sent again,
        self.assertEqual(self.deleted(), [])  # and nothing deleted: the page keeps it as it was.
        self.assertIn(("topic", TOPIC), self.sync.shared.pushed_topics)

    def test_a_pass_of_many_steps_deletes_none_of_the_topics_it_left_unbuilt_and_still_deletes_one_gone(self):
        topics = [f"{n:04x}" + "a" * 28 for n in range(1, 2 * app_collect.PASS_SLICE + 5)]  # topic() keys a job by its first 4
        for number, topic in enumerate(topics, 10):
            self.topic(topic, number=number, title=f"话题{number}")
        self.assertEqual(len([t for t in self.full_pass(T0) if t in topics]), len(topics))
        self.assertEqual([t for t in self.full_pass(T0 + STEP) if t in topics], [])
        self.assertEqual([t for t in self.full_pass(T0 + 2 * STEP) if t in topics], [])
        self.assertEqual(self.deleted(), [])
        # A month on, none had a job in TOPIC_DAYS: the pass does not look at them and deletes them, as before.
        later = T0 + (app_collect.TOPIC_DAYS + 1) * 86400
        self.full_pass(later)
        self.assertEqual(sorted(each["key"] for each in self.deleted() if each["type"] == "topic"), sorted(topics))
        self.assertFalse(set(topics) & set(self.sync.shared.prints))  # What it kept of them goes with them.

    def test_without_what_the_page_has_every_topic_is_built_as_before(self):
        self.topic()
        passer = Collector(self.env, None, self.logs.append)
        for now in (T0, T0 + STEP):
            with mock.patch.object(Collector, "topic_items", autospec=True, side_effect=Collector.topic_items) as items:
                passer.collect_pass(CHAT, now, True)
            self.assertIn(TOPIC, [call.args[3] for call in items.call_args_list])


class ChangeTest(SkipCase):
    """Any input of a topic changed: it is built at the next pass, and left unbuilt again at the one after."""

    def change_builds(self, change, *, settle=None):
        self.topic()
        (settle or (lambda: None))()
        self.full_pass(T0)
        self.assertNotIn(TOPIC, self.full_pass(T0 + STEP))
        change()
        self.assertIn(TOPIC, self.full_pass(T0 + 2 * STEP))
        self.assertNotIn(TOPIC, self.full_pass(T0 + 3 * STEP))

    def test_its_job_record(self):
        self.change_builds(lambda: write_job(self.state, f"k-{TOPIC[:4]}", memory_notes=[{"kind": "remembered", "text": "记下了"}]))

    def test_a_job_record_more(self):
        self.change_builds(lambda: write_job(self.state, "k-2nd", topic_id=TOPIC, chat_id=CHAT, job_id=8, status="done", model="opus"))

    def test_its_history(self):
        self.change_builds(lambda: append_history(self.state / "topics" / TOPIC / "history.jsonl", "user", "再看一下", {"message_id": "m3"}))

    def test_its_topic_json(self):
        self.change_builds(lambda: write_topic(self.state, topic_id=TOPIC, chat_id=CHAT, harness_id="claude", topic_number=7,
                                               origin={"title": "整理账单"}, workspace_name="ws2"))

    def test_a_question_that_ended(self):
        self.change_builds(lambda: self.question(status="answered", answers={"q1": {"answers": ["A"]}}))

    def test_its_gist(self):
        with mock.patch.object(project_proposals, "enabled", return_value=True):
            self.change_builds(lambda: write_json(topic_gist.path(self.state, TOPIC), {"essence": "整理账单", "updated_at": T0}))

    def test_its_revisit(self):
        def revisit():
            revisits.path(self.state, TOPIC).parent.mkdir(parents=True, exist_ok=True)
            write_json(revisits.path(self.state, TOPIC), {"topic_id": TOPIC, "state": revisits.PENDING, "due_at": T0 + 3600,
                                                          "look": "CI 跑完没有"})
        with mock.patch.object(revisits, "enabled", return_value=True):
            self.change_builds(revisit)

    def test_a_draft_of_it(self):
        def draft():
            owner_send_records.write(self.state, {"id": "d1", "topic_id": TOPIC, "status": "drafted", "to": "张三", "text": "周报",
                                                  "created_at": T0})
        with mock.patch.object(app_collect.owner_send, "enabled", return_value=True):
            self.change_builds(draft)

    def test_its_board_group_and_whether_its_result_was_seen(self):
        """What the board's reading says of it (read once a pass, app/pins.py; the board's own times are its record's)."""
        self.topic()
        collector = Collector(self.env, None, self.logs.append)
        collector.look_begins(CHAT, T0)
        records = topic_job_records(self.state, TOPIC, chat_id=CHAT)
        seen = []
        for board, unseen in ((None, set()), ({TOPIC: "result"}, set()), ({TOPIC: "result"}, {TOPIC}), ({TOPIC: "done"}, set()),
                              ({}, set())):
            collector.board, collector.unseen = board, unseen
            seen.append(collector.inputs(self.state, CHAT, TOPIC, records))
        self.assertEqual(len(set(seen)), len(seen))
        collector.board, collector.unseen = {TOPIC: "done", OTHER_TOPIC: "result"}, {OTHER_TOPIC}
        self.assertEqual(collector.inputs(self.state, CHAT, TOPIC, records), seen[3])  # Another topic's group is not its input.

    def test_when_it_joined_a_project(self):
        self.change_builds(lambda: projects.update(self.state, PID, lambda record: record.update(
            joined={**(record.get("joined") or {}), TOPIC: T0 + 150})))

    def test_a_relay_of_its_turn(self):
        def relay():
            record = self.job_of()
            (self.state / RELAYS).mkdir(parents=True, exist_ok=True)
            write_json(self.state / RELAYS / "r1.json", {"state": "sent", "sent_at": T0 + 150,
                                                         "job_key": job_key(str(record.get("message_id") or ""), record.get("job_id"))})
        self.change_builds(relay)

    def test_the_model_menu(self):
        menu = {}
        with mock.patch.object(Collector, "menu", autospec=True, side_effect=lambda collector: dict(menu)):
            self.change_builds(lambda: menu.update({"claude:opus": {"display_name": "Opus 5.5", "harness": "claude", "model": "opus"}}))

    def test_a_switch(self):
        self.topic()
        self.full_pass(T0)
        with mock.patch.object(revisits, "enabled", return_value=True):
            self.assertIn(TOPIC, self.full_pass(T0 + STEP))
            self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP))

    def test_a_change_made_while_it_is_built_is_seen_at_the_next_pass(self):
        """Its inputs are read before anything its build reads: a line written in between builds it again, not never."""
        self.topic()
        real = Collector.topic_items

        def topic_items(collector, state, chat, topic, records, now):
            if topic == TOPIC and not getattr(self, "wrote", False):
                self.wrote = True
                append_history(self.state / "topics" / TOPIC / "history.jsonl", "assistant", "又一行", {"message_id": "m9"})
            return real(collector, state, chat, topic, records, now)
        with mock.patch.object(Collector, "topic_items", topic_items):
            self.sync.push_once(T0)
        self.assertIn(TOPIC, self.full_pass(T0 + STEP))
        self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP))


class CollabChangeTest(CollabCase):
    def test_a_collaboration_of_the_topic_changes_its_inputs(self):
        """Its record rewritten within one tick of the clock (the same mtime and, here, the same size) is a change too."""
        collector = Collector(self.env, None, self.logs.append)
        collector.look_begins(CHAT, T0)
        records = topic_job_records(self.state, THIRD, chat_id=CHAT)
        before = collector.inputs(self.state, CHAT, THIRD, records)
        with mock.patch.object(collab_records, "time", mock.Mock(time=lambda: T0)):  # The same updated_at, so the same size.
            self.collaboration(helpers=(THIRD,), asks=[(THIRD, [], {})])
            collector.look_begins(CHAT, T0 + 1)
            joined = collector.inputs(self.state, CHAT, THIRD, records)
            self.assertNotEqual(before, joined)
            cid = next(iter(collector.collab_now))
            target, first = collab_records.path(self.state, cid), collab_records.path(self.state, cid).stat()
            collab_records.change(self.state, cid, lambda record: {**record, "goal_rev": 6})
        os.utime(target, ns=(first.st_atime_ns, first.st_mtime_ns))
        self.assertEqual(target.stat().st_size, first.st_size)
        collector.look_begins(CHAT, T0 + 2)
        self.assertNotEqual(collector.inputs(self.state, CHAT, THIRD, records), joined)


class VolatileTest(SkipCase):
    def test_a_topic_whose_items_change_by_themselves_has_no_inputs(self):
        collector = Collector(self.env, None, self.logs.append)
        collector.look_begins(CHAT, T0)
        for status in ("queued", "running", "cancel_requested", "waiting_user", "waiting_workspace"):
            with self.subTest(status=status):
                self.topic(status=status)
                self.assertIsNone(collector.inputs(self.state, CHAT, TOPIC, topic_job_records(self.state, TOPIC, chat_id=CHAT)))
        self.topic(status="done")
        records = topic_job_records(self.state, TOPIC, chat_id=CHAT)
        self.assertIsNotNone(collector.inputs(self.state, CHAT, TOPIC, records))
        self.question()  # Pending: it asks.
        self.assertIsNone(collector.inputs(self.state, CHAT, TOPIC, records))
        self.question(status="answered")
        self.assertIsNotNone(collector.inputs(self.state, CHAT, TOPIC, records))

    def test_a_running_topic_the_quick_look_does_not_build_is_built_every_pass(self):
        self.topic(status="running")
        passer, sent = Collector(self.env, None, self.logs.append), {}
        for now in (T0, T0 + STEP, T0 + 2 * STEP):
            with mock.patch.object(Collector, "topic_items", autospec=True, side_effect=Collector.topic_items) as items:
                found, _ = passer.collect_pass(CHAT, now, True, sent=sent)
            sent.update({(each["type"], each["key"]): each["rev"] for each in found})
            self.assertIn(TOPIC, [call.args[3] for call in items.call_args_list])

    def test_the_butler_s_and_a_lead_s_conversations_are_built_once_every_pass(self):
        """They read other topics' files (whom the butler handed on to, a lead's members): no inputs of their own say all of it. Once:
        a lead with jobs was built as the pass started and again in its step."""
        self.butler_topic()
        self.lead_job(status="done")
        append_history(self.state / "topics" / LEAD / "history.jsonl", "user", "进展如何", {"message_id": "m-lead"})
        self.full_pass(T0)
        built = self.full_pass(T0 + STEP)
        self.assertEqual((built.count(BUTLER), built.count(LEAD)), (1, 1))
        self.assertEqual(self.deleted(), [])
        self.assertIn(("topic", LEAD), self.sync.shared.pushed_topics)

    def test_artifacts_going_up_are_read_again_at_the_next_pass_and_those_that_failed_or_went_up_are_not(self):
        self.topic()
        cases = {"going": [{"name": "report.md", "uploading": True}], "failed": [{"name": "report.md", "error": "上传超时"}],
                 "up": [{"name": "report.md", "link": "https://example.invalid/f", "size": 3}]}
        for name, items in cases.items():
            with self.subTest(name), mock.patch.object(web_turns, "artifacts_of", return_value=items) as read:
                fresh = WebSync(self.runtime, self.env)
                fresh.client.opener = http_upstream.opener(direct=True)
                start = T0 + 10_000 * (list(cases).index(name) + 1)
                self.assertIn(TOPIC, self.full_pass(start, fresh))
                again = TOPIC in self.full_pass(start + STEP, fresh)
                settled = TOPIC in self.full_pass(start + STEP + app_collect.FILES_SETTLED, fresh)
                self.assertEqual((again, settled), {"going": (True, True), "failed": (False, False), "up": (False, False)}[name])
                self.assertGreater(read.call_count, 0)


class AgainTest(SkipCase):
    """What builds an unchanged topic again all the same."""

    def test_its_limit_passed(self):
        self.topic()
        self.full_pass(T0)
        limit = app_collect.limit(TOPIC)
        self.assertNotIn(TOPIC, self.full_pass(T0 + limit - STEP))
        self.assertIn(TOPIC, self.full_pass(T0 + limit + 1))
        self.assertNotIn(TOPIC, self.full_pass(T0 + limit + 1 + STEP))

    def test_the_limits_of_a_big_chat_s_topics_spread_over_half_of_rebuild_seconds(self):
        limits = [app_collect.limit(f"{n:032x}") for n in range(600)]
        self.assertTrue(all(app_collect.REBUILD_SECONDS / 2 <= each <= app_collect.REBUILD_SECONDS for each in limits))
        self.assertLess(min(limits), app_collect.REBUILD_SECONDS * 0.55)
        self.assertGreater(max(limits), app_collect.REBUILD_SECONDS * 0.95)
        self.assertEqual(app_collect.limit(TOPIC), app_collect.limit(TOPIC))  # The same topic, the same limit.

    def test_a_new_process(self):
        """A restart: what the page has comes back from sent.json, what the pass kept of the inputs does not; nothing is sent again."""
        self.topic()
        self.full_pass(T0)
        self.sync.save_sent(T0)
        posted = len(self.web.items())
        fresh = WebSync(self.runtime, self.env)
        fresh.client.opener = http_upstream.opener(direct=True)
        self.assertIn(TOPIC, self.full_pass(T0 + STEP, fresh))
        self.assertEqual(len(self.web.items()), posted)
        self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP, fresh))

    def test_a_new_day_s_empty_sent(self):
        """Once a day ``sent`` starts empty, so everything goes once (a page whose database was emptied fills again)."""
        self.topic()
        self.full_pass(T0)
        posted = len(self.web.items())
        self.sync.sent_since = T0 + STEP - app_web.SENT_KEEP_SECONDS
        self.assertIn(TOPIC, self.full_pass(T0 + STEP))
        self.assertIn(("topic", TOPIC), {(each["type"], each["key"]) for each in self.web.items()[posted:]})
        self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP))

    def test_a_post_the_page_refused_goes_once_it_is_back(self):
        """The page was down while the pass read the topic: what was read waits and goes with the next quick look; then the topic is
        left unbuilt, as the page has it."""
        self.topic()
        self.web.fail = 503
        with self.assertRaises(app_web.WebError):
            self.sync.push_once(T0)
        self.assertNotIn(("topic", TOPIC), self.sync.sent)
        self.assertNotIn(TOPIC, [item["key"] for item in self.web.items("topic")])
        self.web.fail = 0
        self.sync.push_hot(T0 + 1)
        self.assertIn(TOPIC, [item["key"] for item in self.web.items("topic")])
        self.assertNotIn(TOPIC, self.full_pass(T0 + STEP))

    def test_a_build_whose_items_never_reached_the_page(self):
        """The step that built the topic was left behind further on (a read stuck after it): its items never went, so the next pass
        builds the topic again although its inputs did not change."""
        self.topic()
        self.topic(QUIET, number=20, title="安静的话题")
        real = Collector.topic_items

        def topic_items(collector, state, chat, topic, records, now):
            if topic == QUIET and not collector.retired:
                self.sync.start_over_pass()  # What the loop does once the step has not moved in STUCK_SECONDS.
            return real(collector, state, chat, topic, records, now)
        with mock.patch.object(Collector, "topic_items", topic_items):
            self.sync.push_once(T0)
        self.assertIn(TOPIC, self.sync.shared.prints)  # Built before the step was left behind,
        self.assertNotIn(TOPIC, [item["key"] for item in self.web.items("topic")])  # but nothing of it went.
        self.assertIn(TOPIC, self.full_pass(T0 + STEP))
        self.assertIn(TOPIC, [item["key"] for item in self.web.items("topic")])
        self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP))

    def test_another_reading_a_quick_look_sent_since(self):
        self.topic()
        self.full_pass(T0)
        self.sync.sent[("topic", TOPIC)] = "another-rev"
        self.assertIn(TOPIC, self.full_pass(T0 + STEP))
        self.assertNotIn(TOPIC, self.full_pass(T0 + 2 * STEP))

    def test_a_pass_left_behind_keeps_what_it_knew_and_one_back_late_writes_nothing(self):
        self.topic()
        self.topic(QUIET, number=20, title="安静的话题")
        self.full_pass(T0)
        old = self.sync.passer
        self.sync.start_over_pass()
        self.assertTrue(old.retired)
        kept = dict(self.sync.shared.prints)
        old.keep_inputs(QUIET, "late", [], T0 + 5)  # The old one comes back from a stuck read.
        self.assertEqual(self.sync.shared.prints, kept)
        built = self.full_pass(T0 + STEP)
        self.assertNotIn(TOPIC, built)
        self.assertNotIn(QUIET, built)
        self.assertEqual(self.deleted(), [])


class GuardTest(SkipCase):
    """A file a topic's build reads that its inputs do not cover would leave the page wrong until the topic's limit, the next time
    that file changes alone. Every file under the state directory a build of a topic with all of it reads (its records, history,
    topic.json, gist, 到点回来看, a draft, an answered question, a turn with a checkpoint, a plan, 产物 and a trace, a relay) is one
    ``inputs`` reads, or one that does not change once the turn it belongs to has ended."""

    INPUTS = ("jobs(/.*)?", "questions(/.*)?",  # The records, as the stores hold them.
              "topics/{t}/(history\\.jsonl|topic\\.json|gist\\.json)",  # Stats of its own files.
              "revisits(/{t}\\.json)?", "owner-send(/[^/]+\\.json)?")  # The folders the look reads whole.
    SETTLED = ("", "topics", "topics/{t}",  # The folders on the way.
               "checkpoints(/.*)?",  # A job's own checkpoint, its 产物 beside it: written by its task, which has ended.
               "traces(/.*)?",  # A job's process record: read keyed by the job's record (ended_extras).
               "artifact-drive(/.*)?",  # An upload's ledger: a turn whose 产物 go up is built again (files_due), else its limit.
               "web(/images\\.json)?")  # What the page has of the images: an upload builds its topics again (WebSync.push_images).

    def test_every_file_a_build_reads_is_an_input_or_settled(self):
        import builtins
        import contextlib
        import io
        import pathlib
        import re

        from covey.core import owner_send as drafts
        cp = self.state / "checkpoints" / "k-cccc.json"
        cp.parent.mkdir(parents=True, exist_ok=True)
        (cp.parent / "artifacts").mkdir(exist_ok=True)
        (cp.parent / "artifacts" / "report.md").write_text("报告")
        write_json(cp, {"phase": "做完", "steps": [{"title": "读代码", "state": "done"}], "artifacts": [str(cp.parent / "artifacts" / "report.md")],
                        "criteria": [{"item": "测试全过", "state": "满足"}]})
        with mock.patch.object(project_proposals, "enabled", return_value=True), mock.patch.object(revisits, "enabled", return_value=True), \
                mock.patch.object(app_collect.owner_send, "enabled", return_value=True):
            self.topic()
            write_job(self.state, f"k-{TOPIC[:4]}", checkpoint_path=str(cp), message_id="m你好", workdir=str(self.state),  # Its user line's
                      history_path=str(self.state / "topics" / TOPIC / "history.jsonl"))
            self.question(status="answered", answers={"q1": {"answers": ["A"]}})
            write_json(topic_gist.path(self.state, TOPIC), {"essence": "整理账单", "updated_at": T0})
            revisits.path(self.state, TOPIC).parent.mkdir(parents=True, exist_ok=True)
            write_json(revisits.path(self.state, TOPIC), {"topic_id": TOPIC, "state": revisits.PENDING, "due_at": T0 + 600, "look": "CI"})
            drafts.write(self.state, {"id": "d1", "topic_id": TOPIC, "status": "drafted", "to": "张三", "text": "周报", "created_at": T0})
            (self.state / RELAYS).mkdir(parents=True, exist_ok=True)
            write_json(self.state / RELAYS / "r1.json", {"state": "sent", "sent_at": T0, "job_key": job_key("m你好", 7)})
            self.full_pass(T0)  # Every cache warm but the ones a build reads anyway.
            collector, records = self.sync.passer, topic_job_records(self.state, TOPIC, chat_id=CHAT)
            collector.look_begins(CHAT, T0 + STEP)
            collector.look_inputs(self.state)
            touched = []
            real_open, real_stat, real_lstat, real_scandir, real_listdir = io.open, os.stat, os.lstat, os.scandir, os.listdir

            def seen(real):
                def call(path, *args, **kwargs):
                    if isinstance(path, (str, bytes, os.PathLike)):
                        touched.append(os.fsdecode(os.fspath(path)))
                    return real(path, *args, **kwargs)
                return call
            with contextlib.ExitStack() as stack:
                for owner, name, real in ((io, "open", real_open), (builtins, "open", real_open), (os, "stat", real_stat),
                                          (os, "lstat", real_lstat), (os, "scandir", real_scandir), (os, "listdir", real_listdir)):
                    stack.enter_context(mock.patch.object(owner, name, seen(real)))
                accessor = getattr(pathlib, "_NormalAccessor", None)  # Python 3.10: Path's calls go through it, bound at its import.
                for name in ("open", "stat", "lstat", "scandir", "listdir") if accessor is not None else ():
                    if hasattr(accessor, name):
                        stack.enter_context(mock.patch.object(accessor, name, staticmethod(seen(getattr(accessor, name)))))
                collector.shared.files.clear()  # 产物 read again, as a build after FILES_SETTLED does.
                items = collector.topic_items(self.state, CHAT, TOPIC, records, T0 + STEP)
        self.assertTrue(any(item["type"] == "question" for item in items))
        self.assertTrue(any(item["type"] == "turn" and item["data"].get("artifacts") for item in items))
        root = os.path.realpath(self.state)
        relative = sorted({os.path.relpath(os.path.realpath(path), root) if os.path.realpath(path).startswith(root) else None
                           for path in touched} - {None})
        allowed = [re.compile(pattern.format(t=TOPIC) + "$") for pattern in (*self.INPUTS, *self.SETTLED)]
        unknown = [path for path in relative if not any(rule.match("" if path == "." else path) for rule in allowed)]
        self.assertEqual(unknown, [], f"read by the build, not by Collector.inputs: {unknown}")
        self.assertIn(f"topics/{TOPIC}/history.jsonl", relative)  # It did read what it should.


if __name__ == "__main__":
    unittest.main()
