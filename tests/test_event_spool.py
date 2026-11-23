"""Events the SDK connection took in survive a stop, a restart or a crash before they are handled
(feishu/event_spool.py, COVEY_EVENT_TRANSPORT=sdk).

2026-11-23 15:31 the message consumer waited 18 minutes on a lock held over a read hung on the NAS; the owner's two
messages behind it waited in memory, and the restart at 15:49 dropped them (``stopping with events not handled
im.message.receive_v1=2``). The restart tests below are that case: they use only what the Intake had before, so on
the old code the second start hands nothing over and they fail."""
from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from covey.core.state import claim_once
from covey.feishu import ws_intake
from covey.feishu.events import CARD_ACTION_EVENT_KEY, MENU_EVENT_KEY, MESSAGE_EVENT_KEY, READ_EVENT_KEY

FOLDER = 'event-spool'


def envelope(event_type, event, event_id):
    return {'schema': '2.0', 'header': {'event_id': event_id, 'token': 'fake', 'create_time': '1790000000123',
                                        'tenant_key': 't1', 'app_id': 'cli_fake', 'event_type': event_type},
            'event': event}


def message(n, text=None):
    return envelope(MESSAGE_EVENT_KEY, {
        'sender': {'sender_id': {'open_id': 'ou_owner'}, 'sender_type': 'user', 'tenant_key': 't1'},
        'message': {'message_id': f'om_{n}', 'chat_id': 'oc_1', 'chat_type': 'p2p', 'message_type': 'text',
                    'content': json.dumps({'text': text or f'words {n}'}, ensure_ascii=False),
                    'create_time': '1790000000000', 'mentions': []}}, f'ev_message_{n}')


def click(n):
    return envelope(CARD_ACTION_EVENT_KEY, {
        'operator': {'open_id': 'ou_owner'}, 'token': f'c-secret-{n}',
        'action': {'value': {'kind': 'stop', 'job': n}, 'tag': 'button', 'name': 'stop_btn'},
        'context': {'open_message_id': 'om_card', 'open_chat_id': 'oc_1'}}, f'ev_click_{n}')


def menu(n):
    return envelope(MENU_EVENT_KEY, {'event_key': 'covey.board', 'timestamp': 1790000000,
                                     'operator': {'operator_id': {'open_id': 'ou_owner'}}}, f'ev_menu_{n}')


def read(n):
    return envelope(READ_EVENT_KEY, {'reader': {'reader_id': {'open_id': 'ou_owner'}, 'read_time': '1790000000500'},
                                     'message_id_list': ['om_a']}, f'ev_read_{n}')


def frame(raw):
    return json.dumps(raw, ensure_ascii=False).encode()


def wait_for(check, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not check():
        time.sleep(.01)
    return check()


class Process:
    """One Bridge process's intake on a state directory: its own shutdown, log and threads."""

    def __init__(self, case, state):
        self.shutdown = threading.Event()
        self.logs = []
        self.intake = ws_intake.Intake(SimpleNamespace(profile='fake', state_dir=state), self.shutdown,
                                       self.logs.append, 300)
        self.intake.started = True  # No client: the tests feed on_payload and the state by hand.
        self.intake._start(connect=False)
        case.addCleanup(self.end)

    def consume(self, key, handle):
        thread = threading.Thread(target=self.intake.consume, args=(key, handle), daemon=True)
        thread.start()
        return thread

    def take(self, raw):
        return self.intake.on_payload(frame(raw))

    def end(self):
        self.shutdown.set()
        spool = getattr(self.intake, 'spool', None)
        if spool is not None:
            spool.close()


class OwnerMessages:
    """What app/card_routing.py does first with a message: claim its id once in inbound-messages/."""

    def __init__(self, state, block=()):
        self.state, self.block = state, set(block)
        self.handled, self.duplicates = [], []
        self.release = threading.Event()

    def __call__(self, event, ctx):
        ident = event['message_id']
        if not claim_once(Path(ctx.state_dir) / 'inbound-messages', hashlib.sha256(ident.encode()).hexdigest()):
            self.duplicates.append(ident)
            return
        self.handled.append(ident)
        if ident in self.block:  # The lock held over a read hung on the NAS.
            self.release.wait(30)


class RestartTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'
        self.state.mkdir()
        ws_intake.reset()
        self.addCleanup(ws_intake.reset)

    def spooled(self):
        folder = self.state / FOLDER
        return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []

    def test_messages_behind_a_stuck_one_are_handled_by_the_next_start_once_each(self):
        owner = OwnerMessages(self.state, block={'om_1'})
        self.addCleanup(owner.release.set)
        first = Process(self, self.state)
        first.consume(MESSAGE_EVENT_KEY, owner)
        first.take(message(1))
        self.assertTrue(wait_for(lambda: owner.handled == ['om_1']))
        first.take(message(2))
        first.take(message(3))
        first.intake.stop()  # The SIGTERM handler, while the consumer still waits on om_1.
        first.end()  # SIGKILL: om_1 never returns in this process.

        second = Process(self, self.state)
        second.consume(MESSAGE_EVENT_KEY, owner)
        self.assertTrue(wait_for(lambda: owner.handled == ['om_1', 'om_2', 'om_3']), owner.handled)
        self.assertTrue(wait_for(lambda: owner.duplicates == ['om_1']), owner.duplicates)  # Claimed: not run again.
        self.assertTrue(wait_for(lambda: not self.spooled()), self.spooled())
        time.sleep(.2)
        self.assertEqual((owner.handled, owner.duplicates), (['om_1', 'om_2', 'om_3'], ['om_1']))

    def test_what_the_last_run_left_goes_before_what_came_since(self):
        owner = OwnerMessages(self.state)
        first = Process(self, self.state)
        for n in (1, 2):
            first.take(message(n))
        first.intake.stop()  # No consumer had attached yet: both were only taken in.
        first.end()
        second = Process(self, self.state)
        second.take(message(3))  # Taken in while the start recovers, before the consumer attaches.
        second.consume(MESSAGE_EVENT_KEY, owner)
        self.assertTrue(wait_for(lambda: len(owner.handled) == 3), owner.handled)
        self.assertEqual(owner.handled, ['om_1', 'om_2', 'om_3'])
        self.assertTrue(wait_for(lambda: not self.spooled()), self.spooled())

    def test_a_click_left_in_its_card_lane_at_stop_runs_at_the_next_start(self):
        # The lead's question: CardLanes clears the clicks it had not started when the Bridge stops, after the SDK
        # answered them 收到. They stay kept and run once at the next start.
        from covey.app.card_lanes import CardLanes
        ran, release = [], threading.Event()
        self.addCleanup(release.set)

        def handle(event, ctx):
            ran.append(json.loads(event['action_value'])['job'])
            if len(ran) == 1:
                release.wait(30)
        first = Process(self, self.state)
        lanes = CardLanes(handle, lambda event, ctx: 'topic:t1', lambda line: None, first.shutdown)
        first.consume(CARD_ACTION_EVENT_KEY, lanes.submit)
        self.assertEqual(first.take(click(1)), ws_intake.TOAST)
        self.assertTrue(wait_for(lambda: ran == [1]))
        self.assertEqual(first.take(click(2)), ws_intake.TOAST)  # Behind the first in its topic's lane.
        time.sleep(.3)
        first.shutdown.set()
        release.set()
        lanes.drain(timeout=5)
        first.intake.stop()
        first.end()
        self.assertEqual(ran, [1])

        second = Process(self, self.state)
        again = CardLanes(handle, lambda event, ctx: 'topic:t1', lambda line: None, second.shutdown)
        second.consume(CARD_ACTION_EVENT_KEY, again.submit)
        self.assertTrue(wait_for(lambda: ran == [1, 2]), ran)
        self.assertTrue(wait_for(lambda: not self.spooled()), self.spooled())
        time.sleep(.2)
        self.assertEqual(ran, [1, 2])

    def test_a_menu_click_left_at_stop_runs_at_the_next_start(self):
        first = Process(self, self.state)
        first.take(menu(1))
        first.intake.stop()
        first.end()
        seen = []
        second = Process(self, self.state)
        second.consume(MENU_EVENT_KEY, lambda event, ctx: seen.append(event['event_id']))
        self.assertTrue(wait_for(lambda: seen == ['ev_menu_1']), seen)


class SpoolTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'
        self.state.mkdir()
        ws_intake.reset()
        self.addCleanup(ws_intake.reset)

    def files(self):
        folder = self.state / FOLDER
        return sorted(folder.iterdir()) if folder.is_dir() else []

    def test_a_handled_event_leaves_nothing_and_a_read_receipt_is_never_written(self):
        process = Process(self, self.state)
        seen = []
        process.consume(MESSAGE_EVENT_KEY, lambda event, ctx: seen.append(event['message_id']))
        process.consume(READ_EVENT_KEY, lambda event, ctx: seen.append('read'))
        process.take(message(1))
        process.take(read(1))
        self.assertTrue(wait_for(lambda: len(seen) == 2))
        process.intake.stop()
        self.assertEqual(self.files(), [])
        self.assertFalse(any('kept for the next start' in line for line in process.logs), process.logs)

    def test_files_are_private_and_hold_no_callback_token(self):
        process = Process(self, self.state)
        process.take(click(1))
        process.take(message(1, 'a secret-looking line stays the owner\'s words'))
        process.intake.stop()
        folder = self.state / FOLDER
        self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700)
        files = self.files()
        self.assertEqual([path.name.split('-')[2] for path in files], ['card', 'message'])
        for path in files:
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        text = ''.join(path.read_text() for path in files)
        self.assertNotIn('c-secret-1', text)
        self.assertIn("the owner's words", text)
        self.assertIn('event spool: 2 events taken in and not handled are kept for the next start', process.logs)

    def test_what_was_taken_in_too_long_ago_is_dropped_not_handled(self):
        from covey.feishu import event_spool
        first = Process(self, self.state)
        first.take(message(1))
        first.take(click(1))
        first.take(menu(1))
        first.intake.stop()
        first.end()
        later = time.time() + event_spool.REPLAY_SECONDS[CARD_ACTION_EVENT_KEY] + 1  # Past a click's and a menu's.
        seen = []
        clock = SimpleNamespace(time=lambda: later, monotonic=time.monotonic)
        with mock.patch.object(event_spool, 'time', clock):
            second = Process(self, self.state)
            for key in (MESSAGE_EVENT_KEY, CARD_ACTION_EVENT_KEY, MENU_EVENT_KEY):
                second.consume(key, lambda event, ctx, key=key: seen.append(key))
            self.assertTrue(wait_for(lambda: seen == [MESSAGE_EVENT_KEY]), seen)
            self.assertTrue(wait_for(lambda: not self.files()), self.files())
        time.sleep(.2)
        self.assertEqual(seen, [MESSAGE_EVENT_KEY])
        self.assertIn(f'event spool: dropped 1 {MENU_EVENT_KEY} taken in too long ago, '
                      f'1 {CARD_ACTION_EVENT_KEY} taken in too long ago', second.logs)

    def test_an_event_feishu_delivers_again_after_the_restart_is_handled_once(self):
        first = Process(self, self.state)
        first.take(click(1))
        first.intake.stop()
        first.end()
        second = Process(self, self.state)
        self.assertTrue(wait_for(second.intake.spool.loaded.is_set))
        self.assertEqual(second.take(click(1)), ws_intake.HELD_TOAST)  # Still answered; not queued again.
        seen = []
        second.consume(CARD_ACTION_EVENT_KEY, lambda event, ctx: seen.append(event['event_id']))
        self.assertTrue(wait_for(lambda: seen))
        time.sleep(.3)
        self.assertEqual(seen, ['ev_click_1'])

    def test_unreadable_and_half_written_files_go(self):
        folder = self.state / FOLDER
        folder.mkdir(mode=0o700)
        (folder / '.1795419554915-000001-message-00.json.x.tmp').write_text('{"v": 1')
        (folder / '1795419554915-000002-message-01.json').write_text('not json')
        (folder / '1795419554915-000003-message-02.json').write_text(json.dumps({'v': 1, 'key': 'nope', 'event': {},
                                                                                'received_at': time.time()}))
        process = Process(self, self.state)
        self.assertTrue(wait_for(process.intake.spool.loaded.is_set))
        self.assertTrue(wait_for(lambda: not self.files()), self.files())
        self.assertIn('event spool: dropped 2 unreadable', process.logs)


class NeverWaitsTest(unittest.TestCase):
    """The SDK's thread answers a click within 3 s and runs the pings: a hung disk must not hold it, and a stop with
    nothing queued must not wait at all (T648 brought a restart's stop down to under half a second)."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / 'state'
        self.state.mkdir()
        ws_intake.reset()
        self.addCleanup(ws_intake.reset)

    def test_taking_events_in_never_waits_for_the_disk(self):
        hung = threading.Event()
        with mock.patch('covey.core.state.atomic_write_bytes', side_effect=lambda *a, **k: hung.wait(30)):
            process = Process(self, self.state)
            self.addCleanup(hung.set)  # Before the process ends (cleanups run last first).
            started = time.monotonic()
            answers = [process.take(click(n)) for n in range(50)] + [process.take(message(n)) for n in range(50)]
            took = time.monotonic() - started
        self.assertLess(took, 1.0)
        self.assertEqual(answers[:50], [ws_intake.HELD_TOAST] * 50)

    def test_a_stop_while_the_disk_hangs_waits_its_bound_and_says_so(self):
        from covey.feishu import event_spool
        hung = threading.Event()
        with mock.patch('covey.core.state.atomic_write_bytes', side_effect=lambda *a, **k: hung.wait(30)):
            process = Process(self, self.state)
            self.addCleanup(hung.set)  # Before the process ends (cleanups run last first).
            process.take(message(1))
            process.take(message(2))
            with mock.patch.object(event_spool, 'FLUSH_SECONDS', .3):
                started = time.monotonic()
                process.intake.stop()
                took = time.monotonic() - started
        self.assertLess(took, 1.5)
        self.assertGreaterEqual(took, .3)
        self.assertTrue(any(line.startswith('event spool: 2 writes still queued at stop') for line in process.logs),
                        process.logs)

    def test_a_stop_with_nothing_queued_does_not_wait(self):
        process = Process(self, self.state)
        seen = []
        process.consume(MESSAGE_EVENT_KEY, lambda event, ctx: seen.append(event))
        process.take(message(1))
        self.assertTrue(wait_for(lambda: seen))
        spool = getattr(process.intake, 'spool', None)
        if spool is not None:
            self.assertTrue(wait_for(lambda: not spool.queued))
        started = time.monotonic()
        process.intake.stop()
        process.intake.stop()
        self.assertLess(time.monotonic() - started, .25)  # Nothing to wait for: microseconds, on a slow runner too.


class LarkCliTest(unittest.TestCase):
    """COVEY_EVENT_TRANSPORT unset (lark-cli's consumers): nothing is kept, no thread, no folder, nothing else changes."""

    def test_lark_cli_consumers_keep_nothing(self):
        from covey.app.card_lanes import CardLanes
        from covey.app.unified import UnifiedBridgeApp
        ws_intake.reset()
        before = {thread for thread in threading.enumerate() if thread.name == 'event-spool'}
        env = {k: v for k, v in os.environ.items() if k not in ('COVEY_EVENT_TRANSPORT', 'LARK_BRIDGE_EVENT_TRANSPORT')}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, env, clear=True), \
                mock.patch('covey.app.unified.consume') as lark_cli:
            state = Path(tmp)
            bridge = SimpleNamespace(runtime=SimpleNamespace(shutdown=threading.Event(), log=lambda line: None),
                                     event_procs={})
            ran = []
            lanes = CardLanes(lambda event, ctx: ran.append(event['event_id']), lambda event, ctx: 'topic:t1',
                              lambda line: None, bridge.runtime.shutdown)
            UnifiedBridgeApp.consume_events(bridge, SimpleNamespace(profile='bot', state_dir=state),
                                            CARD_ACTION_EVENT_KEY, lanes.submit)
            lanes.submit({'event_id': 'ev_1', 'message_id': 'om_card'}, SimpleNamespace(state_dir=state))
            self.assertTrue(wait_for(lambda: ran == ['ev_1']))
            lark_cli.assert_called_once()
            self.assertFalse((state / FOLDER).exists())
            self.assertIsNone(ws_intake._intake)
            self.assertLessEqual({thread for thread in threading.enumerate() if thread.name == 'event-spool'}, before)
            bridge.runtime.shutdown.set()


class HoldTest(unittest.TestCase):
    """A handler that queues a click's work for another thread keeps the click until that work has run."""

    def queue(self, **limit):
        from covey.app.card_queue import CardActionQueue
        runtime = SimpleNamespace(card_queues=[], shutdown=threading.Event(), log=lambda line: None)
        self.addCleanup(runtime.shutdown.set)
        with mock.patch.object(CardActionQueue, 'LIMIT', limit.get('limit', CardActionQueue.LIMIT)):
            return CardActionQueue(SimpleNamespace(runtime=runtime), name='test-queue', workers=1, label='test')

    def test_a_controller_queue_settles_the_click_once_its_work_has_run(self):
        from covey.feishu.event_spool import settling
        actions = self.queue()
        settled, ran, release = [], [], threading.Event()
        self.addCleanup(release.set)
        with settling(lambda: settled.append('click')):
            self.assertTrue(actions.submit('busy', lambda n: release.wait(5) and ran.append(n), 1))
        self.assertEqual(settled, [])  # Held by the queue: a stop before the work runs leaves the click kept.
        release.set()
        self.assertTrue(wait_for(lambda: settled == ['click']))
        self.assertEqual(ran, [1])

    def test_a_click_a_full_queue_drops_is_settled_at_once(self):
        from covey.feishu.event_spool import settling
        actions = self.queue(limit=1)
        release = threading.Event()
        self.addCleanup(release.set)
        self.assertTrue(actions.submit('busy', lambda: release.wait(5)))  # The worker takes it and waits.
        self.assertTrue(wait_for(lambda: actions.queue.empty()))
        self.assertTrue(actions.submit('busy', lambda: None))  # Fills the queue.
        settled = []
        with settling(lambda: settled.append('dropped')):
            self.assertFalse(actions.submit('busy', lambda: None))
        self.assertEqual(settled, ['dropped'])

    def test_off_a_kept_event_nothing_is_held(self):
        from covey.feishu.event_spool import hold, settling
        self.assertIsNone(hold())
        with settling(None):
            self.assertIsNone(hold())
        settled = []
        with settling(lambda: settled.append(1)):
            with settling(None):  # A nested handler of no kept event leaves the outer one alone.
                pass
            self.assertEqual(settled, [])
        self.assertEqual(settled, [1])


if __name__ == '__main__':
    unittest.main()
