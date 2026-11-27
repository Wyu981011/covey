"""What the owner repeated waits in 待审核 (COVEY_MEMORY_LEARN=1, app/memory_candidates.py offer); the Harnesses' own memory
goes there through app/memory_harvest.py queue (tests/test_harness_memory.py), no model asked."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import UNSET_OFF
from covey.app import memory_candidates, memory_harvest
from covey.core import memory, memory_review

NOW = 1_800_000_000.0


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.state = Path(tmp.name) / "state"
        self.state.mkdir()
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))} | UNSET_OFF, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)


class CandidatesTest(Case):
    def test_what_the_owner_repeated_waits_in_review_with_the_switch_or_without(self):
        for env in ({memory.ENV: "1", memory.LEARN_ENV: "1"}, {memory.ENV: "1"}):
            with mock.patch.dict(os.environ, env):
                memory_candidates.offer(self.state, "oc", NOW, lambda: [{"text": "汇报先给结论", "topics": ["a", "b"],
                                                                          "labels": ["T1", "T2"], "workspace": ""}], now=NOW)
        self.assertEqual(memory_candidates.load(self.state)["rows"], [])  # No carried row of the older record any more.
        queued = memory_review.items(self.state)
        self.assertEqual([(item.type, item.text) for item in queued], [("candidate", "汇报先给结论")])  # Once: same proposal.


class NoModelTest(unittest.TestCase):
    def test_the_harvest_asks_no_model(self):
        self.assertFalse(hasattr(memory_harvest, "harvest"))
        self.assertNotIn("track_judge", Path(memory_harvest.__file__).read_text())


if __name__ == "__main__":
    unittest.main()
