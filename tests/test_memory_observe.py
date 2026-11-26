"""What the Bridge counts of a finished turn's use of the memory (app/memory_observe.py): carried and listed entries, the
checkpoint's ``memory_used`` as a half-weight signal, once per turn, nothing with the memory off or in a 代答 topic, and that
app/memory_collect.py ``collect`` runs it at the end of every turn."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from support import UNSET_OFF
from support import make_context
from support.records import write_job, write_topic

from covey.app import memory_collect, memory_observe
from covey.core import memory, memory_usage, memstore
from covey.core.jobs import BridgeReplyJob as ReplyJob
from covey.core.jobs import find_job_record
from covey.core.state import write_json


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        patcher = mock.patch.dict(os.environ, {name: value for name, value in os.environ.items()
                                               if not name.startswith(("COVEY_", "LARK_BRIDGE_"))} | UNSET_OFF | {memory.ENV: "1"},
                                  clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.ctx = make_context(Path(tmp.name))
        self.state = self.ctx.state_dir
        write_topic(self.state, topic_id="t1", topic_number=7)
        self.ctx.topic_id = "t1"
        self.rule = memstore.add(self.state, kind="rule", scope="global", text="汇报先给结论")
        self.note = memstore.add(self.state, kind="note", scope="global", text="rg 会扫 NAS")
        self.listed = memstore.add(self.state, kind="note", scope="global", text="发版走灰度")
        self.count = 0

    def turn(self, *, ids=None, listed=None, used=None):
        self.count += 1
        key = f"om{self.count}"
        path = self.state / f"cp-{key}.json"
        write_json(path, {"phase": "完成", **({"memory_used": used} if used is not None else {})})
        write_job(self.state, key, job_id=self.count, topic_id="t1", chat_id="oc_dm", status="done", user_text="看看",
                  message_id=key, checkpoint_path=str(path), memory_ids=ids or [], memory_listed=listed or [])
        return ReplyJob(job_id=self.count, user_text="看看", chat_id="oc_dm", message_id=key, timeout=0, topic_id="t1")

    def counts(self, entry):
        return {k: v for k, v in memory_usage.counts(self.state).get(entry.ref, {}).items() if k in ("e", "t", "h")}


class ObserveTest(Case):
    def test_carried_listed_and_used_are_counted_with_their_own_weights(self):
        ids = [{"n": e.code, "ref": e.ref, "scope": "global", "kind": e.kind, "by": "owner"} for e in (self.rule, self.note)]
        job = self.turn(ids=ids, listed=[{"n": self.listed.code, "ref": self.listed.ref}], used=[self.rule.code.lower()])
        memory_observe.observe(self.ctx, job, None)
        self.assertEqual(self.counts(self.rule), {"e": 1, "t": 0, "h": 0.5})  # Carried, and named in memory_used (half weight).
        self.assertEqual(self.counts(self.note), {"e": 1, "t": 0, "h": 0})
        self.assertEqual(self.counts(self.listed), {"e": 0, "t": 1, "h": 0})
        self.assertIs(find_job_record(self.state, job.message_id)["memory_observed"], True)

    def test_a_turn_is_counted_once(self):
        job = self.turn(ids=[{"n": self.rule.code, "ref": self.rule.ref}], used=[self.rule.ref])
        for _ in range(3):
            memory_observe.observe(self.ctx, job, None)
        self.assertEqual(self.counts(self.rule), {"e": 1, "t": 0, "h": 0.5})

    def test_an_old_m_number_is_read_through_the_turns_memory_ids(self):
        job = self.turn(ids=[{"n": "M12", "ref": self.note.ref}], used=["M12", "M99", "ZZZZZ"])
        memory_observe.observe(self.ctx, job, None)
        self.assertEqual(self.counts(self.note), {"e": 1, "t": 0, "h": 0.5})

    def test_a_used_entry_the_turn_did_not_name_is_not_a_signal_and_a_bad_checkpoint_costs_nothing(self):
        job = self.turn(ids=[{"n": self.rule.code, "ref": self.rule.ref}], used="not a list")
        memory_observe.observe(self.ctx, job, None)
        self.assertEqual(self.counts(self.rule), {"e": 1, "t": 0, "h": 0})

    def test_nothing_is_counted_with_the_memory_off_or_in_a_proxy_topic(self):
        job = self.turn(ids=[{"n": self.rule.code, "ref": self.rule.ref}])
        with mock.patch.dict(os.environ, {memory.ENV: "0"}):
            memory_observe.observe(self.ctx, job, None)
        self.assertEqual(memory_usage.counts(self.state), {})
        self.assertNotIn("memory_observed", find_job_record(self.state, job.message_id))
        write_topic(self.state, topic_id="t1", topic_number=7, proxy={"contact": "ou_x"})
        self.ctx.history_path = self.state / "topics" / "t1" / "history.jsonl"
        memory_observe.observe(self.ctx, job, None)
        self.assertEqual(memory_usage.counts(self.state), {})

    def test_a_failure_is_swallowed(self):
        job = self.turn(ids=[{"n": self.rule.code, "ref": self.rule.ref}])
        with mock.patch.object(memory_usage, "carried", side_effect=OSError("disk")):
            memory_observe.observe(self.ctx, job, None)
        self.assertNotIn("memory_observed", find_job_record(self.state, job.message_id))

    def test_collect_runs_it_at_the_end_of_every_turn(self):
        job = self.turn(ids=[{"n": self.rule.code, "ref": self.rule.ref}], listed=[{"n": self.listed.code, "ref": self.listed.ref}])
        runtime = mock.Mock(access=mock.Mock(owner_turn=lambda chat, sender: True))
        memory_collect.collect(runtime, None, job, self.ctx)
        self.assertEqual((self.counts(self.rule)["e"], self.counts(self.listed)["t"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
