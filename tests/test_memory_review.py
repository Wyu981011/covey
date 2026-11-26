"""待审核 (core/memory_review.py): what each kind of item writes when the owner decides it, one undo token over a whole
decision, the 14 days, and the health lists."""
from __future__ import annotations

import unittest
from unittest import mock

from support.records import state_dir

from covey.core import memory_review, memstore, projects
from covey.core.memory_review import ReviewItem

CHAT = "oc_owner_dm"
PID = "a1b2c3d4e5f6"
NOW = 1_800_000_000.0
DAY = 86400


def item(kind="learn", text="回复先给结论", **fields):
    suggest = fields.pop("suggest", {"kind": "rule", "scope": "global"})
    return ReviewItem(key="", type=kind, title=fields.pop("title", ""), text=text, suggest=suggest,
                      created_at=fields.pop("created_at", NOW), **fields)


class Case(unittest.TestCase):
    def setUp(self):
        self.state = state_dir(self)
        memstore._cache.clear()
        projects.create(self.state, projects.new_record(chat_id=CHAT, name="记忆专项", project_id=PID, now=NOW))

    def lead_rule(self, text="部署前先问"):
        return memstore.add(self.state, kind="rule", scope="project", owner_key=PID, text=text, said="summary", by="lead", now=NOW)


class DecideTest(Case):
    def test_add_does_not_repeat_a_proposal(self):
        one = memory_review.add(self.state, item())
        self.assertEqual(memory_review.add(self.state, item()), one)
        self.assertEqual([row.key for row in memory_review.items(self.state)], [one])

    def test_migrate_accept_makes_it_the_owners_and_reject_makes_it_a_note(self):
        a, b = self.lead_rule("部署前先问"), self.lead_rule("发布走灰度")
        suggest = {"kind": "rule", "scope": "project", "project_key": PID}
        ka = memory_review.add(self.state, item("migrate", a.text, suggest=suggest, items=(a.ref,)))
        kb = memory_review.add(self.state, item("migrate", b.text, suggest=suggest, items=(b.ref,)))
        done = memory_review.decide(self.state, ka, "accept", now=NOW)
        self.assertEqual((done["state"], done["refs"]), ("accepted", [a.ref]))
        self.assertEqual(memstore.find(self.state, a.ref).said, "owner")
        self.assertEqual(memory_review.decide(self.state, kb, "reject", now=NOW)["state"], "rejected")
        self.assertEqual(memstore.find(self.state, b.ref).kind, "note")
        self.assertEqual(memory_review.items(self.state), [])

    def test_learn_accept_adds_an_entry_the_owner_said_and_reject_writes_nothing(self):
        key = memory_review.add(self.state, item("learn", "回复先给结论", suggest={"kind": "rule", "scope": "project", "project_key": PID}))
        done = memory_review.decide(self.state, key, "accept", now=NOW)
        entry = memstore.find(self.state, done["refs"][0])
        self.assertEqual((entry.said, entry.by, entry.scope, entry.owner_key, entry.text), ("owner", "learn", "project", PID, "回复先给结论"))
        other = memory_review.add(self.state, item("lead", "不要擅自推送"))
        self.assertEqual(memory_review.decide(self.state, other, "reject", now=NOW)["refs"], [])
        self.assertIsNone(next((e for e in memstore.entries(self.state) if e.text == "不要擅自推送"), None))

    def conflict(self, action, new):
        old = memstore.add(self.state, kind="rule", scope="global", text="旧写法", now=NOW)
        key = memory_review.add(self.state, item("conflict", new, conflict_with=old.ref))
        memory_review.decide(self.state, key, action, now=NOW)
        texts = [e.text for e in memstore.entries(self.state)]
        return memstore.find(self.state, old.ref).text, texts

    def test_conflict_keep_left_drops_the_new_words(self):
        old, texts = self.conflict("keep_left", "新写法甲")
        self.assertEqual((old, texts), ("旧写法", ["旧写法"]))

    def test_conflict_keep_right_takes_the_new_words_in_the_old_entry(self):
        old, texts = self.conflict("keep_right", "新写法乙")
        self.assertEqual((old, texts), ("新写法乙", ["新写法乙"]))

    def test_conflict_keep_both_makes_the_new_words_an_entry(self):
        old, texts = self.conflict("keep_both", "新写法丙")
        self.assertEqual((old, sorted(texts)), ("旧写法", sorted(["旧写法", "新写法丙"])))

    def test_tidy_reject_puts_the_lines_back(self):
        one = memstore.add(self.state, kind="note", scope="global", text="某条资料", now=NOW)
        memstore.archive(self.state, one.ref, now=NOW)
        key = memory_review.add(self.state, item("tidy", "收起了一条", items=(one.ref,)))
        self.assertEqual(memory_review.decide(self.state, key, "reject", now=NOW)["refs"], [one.ref])
        self.assertEqual(memstore.find(self.state, one.ref).status, "active")
        again = memstore.add(self.state, kind="note", scope="global", text="另一条资料", now=NOW)
        memstore.archive(self.state, again.ref, now=NOW)
        key = memory_review.add(self.state, item("tidy", "又收起一条", items=(again.ref,)))
        memory_review.decide(self.state, key, "accept", now=NOW)
        self.assertEqual(memstore.find(self.state, again.ref).status, "archived")

    def test_import_accept_takes_and_reject_ignores(self):
        with mock.patch.object(memory_review.harness_memory, "take", return_value=[]) as take, \
                mock.patch.object(memory_review.harness_memory, "ignore") as ignore:
            a = memory_review.add(self.state, item("import", "导入甲", items=("fp1",)))
            b = memory_review.add(self.state, item("import", "导入乙", items=("fp2",)))
            memory_review.decide(self.state, a, "accept", who="owner", token="t1", now=NOW)
            memory_review.decide(self.state, b, "reject", now=NOW)
        self.assertEqual(take.call_args.args[2], ["fp1"])
        self.assertEqual(ignore.call_args.args[1], ["fp2"])

    def test_decided_again_or_unknown_raises(self):
        key = memory_review.add(self.state, item())
        memory_review.decide(self.state, key, "reject", now=NOW)
        with self.assertRaises(ValueError):
            memory_review.decide(self.state, key, "accept", now=NOW)
        with self.assertRaises(ValueError):
            memory_review.decide(self.state, "review:learn:nope00", "accept", now=NOW)

    def test_accept_counts_as_a_strong_sign(self):
        key = memory_review.add(self.state, item())
        ref = memory_review.decide(self.state, key, "accept", now=NOW)["refs"][0]
        self.assertGreater(memory_review.memory_usage.counts(self.state)[ref]["h"], 0)

    def test_decide_all_takes_every_open_item_under_one_token_and_undoes_at_once(self):
        keys = [memory_review.add(self.state, item("learn", text)) for text in ("规矩甲", "规矩乙", "规矩丙")]
        done = memory_review.decide_all(self.state, "accept_all", now=NOW)
        self.assertEqual(sorted(done["decided"]), sorted(keys))
        self.assertEqual((done["failed"], len(done["refs"])), ([], 3))
        self.assertEqual(memory_review.items(self.state), [])
        memstore.undo(self.state, done["undo_token"], now=NOW + 1)
        self.assertEqual([e.text for e in memstore.entries(self.state)], [])

    def test_decide_all_reports_the_ones_that_failed(self):
        key = memory_review.add(self.state, item())
        done = memory_review.decide_all(self.state, "reject_all", keys=[key, "review:learn:nope00"], token="tk", now=NOW)
        self.assertEqual((done["decided"], done["undo_token"]), ([key], "tk"))
        self.assertEqual([row["key"] for row in done["failed"]], ["review:learn:nope00"])


class ExpireHealthTest(Case):
    def test_expire_marks_the_old_open_ones_only(self):
        old = memory_review.add(self.state, item("learn", "旧的", created_at=NOW - 15 * DAY))
        new = memory_review.add(self.state, item("learn", "新的", created_at=NOW - 13 * DAY))
        self.assertEqual(memory_review.expire(self.state, now=NOW), 1)
        self.assertEqual([row.key for row in memory_review.items(self.state)], [new])
        self.assertEqual(memstore.review_items(self.state, states=("expired",))[0]["key"], old)

    def test_health_is_empty_when_all_is_well(self):
        self.assertEqual(memory_review.health(self.state, now=NOW), {})
        memstore.add(self.state, kind="rule", scope="global", text="回复主人用中文", now=NOW)
        self.assertEqual(memory_review.health(self.state, now=NOW), {})

    def test_health_dup_is_two_entries_of_one_scope_that_say_the_same(self):
        a = memstore.add(self.state, kind="rule", scope="global", text="回复主人用中文", now=NOW)
        b = memstore.add(self.state, kind="rule", scope="global", text="回复主人一律用中文", now=NOW)
        for text in ("部署前先问", "提交信息写英文", "测试要跑全量", "不要擅自推送", "改配置先备份", "日志别带密钥", "发布走灰度", "文档用中文写"):
            memstore.add(self.state, kind="rule", scope="global", text=text, now=NOW)
        # A corpus this small weighs the words oddly: the similarity is the search's (core/memory_search.py), stood in for here.
        pair = [memory_review.memory_search.text_doc(text) for text in (a.text, b.text)]
        same = lambda corpus, x, y: (0.667, True) if [x, y] in (pair, pair[::-1]) else (0.1, True)  # noqa: E731
        with mock.patch.object(memory_review.memory_search, "mutual_docs", side_effect=same):
            self.assertEqual(memory_review.health(self.state, now=NOW), {"dup": [a.ref, b.ref]})
        with mock.patch.object(memory_review.memory_search, "mutual_docs", return_value=(0.667, False)):
            self.assertEqual(memory_review.health(self.state, now=NOW), {})  # Not covered: not a duplicate.

    def test_health_names_only_what_is_over(self):
        for i in range(16):
            memstore.add(self.state, kind="rule", scope="global", text=f"第{i}条互不相干的规矩，内容各异{i * 7}", now=NOW)
        with mock.patch.object(memory_review, "_duplicates", return_value=[]):
            self.assertEqual(memory_review.health(self.state, now=NOW), {"over_cap": ["global"]})

    def test_health_stale_vague_conflict_and_idle(self):
        old = memstore.add(self.state, kind="note", scope="global", text="这个服务的地址在别处", verified_at=NOW - 61 * DAY, now=NOW)
        memory_review.add(self.state, item("conflict", "新写法", conflict_with=old.ref))
        with mock.patch.object(memory_review.memory_usage, "counts", return_value={old.ref: {"e": 10, "t": 0, "h": 0}}), \
                mock.patch.object(memory_review, "_duplicates", return_value=[]):
            found = memory_review.health(self.state, now=NOW)
        self.assertEqual(sorted(found), ["conflict", "idle", "stale", "vague"])
        self.assertEqual(found["stale"], [old.ref])
        self.assertEqual(found["conflict"][0][0], old.ref)


if __name__ == "__main__":
    unittest.main()
