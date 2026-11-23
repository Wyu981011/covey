"""The indexed record store (core/store.py directory_store, one_scan, invalidate_directory) under concurrent
writers, and state recovered from what is on disk."""
from __future__ import annotations

import copy
import json
import shutil
import stat
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.records import write_topic
from covey.app import outbox
from covey.app.runtime import JobRegistry
from covey.core.jobs import job_file, upsert_job_record
from covey.core.state import write_private_text
from covey.core.history_storage import recent_history
from covey.core import store as store_module
from covey.core.store import directory_store, invalidate_directory, one_scan
from covey.core.topics import workspace_locked


class IndexedStorageTest(unittest.TestCase):
    def test_bad_record_isolated_and_repeat_query_avoids_parsing(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            write_private_text(path/'a.json', json.dumps({'topic_id':'a','job_id':1}))
            write_private_text(path/'b.json', '{broken')
            store = directory_store(path)
            self.assertEqual(len(store.query(topic_id='a')), 1)
            self.assertIn('b.json', store.invalid)
            with mock.patch('covey.core.store.json.loads', side_effect=AssertionError('unnecessary read')):
                self.assertEqual(len(store.query(topic_id='a')), 1)
            write_private_text(path/'a.json', json.dumps({'topic_id':'b','job_id':1}))
            self.assertEqual(store.query(topic_id='a'), [])
            self.assertEqual(len(store.query(topic_id='b')), 1)

    def copies(self):
        """The store's deepcopy, recording the key (or job_id) of each record it copies."""
        copied, real = [], copy.deepcopy
        fake = SimpleNamespace(deepcopy=lambda value: copied.append(value.get('key', value.get('job_id'))) or real(value))
        return copied, mock.patch('covey.core.store.copy', fake)

    def test_a_where_filter_copies_only_the_records_it_accepts(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for number in (1, 2, 3):
                write_private_text(path / f'{number}.json', json.dumps({'topic_id': 't', 'job_id': number, 'tags': []}))
            store = directory_store(path)
            copied, patched = self.copies()
            with patched:
                found = store.query(lambda record: record['job_id'] != 2, topic_id='t')
            self.assertEqual(([record['job_id'] for _, record in found], copied), ([1, 3], [1, 3]))
            found[0][1]['tags'].append('changed')  # A copy: the cached record stays as it was.
            self.assertEqual(store.query(topic_id='t')[0][1]['tags'], [])

    def test_one_message_scans_a_directory_once_and_sees_this_process_writes(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            write_private_text(path / 'a.json', json.dumps({'topic_id': 't'}))
            store, clock, scans = directory_store(path), [100.0], []
            real_list = type(store)._list

            def listing(self):
                scans.append(self.directory)
                return real_list(self)

            def names():
                return [p.name for p, _ in store.query(topic_id='t')]
            with mock.patch('covey.core.store.time.monotonic', lambda: clock[0]), \
                    mock.patch.object(type(store), '_list', listing):
                with one_scan():
                    self.assertEqual(names(), ['a.json'])
                    (path / 'b.json').write_text(json.dumps({'topic_id': 't'}))  # Another process's write.
                    write_private_text(path / 'c.json', json.dumps({'topic_id': 't'}))  # This process's.
                    clock[0] += 0.5
                    self.assertEqual(names(), ['a.json', 'c.json'])
                    self.assertEqual(len(scans), 1)  # c.json was read by name.
                    clock[0] += 0.6  # The scan is over a second old: redone, as without the block.
                    self.assertEqual(names(), ['a.json', 'b.json', 'c.json'])
                    self.assertEqual(len(scans), 2)
                    invalidate_directory(path)  # A write it cannot name: rescanned at once.
                    self.assertEqual(names(), ['a.json', 'b.json', 'c.json'])
                    self.assertEqual(len(scans), 3)
                write_private_text(path / 'd.json', json.dumps({'topic_id': 't'}))
                self.assertEqual(names(), ['a.json', 'b.json', 'c.json', 'd.json'])
                self.assertEqual(len(scans), 4)  # Outside the block every write still means a rescan.

    def test_a_scan_of_many_files_reads_them_in_parallel_with_the_same_result(self):
        # S35: a task runner's first query read 927 job records one by one from NAS, 2.3 s.
        from covey.core import store as store_module
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)
            for number in range(3 * store_module.SCAN_THREADS):
                write_private_text(path / f'{number}.json', json.dumps({'topic_id': 't', 'job_id': number}))
            write_private_text(path / 'broken.json', '{broken')
            write_private_text(path / 'list.json', '[]')
            store, threads, real = directory_store(path), set(), store_module.JsonDirectoryStore._read

            def read(self, file):
                threads.add(threading.current_thread().name)
                return real(self, file)
            with mock.patch.object(store_module.JsonDirectoryStore, '_read', read):
                found = store.query(topic_id='t')
            self.assertEqual(sorted(r['job_id'] for _, r in found), list(range(3 * store_module.SCAN_THREADS)))
            self.assertEqual(store.invalid, {'broken.json', 'list.json'})
            self.assertTrue(threads and all(name.startswith('store-scan') for name in threads), threads)
            write_private_text(path / '0.json', json.dumps({'topic_id': 'u', 'job_id': 0}))
            invalidate_directory(path)
            loads, real_loads = [], json.loads
            with mock.patch('covey.core.store.json.loads', lambda text: loads.append(text) or real_loads(text)):
                self.assertEqual([r['job_id'] for _, r in store.query(topic_id='u')], [0])
            self.assertEqual(len(loads), 1)  # Only the changed file: unchanged ones, broken or not, are not read again.

    def test_a_rescan_reads_only_the_files_whose_inode_changed(self):
        # S39: a stat per file cost 0.3-0.9 s for 976 job records on NFS; one listing 1.3 ms.
        from covey.core import store as store_module
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'records'  # Not a JOURNALED name: every look lists it.
            for number in (1, 2, 3):
                write_private_text(path / f'{number}.json', json.dumps({'topic_id': 't', 'job_id': number}))
            store, real = directory_store(path), store_module.JsonDirectoryStore._read
            self.assertEqual(len(store.query(topic_id='t')), 3)
            write_private_text(path / '2.json', json.dumps({'topic_id': 't', 'job_id': 22}))  # A new inode.
            (path / '3.json').unlink()
            write_private_text(path / '4.json', json.dumps({'topic_id': 't', 'job_id': 4}))
            (path / '.5.json.tmp').write_text('{}')  # A writer's temp file: not a record.
            read = []
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)):
                self.assertEqual([r['job_id'] for _, r in store.query(topic_id='t')], [1, 22, 4])
            self.assertEqual(sorted(read), ['2.json', '4.json'])
            shutil.rmtree(path)
            invalidate_directory(path)
            self.assertEqual(store.query(), [])

    def test_a_journaled_directory_catches_up_from_its_journal_and_lists_only_when_it_must(self):
        # S45: a changed directory's listing took about 100 ms on NFS with ~1000 job records; the journal 1-3 ms.
        from covey.core import store as store_module
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'jobs'
            write_private_text(path / 'a.json', json.dumps({'topic_id': 't'}))
            write_private_text(Path(root) / 'other' / 'x.json', '{}')
            self.assertEqual((path / '.journal').read_text(), 'a.json\n')
            self.assertFalse((Path(root) / 'other' / '.journal').exists())  # Only the record directories keep one.
            store, clock, listings = directory_store(path), [100.0], []
            real_list = type(store)._list

            def names():
                clock[0] += 2  # Past FRESH_SECONDS: each query catches up.
                return [p.name for p, _ in store.query(topic_id='t')]

            def elsewhere(name, note=True):  # Another process's write_private_text.
                temp = path / f'.{name}.tmp'
                temp.write_text(json.dumps({'topic_id': 't'}))
                temp.replace(path / name)
                if note:
                    store_module.note_change(path, name)
            with mock.patch('covey.core.store.time.monotonic', lambda: clock[0]), \
                    mock.patch.object(type(store), '_list', lambda self: listings.append(1) or real_list(self)):
                self.assertEqual((names(), len(listings)), (['a.json'], 1))
                elsewhere('b.json')
                self.assertEqual((names(), len(listings)), (['a.json', 'b.json'], 1))  # From the new line.
                elsewhere('c.json', note=False)
                with (path / '.journal').open('a') as journal:
                    journal.write('c.js')  # A line still being appended: read next time, whole.
                self.assertEqual((names(), len(listings)), (['a.json', 'b.json'], 1))
                with (path / '.journal').open('a') as journal:
                    journal.write('on\n../escape.json\n.c.json.tmp\n')  # Not record names: ignored.
                self.assertEqual((names(), len(listings)), (['a.json', 'b.json', 'c.json'], 1))
                (path / '.journal').unlink()  # Started again (maintenance): listed once, then read anew.
                elsewhere('d.json')
                self.assertEqual((names(), len(listings)), (['a.json', 'b.json', 'c.json', 'd.json'], 2))
                elsewhere('e.json')
                self.assertEqual((names()[-1], len(listings)), ('e.json', 2))
                elsewhere('f.json', note=False)  # A write the journal missed: seen at the next full listing.
                self.assertEqual((names()[-1], len(listings)), ('e.json', 2))
                clock[0] += store_module.LIST_SECONDS
                self.assertEqual((names()[-1], len(listings)), ('f.json', 3))

    def test_a_new_process_starts_from_the_saved_index_and_reads_only_what_it_asks_for(self):
        # S46: a task runner read all ~1000 job records at its start; parsing them slowed it by 0.3-0.8 s.
        from covey.core import store as store_module
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'jobs'
            for number in range(1, 21):
                write_private_text(path / f'{number}.json', json.dumps({'topic_id': f't{number % 4}', 'job_id': number}))
            bridge = store_module.JsonDirectoryStore(path)  # Not directory_store: each one is another process.
            self.assertEqual(len(bridge.query()), 20)
            self.assertTrue(bridge.save_index(every=0))
            self.assertFalse(bridge.save_index(every=0))  # Nothing changed since.
            write_private_text(path / '21.json', json.dumps({'topic_id': 't1', 'job_id': 21}))  # After .index.
            write_private_text(path / '5.json', json.dumps({'topic_id': 't1', 'job_id': 55}))
            read, real = [], store_module.JsonDirectoryStore._read
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)):
                runner = store_module.JsonDirectoryStore(path)
                runner.catch_up()
                self.assertEqual(sorted(read), ['21.json', '5.json'])  # Only what the journal names since .index.
                self.assertEqual(sorted(r['job_id'] for _, r in runner.query(topic_id='t1')), [1, 9, 13, 17, 21, 55])
                self.assertEqual(sorted(read), ['1.json', '13.json', '17.json', '21.json', '5.json', '9.json'])
                self.assertEqual(len(runner.query(topic_id='t2')), 5)
                self.assertEqual(len(read), 11)
                self.assertEqual(len(runner.query()), 21)  # Asking for all reads them all, as before.
            (path / '.index').write_text('{broken')
            fresh = store_module.JsonDirectoryStore(path)
            self.assertEqual(len(fresh.query(topic_id='t3')), 5)  # No usable .index: reads every record.
            self.assertEqual(len(fresh.records), 21)
            bridge.catch_up()  # The Bridge's next look, then its next save.
            self.assertTrue(bridge.save_index(every=0))
            (path / '.journal').unlink()  # Replaced since .index: listed, reading only changed inodes.
            write_private_text(path / '2.json', json.dumps({'topic_id': 't0', 'job_id': 22}))
            read.clear()
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)):
                later = store_module.JsonDirectoryStore(path)
                later.catch_up()
            self.assertEqual(read, ['2.json'])
            self.assertEqual(later.fields['2.json']['job_id'], 22)

    def test_a_new_process_finds_jobs_by_a_set_of_statuses_and_the_last_job_number_from_the_index(self):
        # Repo review R4: the Bridge's start and a deploy's status read every job record (2.6 s for 1185 on
        # NFS) for the few running ones and the largest job number.
        from covey.app.detached import restart_blockers
        from covey.core import jobs, store as store_module
        from covey.core.statuses import RUNNING
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            statuses = ['done', 'running', 'queued', 'cancel_requested', 'failed', 'waiting_user', 'continued']
            # By hand: each record with its own updated_at, and one malformed (status 7) that no writer makes.
            for number in range(1, 22):
                write_private_text(job_file(state, f'k{number}'), json.dumps({
                    'key': f'k{number}', 'job_id': number, 'status': statuses[number % 7], 'backend': 'codex',
                    'updated_at': f'2026-10-28T10:{number:02}:00'}))
            write_private_text(job_file(state, 'odd'), json.dumps({'key': 'odd', 'job_id': '30', 'status': 7}))
            bridge = store_module.JsonDirectoryStore(state / 'jobs')
            self.assertEqual(len(bridge.query()), 22)
            self.assertTrue(bridge.save_index(every=0))
            read, real = [], store_module.JsonDirectoryStore._read
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)), \
                    mock.patch.dict(store_module._stores, clear=True):
                self.assertEqual(jobs.max_job_id(state), 30)  # The digits of a string job_id count too.
                self.assertEqual(read, [])
                running = jobs.running_job_records(state)
                self.assertEqual([r['job_id'] for r in running], [17, 16, 15, 10, 9, 8, 3, 2, 1])  # Newest first.
                self.assertEqual(sorted(read), sorted(f'k{r["job_id"]}.json' for r in running))
                self.assertEqual(running, [r for r in jobs.list_job_records(state, limit=0)
                                           if r.get('status') in RUNNING])
            read.clear()
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)), \
                    mock.patch.dict(store_module._stores, clear=True), \
                    mock.patch('covey.app.detached.live_keys', return_value={'k2'}):
                blockers = restart_blockers(state)  # A deploy's status: another process.
            self.assertEqual([b['job_id'] for b in blockers], [16, 15, 9, 8, 1])  # Not k2's: its runner lives.
            self.assertEqual(len(read), 9)
            self.assertEqual(sorted(bridge.query(status={'failed', 'continued'})),
                             sorted(bridge.query(status='failed') + bridge.query(status='continued')))
            self.assertEqual(bridge.query(status=set()), [])

    def test_count_reads_no_record_and_warm_reads_each_once_for_the_queries_after_it(self):
        # The Bridge's start: how many answered questions there are (a count) without copying them, and every job record
        # read on a thread while it checks its identity, for the recovery that reads them all.
        from covey.core import store as store_module
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'jobs'
            for number in range(1, 13):
                write_private_text(path / f'{number}.json', json.dumps(
                    {'topic_id': 't', 'job_id': number, 'status': 'failed' if number % 3 == 0 else 'done'}))
            bridge = store_module.JsonDirectoryStore(path)
            self.assertEqual(len(bridge.query()), 12)
            self.assertTrue(bridge.save_index(every=0))
            read, real = [], store_module.JsonDirectoryStore._read
            with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                   lambda self, file: read.append(file.name) or real(self, file)):
                started = store_module.JsonDirectoryStore(path)
                self.assertEqual((started.count(status='failed'), started.count(status={'done', 'failed'}),
                                  started.count(topic_id='t', status='queued')), (4, 12, 0))
                self.assertEqual(read, [])
                started.warm()
                self.assertEqual(sorted(read), sorted(f'{n}.json' for n in range(1, 13)))
                self.assertEqual(len(started.query()), 12)
                self.assertEqual(len(read), 12)  # The query after it reads none again.

    def test_read_each_keeps_the_order_and_raises_what_a_read_raises(self):
        from covey.core import state
        with mock.patch.object(state, 'READ_THREADS', 4):
            self.assertEqual(state.read_each(range(40), lambda n: n * n), [n * n for n in range(40)])
            with self.assertRaises(ZeroDivisionError):
                state.read_each([1, 0, 2], lambda n: 1 / n)
        self.assertEqual((state.read_each([], str), state.read_each([7], str)), ([], ['7']))

    def test_the_boards_read_leaves_old_records_unread_and_says_the_same_as_reading_them_all(self):
        # P1: the butler's snapshot read ~3400 job records in a new process for the ~150 written within three
        # days; updated_at rides in .index (store.CARRIED) so board_read.read does not read the rest.
        import datetime
        from covey.core import board_read, store as store_module
        from covey.core.jobs import select_job_records
        from covey.core.butler import butler_topic_id
        now = time.time()

        def stamp(days):
            return datetime.datetime.fromtimestamp(now - days * 86400).isoformat()
        chat = 'chat-1'
        rows = [('old', 'done', 10, 't1'), ('recent', 'done', 1, 't1'), ('running', 'running', 20, 't2'),
                ('old-kept', 'done', 10, 't3'), ('main', 'done', 1, butler_topic_id(chat)), ('other', 'done', 1, 't4'),
                ('no-time', 'done', None, 't5'), ('odd-time', 'done', 7, 't6'), ('queued', 'queued', 2, 't7')]
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            for number, (key, status, days, topic) in enumerate(rows, 1):
                record = {'key': key, 'job_id': number, 'status': status, 'topic_id': topic,
                          'chat_id': 'chat-2' if key == 'other' else chat}
                if days is not None:
                    record['updated_at'] = stamp(days)
                if key == 'odd-time':
                    record['updated_at'] = 12345  # Not an ISO time: ``fresh`` takes it as now.
                write_private_text(job_file(state, key), json.dumps(record))
            bridge = store_module.JsonDirectoryStore(state / 'jobs')
            self.assertEqual(len(bridge.query()), len(rows))
            self.assertTrue(bridge.save_index(every=0))
            saved = json.loads((state / 'jobs' / '.index').read_text())
            self.assertEqual(saved['entries']['recent.json'][1]['updated_at'], stamp(1))
            self.assertEqual(saved['entries']['odd-time.json'][1]['updated_at'], 12345)
            self.assertNotIn('updated_at', saved['entries']['no-time.json'][1])
            self.assertNotIn(('updated_at', stamp(1)), bridge.index)  # Carried, not indexed.

            def run(keep=frozenset()):
                """(keys read, keys board_read.read returns, the same without ``narrow``), in a new process."""
                read, real = [], store_module.JsonDirectoryStore._read
                with mock.patch.object(store_module.JsonDirectoryStore, '_read',
                                       lambda self, file: read.append(file.name) or real(self, file)), \
                        mock.patch.dict(store_module._stores, clear=True):
                    got = board_read.read(state, chat, now, keep=keep).jobs
                    asked = sorted(read)
                with mock.patch.dict(store_module._stores, clear=True):
                    every = select_job_records(state, lambda r: board_read.listed(r.get('topic_id'), chat) and (
                        board_read.fresh(r, now) or r.get('topic_id') in keep), chat_id=chat)
                self.assertEqual(got, every)
                return asked, [r['key'] for r in got]
            asked, keys = run()
            self.assertEqual(sorted(keys), ['no-time', 'odd-time', 'queued', 'recent', 'running'])
            # Not read: the old one, the one of another chat, the butler's, and the not-kept old one.
            self.assertEqual(asked, ['no-time.json', 'odd-time.json', 'queued.json', 'recent.json', 'running.json'])
            asked, keys = run(keep=frozenset({'t3', 't1'}))
            self.assertEqual(sorted(keys), ['no-time', 'odd-time', 'old', 'old-kept', 'queued', 'recent', 'running'])
            self.assertEqual(len(asked), 7)
            # An .index from before updated_at was carried: the records decide, the answer is the same.
            for _, fields in saved['entries'].values():
                fields.pop('updated_at', None)
            (state / 'jobs' / '.index').write_text(json.dumps(saved))
            asked, keys = run()
            self.assertEqual(sorted(keys), ['no-time', 'odd-time', 'queued', 'recent', 'running'])
            self.assertEqual(len(asked), len(rows) - 2)  # All but the other chat's (indexed) and the butler's.
            # A ``narrow`` that cannot tell leaves the record to ``where``.
            def broken(fields):
                raise TypeError('cannot tell')
            with mock.patch.dict(store_module._stores, clear=True):
                self.assertEqual(len(select_job_records(state, None, narrow=broken)), len(rows))

    def test_a_private_write_skips_repeated_steps_but_remakes_a_removed_directory(self):
        # S39: each step of a write is a NAS round trip; about 20 ms a write.
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root) / 'acks'
            write_private_text(folder / 'a.json', '{}')
            shutil.rmtree(folder)
            with mock.patch.object(Path, 'unlink', autospec=True) as unlink:
                write_private_text(folder / 'b.json', '{"ok": true}')
            unlink.assert_not_called()  # The temp file became b.json: nothing to remove.
            self.assertEqual(stat.S_IMODE((folder / 'b.json').stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
            with mock.patch.object(Path, 'replace', side_effect=OSError('disk full')):
                with self.assertRaises(OSError):
                    write_private_text(folder / 'c.json', '{}')
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['b.json'])

    def test_a_workspace_check_copies_only_its_topics_records(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            upsert_job_record(state, 'mine', job_id=1, topic_id='t', status='waiting_workspace')
            for number in range(2, 12):
                upsert_job_record(state, f'other-{number}', job_id=number, topic_id='u', status='running')
            topic = write_topic(state, topic_id='t').parent
            ctx = SimpleNamespace(state_dir=state, topic_id='t', history_path=topic / 'history.jsonl',
                                  session_path=topic / 'codex_session_id')
            copied, patched = self.copies()
            with patched:
                self.assertFalse(workspace_locked(ctx))  # Another topic's running jobs do not settle this one.
                upsert_job_record(state, 'ran', job_id=12, topic_id='t', status='done')
                self.assertTrue(workspace_locked(ctx))
            self.assertEqual(copied, ['mine', 'mine', 'ran'])

    def test_the_outbox_tick_copies_only_the_results_it_sends_now(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            due = dict(outbox_version=1, delivery_ok=False, outbox_state='pending', outbox_next_at=0, backend='gone',
                       verified_reply_authorized=True, verified_reply_state='authorized')
            upsert_job_record(state, 'due', job_id=1, **due)
            upsert_job_record(state, 'later', job_id=2, **dict(due, outbox_next_at=time.time() + 60))
            upsert_job_record(state, 'paused', job_id=3, **dict(due, outbox_state='paused'))
            for number in range(4, 24):
                upsert_job_record(state, f'sent-{number}', job_id=number, outbox_version=1, delivery_ok=True)
            jobs = JobRegistry()
            copied, patched = self.copies()
            with patched:  # No Harness owns 'gone': the due result is read and left as it is.
                outbox.tick(SimpleNamespace(runtime=SimpleNamespace(jobs=jobs, log=print), apps={}),
                            SimpleNamespace(state_dir=state))
            self.assertEqual(copied, ['due'])

    def test_a_malformed_record_is_skipped_once_logged_and_the_tick_goes_on(self):
        # A field of the wrong type made due() raise: the tick stopped before any record (S21 review).
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            due = dict(outbox_version=1, delivery_ok=False, outbox_state='pending', outbox_next_at=0, backend='gone',
                       verified_reply_authorized=True, verified_reply_state='authorized')
            upsert_job_record(state, 'bad', job_id=1, **dict(due, outbox_next_at='soon'))
            upsert_job_record(state, 'due', job_id=2, **due)
            logs = []
            gateway = SimpleNamespace(runtime=SimpleNamespace(jobs=JobRegistry(),
                                                              log=logs.append), apps={})
            copied, patched = self.copies()
            with patched:
                for _ in range(2):
                    outbox.tick(gateway, SimpleNamespace(state_dir=state))
                self.assertEqual(copied, ['due', 'due'])
                self.assertEqual(logs, ['record jobs/bad.json skipped: TypeError'])  # Once, not every 5 s.
                upsert_job_record(state, 'bad', outbox_next_at='later')
                outbox.tick(gateway, SimpleNamespace(state_dir=state))
            self.assertEqual(logs, ['record jobs/bad.json skipped: TypeError'] * 2)  # Changed since: said again.

    def test_terminal_job_cannot_be_reopened_by_heartbeat(self):
        with tempfile.TemporaryDirectory() as root:
            state = Path(root)
            upsert_job_record(state, 'job', status='done', status_message='finished')
            record = upsert_job_record(state, 'job', status='running', status_message='heartbeat')
            self.assertEqual(record['status'], 'done')
            self.assertEqual(record['status_message'], 'finished')
            self.assertEqual(record['schema_version'], 1)

    def test_recent_history_does_not_open_old_archive(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root)/'history.jsonl'
            archive = Path(str(path)+'.archive'); archive.mkdir()
            (archive/'old.jsonl.gz').write_bytes(b'not needed')
            path.write_text('\n'.join(json.dumps({'role':'user','content':str(i)}) for i in range(10000)))
            with mock.patch('covey.core.history_storage.gzip.open', side_effect=AssertionError('old archive read')):
                self.assertEqual([r['content'] for r in recent_history(path, 2)], ['9998','9999'])

    def test_reverse_history_preserves_unicode_and_reset(self):
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'history.jsonl'
            values=[{'role':'user','content':'旧'}, {'type':'session_reset'}, {'role':'user','content':'长说明\n'+'中文'*6000}]
            path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in values))
            self.assertEqual(recent_history(path), values[-1:])

    def test_history_reader_does_not_hold_other_topic(self):
        from covey.core.history_storage import history_lines
        with tempfile.TemporaryDirectory() as root:
            a, b = Path(root)/'a.jsonl', Path(root)/'b.jsonl'
            a.write_text('{"role":"user","content":"A"}\n')
            b.write_text('{"role":"user","content":"B"}\n')
            reader = history_lines(a)
            next(reader)
            with ThreadPoolExecutor(1) as pool:
                future = pool.submit(recent_history, b)
                try:
                    self.assertEqual(future.result(1)[0]['content'], 'B')
                finally:
                    reader.close()


def statuses(rows):
    """{file name: status} of a query's rows."""
    return {path.name: record.get('status') for path, record in rows}


class StuckDiskTest(unittest.TestCase):
    """T677: an NFS open of jobs/.journal hung 1-5 minutes under the store's lock, and every reader and writer of the
    records waited with it (T673: a lead's topic_read 113 s, several web pushes behind it). Now no read of the disk
    holds that lock: one thread catches up, the others answer from its last catch-up and this process's writes,
    a write is never held up, and once the stuck read ends nothing is lost and nothing older comes back."""

    def setUp(self):
        root = Path(tempfile.mkdtemp(prefix='store-stuck-'))
        self.addCleanup(shutil.rmtree, root, True)
        self.root, self.path, self.threads = root, root / 'jobs', []
        self.addCleanup(lambda: [thread.join(10) for thread in self.threads])
        # Each query tries to catch up: a directory's time may not show a write within its tick (tmpfs, NFS). A catch-up
        # under way is stuck once it is 0.2 s old.
        for name, value in (('FRESH_SECONDS', 0.0), ('PATIENCE', 0.2)):
            patched = mock.patch.object(store_module, name, value, create=True)  # PATIENCE: none before T677.
            patched.start()
            self.addCleanup(patched.stop)

    def write(self, name, path=None, **record):
        """This process's write (write_private_text tells the store, invalidate_directory)."""
        write_private_text((path or self.path) / name, json.dumps(record))

    def elsewhere(self, name, path=None, **record):
        """Another process's write: noted in the journal of a journaled folder, not told to this process's store."""
        folder = path or self.path
        temp = folder / f'.{name}.tmp'
        temp.write_text(json.dumps(record))
        temp.replace(folder / name)
        store_module.note_change(folder, name)

    def background(self, target, into=None):
        """(thread, its result list): ``target`` running on a thread of its own, put in ``into`` before it starts."""
        result = []
        thread = threading.Thread(target=lambda: result.append(target()), daemon=True)
        for each in (self.threads, into if into is not None else []):
            each.append(thread)
        thread.start()
        return thread, result

    def promptly(self, target, seconds=3):
        """``target()``, which must be done within ``seconds``: before T677 it waited for the stuck read."""
        thread, result = self.background(target)
        thread.join(seconds)
        self.assertFalse(thread.is_alive(), 'held up behind a read stuck on the disk')
        return result[0]

    @contextmanager
    def stuck_journal(self):
        """(entered, release): each open of a journal blocks until ``release`` is set, as the live NFS open did."""
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        real = open

        def slow(file, *args, **kwargs):
            if Path(file).name == store_module.JOURNAL:
                entered.set()
                release.wait(20)
            return real(file, *args, **kwargs)
        with mock.patch('covey.core.store.open', slow, create=True):
            yield entered, release
        release.set()

    def held(self, method, threads, name=None, first=False):
        """(held, release, asked, patch): ``method`` (``_read`` or ``_list``) of the stores does its read, then on one of
        ``threads`` (for ``_read``, of file ``name`` only) blocks until ``release``: a read slow to come back (``first``:
        slow to begin). ``asked`` lists the files ``_read`` was asked for."""
        held, release, asked = threading.Event(), threading.Event(), []
        self.addCleanup(release.set)
        real = getattr(store_module.JsonDirectoryStore, method)

        def slow(store, *args):
            asked.extend(each.name for each in args)
            mine = threading.current_thread() in threads and (name is None or args[0].name == name)
            found = None if first else real(store, *args)
            if mine:
                held.set()
                release.wait(20)
            return real(store, *args) if first else found
        return held, release, asked, mock.patch.object(store_module.JsonDirectoryStore, method, slow)

    def test_readers_and_writers_go_on_while_a_catch_up_is_stuck_on_the_journal(self):
        self.write('a.json', topic_id='t', status='running', job_id=1)
        store = directory_store(self.path)
        self.assertEqual(statuses(store.query(topic_id='t')), {'a.json': 'running'})
        self.elsewhere('b.json', topic_id='t', status='queued', job_id=2)  # The next catch-up reads it from the journal.
        with self.stuck_journal() as (entered, release):
            leader, found = self.background(lambda: store.query(topic_id='t'))
            self.assertTrue(entered.wait(5))
            # Others answer from the last catch-up, which b.json is not in yet.
            self.assertEqual(statuses(self.promptly(lambda: store.query(topic_id='t'))), {'a.json': 'running'})
            self.assertEqual(self.promptly(lambda: store.count(topic_id='t')), 1)
            self.assertEqual(self.promptly(lambda: store.max_field('job_id')), 1)
            # This process's writes are not held up, and are read back at once, by name.
            self.promptly(lambda: self.write('a.json', topic_id='t', status='done', job_id=1))
            self.promptly(lambda: self.write('c.json', topic_id='t', status='running', job_id=3))
            self.assertEqual(statuses(self.promptly(lambda: store.query(topic_id='t'))),
                             {'a.json': 'done', 'c.json': 'running'})
            self.assertEqual(self.promptly(lambda: store.max_field('job_id')), 3)
            self.assertEqual([p.name for p, _ in self.promptly(lambda: store.query(status='running'))], ['c.json'])
            with one_scan():
                self.assertEqual(statuses(self.promptly(lambda: store.query(status='done'))), {'a.json': 'done'})
            self.assertTrue(leader.is_alive())
            release.set()
            leader.join(5)
        self.assertFalse(leader.is_alive())
        everything = {'a.json': 'done', 'b.json': 'queued', 'c.json': 'running'}
        self.assertEqual(statuses(found[0]), everything)  # Its catch-up kept what was read while it was stuck.
        self.assertEqual(statuses(store.query(topic_id='t')), everything)
        self.assertEqual([p.name for p, _ in store.query(status='running')], ['c.json'])

    def test_a_reader_waits_for_a_young_catch_up_and_leaves_a_stuck_one_behind(self):
        self.write('a.json', topic_id='t')
        store = directory_store(self.path)
        store.query()
        self.elsewhere('b.json', topic_id='t')
        with mock.patch.object(store_module, 'PATIENCE', 1.0, create=True), self.stuck_journal() as (entered, release):
            leader, _ = self.background(store.query)
            self.assertTrue(entered.wait(5))
            waiting, found = self.background(lambda: store.query(topic_id='t'))
            waiting.join(0.1)
            self.assertTrue(waiting.is_alive())  # A catch-up a moment old: waited for, as before.
            release.set()
            waiting.join(5)
            leader.join(5)
        self.assertEqual([p.name for p, _ in found[0]], ['a.json', 'b.json'])  # What that catch-up found.
        self.elsewhere('c.json', topic_id='t')
        with self.stuck_journal() as (entered, release):
            leader, _ = self.background(store.query)
            self.assertTrue(entered.wait(5))
            time.sleep(0.3)  # Older than PATIENCE: stuck.
            began = time.monotonic()
            self.assertEqual([p.name for p, _ in self.promptly(lambda: store.query(topic_id='t'))], ['a.json', 'b.json'])
            self.assertLess(time.monotonic() - began, 1)
            release.set()
            leader.join(5)
        self.assertEqual([p.name for p, _ in store.query(topic_id='t')], ['a.json', 'b.json', 'c.json'])

    def test_one_thread_reads_the_journal_while_the_others_answer_from_the_last_catch_up(self):
        self.write('a.json', topic_id='t')
        store = directory_store(self.path)
        store.query()
        self.elsewhere('b.json', topic_id='t')
        calls, real = [], store_module.JsonDirectoryStore._from_journal

        def counted(store, *args):
            calls.append(threading.current_thread().name)
            return real(store, *args)
        with mock.patch.object(store_module.JsonDirectoryStore, '_from_journal', counted), \
                self.stuck_journal() as (entered, release):
            leader, _ = self.background(store.query)
            self.assertTrue(entered.wait(5))
            readers = [self.background(lambda: store.query(topic_id='t')) for _ in range(8)]
            for thread, found in readers:
                thread.join(3)
                self.assertFalse(thread.is_alive(), 'held up behind a read stuck on the disk')
                self.assertEqual([p.name for p, _ in found[0]], ['a.json'])
            self.assertEqual(len(calls), 1)  # None of them piled up behind it on the same open.
            release.set()
            leader.join(5)
        self.assertEqual([p.name for p, _ in store.query(topic_id='t')], ['a.json', 'b.json'])

    def test_a_slow_read_of_an_older_version_never_puts_it_back(self):
        self.write('a.json', topic_id='t', status='running', n=1)
        store = directory_store(self.path)
        store.query()
        self.elsewhere('a.json', topic_id='t', status='running', n=2)  # The next catch-up reads it, from the journal.
        leaders = []
        held, release, _, patched = self.held('_read', leaders, 'a.json')
        with patched:
            leader, found = self.background(lambda: store.query(topic_id='t'), leaders)
            self.assertTrue(held.wait(5))  # It has read n=2 and is not back yet.
            self.promptly(lambda: self.write('a.json', topic_id='t', status='done', n=3))
            self.assertEqual([r['n'] for _, r in self.promptly(lambda: store.query(topic_id='t'))], [3])
            release.set()
            leader.join(5)
        self.assertFalse(leader.is_alive())
        self.assertEqual([r['n'] for _, r in found[0]], [3])  # Its own answer, after its catch-up: not n=2 again.
        self.assertEqual([r['n'] for _, r in store.query(topic_id='t')], [3])
        self.assertEqual([p.name for p, _ in store.query(status='done')], ['a.json'])
        self.assertEqual(store.query(status='running'), [])

    def test_two_reads_at_about_the_same_time_that_disagree_are_read_again(self):
        self.write('a.json', topic_id='t', status='running', n=1)
        store = directory_store(self.path)
        store.query()
        self.write('a.json', topic_id='t', status='running', n=2)  # Read back by name, and in the journal.
        leaders = []
        held, release, _, patched = self.held('_read', leaders, 'a.json', first=True)
        with patched:
            leader, found = self.background(lambda: store.query(topic_id='t'), leaders)
            self.assertTrue(held.wait(5))  # Its read of a.json has begun, and has not opened the file yet.
            self.assertEqual([r['n'] for _, r in self.promptly(lambda: store.query(topic_id='t'))], [2])
            self.elsewhere('a.json', topic_id='t', status='done', n=3)  # What the slow read then finds.
            release.set()
            leader.join(5)
        self.assertFalse(leader.is_alive())
        # The slow read began first and saw the newer file: neither read can tell, so the file was read again.
        self.assertEqual([r['n'] for _, r in found[0]], [3])
        self.assertEqual(store.fields['a.json']['status'], 'done')

    def test_a_write_made_while_a_listing_is_under_way_is_not_dropped_by_it(self):
        path = self.root / 'records'  # Not journaled: each catch-up lists it.
        self.write('a.json', path, topic_id='t')
        store = directory_store(path)
        store.query()
        self.elsewhere('b.json', path, topic_id='t')
        leaders = []
        listed, release, _, patched = self.held('_list', leaders)
        with patched:
            leader, found = self.background(lambda: store.query(topic_id='t'), leaders)
            self.assertTrue(listed.wait(5))  # It listed a.json and b.json, and is not back yet.
            self.promptly(lambda: self.write('c.json', path, topic_id='t'))
            self.assertEqual([p.name for p, _ in self.promptly(lambda: store.query(topic_id='t'))], ['a.json', 'c.json'])
            release.set()
            leader.join(5)
        self.assertFalse(leader.is_alive())
        self.assertEqual([p.name for p, _ in found[0]], ['a.json', 'b.json', 'c.json'])  # Its listing missed c.json.
        self.assertIn('c.json', store.fields)

    def test_while_the_start_reads_every_record_a_count_answers_and_a_query_waits_for_the_records(self):
        for number in (1, 2, 3):
            self.write(f'{number}.json', topic_id='t', job_id=number)
        bridge = store_module.JsonDirectoryStore(self.path)  # Not directory_store: each one is another process.
        bridge.query()
        self.assertTrue(bridge.save_index(every=0))
        started, warmers = store_module.JsonDirectoryStore(self.path), []
        held, release, asked, patched = self.held('_read', warmers, '1.json')
        with patched:
            warm, _ = self.background(started.warm, warmers)  # app/unified.py warm_records
            self.assertTrue(held.wait(5))
            # Its fields came from .index: a count needs no record and does not wait.
            self.assertEqual(self.promptly(lambda: started.count(topic_id='t')), 3)
            self.assertEqual(self.promptly(lambda: started.max_field('job_id')), 3)
            waiting, found = self.background(lambda: started.query(topic_id='t'))
            waiting.join(0.3)
            self.assertTrue(waiting.is_alive())  # The records are being read: it waits for them, as before.
            release.set()
            waiting.join(5)
            warm.join(5)
        self.assertEqual(sorted(r['job_id'] for _, r in found[0]), [1, 2, 3])
        self.assertEqual(sorted(asked), ['1.json', '2.json', '3.json'])  # Each read once, by the start alone.

    def test_a_new_process_waits_for_its_first_catch_up_and_a_bounded_query_gives_up(self):
        for number in (1, 2, 3):
            self.write(f'{number}.json', topic_id='t', job_id=number)
        bridge = store_module.JsonDirectoryStore(self.path)
        bridge.query()
        self.assertTrue(bridge.save_index(every=0))
        self.elsewhere('4.json', topic_id='t', job_id=4)
        runner = store_module.JsonDirectoryStore(self.path)  # Another process: nothing to answer from yet.
        with self.stuck_journal() as (entered, release):
            warm, _ = self.background(runner.catch_up)  # app/runner.py warm_records
            self.assertTrue(entered.wait(5))
            with store_module.bounded(0.2), self.assertRaises(store_module.Busy):
                runner.query(topic_id='t')
            with store_module.bounded(0.2), self.assertRaises(store_module.Busy):
                runner.count(topic_id='t')
            waiting, found = self.background(lambda: runner.query(topic_id='t'))
            waiting.join(0.3)
            self.assertTrue(waiting.is_alive())  # It waits for the first catch-up, as before.
            release.set()
            waiting.join(5)
            warm.join(5)
        self.assertEqual(sorted(r['job_id'] for _, r in found[0]), [1, 2, 3, 4])
