"""A Claude profile's quota command (app/quota_retry.py): what it is asked and which answers are taken."""
from __future__ import annotations

import dataclasses
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from covey.app import quota_retry
from covey.core.session_state import capture_session_state, compare_and_set_session

PATTERN = re.compile(r"[0-9a-f-]{36}")
SID = "11111111-2222-3333-4444-555555555555"


@dataclasses.dataclass(frozen=True)
class Ctx:
    """The fields of a BridgeContext the quota command reads."""
    options: dict
    model: str
    session_path: Path


def ctx(cmd='/abs/quota', model='profile/gw/claude-opus', session_path='/nonexistent/session'):
    return Ctx({quota_retry.OPTION: cmd} if cmd else {}, model, Path(session_path))


def answer(data, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(data), stderr='')


class QuotaRetryTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def advise(self, *answers, context=None, session='sid'):
        with mock.patch('covey.app.quota_retry.subprocess.run', side_effect=list(answers)) as run:
            quota = quota_retry.advise(context or ctx(), session, PATTERN, now=self.NOW)
        return quota, [call.args[0] for call in run.call_args_list]

    def test_off_without_a_command_a_profile_or_a_session(self):
        for context, session in ((ctx(cmd=''), 'sid'), (ctx(model='opus'), 'sid'), (ctx(), '')):
            with self.subTest(context=context, session=session):
                self.assertEqual(self.advise(context=context, session=session), (None, []))

    def test_ask_and_wait_are_taken_as_said(self):
        said = {'action': 'ask', 'account': 'Pro', 'other': 'Max', 'resets_at': self.NOW + 300, 'at': self.NOW + 330}
        quota, calls = self.advise(answer(said))
        self.assertEqual(calls, [['/abs/quota', 'advise', '--profile', 'gw', '--session', 'sid']])
        self.assertEqual(quota, {**said, 'switch': False, 'profile': 'gw', 'session': 'sid'})
        wait = {'action': 'wait', 'account': 'Pro', 'resets_at': self.NOW + 3600, 'at': self.NOW + 3630}
        quota, _ = self.advise(answer(wait))
        self.assertEqual((quota['action'], quota['other'], quota['switch']), ('wait', '', False))

    def test_a_switch_moves_the_session_first_and_falls_back_when_it_cannot(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session'
            self.assertTrue(compare_and_set_session(path, PATTERN, 0, None, SID))
            said = {'action': 'switch', 'account': 'Pro', 'other': 'Max', 'resets_at': self.NOW + 9000, 'at': self.NOW}
            quota, calls = self.advise(answer(said), answer({'ok': True, 'to': 'Max'}), context=ctx(session_path=path),
                                       session=SID)
            self.assertEqual(calls[1], ['/abs/quota', 'switch', '--profile', 'gw', '--session', SID])
            self.assertEqual((quota['switch'], quota['moved']), (True, 'Max'))
            self.assertEqual(capture_session_state(path, PATTERN)[1], None)  # The next turn forks it.
            self.assertEqual(self.advise(answer(said), answer({'ok': False}), session=SID)[0], None)

    def test_the_next_turn_forks_the_moved_session_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'session'
            self.assertTrue(compare_and_set_session(path, PATTERN, 0, None, SID))
            context = ctx(session_path=path)
            quota_retry.move_session(context, PATTERN, SID)
            forked = quota_retry.fork_next(context, PATTERN)
            self.assertEqual(forked.options['fork_session'], SID)
            self.assertIs(quota_retry.fork_next(context, PATTERN), context)  # Once.
            # A /new (or any change of the pointer) in between voids it.
            quota_retry.move_session(context, PATTERN, SID)
            revision, _ = capture_session_state(path, PATTERN)
            self.assertTrue(compare_and_set_session(path, PATTERN, revision, None, None))
            self.assertIs(quota_retry.fork_next(context, PATTERN), context)
            # A pointer already on another session is not moved.
            revision, _ = capture_session_state(path, PATTERN)
            compare_and_set_session(path, PATTERN, revision, None, '99999999-2222-3333-4444-555555555555')
            with self.assertRaises(ValueError):
                quota_retry.move_session(context, PATTERN, SID)

    def test_bad_answers_leave_the_usual_retry(self):
        good = {'action': 'ask', 'account': 'Pro', 'other': 'Max', 'resets_at': self.NOW + 300, 'at': self.NOW + 330}
        for bad in ({**good, 'action': 'retry'}, {**good, 'at': 'soon'}, {**good, 'other': ''},
                    {**good, 'account': 'x' * 41}, {**good, 'resets_at': True}, ['ask']):
            with self.subTest(bad=bad):
                self.assertIsNone(self.advise(answer(bad))[0])
        self.assertIsNone(self.advise(answer(good, code=1))[0])
        self.assertIsNone(self.advise(subprocess.TimeoutExpired('quota', quota_retry.TIMEOUT))[0])
        self.assertIsNone(self.advise(OSError('missing'))[0])

    def test_a_past_time_runs_now(self):
        said = {'action': 'wait', 'account': 'Pro', 'resets_at': self.NOW - 60, 'at': self.NOW - 30}
        self.assertEqual(self.advise(answer(said))[0]['at'], self.NOW)


if __name__ == '__main__':
    unittest.main()
