"""The write gate of a memory entry (core/memory_gate.py): time words and a live state refused or rewritten, vague pointers
only flagged, a decision never refused."""
from __future__ import annotations

import unittest

from covey.core.memory_gate import accept, check


class GateTest(unittest.TestCase):
    def test_live_state_is_refused_with_no_rewrite(self):
        verdict = check("现网第 459 代", kind="note")
        self.assertFalse(verdict.ok)
        self.assertEqual(verdict.text, "")
        self.assertIn("dynamic", verdict.flags)
        self.assertTrue(verdict.reason)

    def test_leading_time_word_is_rewritten(self):
        for text, want in (("从今天起回复用中文", "回复用中文"), ("今天开始部署要先问", "部署要先问"), ("目前只用中文回复", "只用中文回复"),
                           ("现在，先问再做", "先问再做")):
            verdict = check(text, kind="rule")
            self.assertFalse(verdict.ok, text)
            self.assertEqual(verdict.text, want)

    def test_time_word_that_cannot_go_is_refused_with_a_reason(self):
        for text in ("今天要先问", "现在的流程是A", "刚才说的那样办"):
            verdict = check(text, kind="rule")
            self.assertFalse(verdict.ok, text)
            self.assertEqual(verdict.text, "")
            self.assertIn("会过时", verdict.reason)

    def test_words_not_in_the_list_pass(self):
        # "上午" is not one of TIME_WORDS and nothing else matches: it passes (the gate keeps to the two hard cases).
        verdict = check("按上午已优化的方式处理", kind="rule")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.flags, ())

    def test_commit_and_clock_time_are_not_refused_or_flagged(self):
        verdict = check("11-26 15:21 授权推送 a1b2c3d", kind="note")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.flags, ())

    def test_vague_pointer_is_flagged_only(self):
        verdict = check("这个专项的部署要先问", kind="rule")
        self.assertTrue(verdict.ok)
        self.assertEqual(verdict.flags, ("vague",))

    def test_clear_rule_passes_clean(self):
        verdict = check("回复主人用中文", kind="rule")
        self.assertTrue(verdict.ok)
        self.assertEqual((verdict.text, verdict.flags), ("回复主人用中文", ()))

    def test_an_automatic_write_keeps_the_rewrite_or_nothing(self):
        self.assertEqual(accept("从今天起回复主人用中文", kind="rule")[0], "回复主人用中文")
        self.assertEqual(accept("现网第 459 代是稳定版", kind="rule")[0], "")
        self.assertEqual(accept("回复主人用中文", kind="rule")[0], "回复主人用中文")

    def test_decision_is_never_refused(self):
        verdict = check("今天部署吗？现网第 459 代，这个先不动", kind="decision")
        self.assertTrue(verdict.ok)
        self.assertEqual(set(verdict.flags), {"vague", "dynamic"})


if __name__ == "__main__":
    unittest.main()
