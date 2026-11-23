"""core/toml_compat.py: the TOML reader Python 3.10 uses where 3.11+ has tomllib reads what tomllib reads."""
from __future__ import annotations

import datetime
import unittest

from support import REPO
from covey.core import toml_compat

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10: compared with the literal below only.
    tomllib = None

# A Codex config.toml and the rest of TOML 1.0 a config may use.
DOCUMENT = '''\
# The owner's config
model = "gpt-x"
model_provider = "acme"
model_reasoning_effort = 'high'
approval_policy = "never"
notify = ["notify-send", "Codex"]
answer = 42
ratio = 0.5
hex = 0xff
on = true
when = 2026-11-23T08:00:00+08:00
day = 2026-11-23
text = """
two
lines"""
path = 'C:\\no\\escapes'
escaped = "tab\\tquote\\""
site.name = "dotted"

[model_providers.acme]
base_url = "https://acme.example/v1"
env_key = "ACME_KEY"
http_headers = { "X-A" = "b", n = 1 }

[projects."/absolute/work"]
trust_level = "trusted"

[[profiles]]
name = "fast"

[[profiles]]
name = "deep"
'''

EXPECTED = {
    "model": "gpt-x", "model_provider": "acme", "model_reasoning_effort": "high", "approval_policy": "never",
    "notify": ["notify-send", "Codex"], "answer": 42, "ratio": 0.5, "hex": 255, "on": True,
    "when": datetime.datetime(2026, 11, 23, 8, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=8))),
    "day": datetime.date(2026, 11, 23), "text": "two\nlines", "path": "C:\\no\\escapes", "escaped": 'tab\tquote"',
    "site": {"name": "dotted"},
    "model_providers": {"acme": {"base_url": "https://acme.example/v1", "env_key": "ACME_KEY",
                                 "http_headers": {"X-A": "b", "n": 1}}},
    "projects": {"/absolute/work": {"trust_level": "trusted"}},
    "profiles": [{"name": "fast"}, {"name": "deep"}],
}


class TomlCompatTest(unittest.TestCase):
    def test_it_reads_a_config_as_expected(self):
        self.assertEqual(toml_compat.loads(DOCUMENT), EXPECTED)

    @unittest.skipIf(tomllib is None, "no tomllib to compare with (Python 3.10)")
    def test_it_reads_what_tomllib_reads(self):
        self.assertEqual(toml_compat.loads(DOCUMENT), tomllib.loads(DOCUMENT))

    def test_a_document_that_is_not_toml_raises_a_value_error(self):
        for text in ("not = [toml", "a = 1\na = 2", "[t]\n[t]", 'x = "open'):
            with self.subTest(text=text), self.assertRaises(toml_compat.TOMLDecodeError) as caught:
                toml_compat.loads(text)
            self.assertIsInstance(caught.exception, ValueError)

    def test_the_copy_keeps_its_release_and_license(self):
        head = (REPO / "covey" / "core" / "toml_compat.py").read_text(encoding="utf-8")[:4000]
        self.assertIn(f"tomli {toml_compat.TOMLI_VERSION}", head)
        self.assertIn("MIT License", head)

    def test_load_reads_bytes_like_tomllib(self):
        import io
        self.assertEqual(toml_compat.load(io.BytesIO(DOCUMENT.encode())), EXPECTED)
        with self.assertRaises(TypeError):
            toml_compat.load(io.StringIO(DOCUMENT))


if __name__ == "__main__":
    unittest.main()
