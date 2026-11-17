"""A Claude profile's quota command (app/quota_retry.py): what it is asked and which answers are taken."""
from __future__ import annotations

import json
import subprocess
import unittest
from types import SimpleNamespace
from unittest import mock

from covey.app import quota_retry


def ctx(cmd='/abs/quota', model='profile/gw/claude-opus'):
    return SimpleNamespace(options={quota_retry.OPTION: cmd} if cmd else {}, model=model)


def answer(data, code=0):
    return subprocess.CompletedProcess([], code, stdout=json.dumps(data), stderr='')


class QuotaRetryTest(unittest.TestCase):
    NOW = 1_800_000_000.0

    def advise(self, *answers, context=None, session='sid'):
        with mock.patch('covey.app.quota_retry.subprocess.run', side_effect=list(answers)) as run:
            quota = quota_retry.advise(context or ctx(), session, now=self.NOW)
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
        said = {'action': 'switch', 'account': 'Pro', 'other': 'Max', 'resets_at': self.NOW + 9000, 'at': self.NOW}
        quota, calls = self.advise(answer(said), answer({'ok': True, 'to': 'Max'}))
        self.assertEqual(calls[1], ['/abs/quota', 'switch', '--profile', 'gw', '--session', 'sid'])
        self.assertEqual((quota['switch'], quota['moved']), (True, 'Max'))
        self.assertEqual(self.advise(answer(said), answer({'ok': False}))[0], None)

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
