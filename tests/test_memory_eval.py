"""查记忆的合成测评 (scripts/memory_eval.py on tests/fixtures/memory_eval/): the lookup a turn uses finds what 40 made-up
queries ask for (paraphrases, answered questions, another project's entries, short symbols like 选 F, P0-A, kvoff-idx256) and
nothing for the six that should find nothing, at the shipped DEFAULT_TAU."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import REPO, UNSET_OFF

from covey.core import memory_search

FIXTURES = REPO / "tests" / "fixtures" / "memory_eval"


def _script():
    spec = importlib.util.spec_from_file_location("memory_eval", REPO / "scripts" / "memory_eval.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyntheticEvalTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name)
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))} | UNSET_OFF, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_lookup_finds_what_the_set_asks_and_nothing_for_the_negatives(self):
        script = _script()
        seeded = script.seed(self.state, FIXTURES / "seed.json")
        queries = script.load_set(FIXTURES / "set.jsonl")
        self.assertEqual(len(queries), 40)
        report = script.run(self.state, queries, tau=memory_search.DEFAULT_TAU, seeded=seeded)
        summary = report["summary"]
        self.assertGreaterEqual(summary["Recall@5"], 0.9, summary)
        self.assertGreaterEqual(summary["MRR"], 0.8, summary)
        self.assertLessEqual(summary["noise@5"], 0.4, summary)
        self.assertEqual(summary["negative_fp_rate"], 0.0, summary)
        short = [row for row in report["per_query"].values() if row["group"] == "short"]
        self.assertEqual(sum(row["hit5"] for row in short), len(short))  # 选 F, P0-A, kvoff-idx256, 910C sleep inf …


if __name__ == "__main__":
    unittest.main()
