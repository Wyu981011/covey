"""Card text boundaries: redaction, Unicode truncation, command summaries, tool step details and counts."""
import subprocess
import sys
import unittest
from pathlib import Path

from covey.core.text import (command_core, command_purpose, redact, safe_text, short_count, shown_command, step_label,
                             tool_detail)


class RedactTests(unittest.TestCase):
    def test_empty_and_none(self):
        for value in ("", None):
            with self.subTest(value=value):
                self.assertEqual(redact(value), "")

    def test_falsy_values_keep_their_text(self):
        self.assertEqual(redact(0), "0")
        self.assertEqual(redact(False), "False")

    def test_plain_unicode_and_long_text_are_unchanged(self):
        for value in ("🙂👩🏽‍💻🇨🇳", "ＡＢＣ１２３，。！", "检查 API v2：成功 ✅", "中A🙂" * 10000):
            with self.subTest(prefix=value[:20], length=len(value)):
                self.assertEqual(redact(value), value)

    def test_secret_names_and_bearer_are_case_insensitive(self):
        for key in ("token", "PASSWORD", "Secret", "api_key", "API-KEY", "apikey"):
            with self.subTest(key=key):
                self.assertEqual(redact(f"{key} = synthetic-value, next=ok"), f"{key} = [已隐藏], next=ok")
        self.assertEqual(redact("Authorization: bEaReR synthetic-value"), "Authorization: Bearer [已隐藏]")

    def test_quoted_secret_values_hide_whitespace_and_escaped_quotes(self):
        for value in ('password="synthetic secret" next=ok', "password='synthetic secret' next=ok",
                      'password="synthetic \\"quoted\\" secret" next=ok'):
            with self.subTest(value=value):
                self.assertEqual(redact(value), "password=[已隐藏] next=ok")

    def test_adjacent_quoted_fragments_are_one_secret(self):
        for value in ('password="synthetic"suffix next=ok',
                      'password="synthetic"\' second fragment\' next=ok'):
            with self.subTest(value=value):
                self.assertEqual(redact(value), "password=[已隐藏] next=ok")

    def test_unfinished_quotes_do_not_expose_the_remainder(self):
        for value in ('password="synthetic unfinished secret', "password='synthetic unfinished secret\\"):
            with self.subTest(value=value):
                self.assertEqual(redact(value), "password=[已隐藏]")

    def test_empty_values_and_multiple_secrets(self):
        self.assertEqual(redact("token=; password=, secret="), "token=; password=, secret=")
        self.assertEqual(redact('token=""; password=synthetic; Bearer synthetic'),
                         "token=[已隐藏]; password=[已隐藏]; Bearer [已隐藏]")
        self.assertEqual(redact('password="token=synthetic secret"; token=second'),
                         "password=[已隐藏]; token=[已隐藏]")

    def test_quoted_keys_and_fullwidth_assignments(self):
        cases = (
            ('{"token": "synthetic secret", "ok": true}', '{"token": [已隐藏], "ok": true}'),
            ("token：synthetic，状态正常", "token：[已隐藏]，状态正常"),
            ("ＰＡＳＳＷＯＲＤ＝＂synthetic secret＂；成功", "ＰＡＳＳＷＯＲＤ＝[已隐藏]；成功"),
            ("说明 api_key＝synthetic；English 正常", "说明 api_key＝[已隐藏]；English 正常"),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(redact(value), expected)

    def test_long_secret_and_repeated_redaction(self):
        value = "开始 token=" + "中A🙂" * 10000 + "; 完成"
        self.assertEqual(redact(value), "开始 token=[已隐藏]; 完成")
        self.assertEqual(redact(redact(value)), redact(value))


class SafeTextTests(unittest.TestCase):
    def test_empty_and_whitespace(self):
        for value in ("", None, " \t\n\u3000"):
            with self.subTest(value=value):
                self.assertEqual(safe_text(value), "")

    def test_falsy_values_keep_their_text(self):
        self.assertEqual(safe_text(0), "0")
        self.assertEqual(safe_text(False), "False")

    def test_default_limit_and_exact_boundary(self):
        self.assertEqual(safe_text("中" * 219), "中" * 219)
        self.assertEqual(safe_text("中" * 220), "中" * 220)
        self.assertEqual(safe_text("中" * 221), "中" * 220 + "…")
        self.assertEqual(safe_text("中A🙂" * 10000), "中A🙂" * 73 + "中…")

    def test_zero_limit_and_negative_limit(self):
        self.assertEqual(safe_text("", 0), "")
        self.assertEqual(safe_text("中🙂A", 0), "…")
        with self.assertRaises(ValueError):
            safe_text("中🙂A", -1)

    def test_unlimited_preserves_layout_and_long_text(self):
        value = "\u3000中A🙂\n\t" * 10000
        self.assertEqual(safe_text(value, None), value)

    def test_unicode_spaces_collapse_only_when_bounded(self):
        value = "\u3000ＡＢＣ\t中文\nEnglish\u00a0🙂\u3000"
        self.assertEqual(safe_text(value), "ＡＢＣ 中文 English 🙂")

    def test_html_and_markdown_are_escaped_after_truncation(self):
        self.assertEqual(safe_text('<&>"\''), "&lt;&amp;&gt;&quot;&#x27;")
        self.assertEqual(safe_text("`*_[]\\"), "\\`\\*\\_\\[\\]\\\\")
        self.assertEqual(safe_text("`*_[]\\", markdown=True), "`*_[]\\")
        self.assertEqual(safe_text("<&", 1), "&lt;…")
        self.assertEqual(safe_text("[中", 1), "\\[…")
        self.assertEqual(safe_text("［全角］＊＿＆＜＞"), "［全角］＊＿＆＜＞")

    def test_redacts_before_truncating_and_in_both_markdown_modes(self):
        for markdown in (False, True):
            with self.subTest(markdown=markdown):
                expected = "token=[已隐藏]" if markdown else "token=\\[已隐藏\\]"
                self.assertEqual(safe_text("token=" + "x" * 10000, 20, markdown=markdown), expected)
                self.assertNotIn("synthetic", safe_text('password="synthetic secret"', None, markdown=markdown))

    def test_simple_emoji_and_mixed_text_cut_at_codepoint_boundary(self):
        self.assertEqual(safe_text("中🙂ＡEnglish", 3), "中🙂Ａ…")
        self.assertEqual(safe_text("中🙂Ａ", 3), "中🙂Ａ")

    def test_combining_and_emoji_sequences_are_not_split(self):
        clusters = ("e\u0301", "👍🏽", "👩🏽‍💻", "👨‍👩‍👧‍👦", "❤️", "1️⃣", "🇨🇳",
                    "🏴\U000e0067\U000e0062\U000e007f")
        for cluster in clusters:
            for cut in range(1, len(cluster)):
                with self.subTest(cluster=cluster, cut=cut):
                    self.assertEqual(safe_text("A" + cluster + "Z", 1 + cut), "A…")
            self.assertEqual(safe_text("A" + cluster + "Z", 1 + len(cluster)), "A" + cluster + "…")

    def test_adjacent_flags_keep_complete_pairs(self):
        self.assertEqual(safe_text("🇨🇳🇬🇧Z", 3), "🇨🇳…")
        self.assertEqual(safe_text("🇨🇳🇬🇧Z", 4), "🇨🇳🇬🇧…")


class ShownCommandTests(unittest.TestCase):
    def test_empty_and_whitespace(self):
        for detail in ("", " \t\n\u3000"):
            with self.subTest(detail=detail):
                self.assertEqual(shown_command(detail), "")

    def test_unicode_and_long_commands_survive_without_a_wrapper(self):
        for command in ("echo 🙂👩🏽‍💻🇨🇳", "echo ＡＢＣ１２３", "printf 中文-English_测试", "echo " + "中A🙂" * 10000):
            with self.subTest(prefix=command[:25], length=len(command)):
                self.assertEqual(shown_command(safe_text(command, None)), safe_text(command, None))

    def test_long_whitespace_does_not_stall_command_rendering(self):
        # Isolate the timeout: the old tail regex revisits every suffix of the whitespace run.
        code = """
from covey.core.text import shown_command
command = 'echo' + ' ' * 100000 + '中文🙂'
assert shown_command(command) == command
assert shown_command(command + ' | tail -1') == command
"""
        try:
            result = subprocess.run([sys.executable, "-B", "-c", code],
                                    cwd=Path(__file__).resolve().parents[1],
                                    capture_output=True, text=True, timeout=5)
        except subprocess.TimeoutExpired:
            self.fail("rendering a command with 100000 spaces exceeded 5 seconds")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_purpose_keeps_escaping_without_double_escape(self):
        purpose = "检查 [中文] & English_🙂"
        self.assertEqual(shown_command(safe_text(purpose + " · echo command", None)), safe_text(purpose, None))
        self.assertEqual(shown_command(safe_text("  · echo 中文", None)), "· echo 中文")

    def test_shell_wrappers_and_single_quote_escape(self):
        for shell in ("sh", "bash", "zsh", "/bin/bash", "/usr/bin/bash"):
            with self.subTest(shell=shell):
                command = f"{shell} -lc 'printf 中文🙂'"
                self.assertEqual(shown_command(safe_text(command, None)), "printf 中文🙂")
        self.assertEqual(shown_command(safe_text('/bin/sh -c "echo ＡＢＣ"', None)), "echo ＡＢＣ")
        self.assertEqual(shown_command(safe_text("/bin/bash -lc 'echo it'\\''s'", None)), "echo it&#x27;s")

    def test_output_trimming_and_trim_only_fallback(self):
        for tail in (" | tail -1", " | head -n 5", " | cut -c1-80", " 2>&1", " > /dev/null",
                     " 2>&1 | tail -1 | cut -c1-60 > /dev/null"):
            with self.subTest(tail=tail):
                self.assertEqual(shown_command(safe_text("echo 中文🙂" + tail, None)), "echo 中文🙂")
        self.assertEqual(shown_command(safe_text("> /dev/null", None)), "&gt; /dev/null")

    def test_paths_shorten_but_urls_and_relative_paths_survive(self):
        cases = (
            ("cat /a/b/c", "cat /a/b/c"),
            ("cat /a/b/c/d", "cat …/c/d"),
            ("cat /a/b/中文/Ａ🙂/", "cat …/中文/Ａ🙂"),
            ("R=/a/b/c/d/报告.txt", "R=…/d/报告.txt"),
            ("cat /" + "层/" * 1000 + "报告.txt", "cat …/层/报告.txt"),
            ("curl https://example.invalid/a/b/c/d", "curl https://example.invalid/a/b/c/d"),
            ("cat ./a/b/c/d ~/a/b/c/d", "cat ./a/b/c/d ~/a/b/c/d"),
        )
        for command, expected in cases:
            with self.subTest(prefix=command[:50]):
                self.assertEqual(shown_command(safe_text(command, None)), safe_text(expected, None))


# The shapes of the commands Antigravity and Codex ran on 2026-11-24 (T738), their names and paths made up: 执行过程 read
# "set -euo pipefail for v in http_proxy https_proxy…" under one another.
PROXIES = "for v in http_proxy https_proxy all_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY; do unset \"$v\"; done"
SAMPLES = (
    # (command, what it runs)
    ("set -euo pipefail\n" + PROXIES + "\nS=state/serving/pool-a\n.venv/bin/python tools/check.py --pool a --watch 10m",
     ".venv/bin/python tools/check.py --pool a --watch 10m"),
    ("set -e\nfor v in http_proxy https_proxy all_proxy; do\n  unset \"$v\"\ndone\nsvc-cli log search --since 10m | tail -n 20",
     "svc-cli log search --since 10m | tail -n 20"),
    ("/bin/bash -lc \"timeout --kill-after=2s 10s rg -n -i 'alpha|beta' /absolute/ws-root/notes.md\"",
     "rg -n -i 'alpha|beta' /absolute/ws-root/notes.md"),
    ("timeout --kill-after=2s 15s bash -c '\nset -euo pipefail\nBASE=/absolute/ws-root\ngit -C \"$BASE\" status --short\n'",
     'git -C "$BASE" status --short'),
    ("set -euo pipefail\nROOT=/absolute/ws-root\nPY=\"$ROOT/.venv/bin/python\"\n\necho \"=== NOW ===\"\ndate -u\n\"$PY\" scripts/status.py",
     'date -u\n"$PY" scripts/status.py'),
    ("cd /absolute/ws-root && timeout 60s python3 -m pytest -q tests/test_a.py", "python3 -m pytest -q tests/test_a.py"),
    ("timeout --kill-after=2s 30s python3 - <<'PY'\nimport json\n# 这不是说明\nprint(1)\nPY",
     "python3 - <<'PY'\nimport json\n# 这不是说明\nprint(1)\nPY"),
    ("bash -euo pipefail -c 'git fetch origin && git log -1'", "git fetch origin && git log -1"),
    ("pwd && sleep 10", "pwd && sleep 10"),  # Every command that does something stays.
    ("env -u HTTPS_PROXY LANG=C nice -n 10 make -j8 all", "make -j8 all"),
    ("for f in a.md b.md; do cat \"$f\"; done", 'for f in a.md b.md; do cat "$f"; done'),
    ("(cd sub && make test)", "(cd sub && make test)"),
    ("echo hello", "echo hello"),  # Nothing but setup: as it is.
    ("R=/a/b/c/d/报告.txt", "R=/a/b/c/d/报告.txt"),
)


class CommandWordsTests(unittest.TestCase):
    """T738 (2026-11-24): a command its model said nothing of in a field reads as what it runs, or as the comment it began with."""

    def test_what_a_command_runs_is_past_its_wrappers_and_setup_lines(self):
        for command, core in SAMPLES:
            with self.subTest(command=command[:40]):
                self.assertEqual(command_core(command), core)
                self.assertEqual(command_purpose(command), "")

    def test_a_comment_it_begins_with_is_what_it_is_for(self):
        cases = (("# 看 7 台机器的在线状态\nset -euo pipefail\n" + PROXIES + "\npython3 tools/x.py", "看 7 台机器的在线状态"),
                 ("set -euo pipefail\n# 搜 foo 的调用\nrg -n foo src", "搜 foo 的调用"),
                 ("set -euo pipefail  # 严格模式\nrg -n foo src  # 搜 foo 的调用", "搜 foo 的调用"),
                 ("/bin/bash -lc '# 跑单测\ntimeout 60s python3 -m pytest -q'", "跑单测"),
                 ("#!/bin/bash\n# 重启服务\nsystemctl --user restart x", "重启服务"),
                 ("rg -n '#notacomment' src", ""),
                 ("echo a # not a purpose of anything that runs", ""))  # Nothing runs: the comment is the echo's.
        for command, said in cases:
            with self.subTest(command=command[:40]):
                self.assertEqual(command_purpose(command), said)

    def test_a_card_shows_the_purpose_else_what_runs(self):
        boiler = SAMPLES[0][0]
        self.assertEqual(shown_command(safe_text(boiler, None)), safe_text(".venv/bin/python tools/check.py --pool a --watch 10m", None))
        self.assertEqual(shown_command(safe_text(SAMPLES[1][0], None)), "svc-cli log search --since 10m")  # Its tail trimmed.
        self.assertEqual(shown_command(safe_text("# 看状态 [a] & b\n" + boiler, None)), safe_text("看状态 [a] & b", None))
        self.assertNotIn("pipefail", shown_command(safe_text(boiler, None)))
        step = {"title": "执行命令", "detail": safe_text(boiler, None)}
        self.assertEqual(step_label(step), "执行命令 · " + safe_text(".venv/bin/python tools/check.py --pool a --watch 10m", None))

    def test_a_long_or_cut_command_still_reads(self):
        cut = "timeout 15s bash -c 'set -e\n" + PROXIES + "\npython3 run.py --step " + "x" * 600  # Cut before its quote ends.
        self.assertEqual(command_core(cut), "python3 run.py --step " + "x" * 600)
        self.assertEqual(command_core(""), "")
        self.assertEqual(command_purpose(None), "")


class ToolDetailTests(unittest.TestCase):
    CLAUDE = ("command", "file_path", "pattern", "url", "query")
    DSH = ("command", "path", "file_path", "pattern", "query", "url")

    def test_each_backend_keeps_its_own_key_order(self):
        grep = {"pattern": "def main", "path": "src"}
        self.assertEqual(tool_detail(grep, self.CLAUDE, "Grep"), "def main")
        self.assertEqual(tool_detail(grep, self.DSH), "src")
        self.assertEqual(tool_detail({"limit": 3}, self.CLAUDE, "Read"), "Read")
        self.assertEqual(tool_detail({"path": ""}, self.DSH), "")
        self.assertEqual(tool_detail(None, self.DSH), "")

    def test_a_command_leads_with_its_description(self):
        inputs = {"command": "ls -la", "description": "List files"}
        for keys in (self.CLAUDE, self.DSH):
            with self.subTest(keys=keys):
                self.assertEqual(tool_detail(inputs, keys), "List files · ls -la")
                self.assertEqual(tool_detail({"command": "ls"}, keys), "ls")
        self.assertEqual(tool_detail({"path": "a.py", "description": "Read it"}, self.DSH), "a.py")

    def test_a_command_or_a_call_leads_with_what_the_model_said(self):
        """T738: Antigravity's toolSummary (``said``) and a comment a command began with lead its detail as Claude's description does."""
        self.assertEqual(tool_detail({"command": "# 看状态\nls"}, self.DSH), "看状态 · # 看状态\nls")
        self.assertEqual(tool_detail({"command": "ls"}, self.DSH, said="列目录"), "列目录 · ls")
        self.assertEqual(tool_detail({"command": "ls", "description": "List"}, self.CLAUDE, said="列目录"), "列目录 · ls")
        self.assertEqual(tool_detail({"path": "a.py"}, self.DSH, said="读配置"), "读配置 · a.py")
        self.assertEqual(tool_detail({"url": "https://example.invalid/a?token=x"}, self.DSH, said="看文档"),
                         "看文档 · https://example.invalid/a")
        self.assertEqual(tool_detail({}, self.DSH, "转给 T12", said="转给 T12"), "转给 T12")

    def test_a_url_loses_its_query_and_fragment(self):
        for keys in (self.CLAUDE, self.DSH):
            with self.subTest(keys=keys):
                self.assertEqual(tool_detail({"url": "https://example.invalid/a/b?token=PRIVATE#frag"}, keys),
                                 "https://example.invalid/a/b")
                self.assertEqual(tool_detail({"url": "https://[::1"}, keys), "网页地址")
        # Another key's text is shown as it is.
        self.assertEqual(tool_detail({"query": "a?b=c"}, self.DSH), "a?b=c")


class ShortCountTests(unittest.TestCase):
    # Counts are numeric; empty, fullwidth and emoji strings are not accepted as counts.
    def test_zero_and_small_counts(self):
        for value, expected in ((0, "0"), (1, "1"), (999, "999"), (1000, "1,000"), (9999, "9,999")):
            with self.subTest(value=value):
                self.assertEqual(short_count(value), expected)

    def test_text_is_not_silently_coerced_to_a_count(self):
        for value in ("", "9" * 10000, "🙂", "１２３", "中文123", None):
            with self.subTest(value=str(value)[:20]):
                with self.assertRaises(TypeError):
                    short_count(value)

    def test_precision_and_unit_transitions(self):
        cases = ((10000, "1.00 万"), (99949, "9.99 万"), (99950, "10.0 万"),
                 (999499, "99.9 万"), (999500, "100 万"), (99994999, "9999 万"),
                 (99995000, "1.00 亿"), (100000000, "1.00 亿"),
                 (999499999, "9.99 亿"), (999500000, "10.0 亿"),
                 (9994999999, "99.9 亿"), (9995000000, "100 亿"))
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(short_count(value), expected)
