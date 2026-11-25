"""有结果未看 is one set (the owner, 2026-11-10: 以看板为准): the same records fed to the board (app/pins.py), 手上的事
(app/overview.py), 早晚汇总 (app/digest.py), the butler's snapshot (app/butler.py) and its tool topics_list
(app/butler_tools.py) give the same topics, the board's (core/board_read.py unseen)."""
from __future__ import annotations

import json
import os
import re
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from support.records import state_dir, write_job, write_topic

from covey.app import digest, butler, butler_tools, overview, pins
from covey.app.butler_env import ButlerEnv
from covey.app.relay_send import relay_path
from covey.core import butler_requests
from covey.core.jobs import job_path
from covey.core.butler import butler_topic_id
from covey.core.state import write_json

CHAT = "oc_dm"
HOUR, DAY = 3600, 86400
ON = {"COVEY_PINNED_TOPICS": "1", "COVEY_PINNED_OVERVIEW": "1"}


def iso(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


class OneSetTest(unittest.TestCase):
    def setUp(self):
        self.state = Path(state_dir(self))
        self.now = time.time()
        now = self.now
        self.topics = {}
        # T1 stopped after it ran: a result on the board (stopped ones too), never seen.
        self.job(1, "cancelled", now - 1800, timings={"backend_started": now - 2400})
        # T2 ended four days ago, never seen: the board's record keeps it, a result not seen stays however old.
        self.job(2, "done", now - 4 * DAY, updated=now - 4 * DAY)
        # T3 seen an hour ago, after it ended: on the board for KEEP_SEEN more, but seen.
        self.job(3, "done", now - 2 * HOUR)
        # T4 seen thirteen hours ago: off the board.
        self.job(4, "done", now - 14 * HOUR)
        # T5's conclusion was written on the butler's card (a release before 2026-11-09), and the owner read the
        # top level since: seen.
        record = self.job(5, "done", now - 1200)
        write_json(relay_path(self.state, record["key"]), {"state": "inline", "outcome": "done", "sent_at": now - 1140})
        # T6 done ten minutes ago, never seen.
        self.job(6, "done", now - 600)
        write_json(self.state / "topic-seen.json", {self.topics[3]: now - HOUR, self.topics[4]: now - 13 * HOUR,
                                                    butler_topic_id(CHAT): now - 60})
        long_ago = now - 30 * DAY
        write_json(self.state / pins.RECORD, {
            "schema_version": 1, "chat_id": CHAT, "since": long_ago, "keep_since": long_ago,
            "stopped_since": long_ago, "pins": [], "dismissed": {},
            "results": {self.topics[2]: {"at": now - 4 * DAY, "seen": None}}})

    def job(self, number, status, ended, *, timings=None, updated=None):
        topic = f"{number:02d}" * 16
        self.topics[number] = topic
        write_topic(self.state, topic_id=topic, chat_id=CHAT, topic_number=number, harness_id="claude",
                    workspace_name="bridge", root_id=f"om_root{number}")
        key = f"om_job{number}-{number}"
        record = write_job(self.state, key, chat_id=CHAT, topic_id=topic, job_id=number, status=status,
                           card_message_id=f"om_card{number}", harness_id="claude",
                           timings={"backend_started": ended - 60, **(timings or {}), "execution_finished": ended})
        if updated is not None:
            path = job_path(self.state, key)
            data = json.loads(path.read_text())
            data["updated_at"] = iso(updated)
            path.write_text(json.dumps(data))
        return {**record, "key": key}

    def numbers(self, topics):
        named = {topic: number for number, topic in self.topics.items()}
        return sorted(named[topic] for topic in topics)

    def board(self):
        rows, _ = pins.PinnedTopics(None, None).look(self.state, CHAT, self.now)
        return self.numbers(row["topic"] for row in rows if row["group"] == "result" and row["seen"] is None)

    def overview(self):
        # The results not seen: 有结果 and 停住了 (its own part, P0-1: what 要你处理 counts) of the board's index.
        view = overview.Overview(None, None, None, {}).view(SimpleNamespace(state_dir=self.state), CHAT, self.now)
        return self.numbers(row["topic"] for key in ("stopped", "result") for row in view["board"][key] if not row.get("seen"))

    def digest(self):
        view = digest.collect(self.state, CHAT, self.now, self.now - HOUR, self.now, board=True)
        return self.numbers(row["topic"] for row in view["done"] if not row["seen"])

    def snapshot(self):
        groups = butler.snapshot_groups(SimpleNamespace(state_dir=self.state), CHAT, self.now)
        return self.numbers(groups.get("result", {}))

    def topics_list(self):
        runtime = SimpleNamespace(log=lambda line: None, access=SimpleNamespace(owner_chat=lambda: CHAT))
        env = ButlerEnv(runtime, SimpleNamespace(harnesses={}, default="claude", target=lambda *args: None), None, None,
                      state_dir=self.state, profile="unit")
        answer = butler_tools.topics_list(env, butler_requests.Request("r1", "topics_list", {"group": "result", "limit": 60},
                                                                   "main-1", self.now))
        lines = answer["text"].splitlines() if answer["data"].get("total") else []
        return self.numbers(line.split(" · ")[-1] for line in lines if " · " in line)

    def test_the_five_readers_have_the_boards_unseen_results(self):
        with mock.patch.dict(os.environ, ON):
            board = self.board()
            self.assertEqual(board, [1, 2, 6])  # Stopped, four days old; not T3/T4 (seen), nor T5 (read at the top).
            self.assertEqual({"手上的事": self.overview(), "早晚汇总": self.digest(), "快照": self.snapshot(),
                              "topics_list": self.topics_list()},
                             {"手上的事": board, "早晚汇总": board, "快照": board, "topics_list": board})

    def test_topics_list_still_takes_the_old_group_name(self):
        with mock.patch.dict(os.environ, ON):
            runtime = SimpleNamespace(log=lambda line: None, access=SimpleNamespace(owner_chat=lambda: CHAT))
            env = ButlerEnv(runtime, SimpleNamespace(harnesses={}, default="claude", target=lambda *args: None), None,
                          None, state_dir=self.state, profile="unit")
            answer = butler_tools.topics_list(env, butler_requests.Request("r1", "topics_list", {"group": "unread"},
                                                                       "main-1", self.now))
        self.assertEqual(answer["data"]["total"], 3)

    def test_with_the_board_off_an_old_records_topics_taken_off_filter_nothing(self):
        # r4 review P4: a deployment that had the board on and turned it off reads 有结果未看 as one without it would.
        with mock.patch.object(pins, "laid", return_value=False):
            before, off = pins.board_results(self.state, CHAT, self.now)
        self.assertIn(self.topics[6], before)
        self.assertEqual(off, {})
        record = json.loads((self.state / pins.RECORD).read_text())
        record["dismissed"] = {self.topics[6]: {"group": "result", "at": self.now}}
        write_json(self.state / pins.RECORD, record)
        with mock.patch.object(pins, "laid", return_value=False):
            self.assertEqual(pins.board_results(self.state, CHAT, self.now), (before, {}))
        with mock.patch.dict(os.environ, ON):  # The board on: taken off.
            unseen, off = pins.board_results(self.state, CHAT, self.now)
        self.assertNotIn(self.topics[6], unseen)
        self.assertIn(self.topics[6], off)

def callbacks(card):
    """The callback values of every button on ``card``."""
    found = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("type") == "callback" and isinstance(node.get("value"), dict):
                found.append(node["value"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
    walk(card)
    return found


class AsksTest(unittest.TestCase):
    """要你处理 is one count (P0-2, T647: the 看板 counted 等你, 停住了 and 可能卡住, 手上的事 only 等你): the 看板, 手上的事 and
    its index over the pinned board say the same number at the same time, from core/board_read.py Asks, and list what it
    names: 等你, what stopped (not the owner's own stop: 已停止, background), what may be stuck, a project a guard paused."""

    def setUp(self):
        from covey.core import projects
        self.state = Path(state_dir(self))
        self.now = now = time.time()
        self.topics = {}
        for number, status, fields in ((11, "waiting_user", {}),
                                       (12, "failed", {}),
                                       (13, "cancelled", {"cancel_requested_by": "lead"}),
                                       (14, "cancelled", {"cancel_requested_by": "card"}),  # The owner's: not counted.
                                       (15, "running", {"last_activity_at": now - 3 * HOUR}),  # Quiet three hours.
                                       (16, "running", {"last_activity_at": now - 60}),
                                       (17, "done", {})):
            topic = f"{number:02d}" * 16
            self.topics[number] = topic
            write_topic(self.state, topic_id=topic, chat_id=CHAT, topic_number=number, harness_id="claude",
                        root_id=f"om_r{number}")
            ended = {} if status in ("running", "waiting_user") else {"execution_finished": now - 1200}
            write_job(self.state, f"om_j{number}-{number}", chat_id=CHAT, topic_id=topic, job_id=number, status=status,
                      card_message_id=f"om_card{number}", harness_id="claude",
                      timings={"backend_started": now - 2 * HOUR, **ended}, **fields)
        write_json(self.state / "questions" / "q11.json", {
            "token": "q11", "topic_id": self.topics[11], "chat_id": CHAT, "job_id": 11, "status": "pending",
            "created_at": now - 300, "question_message_id": "om_q11", "questions": [{"question": "推哪几个？"}]})
        long_ago = now - 30 * DAY  # The board has been on for a while (its rules hold since then).
        write_json(self.state / pins.RECORD, {"schema_version": 1, "chat_id": CHAT, "since": long_ago, "keep_since": long_ago,
                                              "stopped_since": long_ago, "pins": [], "dismissed": {}, "results": {}})
        record = projects.new_record(chat_id=CHAT, name="迁库", goal="周末前切完")
        self.project = record["id"]
        projects.create(self.state, {**record, "state": projects.PAUSED, "state_reason": "tokens"})

    def counted(self, card):
        """The band's 要你处理 and the title bar's tags of ``card``."""
        found = re.search(r"\*\*(\d+)\*\*</font> \*\*件事\*\*", json.dumps(card, ensure_ascii=False))
        return (int(found.group(1)) if found else 0), [tag["text"]["content"] for tag in card["header"]["text_tag_list"]]

    def board(self):
        from covey.cards.board import board_card
        runtime = SimpleNamespace(access=SimpleNamespace(agent_groups=(), notify_chat=lambda: CHAT), log=lambda line: None)
        reader = digest.Digest(runtime, None, None)
        reader.url = lambda ctx, topic, card="": ""
        view = reader.board_view(SimpleNamespace(state_dir=self.state, profile=None), CHAT, self.now)
        return view, board_card(view)

    def overview(self):
        from covey.cards.overview import overview_card
        reader = overview.Overview(None, None, None, {})
        reader.link = lambda state, topic, card: ""
        view = reader.view(SimpleNamespace(state_dir=self.state), CHAT, self.now)
        return view, overview_card(view, self.now)

    def test_the_ledger_is_what_every_card_counts(self):
        """等主人的账 (app/owner_ledger.py): the 看板, 手上的事 and the web page count from it, each thing once with its card."""
        from covey.app import owner_ledger
        from covey.app.web_collect import Collector
        from covey.core import projects
        for switches in ({}, ON):
            with self.subTest(board=bool(switches)), mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1",
                                                                                  **switches}):
                looked = pins.board_look(self.state, CHAT, self.now)
                ledger = owner_ledger.of(self.state, CHAT, self.now, looked, proposals=True)
                counts = ledger.counts()
                self.assertEqual({key: counts[key] for key in ("waiting", "stopped", "stuck")},
                                 {"waiting": 1, "stopped": 3, "stuck": 1})
                self.assertEqual(ledger.asks.counts(), Collector.asked(self.state, CHAT, self.now, looked).counts())
                keys = [entry.key for entry in ledger.entries()]
                self.assertEqual(len(keys), len(set(keys)))
                self.assertEqual(ledger.missing(), ())
                self.assertEqual(self.counted(self.board()[1])[0], ledger.asks.count())
                self.assertEqual(self.counted(self.overview()[1])[0], ledger.asks.count())

    def test_the_board_and_both_overviews_count_the_same_and_list_it(self):
        from covey.core import board_read, projects
        number = {topic: n for n, topic in self.topics.items()}
        tags = ["1 等你", "3 停住了", "1 可能卡住"]
        for switches in ({}, ON):
            with self.subTest(board=bool(switches)), mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1",
                                                                                  **switches}):
                asks = pins.board_look(self.state, CHAT, self.now).asks(
                    self.state, CHAT, board_read.waits(self.state, CHAT, self.now), self.now)
                self.assertEqual(asks.counts(), {"waiting": 1, "stopped": 3, "stuck": 1})  # T12, T13 and the project.
                self.assertEqual(asks.count(), 5)
                self.assertEqual(sorted(number[topic] for topic in asks.stopped), [12, 13])
                self.assertEqual(list(asks.projects), [self.project])
                self.assertEqual([number[topic] for topic in asks.stuck], [15])
                view, card = self.board()
                self.assertEqual(self.counted(card), (5, tags))
                self.assertEqual(sorted(number[row["topic"]] for row in view["done"] if row.get("tone") == "stopped"), [12, 13])
                self.assertEqual([number[row["topic"]] for row in view["running"] if row.get("stuck")], [15])
                self.assertIn("token 用完了", json.dumps(card, ensure_ascii=False))  # The project's block: 停住了 and why.
                shown, drawn = self.overview()
                self.assertEqual(self.counted(drawn), (5, tags))
                listed = shown["board"]["stopped"] if switches else shown["stopped"]
                self.assertEqual(sorted(number.get(row["topic"], 0) for row in listed if not row.get("project")), [12, 13])
                self.assertEqual([row["project"] for row in listed if row.get("project")], [self.project])
                if switches:  # The owner's own stop: 已停止, apart from 有结果, not counted.
                    self.assertEqual([number[row["topic"]] for row in shown["board"]["cancelled"]], [14])
                    self.assertEqual(shown["board"]["counts"]["stopped"], 3)

    def test_a_project_members_stop_is_the_leads_while_it_wakes_the_lead_and_else_listed_wherever_counted(self):
        """2026-11-24 T734: nine members of one project stopped in a day and 要你处理 said 9 停住了 for them, though the lead was
        woken for each (it took several over in topics of its own); the web page drew none of them. With
        COVEY_PROJECT_AUTOWAKE=1 a member's stop is its lead's: no card counts it or lists it, and a member that may be stuck
        still is the owner's (it wakes no one). Without it nothing wakes the lead: the stop is the owner's, counted and listed
        on every card, on 手上的事's pinned board too while the project's pinned cell shows another thread at work."""
        from covey.core import board_read, projects
        record = projects.new_record(chat_id=CHAT, name="扩缩容", goal="一周内上线")
        pid = record["id"]
        projects.create(self.state, record)
        lead = projects.lead_topic_id(CHAT, pid)
        write_topic(self.state, topic_id=lead, chat_id=CHAT, harness_id="claude", project=projects.project_field(pid, projects.LEAD))
        number = {topic: n for n, topic in self.topics.items()}
        # 21 stopped (no one asked it to stop: an official refusal's record), 22 at work and quiet three hours: the cell shows 22.
        for n, status, fields in ((21, "cancelled", {}), (22, "running", {"last_activity_at": self.now - 3 * HOUR})):
            topic = f"{n:02d}" * 16
            number[topic] = n
            write_topic(self.state, topic_id=topic, chat_id=CHAT, topic_number=n, harness_id="claude", root_id=f"om_r{n}",
                        project=projects.project_field(pid, projects.MEMBER))
            projects.add_member(self.state, pid, topic)
            ended = {} if status == "running" else {"execution_finished": self.now - 1200}
            write_job(self.state, f"om_j{n}-{n}", chat_id=CHAT, topic_id=topic, job_id=n, status=status,
                      card_message_id=f"om_card{n}", harness_id="claude", timings={"backend_started": self.now - 2 * HOUR, **ended},
                      **fields)
        saved = json.loads((self.state / pins.RECORD).read_text())
        write_json(self.state / pins.RECORD, {**saved, "pins": [{"topic_id": lead, "message_id": "om_project_card"}]})
        for autowake, stopped, tags in (("", [12, 13, 21], ["1 等你", "4 停住了", "2 可能卡住"]),
                                        ("1", [12, 13], ["1 等你", "3 停住了", "2 可能卡住"])):
            with self.subTest(autowake=autowake), mock.patch.dict(os.environ, {projects.ENV: "1", projects.AUTOWAKE_ENV: autowake,
                                                                               "COVEY_BOARD": "1", **ON}):
                asks = pins.board_look(self.state, CHAT, self.now).asks(
                    self.state, CHAT, board_read.waits(self.state, CHAT, self.now), self.now)
                self.assertEqual(sorted(number[topic] for topic in asks.stopped), stopped)
                self.assertEqual(sorted(number[topic] for topic in asks.stuck), [15, 22])  # The quiet member's: no one else hears of it.
                view, card = self.board()
                self.assertEqual(self.counted(card), (len(stopped) + 4, tags))
                self.assertEqual(sorted(number[row["topic"]] for row in view["done"] if row.get("tone") == "stopped"), stopped)
                shown, drawn = self.overview()
                self.assertEqual(self.counted(drawn), (len(stopped) + 4, tags))
                listed = [number.get(row["topic"], 0) for row in shown["board"]["stopped"] if not row.get("project")]
                self.assertEqual(sorted(listed), stopped)  # 21 is listed though its project's cell is pinned (showing 22).

    def test_a_proposal_waiting_is_counted_and_listed_alike_by_the_board_and_both_overviews(self):
        """B3 (T657, docs/ui.md 2.2: 等你定的 are 等你): with 整理专项 on, its proposal waiting for his 好 is 等你 on every card at
        once: counted in 要你处理 (core/board_read.py Asks.proposals) by the 看板, 手上的事 and its index over the pinned board,
        listed under 等你 with 建专项 and 不管了; decided, it is counted by none. A personal group's cards have none."""
        from covey.cards.project_proposal import BOARD_FROM, CREATE_KIND
        from covey.core import board_read, project_proposals as tidy, projects
        record = tidy.new_proposal(tidy.CREATE, topics=[self.topics[16], self.topics[17]], name="迁库收尾", goal="周末前收完")
        record["card"] = {"message_id": "om_proposal"}
        tidy.put_proposal(self.state, record)
        tags = ["2 等你", "3 停住了", "1 可能卡住"]
        for switches in ({}, ON):
            with self.subTest(board=bool(switches)), mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1",
                                                                                  tidy.ENV: "suggest", **switches}):
                looked = pins.board_look(self.state, CHAT, self.now)
                asks = looked.asks(self.state, CHAT, board_read.waits(self.state, CHAT, self.now), self.now, proposals=True)
                self.assertEqual((asks.counts()["waiting"], asks.count()), (2, 6))
                self.assertEqual(list(asks.proposals), [record["id"]])
                # 还有 N 件等你 under an answered question (app/question_display.py): the 看板's 等你, in the private chat.
                self.assertEqual(overview.waiting_count(self.state, CHAT, self.now, proposals=True), 2)
                self.assertEqual(overview.waiting_count(self.state, CHAT, self.now), 1)
                view, card = self.board()
                self.assertEqual(self.counted(card), (6, tags))
                self.assertIn({"from": BOARD_FROM, "kind": CREATE_KIND, "proposal": record["id"]}, callbacks(card))
                self.assertIn("「迁库收尾」", json.dumps(card, ensure_ascii=False))
                shown, drawn = self.overview()
                self.assertEqual(self.counted(drawn), (6, tags))
                listed = (shown["board"] if switches else shown)["proposals"]
                self.assertEqual([row["id"] for row in listed], [record["id"]])
                self.assertIn({"from": BOARD_FROM, "kind": CREATE_KIND, "proposal": record["id"]}, callbacks(drawn))
        tidy.update_proposal(self.state, record["id"], lambda data: data.update(state=tidy.DECLINED))
        with mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1", tidy.ENV: "suggest", **ON}):
            self.assertEqual(self.counted(self.board()[1])[0], 5)
            self.assertEqual(self.counted(self.overview()[1])[0], 5)
            group = overview.Overview(None, None, None, {}, chat=CHAT)  # A personal group's own card.
            group.link = lambda state, topic, card: ""
            self.assertNotIn("proposals", group.view(SimpleNamespace(state_dir=self.state), CHAT, self.now))
        with mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1", tidy.ENV: "suggest"}):
            record = tidy.new_proposal(tidy.CREATE, topics=[self.topics[11], self.topics[17]], name="另一件")
            record["card"] = {"message_id": "om_proposal2"}
            tidy.put_proposal(self.state, record)
            self.assertEqual(self.counted(self.board()[1])[0], 6)  # A new one is read at once (its file changes the folder).
        with mock.patch.dict(os.environ, {projects.ENV: "1", "COVEY_BOARD": "1", tidy.ENV: ""}):  # 整理专项 off: as before.
            self.assertEqual(self.counted(self.board()[1])[0], 5)
            self.assertEqual(self.counted(self.overview()[1])[0], 5)


if __name__ == "__main__":
    unittest.main()
