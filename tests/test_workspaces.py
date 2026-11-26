"""Where a task runs: workspaces, the retired workspace manager (and the 仓库 tab in its place) and the directory picker.

- A topic's workspace is chosen once and kept; the scheduler runs one task per workspace.
- 管理工作区 (the old card, retired in v43) only says it is offline; the 设置 card's 仓库 tab shows the home and the repositories.
- The directory picker on a launch card browses, caches and picks a directory; stale
  views and old cards cannot apply.
"""

from __future__ import annotations

import dataclasses
import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.cards import selects, walk_dicts, walk_elements, walk_elements as walk
from support.sessions import write_session_id
from support.world import PickerCase, TopicFixture, UnifiedCase, build_claude_app

from support import requires_extension
from covey.app import directory_picker
from covey.app.directory_picker import DirectoryCache, DirectoryPicker, scan_directory, search_directories
from covey.app.launch import card_token
from covey.app.launch_submit import submit_launch_form
from covey.cards.launch_config import SUBMIT_PREFIX
from covey.cards.launch_config import PICKER_PREFIX
from covey.app import workspace_manager
from covey.cards.directory import LAUNCH, SEARCH_PLACEHOLDER, directory_card
from covey.core.text import literal
from covey.cards.launch_config import MANAGE_OPTION
from covey.cards.workspace_manager import BROWSE_HOST, MANAGER_PREFIX, row_key
from covey.core import locks, topics, workspaces
from covey.core.scheduler import WorkspaceScheduler
from covey.core.state import write_json as write_json_file, write_private_text
from covey.core.topics import read_topic, remember_topic_message
from covey.core.workspaces import config_path, load_config, resolve_selection



class WorkspaceSelectionTest(TopicFixture, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.ctx = dataclasses.replace(self.ctx, options={**self.ctx.options, "workspace_selection": True})
        self.app.submission.selection_card = mock.Mock()
        self.other = self.root / "other"
        self.other.mkdir()
        config = load_config(self.ctx.state_dir, self.ctx.default_workdir)
        config["workspaces"]["另一个仓库"] = str(self.other)
        write_private_text(config_path(self.ctx.state_dir), json.dumps(config))

    def test_first_message_waits_and_choice_binds_all_followups(self):
        self.receive("om_a", "first")
        self.receive("om_a2", "second", root="om_a")
        self.assertTrue(self.app.runtime.jobs.queue.empty())
        ctx = self.topic("om_a")
        self.assertEqual(len(self.app.harness.topic_records(ctx, "oc_chat")), 2)
        self.app.submission.start_workspace(ctx, "oc_chat", "另一个仓库")
        jobs = list(self.app.runtime.jobs.queue.queue)
        self.assertEqual([j.user_text for j in jobs], ["first", "second"])
        self.assertTrue(all(j.workdir == self.other for j in jobs))
        self.assertNotEqual(jobs[0].history_snapshot, jobs[1].history_snapshot)
        again = self.topic("om_a")
        self.assertEqual(again.workdir, self.other)
        self.assertTrue(read_topic(again)["workspace_locked"])
        self.app.submission.start_workspace(again, "oc_chat", self.ctx.default_workdir.name)
        self.assertEqual(self.app.runtime.jobs.queue.qsize(), 2)
        self.assertEqual(self.topic("om_a").workdir, self.other)

    def test_default_change_only_affects_new_topics(self):
        self.receive("om_a", "first")
        previous = self.topic("om_a")
        config = load_config(self.ctx.state_dir, self.ctx.default_workdir)
        config["default"] = "另一个仓库"
        write_private_text(config_path(self.ctx.state_dir), json.dumps(config))
        self.receive("om_b", "new")
        self.assertEqual(self.topic("om_a").workdir, previous.workdir)
        self.assertEqual(self.topic("om_b").workdir, self.other)

    def test_waiting_jobs_survive_restart_without_rebinding_session(self):
        self.receive("om_a", "first")
        self.app = build_claude_app(self.backend)
        self.app.cards.streaming = False
        self.app.messenger.send_message = mock.Mock(return_value=True)
        self.app.submission.start_workspace(self.topic("om_a"), "oc_chat", "另一个仓库")
        job = self.app.runtime.jobs.queue.get_nowait()
        self.assertEqual(job.user_text, "first")
        self.assertEqual(job.workdir, self.other)
        self.assertIsNone(self.app.sessions.read_session_id(job.session_path))

    def test_missing_default_directory_does_not_break_existing_topic(self):
        self.receive("om_a", "existing")
        config = load_config(self.ctx.state_dir, self.ctx.default_workdir)
        config["workspaces"]["missing"] = str(self.root / "missing")
        config["default"] = "missing"
        write_private_text(config_path(self.ctx.state_dir), json.dumps(config))
        self.receive("om_a2", "followup", root="om_a")
        self.assertEqual(len(self.app.harness.topic_records(self.topic("om_a"), "oc_chat")), 2)

    def test_absolute_path_registers_and_binds_waiting_job(self):
        directory = self.root / "directory with spaces"
        directory.mkdir()
        self.receive("om_path", "task")
        self.app.submission.start_workspace(self.topic("om_path"), "oc_chat", str(directory))
        job = self.app.runtime.jobs.queue.get_nowait()
        self.assertEqual(job.workdir, directory)
        saved = load_config(self.ctx.state_dir, self.ctx.default_workdir)
        self.assertIn(str(directory), saved["workspaces"].values())

    def test_path_alias_collision_and_invalid_directory(self):
        first = self.root / "one" / "repo"
        second = self.root / "two" / "repo"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        a, _ = resolve_selection(self.ctx.state_dir, self.ctx.default_workdir, str(first))
        b, _ = resolve_selection(self.ctx.state_dir, self.ctx.default_workdir, str(second))
        self.assertNotEqual(a, b)
        self.assertEqual(resolve_selection(self.ctx.state_dir, self.ctx.default_workdir, str(first))[0], a)
        with self.assertRaises(ValueError):
            resolve_selection(self.ctx.state_dir, self.ctx.default_workdir, str(self.root / "missing"))


class SubmissionLockTest(TopicFixture, unittest.TestCase):
    """A Feishu call stuck while one topic submits holds up that topic only, never LOCK."""

    def setUp(self):
        super().setUp()
        self.release, self.sending = threading.Event(), threading.Event()
        self.addCleanup(self.release.set)

        def card(ctx, job, content, **_):
            if job.message_id == "om_a":
                self.sending.set()
                self.release.wait(10)
            if job.message_id == "om_c":
                raise RuntimeError("synthetic card failure")
            return None
        self.app.cards.create_streaming_reply = card

    def background(self, *args, **kwargs):
        thread = threading.Thread(target=self.receive, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    def test_card_stuck_in_one_topic_leaves_other_topics_and_lock_free(self):
        first = self.background("om_a", "first")
        self.assertTrue(self.sending.wait(5))
        # Registered before its card exists: a binding switch or maintenance sees the topic busy.
        self.assertEqual([j.message_id for j in self.app.runtime.jobs.by_id.values()], ["om_a"])
        self.assertTrue(self.app.runtime.jobs.queue.empty())
        self.assertTrue(locks.LOCK.acquire(timeout=1))
        locks.LOCK.release()
        other = self.background("om_b", "another topic")
        other.join(5)
        self.assertFalse(other.is_alive())
        same = self.background("om_a2", "same topic", root="om_a")
        same.join(0.3)
        self.assertTrue(same.is_alive())  # Behind the stuck card, so the topic keeps its order.
        self.release.set()
        first.join(5)
        same.join(5)
        self.assertEqual([j.message_id for j in self.app.runtime.jobs.queue.queue], ["om_b", "om_a", "om_a2"])

    def test_card_failure_leaves_the_topic_free(self):
        with self.assertRaises(RuntimeError):
            self.receive("om_c", "fails")
        self.assertEqual(self.app.runtime.jobs.by_id, {})
        self.assertTrue(self.app.runtime.jobs.queue.empty())

    def test_topic_lock_is_never_taken_inside_lock(self):
        with locks.LOCK, self.assertRaises(RuntimeError):
            with locks.topic_lock(self.topic("om_d")):
                pass
        with locks.topic_lock(self.topic("om_d")), locks.LOCK, locks.topic_lock(self.topic("om_d")):
            pass  # Reentry by the holder is fine.


class LockHomeTest(unittest.TestCase):
    def test_workspaces_still_names_the_moved_lock_and_topic_helpers(self):
        # Round 2 D3 moved them to core/locks.py and core/topics.py: one RLock, whichever module a caller
        # (an old release's script, a deployer's branch) imports it from.
        self.assertIs(workspaces.LOCK, locks.LOCK)
        self.assertIsInstance(locks.LOCK, type(threading.RLock()))
        self.assertIs(workspaces.topic_lock, locks.topic_lock)
        for name in ("read_topic", "proxy_topic", "workspace_locked", "bind_topic"):
            self.assertIs(getattr(workspaces, name), getattr(topics, name), name)


class WorkspaceSchedulerTest(unittest.TestCase):
    def test_same_topic_fifo_and_same_directory_topics_parallel(self):
        shutdown = threading.Event()
        incoming = queue.Queue()
        release = threading.Event()
        a_started = threading.Event()
        b_started = threading.Event()
        second = threading.Event()
        self.addCleanup(release.set)
        self.addCleanup(shutdown.set)

        def process(job):
            if job.message_id == "a1":
                a_started.set()
                release.wait(2)
            elif job.message_id == "b":
                b_started.set()
                release.wait(2)
            else:
                second.set()

        for name, directory in [("a1", "/tmp/work-a"), ("a2", "/tmp/work-a"), ("b", "/tmp/work-a")]:
            incoming.put(
                SimpleNamespace(
                    message_id=name,
                    chat_id="chat",
                    topic_id="a" if name.startswith("a") else "b",
                    workdir=Path(directory),
                    cancel_event=threading.Event(),
                )
            )
        scheduler = WorkspaceScheduler(shutdown, incoming, process, lambda _: None)
        thread = threading.Thread(target=scheduler.run, daemon=True)
        thread.start()
        try:
            self.assertTrue(a_started.wait(1))
            self.assertTrue(b_started.wait(1))
            self.assertFalse(second.is_set())
            release.set()
            self.assertTrue(second.wait(1))
        finally:
            release.set()
            shutdown.set()
            thread.join(3)
        self.assertFalse(thread.is_alive())

    def test_the_limit_is_its_setting_and_two_slots_wait_for_the_butler_and_the_leads(self):
        """T744 (2026-11-24): the limit was 10, written in, and a new topic waited "排队中 · 并发已满（最多 10 个任务）". It is
        COVEY_MAX_WORKERS now; ordinary topics take all but RESERVED slots, which a turn of the butler or of a lead may take."""
        from covey.core import scheduler as sched
        shutdown, release = threading.Event(), threading.Event()
        incoming, started, lock = queue.Queue(), [], threading.Lock()
        changed = threading.Condition(lock)

        def process(job):
            with changed:
                started.append(job.message_id)
                changed.notify_all()
            release.wait(5)

        def wait_for(count):
            with changed:
                return changed.wait_for(lambda: len(started) >= count, timeout=3)

        for i in range(9):
            incoming.put(SimpleNamespace(message_id=str(i), chat_id="chat", topic_id=str(i), workdir=Path("/tmp/same"),
                                         cancel_event=threading.Event()))
        incoming.put(SimpleNamespace(message_id="lead", chat_id="chat", topic_id="lead-topic", workdir=Path("/tmp/same"),
                                     cancel_event=threading.Event()))
        with mock.patch.dict(os.environ, {sched.WORKERS_ENV: "10"}), \
                mock.patch.object(sched, "keeps_slot", lambda job: job.topic_id == "lead-topic"):
            scheduler = WorkspaceScheduler(shutdown, incoming, process, lambda _: None)
            self.assertEqual((scheduler.max_workers, sched.topic_limit(scheduler.max_workers)), (10, 8))
            thread = threading.Thread(target=scheduler.run, daemon=True)
            thread.start()
            try:
                self.assertTrue(wait_for(9))  # Eight topics and the lead, in a slot kept for it.
                time.sleep(0.3)
                with lock:
                    self.assertEqual((len(started), "lead" in started, "8" in started), (9, True, False))
                release.set()
                self.assertTrue(wait_for(10))  # The ninth topic once a slot is free.
            finally:
                release.set()
                shutdown.set()
                thread.join(3)

    def test_the_limit_reads_its_setting(self):
        from covey.core import scheduler as sched
        for raw, limit in (("", 32), ("64", 64), ("0", 32), ("-3", 32), ("abc", 32), ("99999", sched.WORKERS_CEILING)):
            with self.subTest(raw=raw), mock.patch.dict(os.environ, {sched.WORKERS_ENV: raw}):
                self.assertEqual(sched.worker_limit(), limit)
        self.assertEqual([sched.topic_limit(n) for n in (1, 2, 3, 32)], [1, 1, 1, 30])
        job = SimpleNamespace(topic_id="t", chat_id="c")
        with mock.patch.object(sched, "keeps_slot", lambda job: False):
            self.assertEqual([sched.room_for(job, n, 10) for n in ((7, 7), (8, 8), (9, 7), (10, 7))], [True, False, True, False])
        with mock.patch.object(sched, "keeps_slot", lambda job: True):
            self.assertEqual([sched.room_for(job, n, 10) for n in ((8, 8), (9, 8), (10, 8))], [True, True, False])

    def test_a_queued_task_says_the_limit_its_kind_has(self):
        from covey.app.submission import capacity_words
        from covey.core import scheduler as sched
        job = SimpleNamespace(topic_id="t", chat_id="c")
        with mock.patch.dict(os.environ, {sched.WORKERS_ENV: "40"}):
            with mock.patch.object(sched, "keeps_slot", lambda job: False):
                with mock.patch("covey.app.submission.keeps_slot", lambda job: False):
                    self.assertEqual(capacity_words(job), 38)
            with mock.patch("covey.app.submission.keeps_slot", lambda job: True):
                self.assertEqual(capacity_words(job), 40)

    def test_overlapping_directories_do_not_block_different_topics(self):
        scheduler = WorkspaceScheduler(None, None, None, None)
        scheduler.active = {"first": ("chat", "a")}
        scheduler.pending = [SimpleNamespace(chat_id="chat", topic_id="b", workdir=Path("/tmp/code/sub"))]
        self.assertTrue(scheduler.eligible(0))


def find(card, tag, name=None):
    return next(e for e in walk(card['body']['elements']) if e.get('tag') == tag and (name is None or e.get('name') == name))


def buttons(card):
    return {e['name'].rsplit(':', 1)[1]: e for e in walk(card['body']['elements']) if e.get('tag') == 'button'}


def values(element):
    return [o['value'] for o in element['options']]


def row_buttons(card, name):
    """The buttons of the browser row whose text names the directory ``name`` (进入, then 使用/添加)."""
    for line in walk(card['body']['elements']):
        if line.get('tag') == 'column_set' and any(
                e.get('tag') == 'markdown' and f'**{literal(name)}**' in e['content'] for e in walk(line['columns'])):
            return [e for e in walk(line['columns']) if e.get('tag') == 'button']
    return []


class RetiredWorkspaceManagerTests(UnifiedCase):
    """v43: the 工作区 manager card is retired. No entry sends it; a click on one already sent (its own buttons, or the launch card's
    ⚙️ 添加或管理工作区… option) gets one line, changes nothing and does not crash. The 设置 card's 仓库 tab (app/workspace_manager.py)
    is read only: the home, the repositories, the web page's link."""

    def setUp(self):
        super().setUp()
        self.manager = self.app.workspace_manager
        self.manager.started = True  # The tests run each queued request themselves.
        self.app.runtime.access.remember_owner_chat('dm')
        self.said = self.app.messenger.send_message = mock.Mock()
        write_json_file(config_path(self.ctx.state_dir), {'default': 'project', 'workspaces': {
            'project': str(self.work), 'docs': str(self.root), 'dev': 'gpu1:/srv/x'}, 'recent': {'docs': 1700000000}})

    def click(self, event_id, operator='owner', **more):
        return self.app._handle_card_action_event({'event_id': event_id, 'operator_id': operator, 'chat_id': 'dm',
                                                   'message_id': 'om_old', **more}, self.ctx)

    def run_queued(self):
        handler, ctx, event = self.manager.queue.get_nowait()
        handler(ctx, event)

    def test_a_click_on_the_old_manager_card_says_it_is_offline_and_changes_nothing(self):
        before = (self.ctx.state_dir / 'workspace-config.json').read_text()
        names = (f'{MANAGER_PREFIX}{"a" * 24}:3:{verb}' for verb in ('refresh', 'add', 'prune', 'remove-' + row_key('docs'),
                                                                     'done', 'back', 'dir-open0', 'notes', 'filter', 'page2'))
        for n, name in enumerate(names):
            self.assertEqual(self.click(f'ev-{n}', action_name=name, form_value={'names': ['docs'], 'add_path': str(self.work)}),
                             'workspace_manager')
            self.run_queued()
            self.assertEqual(self.said.call_args.args[2], workspace_manager.RETIRED_TEXT)
        self.assertEqual(self.said.call_count, 10)
        self.assertEqual((self.ctx.state_dir / 'workspace-config.json').read_text(), before)  # The list is as it was.
        self.assertFalse((self.ctx.state_dir / 'workspace-managers').exists())  # No record or card made.

    def test_the_launch_cards_manage_option_says_it_is_offline_to_the_owner_only(self):
        event = {'action_value': {'kind': 'bridge_launch_workspace', 'token': 'a' * 24}, 'option': MANAGE_OPTION}
        self.assertTrue(self.manager.matches(event))
        self.assertEqual(self.click('ev-m1', **event), 'workspace_manager')
        self.run_queued()
        self.assertEqual(self.said.call_args.args[2], workspace_manager.RETIRED_TEXT)
        self.assertEqual(self.click('ev-m2', operator='ou_member', **event), 'not_owner')  # Not even asked: the chat is the owner's.
        self.assertTrue(self.manager.queue.empty())
        self.assertEqual(self.said.call_count, 1)

    def test_the_home_and_the_old_list_make_the_repositories_the_tab_shows_until_repos_json_exists(self):
        home = self.work
        repos, stored = workspace_manager.repo_entries(self.ctx.state_dir, home)
        self.assertEqual((stored, [(r.name, r.path, r.status, r.added_by) for r in repos]),
                         (False, [('docs', str(self.root), 'active', 'migrate')]))  # The home and a device's workspace are no repository.
        self.assertEqual(repos[0].last_used, 1700000000.0)
        self.assertFalse((self.ctx.state_dir / 'repos.json').exists())  # Reading makes no file.
        write_json_file(self.ctx.state_dir / 'repos.json', {'version': 1, 'repos': [{'name': 'covey', 'path': '/srv/covey'}]})
        repos, stored = workspace_manager.repo_entries(self.ctx.state_dir, home)
        self.assertEqual((stored, [r.name for r in repos]), (True, ['covey']))
        (self.ctx.state_dir / 'repos.json').write_text('{broken')
        self.assertEqual(workspace_manager.repo_entries(self.ctx.state_dir, home), ([], True))  # Unreadable: none, never the old list.

    def test_the_tab_is_read_only_and_names_the_web_page_or_the_repositories(self):
        record = {'view': {'token': 'a' * 24, 'revision': 1, 'hub': True}, 'tab': 'repos'}
        ctx = SimpleNamespace(state_dir=self.ctx.state_dir, default_workdir=self.work, profile=self.ctx.profile)
        card = self.manager.tab_card(ctx, 'a' * 24, record)
        text = json.dumps(card, ensure_ascii=False)
        for part in ('主目录', '**docs**', '可写', '没开网页'):
            self.assertIn(part, text)
        self.assertEqual([e for e in walk(card['body']['elements']) if e.get('tag') in ('button', 'input', 'form')
                          and 'bridge_settings_tab' not in json.dumps(e)], [])  # Only the tab row's buttons.
        with mock.patch('covey.core.web_sync.page_url', return_value='https://web.example'):
            text = json.dumps(self.manager.tab_card(ctx, 'a' * 24, record), ensure_ascii=False)
        self.assertIn('(https://web.example/settings/repos)', text)
        self.assertNotIn('**docs**', text)


class WorkspaceCliTests(unittest.TestCase):
    def test_remove_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, work = root / 'state', root / 'work'
            work.mkdir()
            for name in ('a', 'b'):
                (root / name).mkdir()
                resolve_selection(state, work, str(root / name))
            (root / 'b').rmdir()
            script = Path(__file__).parents[1] / 'bin/covey_workspaces.py'

            def run(*args):
                return subprocess.run([sys.executable, str(script), '--state-dir', str(state), *args],
                                      cwd=work, capture_output=True, text=True)
            self.assertEqual(json.loads(run('prune').stdout)['workspaces'].keys(), {'work', 'a'})
            self.assertEqual(json.loads(run('remove', 'a').stdout)['workspaces'].keys(), {'work'})
            self.assertIn('不能移除', run('remove', 'work').stderr)
            self.assertIn('unknown workspace', run('remove', 'missing').stderr)

    def test_add_names_a_new_directory_and_never_waits_on_a_silent_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state, work = root / 'state', root / 'work'
            (root / 'a' / 'work').mkdir(parents=True)
            work.mkdir()
            self.assertEqual(workspaces.add_workspace(state, work, str(root / 'a' / 'work')), ('work-2', True))
            self.assertEqual(workspaces.add_workspace(state, work, str(work)), ('work', False))
            # "~name" of no user: said like any path that is not absolute (pathlib raised RuntimeError, 2026-11-11).
            for typed in ('~$预算表', '~nosuchuser/work'):
                with self.assertRaisesRegex(ValueError, '绝对路径'):
                    workspaces.add_workspace(state, work, typed)
                with self.assertRaisesRegex(ValueError, '绝对目录路径'):
                    workspaces.resolve_selection(state, work, typed)
            release = threading.Event()
            resolve = Path.resolve
            with mock.patch.object(Path, 'resolve', lambda path, *a, **k: release.wait(5) and resolve(path)):
                started = time.monotonic()
                with self.assertRaisesRegex(ValueError, '没有答复'):
                    workspaces.add_workspace(state, work, str(root / 'slow'), timeout=.05)
                self.assertLess(time.monotonic() - started, 2)
                release.set()
            self.assertEqual(set(load_config(state, work)['workspaces']), {'work', 'work-2'})


class DirectoryReadTests(unittest.TestCase):
    def test_shallow_scan_hidden_links_and_bounded_listing(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root / '.hidden').mkdir()
            (root / 'directory').mkdir()
            (root / 'directory/nested').mkdir()
            (root / 'file').write_text('not read')
            (root / 'link').symlink_to(root / 'absent')
            result = scan_directory(root)
            self.assertEqual([e['name'] for e in result['entries']], ['.hidden', 'directory', 'link'])
            self.assertTrue(result['entries'][-1]['link'])
            self.assertFalse(result['error'])
            self.assertTrue(scan_directory(root / 'link')['error'])
            self.assertTrue(scan_directory(root / 'file')['error'])
            with mock.patch('covey.app.directory_picker.SCAN_LIMIT', 1):
                self.assertTrue(scan_directory(root)['truncated'])
            with mock.patch('covey.app.directory_picker.os.scandir', side_effect=PermissionError):
                self.assertIn('权限', scan_directory(root)['error'])

    def test_search_reads_within_its_directory_and_time_budgets(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            for i in range(5):
                (root / f'd{i}' / f'match-{i}').mkdir(parents=True)
            (root / 'match-top').mkdir()
            found = search_directories(root, 'MATCH')
            self.assertEqual([e['name'] for e in found['entries']], ['match-top'] + [f'd{i}/match-{i}' for i in range(5)])
            self.assertEqual((found['truncated'], found['scanned']), (False, 12))
            with mock.patch.object(directory_picker, 'SEARCH_DIRECTORIES', 3):
                found = search_directories(root, 'match')
            self.assertEqual((found['truncated'], found['scanned']), (True, 3))
            self.assertEqual([e['name'] for e in found['entries']], ['match-top', 'd0/match-0', 'd1/match-1'])
            view = {'path': str(root), 'revision': 1, 'query': 'match', 'results': True, **found}
            self.assertIn('只查了前 3 个目录，可进入子目录再搜', json.dumps(directory_card('a' * 24, view), ensure_ascii=False))
            with mock.patch.object(directory_picker, 'SEARCH_SECONDS', -1):
                self.assertTrue(search_directories(root, 'match')['truncated'])
            self.assertIn('不存在', search_directories(root / 'absent', 'x')['error'])
            with mock.patch.object(directory_picker, 'SEARCH_RESULTS', 2):
                found = search_directories(root, 'match')
            self.assertEqual((len(found['entries']), found['more']), (2, True))
            # A search is cached apart from the listing of the same directory.
            cache = DirectoryCache()
            self.assertEqual(len(cache.request(str(root)).result(2)['entries']), 6)
            self.assertEqual(len(cache.request(str(root), query='match-1').result(2)['entries']), 1)
            self.assertEqual(set(cache.cache), {str(root), (str(root), 'match-1')})

    def test_cache_refresh_expiry_and_capacity(self):
        cache = DirectoryCache(ttl=10, capacity=2, stale_ttl=0)
        with mock.patch('covey.app.directory_picker.scan_directory', return_value={'entries': []}) as scan:
            first = cache.request('/a').result(2)
            self.assertIs(cache.request('/a').result(), first)
            self.assertEqual(scan.call_count, 1)
            cache.request('/a', refresh=True).result(2)
            self.assertEqual(scan.call_count, 2)
            cache.ttl = -1
            cache.request('/a').result(2)
            self.assertEqual(scan.call_count, 3)
            cache.request('/b').result(2)
            cache.request('/c').result(2)
            self.assertEqual(len(cache.cache), 2)
            self.assertNotIn('/a', cache.cache)

    def test_recent_listing_returns_immediately_while_refresh_is_bounded(self):
        cache = DirectoryCache(ttl=0, stale_ttl=120)
        first = {'entries': [{'name': 'old', 'link': False}], 'error': ''}
        cache.cache['/a'] = (time.monotonic() - 21, first)
        release, entered = threading.Event(), threading.Event()
        def scan(path):
            entered.set()
            release.wait(3)
            return {'entries': [{'name': 'new', 'link': False}], 'error': ''}
        with mock.patch('covey.app.directory_picker.scan_directory', side_effect=scan) as read:
            try:
                result = cache.request('/a').result(.05)
                self.assertTrue(result['stale'])
                self.assertEqual(result['entries'], first['entries'])
                self.assertTrue(entered.wait(1))
                self.assertTrue(cache.request('/a').result(.05)['stale'])
                self.assertEqual(read.call_count, 1)
                # User-requested freshness waits for the existing reader.
                refresh = cache.request('/a', refresh=True)
                self.assertFalse(refresh.done())
            finally:
                release.set()
            self.assertEqual(refresh.result(2)['entries'][0]['name'], 'new')
            self.assertFalse(refresh.result()['stale'])

    def test_old_listing_and_cached_errors_are_never_served_as_recent(self):
        cache = DirectoryCache(ttl=0, stale_ttl=120)
        for value, age in [({'entries': [], 'error': ''}, 121),
                           ({'entries': [], 'error': 'permission denied'}, 21)]:
            cache.cache['/a'] = (time.monotonic() - age, value)
            with mock.patch('covey.app.directory_picker.scan_directory', return_value={'entries': [], 'error': 'fresh'}) as read:
                result = cache.request('/a').result(2)
                self.assertEqual(result['error'], 'fresh')
                self.assertFalse(result['stale'])
                read.assert_called_once()

    def test_stalled_reads_are_bounded_and_same_path_coalesces(self):
        release = threading.Event()
        cache = DirectoryCache()
        def stalled(path):
            release.wait(3)
            return {'entries': [], 'error': ''}
        with mock.patch('covey.app.directory_picker.scan_directory', side_effect=stalled) as scan:
            try:
                first = cache.request('/a')
                second = cache.request('/b')
                self.assertIs(cache.request('/a'), first)
                self.assertIn('读取', cache.request('/c').result(.1)['error'])
                self.assertLessEqual(scan.call_count, 2)
            finally:
                release.set()
                first.result(2)
                second.result(2)


class PickerTests(PickerCase):
    def enter(self, name):
        index = next(i for i, e in enumerate(self.record()['picker']['entries']) if e['name'] == name)
        self.click('enter', index=index)

    def press(self, verb, **fields):
        self.picker.process(self.ctx, {**self.open_event, 'action_name':
                            f"bridge_dir_{self.token}:{self.record()['picker']['revision']}:{verb}",
                            'form_value': {'query': '', **fields}})

    def row(self, name, verb='pick'):
        """The verb of the button for the row named ``name``: enter<i> or pick<i>."""
        for found in row_buttons(self.current_card(), name):
            if found['name'].rsplit(':', 1)[1].startswith(verb):
                return found['name'].rsplit(':', 1)[1]
        raise AssertionError(f'no row {name}')

    def text(self):
        return json.dumps(self.current_card(), ensure_ascii=False)

    def test_rows_enter_page_and_use_a_row_return_to_the_launch_card(self):
        self.prepare()
        for i in range(45):
            (self.work / f'child-{i:02}').mkdir()
        self.picker.process(self.ctx, self.open_event)
        card = self.current_card()
        self.assertEqual(card['header']['title']['content'], '选择工作区目录')
        form = card['body']['elements'][0]['elements']
        self.assertEqual(form[0]['content'], "📂 **project** <font color='grey'>· 已在列表</font>")  # Listed as project.
        self.assertEqual(form[1]['content'], literal(self.work))
        self.assertEqual(find(card, 'input', 'query')['placeholder']['content'], SEARCH_PLACEHOLDER)
        labels = [b['text']['content'] for b in walk(form) if b.get('tag') == 'button']
        self.assertEqual(labels[:3], ['上一级', '刷新', '搜索'])
        self.assertEqual(labels[3:5], ['进入', '使用'])
        self.assertEqual([b['name'].rsplit(':', 1)[1] for b in row_buttons(card, 'child-00')], ['enter0', 'pick0'])
        self.assertEqual(labels[-4:], ['上一页', '下一页', '返回', '使用此目录'])
        self.assertEqual(labels.count('使用'), 15)
        self.assertIn('共 45 个子目录', self.text())
        self.assertIn('第 1/3 页', self.text())
        self.assertNotIn(literal('child-20'), self.text())
        self.assertTrue({e.get('flex_mode') for e in walk_dicts(card) if e.get('tag') == 'column_set'} == {None})
        self.press('page2')
        self.assertIn(literal('child-44'), self.text())
        self.assertIn('第 3/3 页', self.text())
        self.assertTrue(buttons(self.current_card())['page2']['disabled'])  # 下一页 on the last page.
        self.press(self.row('child-41', 'enter'))
        self.assertEqual(self.record()['picker']['path'], str(self.work / 'child-41'))
        self.assertIn('没有子目录', self.text())
        self.press('up')
        self.assertEqual(self.record()['picker']['path'], str(self.work))
        self.assertIn('第 1/3 页', self.text())
        self.press(self.row('child-07'))
        self.assertEqual(self.record()['status'], 'replaced')
        self.assertIn('已选择工作区：child&#45;07', self.text())
        self.assertEqual(selects(self.current_card())['workspace']['initial_option'], 'child-07')
        self.assertTrue(self.app.runtime.jobs.queue.empty())

    def test_search_this_level_first_then_deeper_and_paste_a_path(self):
        self.prepare()
        for relative in ('Alpha', 'x/alpha-deep', 'x/y/alpha3', 'x/y/z/alpha4', '.hid/alpha', 'node_modules/alpha'):
            (self.work / relative).mkdir(parents=True)
        (self.work / 'alpha-link').symlink_to(self.work / 'x')
        self.picker.process(self.ctx, self.open_event)
        self.press('search', query=' ALPHA ')
        self.assertEqual([e['name'] for e in self.record()['picker']['entries']],
                         ['Alpha', 'alpha-link', 'x/alpha-deep', 'x/y/alpha3'])
        self.assertIn('搜索“ALPHA”：4 个结果', self.text())
        self.assertEqual(find(self.current_card(), 'input', 'query')['default_value'], 'ALPHA')
        self.assertIn(f'🔗 **{literal("alpha-link")}**', self.text())
        self.assertIn("📁 **alpha3**\\n<font color='grey'>x/y</font>", self.text())  # Where a deeper result is.
        self.assertIn('清除搜索', self.text())
        self.press('search', query='.hid')
        self.assertEqual([e['name'] for e in self.record()['picker']['entries']], ['.hid'])
        self.press('search', query='nothing-like-it')
        self.assertIn('没有匹配的目录', self.text())
        self.press('search', query='alpha')
        self.press(self.row('alpha-deep', 'enter'))
        self.assertEqual(self.record()['picker']['path'], str(self.work / 'x/alpha-deep'))
        self.assertEqual(self.record()['picker']['query'], '')
        self.press('search', query=f'{self.root}/')
        self.assertEqual(self.record()['picker']['path'], str(self.root))
        with mock.patch.dict(os.environ, {'HOME': str(self.work)}):
            self.press('search', query='~/x')
        self.assertEqual(self.record()['picker']['path'], str(self.work / 'x'))
        self.press('search', query=str(self.root / 'nowhere'))
        self.assertIn('路径不存在', self.text())
        self.assertTrue(buttons(self.current_card())['use']['disabled'])
        self.press('up')
        self.press('clear')
        self.assertEqual(self.record()['picker']['path'], str(self.root))
        self.press('use')
        self.assertEqual(selects(self.current_card())['workspace']['initial_option'], self.root.name[:32])

    def test_browser_ignores_stale_rows_and_other_people(self):
        self.prepare()
        (self.work / 'one').mkdir()
        self.picker.process(self.ctx, self.open_event)
        old = {**self.open_event, 'form_value': {'query': ''},
               'action_name': f"bridge_dir_{self.token}:{self.record()['picker']['revision']}:{self.row('one')}"}
        self.press('refresh')
        calls = self.api.call_count
        before = load_config(self.ctx.state_dir, self.work)
        for event in (old, {**old, 'action_name': f"bridge_dir_{self.token}:{self.record()['picker']['revision']}:pick99"},
                      {**old, 'action_name': f"bridge_dir_{self.token}:{self.record()['picker']['revision']}:use",
                       'operator_id': 'other'}):
            self.picker.process(self.ctx, event)
        self.assertEqual((self.api.call_count, load_config(self.ctx.state_dir, self.work)), (calls, before))
        self.assertEqual(self.record()['status'], 'ready')

    def test_root_down_up_and_near_only_update_original_card(self):
        self.prepare().process(self.ctx, self.open_event)
        self.assertEqual(self.record()['picker']['path'], str(self.work))
        self.click('root')
        child = self.root.parts[1]
        self.enter(child)
        self.assertEqual(self.record()['picker']['path'], '/' + child)
        self.click('up')
        self.assertEqual(self.record()['picker']['path'], '/')
        self.click('near')
        self.assertEqual(self.record()['picker']['path'], str(self.root))
        self.enter(self.work.name)
        self.assertEqual(self.record()['picker']['path'], str(self.work))
        self.click('root')
        self.assertTrue(all(call.args[1:3] == ('PUT', '/open-apis/cardkit/v1/cards/existing-card')
                            for call in self.api.call_args_list))
        self.assertEqual([call.args[3]['sequence'] for call in self.api.call_args_list], list(range(5, 12)))
        self.assertTrue(self.app.runtime.jobs.queue.empty())

    def test_callbacks_from_cards_sent_before_the_browser_still_page_and_show_hidden(self):
        self.prepare()
        for i in range(14):
            (self.work / f'child-{i:02}').mkdir()
        (self.work / '.hidden').mkdir()
        self.picker.process(self.ctx, self.open_event)
        self.click('near')
        self.enter(self.work.name)
        card = json.dumps(self.current_card(), ensure_ascii=False)
        self.assertIn(literal('child-00'), card)
        self.assertIn(literal('child-13'), card)
        self.assertNotIn('下一页', card)
        self.assertNotIn(literal('.hidden'), card)
        self.click('page', page=1)
        self.assertIn(literal('child-13'), json.dumps(self.current_card()))
        self.click('hidden')
        self.assertIn(literal('.hidden'), json.dumps(self.current_card()))
        view = {**self.record()['picker'], 'path': '/<at id=all>*abc*'}
        self.assertNotIn('<at', directory_card(self.token, view)['body']['elements'][0]['elements'][0]['content'])

    def test_a_card_sent_before_the_browser_still_filters_and_selects(self):
        self.prepare()
        for i in range(140):
            (self.work / f'child-{i:03}').mkdir()
        self.picker.process(self.ctx, self.open_event)
        def form(verb, **fields):
            return {**self.open_event, 'action_name':
                    f"bridge_dir_{self.token}:{self.record()['picker']['revision']}:{verb}",
                    'form_value': {'location': str(self.work), 'query': '', 'directory': 'current', **fields}}
        self.picker.process(self.ctx, form('filter', query='139'))
        self.assertIn(literal('child-139'), json.dumps(self.current_card()))
        self.assertNotIn(literal('child-001'), json.dumps(self.current_card()))
        index = next(i for i, e in enumerate(self.record()['picker']['entries']) if e['name'] == 'child-139')
        self.picker.process(self.ctx, form('select', directory=str(index), query='139'))
        self.assertEqual(self.record()['status'], 'replaced')
        self.assertEqual(self.api.call_count, 3)  # Open, filter, select; no enter/extra page.
        workspaces = load_config(self.ctx.state_dir, self.work)['workspaces']
        self.assertIn(str(self.work / 'child-139'), workspaces.values())

    def test_card_is_bounded_for_long_unicode_directory_names(self):
        view = {'path': '/' + '😀' * 999, 'revision': 1, 'entries': [
            {'name': str(i) + '😀中文' * 90, 'link': False} for i in range(4000)]}
        for host, listed in ((LAUNCH, {}), (BROWSE_HOST, {'/' + '😀' * 999: 'x' * 32})):
            card = directory_card('a' * 24, view, host, listed)
            self.assertLess(len(json.dumps(card, ensure_ascii=False).encode()), 30000)
            self.assertLessEqual(json.dumps(card).count('"tag"'), 200)
            self.assertIn('第 1/267 页', json.dumps(card, ensure_ascii=False))  # 4000 directories, 15 a page.
        many = {**view, 'path': '/' + 'p' * 900, 'entries': [{'name': '名' * 255, 'link': True}] * 20,
                'notice': '✓ 已添加 ' + 'n' * 32}
        card = json.dumps(directory_card('a' * 24, many, BROWSE_HOST), ensure_ascii=False)
        self.assertLess(len(card.encode()), 30000)
        self.assertLessEqual(card.count('"tag"'), 200)

    @requires_extension()
    def test_select_registers_path_preserves_draft_without_binding(self):
        self.prepare()
        selected = self.root / 'another project'
        selected.mkdir()
        before = read_topic(self.target)
        self.picker.process(self.ctx, self.open_event)
        self.click('near')
        self.enter(selected.name)
        self.click('select')
        self.assertEqual(self.record()['status'], 'replaced')
        fields = list(walk_elements(self.current_card()['body']['elements']))
        shown = selects(self.current_card())
        self.assertEqual([shown['effort']['initial_option'], shown['workspace']['initial_option']], ['1:high', selected.name])
        self.assertEqual(shown['model']['initial_option'], 'maso:maso-model')
        self.assertNotIn('path', [e.get('name') for e in fields])  # No path input since 2026-11-03.
        config = load_config(self.ctx.state_dir, self.work)
        self.assertEqual(config['workspaces'][selected.name], str(selected))
        self.assertEqual(read_topic(self.target), before)
        self.assertTrue(self.app.runtime.jobs.queue.empty())
        replacement = card_token(self.current_card())
        record = json.loads((self.record_path.parent / (replacement + '.json')).read_text())
        self.assertEqual(record['card_id'], 'existing-card')
        self.assertEqual(record['sequence'], self.record()['sequence'])
        self.assertFalse(record['new_topic'])

    @requires_extension()
    def test_cancel_restores_all_draft_fields_without_adding_workspace(self):
        self.prepare()
        self.open_event['form_value'] = json.dumps(self.open_event['form_value'])
        before = load_config(self.ctx.state_dir, self.work)
        self.picker.process(self.ctx, self.open_event)
        self.click('cancel')
        fields = list(walk_elements(self.current_card()['body']['elements']))
        self.assertNotIn('path', [e.get('name') for e in fields])  # No path input since 2026-11-03.
        self.assertEqual(self.record()['draft']['path'], 'draft path')  # A path an older card sent is kept.
        self.assertEqual(selects(self.current_card())['model']['initial_option'], 'maso:maso-model')
        self.assertEqual(load_config(self.ctx.state_dir, self.work), before)

    @requires_extension()
    def test_returned_form_starts_waiting_task_in_selected_harness_and_directory_once(self):
        self.prepare()
        self.receive('source', 'queued request')
        remember_topic_message(self.ctx.state_dir, self.target.topic_id, 'chat', 'card-message')
        selected = self.root / 'chosen'
        selected.mkdir()
        self.picker.process(self.ctx, self.open_event)
        self.click('near')
        self.enter(selected.name)
        self.click('select')
        self.assertTrue(self.app.runtime.jobs.queue.empty())
        event = {**self.open_event, 'action_name': SUBMIT_PREFIX + card_token(self.current_card()), 'form_value': {
            'model': 'maso:maso-model', 'effort': '1:high', 'workspace': selected.name, 'path': '',
            'run_mode': 'direct'}}
        self.app.handle_card_action_event(event, self.ctx)
        self.app.handle_card_action_event(event, self.ctx)
        self.assertEqual(self.app.runtime.jobs.queue.qsize(), 1)
        job = self.app.runtime.jobs.queue.get_nowait()
        self.assertEqual((job.harness_id, job.workdir, job.user_text), ('maso', selected, 'queued request'))

    def test_wrong_owner_chat_source_and_changed_binding_are_rejected(self):
        self.prepare()
        for change in ({'operator_id': 'other'}, {'chat_id': 'other'}, {'message_id': 'other'},
                       {'action_name': PICKER_PREFIX + '../other'}):
            self.picker.process(self.ctx, {**self.open_event, **change})
        self.api.assert_not_called()
        self.app.topics.select_harness(self.target, 'chat', 'claude')
        self.picker.process(self.ctx, self.open_event)
        self.api.assert_not_called()

    def test_duplicates_old_views_and_old_start_cannot_apply(self):
        self.prepare().process(self.ctx, self.open_event)
        self.picker.process(self.ctx, self.open_event)
        self.assertEqual(self.api.call_count, 1)
        old = self.action('near')
        self.picker.process(self.ctx, old)
        self.picker.process(self.ctx, old)
        self.assertEqual(self.api.call_count, 2)
        with self.assertRaisesRegex(ValueError, '最新选择表单'):
            submit_launch_form(self.child, self.target, {**self.open_event, 'action_name': SUBMIT_PREFIX + self.token})

    def test_failed_put_keeps_previous_view_and_retry_uses_new_sequence(self):
        self.prepare().process(self.ctx, self.open_event)
        before = self.record()['picker']
        action = self.action('near')
        self.api.return_value = None
        self.picker.process(self.ctx, action)
        self.assertEqual(self.record()['picker'], before)
        self.api.return_value = {'code': 0}
        self.picker.process(self.ctx, action)
        self.assertEqual(self.record()['picker']['path'], str(self.root))
        self.assertEqual([c.args[3]['sequence'] for c in self.api.call_args_list], [5, 6, 7])

    def test_slow_scan_shows_loading_and_late_result_cannot_overwrite_navigation(self):
        self.prepare()
        slow = Future()
        ready = Future()
        ready.set_result({'entries': [], 'error': ''})
        self.picker.started = True  # The test runs the queued completion itself.
        with mock.patch.object(self.picker.cache, 'request', side_effect=[slow, ready]):
            started = time.monotonic()
            self.picker.process(self.ctx, self.open_event)
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(self.record()['picker']['loading'])
            self.assertIn('正在读取', json.dumps(self.current_card(), ensure_ascii=False))
            self.click('near')
            slow.set_result({'entries': [{'name': 'late', 'link': False}], 'error': ''})
            _, ctx, event = self.picker.queue.get_nowait()
            self.picker.process(ctx, event)
            self.assertEqual(self.record()['picker']['path'], str(self.root))
            self.assertEqual(self.api.call_count, 2)

    def test_async_completion_and_restart_refresh(self):
        self.prepare()
        slow = Future()
        self.picker.started = True  # The test runs the queued completion itself.
        with mock.patch.object(self.picker.cache, 'request', return_value=slow):
            self.picker.process(self.ctx, self.open_event)
            slow.set_result({'entries': [], 'error': ''})
            _, ctx, event = self.picker.queue.get_nowait()
            self.picker.process(ctx, event)
        self.assertFalse(self.record()['picker']['loading'])
        self.picker = DirectoryPicker(self.app)
        self.click('refresh')
        self.assertFalse(self.record()['picker']['error'])

    def test_symlink_file_and_removed_directory_are_recoverable(self):
        self.prepare()
        (self.work / 'link').symlink_to(self.work / 'missing')
        self.picker.process(self.ctx, self.open_event)
        self.click('near')
        self.enter(self.work.name)
        self.enter('link')
        self.assertTrue(self.record()['picker']['error'])
        count = self.api.call_count
        self.click('select')
        self.assertEqual(self.api.call_count, count)
        self.click('up')
        (self.work / 'link').unlink()
        self.work.rmdir()
        self.click('select')
        self.assertIn('不可用', self.record()['picker']['notice'])
        self.assertIn('不可用', json.dumps(self.current_card(), ensure_ascii=False))

    def test_dispatch_does_not_block_message_consumer(self):
        self.prepare()
        entered, release = threading.Event(), threading.Event()
        def slow(ctx, event):
            entered.set()
            release.wait(3)
        with mock.patch.object(self.picker, 'process', side_effect=slow):
            try:
                started = time.monotonic()
                self.app.handle_card_action_event(self.open_event, self.ctx)
                self.assertLess(time.monotonic() - started, .2)
                self.assertTrue(entered.wait(1))
            finally:
                release.set()
                self.picker.queue.join()
                self.app.runtime.shutdown.set()

    def test_picker_issued_before_legacy_session_cannot_change_its_workspace(self):
        self.prepare()
        write_session_id(self.target.session_path, 'preserved-session')
        before = read_topic(self.target)
        self.picker.process(self.ctx, self.open_event)
        self.api.assert_not_called()
        self.assertEqual(read_topic(self.target), before)
        self.assertEqual(self.target.session_path.read_text().strip(), 'preserved-session')
