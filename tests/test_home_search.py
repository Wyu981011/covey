"""The home-search hook (backends/claude/tool_guard.py ``--mode home-search``): a turn started from the home has no Bash,
Grep or Glob call that walks the whole home unbounded, and nothing else of its work is held up. Which turns get it is
backends/claude/argv.py ``home_hooks``; what it refuses and lets through is ``search_refusal``; whatever goes wrong in it
lets the call run (fail-open)."""
from __future__ import annotations

import contextlib
import io
import json
import os
import shlex
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import make_context
from covey.backends.claude import argv as claude_argv
from covey.backends.claude import tool_guard
from covey.backends.claude.bridge import ClaudeBackend
from covey.core.harness import CONSULT, LEAD, LOOK, PROXY, READ, TOOL_LIMIT, TOOL_NOTES


def settings_of(argv):
    return json.loads(argv[argv.index('--settings') + 1]) if '--settings' in argv else None


class HomeHooksArgvTests(unittest.TestCase):
    """Which Claude Code turns carry the hook, and how it sits in the turn's one --settings."""

    def argv(self, workdir=Path('/x'), **fields):
        options = fields.pop('options', {})
        ctx = make_context(Path('/x'), workdir=workdir, backend_cmd=['claude'], options=options, **fields)
        return claude_argv.stream_argv(ClaudeBackend(), ctx)

    def assert_home_hook(self, hooks, home='/x'):
        [entry] = hooks['PreToolUse']
        self.assertEqual(entry['matcher'], 'Bash|Grep|Glob')  # Never Read, Edit or Write.
        for tool in ('Read', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit'):
            self.assertNotIn(tool, entry['matcher'].split('|'))
        [hook] = entry['hooks']
        self.assertEqual(hook['type'], 'command')
        words = shlex.split(hook['command'])
        self.assertTrue(words[2].endswith('bin/covey_tool_guard.py'), words)
        self.assertEqual(words[3:], ['--mode', 'home-search', '--home', home])

    def test_a_turn_started_from_the_home_has_the_hook_whatever_else_it_is_held_to(self):
        for options in ({}, {TOOL_LIMIT: LOOK}, {TOOL_LIMIT: READ}, {TOOL_LIMIT: LEAD}):
            with self.subTest(options=options):
                settings = settings_of(self.argv(options=options))
                self.assertEqual(list(settings), ['hooks'])
                self.assert_home_hook(settings['hooks'])

    def test_a_turn_in_a_repository_a_device_a_proxy_or_a_consult_turn_has_none(self):
        self.assertIsNone(settings_of(self.argv(workdir=Path('/x/repo'))))  # Started in a repository: as before.
        self.assertIsNone(settings_of(self.argv(device='box', remote_workdir='~/x')))  # The hook would run on the device.
        self.assertIsNone(settings_of(self.argv(options={TOOL_LIMIT: CONSULT})))
        proxy = settings_of(self.argv(options={TOOL_LIMIT: PROXY, TOOL_NOTES: '/abs/notes'}))
        [entry] = proxy['hooks']['PreToolUse']  # Its 代答 guard alone.
        self.assertEqual(entry['matcher'], 'Bash|Edit|Write|MultiEdit|NotebookEdit')
        self.assertNotIn('home-search', entry['hooks'][0]['command'])

    def test_the_home_through_a_link_is_the_home(self):
        with tempfile.TemporaryDirectory() as root:
            home = Path(root) / 'home'
            home.mkdir()
            (Path(root) / 'link').symlink_to(home)
            ctx = make_context(home, workdir=Path(root) / 'link', backend_cmd=['claude'])
            self.assert_home_hook(claude_argv.home_hooks(ctx), str(home))

    def test_the_extensions_hooks_come_after_it_in_the_one_settings(self):
        hooks = {'PreToolUse': [{'matcher': 'Bash', 'hooks': [{'type': 'command', 'command': '/abs/hook'}]}],
                 'SessionStart': [{'hooks': [{'type': 'command', 'command': '/abs/start'}]}]}
        argv = self.argv(options={claude_argv.TURN_HOOKS: hooks})
        self.assertEqual(argv.count('--settings'), 1)
        settings = settings_of(argv)
        self.assertEqual(settings['hooks']['SessionStart'], hooks['SessionStart'])
        home, extension = settings['hooks']['PreToolUse']
        self.assert_home_hook({'PreToolUse': [home]})
        self.assertEqual(extension, hooks['PreToolUse'][0])


class HomeSearchTests(unittest.TestCase):
    """search_refusal on a home with a repository (covey/) and a data directory (data/runs/), as the hook reads a call."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(os.path.join(tmp.name, 'home'))
        for sub in ('covey/x', 'data/runs'):
            os.makedirs(os.path.join(self.home, sub))
        Path(self.home, 'AGENTS.md').write_text('# home\n')

    def bash(self, command, cwd=None):
        call = {'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': cwd or self.home}
        return tool_guard.search_refusal(call, self.home)

    def tool(self, name, cwd=None, **given):
        return tool_guard.search_refusal({'tool_name': name, 'tool_input': given, 'cwd': cwd or self.home}, self.home)

    # A recursive search with no depth limit whose target is the home (or above it).
    REFUSED = (
        'rg foo', 'rg --files', 'rg -n "a b" .', 'rg -uuu foo', 'rg foo *', 'rg -g "*.py" foo', 'ripgrep foo',
        'grep -rn foo .', 'grep -r foo', 'grep -R --include=*.py foo', 'egrep -Ri x', 'cat x | grep -r foo',
        'find .', 'find', 'find . -name "*.py"', 'find -L . -type f', 'ls -R', 'ls -laR .', 'ls --recursive',
        'du -sh .', 'du -sh *', 'du -d 1', 'du --max-depth=1 .', 'tree', 'tree -a', 'fd py', 'fd -e py', 'fdfind x',
        'rg foo $COVEY_HOME', 'rg foo "${COVEY_HOME}"', 'find / -name libfoo.so', 'rg foo ..',
        'timeout --kill-after=2s 30s rg foo', 'FOO=1 nice -n 5 rg foo', 'env A=1 rg foo', 'cd covey && cd .. && rg foo',
        'echo $(find . -name x)', 'rg foo 2>/dev/null | head -5', 'ls; rg foo', 'true\nrg foo', 'bash -lc "rg foo ."',
        "sh -c 'find . -name x'", 'cd covey && rg x; cd .. && du -sh .',
        "python3 -c \"import os\nfor r, d, f in os.walk('.'):\n    pass\"",
        "python3 - <<'EOF'\nimport os\nfor r, d, f in os.walk(os.getcwd()):\n    print(r)\nEOF",
        "python3 -c \"from pathlib import Path; print(list(Path('.').rglob('*.py')))\"",
        "python3 -c \"from pathlib import Path; print(list(Path().rglob('*.py')))\"",
        "python3 -c \"import glob; glob.glob('**/*', recursive=True)\"",
        "python3 -c \"from pathlib import Path; Path.cwd().glob('**/*.md')\"",
        "python3 -B -c \"import os; os.walk(os.environ['COVEY_HOME'])\"",
    )
    # A concrete repository or subdirectory, a depth limit, a data subdirectory, input from a pipe, a single file.
    ALLOWED = (
        'rg foo covey', 'rg foo covey/x data/runs', 'cd covey && rg foo', 'cd covey; rg --files', 'cd covey && find .',
        'pushd covey && grep -rn foo .', 'find . -maxdepth 2 -name "*.md"', 'find covey -name x', 'rg --max-depth 2 foo',
        'rg -d 1 foo', 'fd -d 2 py', 'fd py covey', 'tree -L 2', 'ls', 'ls -la', 'ls -R covey', 'du -sh covey',
        'du -sh covey/*', 'grep foo AGENTS.md', 'grep -rn foo covey/', 'cat x | rg foo', 'git log | rg foo',
        'rg foo < AGENTS.md', 'cat data/runs/x.json', 'rg -n foo data/runs', 'find data -maxdepth 3 -name x',
        'find data/runs -name "*.json"', 'ls -R data/runs', 'rg --files data/runs', 'rg foo /tmp', 'find /tmp -name x',
        "python3 -c \"import os; os.walk('covey')\"", "python3 -c \"import glob; glob.glob('**/*')\"",
        "python3 -c \"import glob; glob.glob('covey/**/*.py', recursive=True)\"", 'python3 script.py',
        "cat <<'EOF' > notes.md\nfind . -name x\nrg foo\nEOF", 'rg --version', 'rg --type-list', 'grep -c x a.txt',
        'echo rg foo', 'git grep foo', 'ls | xargs rg foo',
        # What it cannot tell runs: another variable, a directory it cannot follow, an open quote.
        'rg foo $SOMEWHERE', 'cd - && rg foo', 'cd "$DIR" && rg foo', 'echo "unterminated',
    )

    def test_a_recursive_search_over_the_whole_home_is_refused_with_what_to_do(self):
        for command in self.REFUSED:
            with self.subTest(command=command):
                reason = self.bash(command)
                self.assertIn(self.home, reason)
                self.assertIn('没有执行', reason)
        self.assertIn('cd <仓库> && rg', self.bash('rg foo'))
        self.assertIn('Python', self.bash("python3 -c \"import os; os.walk('.')\""))
        self.assertIn(self.home, self.bash(f'rg foo {self.home}'))  # The home by its absolute path, from anywhere.
        self.assertIn(self.home, self.bash(f'find {self.home} -name x', cwd='/tmp'))
        self.assertIn(self.home, self.bash('rg foo ..', cwd=os.path.join(self.home, 'covey')))

    def test_a_search_in_a_repository_a_subdirectory_or_with_a_depth_limit_runs(self):
        for command in self.ALLOWED:
            with self.subTest(command=command):
                self.assertEqual(self.bash(command), '')
        covey = os.path.join(self.home, 'covey')
        self.assertEqual(self.bash('rg foo', cwd=covey), '')  # The session's cwd already in a repository.
        self.assertEqual(self.bash('find . -name x', cwd=covey), '')
        self.assertEqual(self.bash(f'rg foo {self.home}/data/runs', cwd='/tmp'), '')

    def test_the_grep_tool_with_the_home_as_its_path_is_refused(self):
        self.assertIn('Grep', self.tool('Grep', pattern='x'))  # No path: the cwd, the home.
        self.assertIn('Grep', self.tool('Grep', pattern='x', path=self.home))
        self.assertIn('Grep', self.tool('Grep', pattern='x', path='.', glob='covey/**'))  # Its glob filters, not narrows.
        self.assertEqual(self.tool('Grep', pattern='x', path='covey'), '')
        self.assertEqual(self.tool('Grep', pattern='x', path=os.path.join(self.home, 'data', 'runs')), '')
        self.assertEqual(self.tool('Grep', pattern='x', path='AGENTS.md'), '')
        self.assertEqual(self.tool('Grep', pattern='x', cwd=os.path.join(self.home, 'covey')), '')

    def test_the_glob_tool_with_double_star_from_the_home_is_refused(self):
        self.assertIn('Glob', self.tool('Glob', pattern='**/*.py'))
        self.assertIn('Glob', self.tool('Glob', pattern='**/*', path=self.home))
        self.assertIn('Glob', self.tool('Glob', pattern=self.home + '/**/*.md'))
        self.assertEqual(self.tool('Glob', pattern='*.md'), '')  # One level.
        self.assertEqual(self.tool('Glob', pattern='*/*.md'), '')
        self.assertEqual(self.tool('Glob', pattern='covey/**/*.py'), '')  # Starts at a repository.
        self.assertEqual(self.tool('Glob', pattern='**/*', path=os.path.join(self.home, 'covey')), '')
        self.assertEqual(self.tool('Glob', pattern=self.home + '/data/runs/**/*.json'), '')

    def test_read_edit_write_and_other_tools_are_never_looked_at(self):
        for name, given in (('Read', {'file_path': self.home}), ('Edit', {'file_path': self.home + '/AGENTS.md'}),
                            ('Write', {'file_path': self.home + '/x'}), ('WebFetch', {'url': 'rg foo'}),
                            ('Task', {'prompt': 'rg foo'})):
            self.assertEqual(self.tool(name, **given), '', name)

    def test_it_lets_the_call_run_when_anything_goes_wrong(self):
        self.assertEqual(tool_guard.search_refusal({'tool_name': 'Bash', 'tool_input': 'rg foo'}, self.home), '')
        self.assertEqual(tool_guard.search_refusal({'tool_name': 'Bash', 'tool_input': {'command': 'rg foo'}}, ''), '')
        self.assertEqual(tool_guard.search_refusal({'tool_name': 'Grep', 'tool_input': {'path': 3}}, self.home), '')
        with mock.patch.object(tool_guard, 'bash_refusal', side_effect=RuntimeError('boom')):
            self.assertEqual(self.bash('rg foo'), '')
        with mock.patch.object(tool_guard, 'covers_home', side_effect=OSError('nas')):
            self.assertEqual(self.tool('Grep', pattern='x'), '')
        with mock.patch.object(tool_guard.shlex, 'shlex', side_effect=ValueError('No closing quotation')):
            self.assertEqual(self.bash('rg foo'), '')


class HomeSearchHookTests(unittest.TestCase):
    """main in its home-search mode: exit 2 with the reason for a refused call, 0 for anything else, its own faults
    included; the 代答 mode is as it was."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = os.path.realpath(tmp.name)
        os.makedirs(os.path.join(self.home, 'covey'))

    def run_main(self, text, *args):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = tool_guard.main(list(args), stdin=io.StringIO(text))
        return code, err.getvalue()

    def call(self, command, cwd=None):
        return json.dumps({'tool_name': 'Bash', 'tool_input': {'command': command}, 'cwd': cwd or self.home})

    def test_a_refused_call_exits_2_with_the_reason_and_another_exits_0(self):
        code, said = self.run_main(self.call('rg foo'), '--mode', 'home-search', '--home', self.home)
        self.assertEqual(code, 2)
        self.assertIn('没有执行', said)
        self.assertEqual(self.run_main(self.call('rg foo covey'), '--mode', 'home-search', '--home', self.home), (0, ''))
        self.assertEqual(self.run_main(self.call('rg foo'), '--mode=home-search', '--home', self.home)[0], 2)

    def test_what_it_cannot_read_lets_the_call_run(self):
        for text in ('not json', '[]', '{"tool_name": "Bash"}', '', json.dumps({'tool_name': 'Bash', 'tool_input': None})):
            with self.subTest(text=text):
                self.assertEqual(self.run_main(text, '--mode', 'home-search', '--home', self.home), (0, ''))
        self.assertEqual(self.run_main(self.call('rg foo'), '--mode', 'home-search')[0], 0)  # No home given.
        code, _ = self.run_main(self.call('rg foo'), '--mode', 'home-search', '--home', self.home, '--bogus')
        self.assertEqual(code, 0)  # An argument it does not take.
        with mock.patch.object(tool_guard, 'search_refusal', side_effect=RuntimeError('boom')):
            self.assertEqual(self.run_main(self.call('rg foo'), '--mode', 'home-search', '--home', self.home), (0, ''))

    def test_the_proxy_mode_still_refuses_what_it_cannot_read(self):
        self.assertEqual(self.run_main('not json', '--notes', '/abs/notes')[0], 2)
        self.assertEqual(self.run_main('not json', '--mode', 'proxy')[0], 2)
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                tool_guard.main(['--bogus'], stdin=io.StringIO('{}'))

    def test_the_hook_command_argv_writes_runs_as_claude_code_would_run_it(self):
        ctx = make_context(Path(self.home), backend_cmd=['claude'])
        [entry] = claude_argv.home_hooks(ctx)['PreToolUse']
        command = shlex.split(entry['hooks'][0]['command'])
        for given, expected in (('rg foo', 2), ('rg foo covey', 0), ('find . -maxdepth 2', 0)):
            with self.subTest(command=given):
                done = subprocess.run(command, input=self.call(given), capture_output=True, text=True, timeout=60,
                                      cwd=self.home)
                self.assertEqual(done.returncode, expected, done.stderr)
                self.assertEqual(bool(done.stderr.strip()), expected == 2)
        done = subprocess.run(command, input='garbage', capture_output=True, text=True, timeout=60, cwd=self.home)
        self.assertEqual(done.returncode, 0)


if __name__ == '__main__':
    unittest.main()
