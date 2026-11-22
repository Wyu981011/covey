"""多参与者协作的契约 (core/collab.py, docs/architecture.md 多参与者协作): each example message flow has one owner of its
delivery, the states only go by their tables, and the ids make a second submission find the first."""
from __future__ import annotations

import unittest

from covey.core import collab
from covey.core.collab import (BUTLER, COLLAB, DESK, DIRECT, IN_TOPIC, LEAD, REFUSED, ROOM, ROUTER, TOPIC, Entry,
                               Participant, Quote, Route, route)

BUTLER_P = Participant("b0", BUTLER)
LEAD_A = Participant("la", LEAD, project="pa")
LEAD_B = Participant("lb", LEAD, project="pb")
T3 = Participant("t3", TOPIC)
T5 = Participant("t5", TOPIC, project="pa")
T7 = Participant("t7", TOPIC)
T9 = Participant("t9", TOPIC)


class ExampleFlowsTest(unittest.TestCase):
    """docs/architecture.md 多参与者协作 · 示例消息流, one test a row."""

    def test_the_room_without_an_at_is_the_butlers_as_before(self):
        self.assertEqual(route(Entry(ROOM)), Route(DESK))

    def test_one_at_goes_straight_to_it_and_may_now_be_an_ordinary_topic(self):
        self.assertEqual(route(Entry(ROOM, mentions=(LEAD_A,))), Route(DIRECT, "la"))
        self.assertEqual(route(Entry(ROOM, mentions=(T3,))), Route(DIRECT, "t3"))
        self.assertEqual(route(Entry(ROOM, mentions=(BUTLER_P,))), Route(DESK))

    def test_several_ats_with_a_quoted_topic_make_it_the_owner(self):
        found = route(Entry(ROOM, mentions=(T5, T7), quote=Quote(T3)))
        self.assertEqual((found.to, found.owner, found.helpers, found.shown_default), (COLLAB, "t3", ("t5", "t7"), False))

    def test_several_ats_without_context_take_the_first_ordinary_topic_shown_and_changeable(self):
        found = route(Entry(ROOM, mentions=(LEAD_A, T5, T7)))
        self.assertEqual((found.to, found.owner, found.helpers, found.shown_default), (COLLAB, "t5", ("la", "t7"), True))
        chosen = route(Entry(ROOM, mentions=(LEAD_A, T5, T7), integrator=T7))
        self.assertEqual((chosen.owner, chosen.helpers, chosen.shown_default), ("t7", ("la", "t5"), False))

    def test_leads_alone_go_to_the_butler_once_to_find_the_owner_unless_the_butler_is_picked(self):
        self.assertEqual(route(Entry(ROOM, mentions=(LEAD_A, LEAD_B))), Route(ROUTER, helpers=("la", "lb")))
        self.assertEqual(route(Entry(ROOM, mentions=(LEAD_A, BUTLER_P))), Route(COLLAB, "b0", ("la",)))
        self.assertEqual(route(Entry(ROOM, mentions=(LEAD_A, LEAD_B), integrator=LEAD_B)), Route(COLLAB, "lb", ("la",)))

    def test_inviting_others_in_a_topic_keeps_the_topic_its_owner(self):
        self.assertEqual(route(Entry(IN_TOPIC, here=T3, mentions=(T5,))), Route(COLLAB, "t3", ("t5",)))
        self.assertEqual(route(Entry(IN_TOPIC, here=T3)), Route(DIRECT, "t3"))
        self.assertEqual(route(Entry(IN_TOPIC, here=T3, mentions=(T3,))), Route(DIRECT, "t3"))  # Itself: nobody else.
        self.assertEqual(route(Entry(IN_TOPIC, here=T3, mentions=(T5,), integrator=T5)), Route(COLLAB, "t5", ("t3",)))

    def test_a_quote_goes_to_the_one_quoted_and_with_an_at_to_the_one_picked(self):
        self.assertEqual(route(Entry(ROOM, quote=Quote(T3))), Route(DIRECT, "t3"))
        self.assertEqual(route(Entry(ROOM, quote=Quote(LEAD_A))), Route(DIRECT, "la"))
        self.assertEqual(route(Entry(ROOM, quote=Quote(BUTLER_P))), Route(DESK))
        self.assertEqual(route(Entry(ROOM, quote=Quote(T3), mentions=(T5,))), Route(DIRECT, "t5"))

    def test_a_quote_of_a_collaboration_stays_in_it_with_its_integrator(self):
        quoted = Quote(T5, collab="c1", integrator=T3)
        self.assertEqual(route(Entry(ROOM, quote=quoted)), Route(COLLAB, "t3", (), "c1"))
        self.assertEqual(route(Entry(ROOM, quote=quoted, mentions=(T5,))), Route(COLLAB, "t3", ("t5",), "c1"))
        with self.assertRaises(ValueError):
            route(Entry(ROOM, quote=Quote(T5, collab="c1")))

    def test_a_lead_named_takes_part_and_its_ordinary_receipt_wakes_nobody(self):
        found = route(Entry(IN_TOPIC, here=T5, mentions=(LEAD_A,)))
        self.assertEqual((found.to, found.owner, found.helpers), (COLLAB, "t5", ("la",)))
        self.assertFalse(collab.RECEIPT_WAKES[collab.RECEIPT_ANSWERED])
        self.assertTrue(collab.RECEIPT_WAKES[collab.RECEIPT_GAP])

    def test_each_flow_has_exactly_one_owner_or_says_who_decides(self):
        entries = (Entry(ROOM), Entry(ROOM, mentions=(T3,)), Entry(ROOM, mentions=(T3, T5)), Entry(ROOM, mentions=(LEAD_A, LEAD_B)),
                   Entry(IN_TOPIC, here=T3, mentions=(T5, T7)), Entry(ROOM, quote=Quote(T3), mentions=(T5, T7)))
        for entry in entries:
            with self.subTest(entry):
                found = route(entry)
                if found.to in (DESK, ROUTER):
                    self.assertEqual(found.owner, "")  # The butler decides, as before or once.
                else:
                    self.assertTrue(found.owner)
                    self.assertNotIn(found.owner, found.helpers)

    def test_more_helpers_than_the_owner_may_name_are_refused_before_anything_is_sent(self):
        four = (T5, T7, T9, LEAD_A)
        for entry in (Entry(IN_TOPIC, here=T3, mentions=four), Entry(ROOM, mentions=(T3, *four)),
                      Entry(ROOM, mentions=(LEAD_A, LEAD_B, Participant("lc", LEAD), Participant("ld", LEAD)))):
            with self.subTest(entry):
                found = route(entry)
                self.assertEqual(found.to, REFUSED)
                self.assertIn("最多请 3 位", found.reason)
        self.assertEqual(route(Entry(IN_TOPIC, here=T3, mentions=four[:3])).helpers, ("t5", "t7", "t9"))


class StatesTest(unittest.TestCase):
    def test_an_ask_goes_forward_only_and_its_ended_states_never_go_back(self):
        path = (collab.CHECKING, collab.QUEUED, collab.TAKEN, collab.REPLIED, collab.READ)
        for current, new in zip(path, path[1:]):
            self.assertEqual(collab.moved(collab.ASK_TRANSITIONS, current, new), new)
        for ended in collab.ASK_ENDED:
            for new in collab.ASK_TRANSITIONS:
                with self.subTest(ended=ended, new=new), self.assertRaises(ValueError):
                    collab.moved(collab.ASK_TRANSITIONS, ended, new)
        self.assertEqual(collab.ASK_ENDED, {collab.READ, collab.NOT_TAKEN, collab.FAILED, collab.EXPIRED, collab.CANCELLED})
        with self.assertRaises(ValueError):  # An answer is never taken back into the queue.
            collab.moved(collab.ASK_TRANSITIONS, collab.REPLIED, collab.QUEUED)
        self.assertEqual(set(collab.ASK_WORDS), set(collab.ASK_TRANSITIONS))

    def test_a_collaboration_is_open_until_delivered_or_stopped(self):
        self.assertEqual(collab.moved(collab.COLLAB_TRANSITIONS, collab.OPEN, collab.DONE), collab.DONE)
        self.assertEqual(collab.moved(collab.COLLAB_TRANSITIONS, collab.OPEN, collab.CANCELLED), collab.CANCELLED)
        for ended in (collab.DONE, collab.CANCELLED):
            with self.assertRaises(ValueError):
                collab.moved(collab.COLLAB_TRANSITIONS, ended, collab.OPEN)


class IdsTest(unittest.TestCase):
    def test_the_same_message_and_participants_give_the_same_collaboration(self):
        first = collab.collab_id("om_1", "t3", ["t5", "t7"])
        self.assertEqual(first, collab.collab_id("om_1", "t3", ("t7", "t5", "t5")))
        self.assertNotEqual(first, collab.collab_id("om_2", "t3", ["t5", "t7"]))
        self.assertNotEqual(first, collab.collab_id("om_1", "t5", ["t3", "t7"]))
        self.assertRegex(first, r"^[0-9a-f]{24}$")
        with self.assertRaises(ValueError):
            collab.collab_id("", "t3", [])

    def test_each_helper_has_one_ask_and_one_clarification(self):
        first, second = collab.ask_id("c1", "t5", 1), collab.ask_id("c1", "t5", 2)
        self.assertNotEqual(first, second)
        self.assertEqual(first, collab.ask_id("c1", "t5", 1))
        self.assertNotEqual(first, collab.ask_id("c1", "t7", 1))
        with self.assertRaises(ValueError):
            collab.ask_id("c1", "t5", 3)


if __name__ == "__main__":
    unittest.main()
