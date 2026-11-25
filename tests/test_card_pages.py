"""A card's text too large for one card over several (cards/pages.py, T663): the owner, 2026-11-22: 超长输出拆卡或降级
发送时丢了新版卡头 (no T badge, title, state, link into the topic, the owner's words). Every card one message carries
stays within ANSWER_CARD_BYTES and Feishu's 30 KB once escaped again, each opens with the row, the text is cut where it
reads well and nothing of it or of what follows it is lost."""
from __future__ import annotations

import json
import re
import unittest

from covey.cards import pages
from covey.cards.answer_card import (ARTIFACTS_ID, FACTS_ID, WORDS_ID, ask_block, figure, tail, tail_card,
                                     topic_head)
from covey.cards.elements import json_size
from covey.cards.question_cards import OUTPUT_ID, OUTPUT_NEXT, output_pages
from covey.cards.relay_card import DONE, HINT_ID, relay_card, relay_pages
from covey.cards.review import ANSWER_CARD_BYTES, ANSWER_ID, FOLD_ID
from covey.cards.ui import ROW_ID

FILES = {"tag": "collapsible_panel", "element_id": ARTIFACTS_ID, "expanded": False,
         "header": {"title": {"tag": "markdown", "content": "产物 1 个"}}, "elements": []}
REPLY = "## 结论\n先说结论。\n\n" + "\n\n".join(f"### 第{n}节\n" + "这一节说的是很长的细节，" * 120 for n in range(1, 20))


def ids(built):
    return [element.get("element_id") or element.get("tag") for element in built["body"]["elements"]]


def row_words(built):
    """The words of a card's row, its tags and grey markup dropped."""
    return re.sub(r"<[^>]*>|\*\*", "", json.dumps(built["body"]["elements"][0], ensure_ascii=False))


def body_text(paged, element_id):
    """The text the cards carry, joined as the owner reads them one after another."""
    return "\n".join(element["content"] for page in paged.pages for element in page.card["body"]["elements"]
                     if element.get("element_id") == element_id)


def room(size):
    return lambda n: (size, size + size // 5)


class SplitTest(unittest.TestCase):
    def test_paragraphs_are_cut_after_one_and_every_part_keeps_to_its_room(self):
        text = "\n\n".join(f"第{n}段。" + "很长的内容，" * 60 for n in range(12))
        parts = pages.split(text, room(3000))
        self.assertGreater(len(parts), 2)
        for part in parts:
            self.assertLessEqual(pages._cost(part)[0], 3000)
            self.assertTrue(part.startswith("第"), part[:20])  # Each starts a paragraph: never mid-way through one.
        self.assertEqual("\n\n".join(parts), text)

    def test_a_code_block_cut_in_two_is_closed_and_opened_again(self):
        code = "前言\n```python\n" + "\n".join(f"x{n} = {n}  # 注释" for n in range(400)) + "\n```\n后记"
        parts = pages.split(code, room(3000))
        self.assertGreater(len(parts), 1)
        for part in parts:
            self.assertEqual(part.count("```") % 2, 0, part[:60])  # Every part's code block is closed.
        for part in parts[1:-1]:
            self.assertTrue(part.startswith("```python\n"), part[:30])  # And opened again, its language kept.
        lines = [line for part in parts for line in part.split("\n") if line not in ("```", "```python")]
        self.assertEqual(lines, [line for line in code.split("\n") if line not in ("```", "```python")])

    def test_a_table_goes_on_under_its_header(self):
        table = "说明\n\n| 名 | 值 |\n| --- | --- |\n" + "\n".join(f"| {n} | {'值' * 30} |" for n in range(200)) + "\n\n结尾"
        parts = pages.split(table, room(3000))
        self.assertGreater(len(parts), 2)
        for part in parts[1:]:
            self.assertTrue(part.startswith("| 名 | 值 |\n| --- | --- |\n| "), part[:40])
        rows = [line for part in parts for line in part.split("\n") if re.match(r"\| \d+ \|", line)]
        self.assertEqual(len(rows), 200)  # Every row once.

    def test_a_line_too_long_for_a_card_is_cut_after_a_sentence_and_never_inside_a_link(self):
        line = "一句话说完了。" * 1500
        parts = pages.split(line, room(3000))
        self.assertEqual("".join(parts), line)
        self.assertTrue(all(part.endswith("。") for part in parts[:-1]))
        links = " ".join(f"[T{n}](https://applink.feishu.cn/client/thread/open?open_chat_id=oc_x&open_thread_id=omt_{n})"
                         for n in range(10, 210))
        parts = pages.split(links, room(3000))
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), links)
        for part in parts:
            self.assertEqual(part.count("["), part.count("]("), part[:40])  # No link cut in two.

    def test_a_heading_never_ends_a_part(self):
        text = "\n".join(f"### 第{n}节\n" + "很长的一行，" * 150 for n in range(1, 8))
        parts = pages.split(text, room(3000))
        self.assertGreater(len(parts), 2)
        for part in parts:
            self.assertTrue(part.startswith("### 第"), part[:20])
            self.assertFalse(part.split("\n")[-1].startswith("###"), part[-30:])

    def test_a_text_that_fits_is_one_part_as_it_is(self):
        self.assertEqual(pages.split("短\n\n句", room(3000)), ["短\n\n句"])


class PagedTest(unittest.TestCase):
    def draw(self, summary="T1 有结果", tail_elements=()):
        return pages.drawer(summary, row=lambda page: {"tag": "markdown", "element_id": ROW_ID, "content": f"T1 {page}"},
                            element_id=ANSWER_ID, tail=list(tail_elements))

    def test_each_card_fits_a_message_even_of_a_text_escaped_twice(self):
        # Quotes and line breaks take more bytes each time the card's JSON is escaped (Feishu takes 30 KB in all).
        text = '"x": "y",\n' * 6000
        cut = pages.paged(text, self.draw())
        self.assertGreater(len(cut.pages), 2)
        for page in cut.pages:
            self.assertTrue(pages.fits(page.card))
            self.assertLessEqual(json_size(page.card), ANSWER_CARD_BYTES)
            self.assertLessEqual(pages.sent_size(page.card), pages.SENT_BYTES)
        self.assertEqual("\n".join(page.text for page in cut.pages), text.rstrip("\n").rstrip())

    def test_what_follows_goes_under_the_last_card_else_on_its_own(self):
        small = [{"tag": "markdown", "element_id": FACTS_ID, "content": "输入 ｜ 输出"}]
        cut = pages.paged(REPLY, self.draw(tail_elements=small))
        self.assertFalse(cut.alone)
        self.assertEqual(ids(cut.pages[-1].card)[-1], FACTS_ID)
        self.assertTrue(all(FACTS_ID not in ids(page.card) for page in cut.pages[:-1]))
        big = [{"tag": "markdown", "element_id": FACTS_ID, "content": "很大" * 7000}]
        cut = pages.paged(REPLY, self.draw(tail_elements=big))
        self.assertTrue(cut.alone)  # The caller sends it on a card of its own.
        self.assertTrue(all(FACTS_ID not in ids(page.card) for page in cut.pages))
        cut = pages.paged(REPLY, self.draw(tail_elements=small), reserve=True)
        self.assertEqual(ids(cut.pages[-1].card)[-1], FACTS_ID)

    def test_cards_that_grow_once_finished_are_cut_again(self):
        # Links put in after the cut (their other parts' T numbers) take room: a card that no longer fits is cut smaller.
        grow = {"tag": "markdown", "content": ""}

        def finish(built):
            built["body"]["elements"].append({**grow, "content": "链" * 2500})
            return built
        cut = pages.paged(REPLY, self.draw(), finish=finish)
        self.assertTrue(all(pages.fits(page.card) for page in cut.pages))

    def test_the_page_is_in_the_row_and_the_preview_and_a_card_without_a_row_says_it(self):
        cut = pages.paged(REPLY, self.draw())
        total = len(cut.pages)
        for n, page in enumerate(cut.pages, 1):
            self.assertEqual(page.card["body"]["elements"][0]["content"], f"T1 {n}/{total}")
            self.assertEqual(page.card["config"]["summary"]["content"], f"T1 有结果（{n}/{total}）")
        bare = pages.paged(REPLY, pages.drawer("#7 有结果", element_id=ANSWER_ID))
        self.assertEqual(bare.pages[1].card["body"]["elements"][0]["content"],
                         f"<font color='grey'>分 {len(bare.pages)} 张发 · 2/{len(bare.pages)}</font>")


class AnswerPagesTest(unittest.TestCase):
    def test_a_topic_s_answer_in_its_thread_has_its_row_on_each_card_and_its_facts_under_the_last(self):
        facts = tail(FILES, ["Claude Code"], [figure("用时", "1分")])
        cut = pages.answer_pages(REPLY, "T43 有结果 · 先说结论", facts, [topic_head("T43", "改看板", "done")])
        self.assertGreater(len(cut.pages), 1)
        total = len(cut.pages)
        for n, page in enumerate(cut.pages, 1):
            words = row_words(page.card)
            for said in ("T43", "改看板", "有结果", f"{n}/{total}"):
                self.assertIn(said, words)
            self.assertIn("topic-", json.dumps(page.card["config"], ensure_ascii=False))  # The badge's colour.
            self.assertLessEqual(json_size(page.card), ANSWER_CARD_BYTES)
        self.assertEqual(ids(cut.pages[-1].card)[-3:], [ANSWER_ID, ARTIFACTS_ID, FACTS_ID])
        self.assertNotIn("## 结论", body_text(cut, ANSWER_ID))  # Its "## 结论" left out, as on one card.
        self.assertEqual(body_text(cut, ANSWER_ID).count("这一节说的是很长的细节，"), 19 * 120)  # Nothing lost.

    def test_its_t_numbers_are_linked_once_not_again_for_each_card(self):
        # Linking reads Feishu (up to seconds): the answer once before it is cut, its other parts once, together.
        texts, cards = [], []
        block = ask_block("看看 T12", who="T43 改看板", doing="answer", url="https://x/t43", at="12:31")

        def link(words):
            texts.append(words)
            return words.replace("细节", "[细节](https://x/d)")

        def finish(built):
            cards.append(built)
            return built
        cut = pages.answer_pages(REPLY, "s", tail(FILES, ["Claude Code"], []), [block], link=link, finish=finish)
        self.assertGreater(len(cut.pages), 1)
        self.assertEqual((len(texts), len(cards)), (1, 1))
        self.assertEqual([part.get("element_id") for part in cards[0]["body"]["elements"]],
                         [WORDS_ID, ARTIFACTS_ID, FACTS_ID])
        self.assertIn("[细节](https://x/d)", body_text(cut, ANSWER_ID))
        self.assertTrue(all(pages.fits(page.card) for page in cut.pages))

    def test_the_owner_s_words_open_under_the_first_card_of_a_topic_not_the_butler_s(self):
        block = ask_block("把话题里的卡片改一改", who="T43 改看板", doing="answer", url="https://x/t43", at="12:31")
        cut = pages.answer_pages(REPLY, "s", (), [block])
        self.assertEqual(ids(cut.pages[0].card)[:2], [ROW_ID, WORDS_ID])
        self.assertTrue(all(WORDS_ID not in ids(page.card) for page in cut.pages[1:]))
        self.assertIn("https://x/t43", json.dumps(cut.pages[1].card["body"]["elements"][0], ensure_ascii=False))
        butler = ask_block("帮我查一下", who="管家", doing="answer", url="https://x/m", at="09:00")
        cut = pages.answer_pages(REPLY, "s", (), [butler])
        self.assertTrue(all(WORDS_ID not in ids(page.card) for page in cut.pages))  # His row quotes them itself.
        self.assertIn("回你 09:00「帮我查一下」 · 1/", row_words(cut.pages[0].card))


class RelayPagesTest(unittest.TestCase):
    def test_a_long_relay_has_its_row_on_each_card_the_words_on_the_first_and_its_facts_on_the_last(self):
        block = ask_block("把话题里的卡片改一改", who="T43 改看板", doing="done", url="https://x/ask", at="12:31")
        facts = dict(inputs=["Claude Code"], outputs=[figure("用时", "1分")], files=FILES)
        self.assertIsNone(relay_card("T43", DONE, text=REPLY, ask=block, url="https://x/t43", **facts)[0])
        cut = relay_pages("T43", text=REPLY, ask=block, url="https://x/t43", **facts)
        self.assertGreater(len(cut.pages), 1)
        self.assertFalse(cut.alone)
        total = len(cut.pages)
        for n, page in enumerate(cut.pages, 1):
            row = page.card["body"]["elements"][0]
            self.assertEqual(row["element_id"], ROW_ID)
            self.assertEqual(row["behaviors"][0]["default_url"], "https://x/t43")  # The way into the topic, on each.
            for said in ("T43", "改看板", "有结果", f"{n}/{total}"):
                self.assertIn(said, row_words(page.card))
            self.assertTrue(page.card["config"]["update_multi"])
            self.assertTrue(pages.fits(page.card))
        self.assertEqual(ids(cut.pages[0].card)[:3], [ROW_ID, WORDS_ID, FOLD_ID])
        self.assertEqual(ids(cut.pages[-1].card)[-3:], [ARTIFACTS_ID, FACTS_ID, HINT_ID])  # Where a reply goes, last.
        self.assertTrue(all(HINT_ID not in ids(page.card) for page in cut.pages[:-1]))
        self.assertEqual(body_text(cut, FOLD_ID).count("这一节说的是很长的细节，"), 19 * 120)
        self.assertIn("T43 · 有结果：先说结论（1/", cut.pages[0].card["config"]["summary"]["content"])


class StagesOnPagesTest(unittest.TestCase):
    """这一轮中途的汇报 under a reply too large for one card (the owner, 2026-11-25: T732's long relay had them open): never cut
    with the text, folded under the last card, atop the caller's card of the parts, or, too long for one card, on cards
    of their own, each one closed fold."""

    def stages(self, notes):
        from covey.core.trace import with_stage_notes

        return with_stage_notes(REPLY, [(None, text) for text in notes])

    def folds(self, built):
        return [element for element in built["body"]["elements"] if element.get("tag") == "collapsible_panel"
                and "这一轮中途的汇报" in json.dumps(element.get("header"), ensure_ascii=False)]

    def test_a_long_relay_s_reports_fold_under_its_last_card_before_its_parts(self):
        from covey.app.fold_close import has_fold
        from covey.core.trace import STAGE_HEADING

        facts = dict(inputs=["Claude Code"], outputs=[figure("用时", "1分")], files=FILES)
        cut = relay_pages("T43", text=self.stages(["汇报甲" * 200, "汇报乙" * 300]), **facts)
        self.assertFalse(cut.alone)
        self.assertTrue(all(STAGE_HEADING not in page.text and "汇报甲" not in page.text for page in cut.pages))
        last = cut.pages[-1].card
        fold, = self.folds(last)
        self.assertEqual((fold["element_id"], fold["expanded"]), ("relay_reply_s0", False))
        self.assertTrue(has_fold(last))  # Its text closes it (app/fold_close.py).
        self.assertLess(ids(last).index("relay_reply_s0"), ids(last).index(ARTIFACTS_ID))
        self.assertTrue(all(not self.folds(page.card) for page in cut.pages[:-1]))
        self.assertTrue(all(pages.fits(page.card) for page in cut.pages))
        self.assertEqual(body_text(cut, FOLD_ID).count("这一节说的是很长的细节，"), 19 * 120)
        # Parts too large for the last card: the fold goes atop the caller's card of them (app/relay_send.py).
        big = dict(FILES, elements=[{"tag": "markdown", "content": "很" * 5400}])
        cut = relay_pages("T43", text=self.stages(["汇报甲" * 200]), **{**facts, "files": big})
        self.assertTrue(cut.alone)
        self.assertEqual([fold["element_id"] for fold in cut.after], ["relay_reply_s0"])
        self.assertTrue(all(not self.folds(page.card) for page in cut.pages))
        self.assertEqual(relay_pages("T43", text=REPLY, **facts).after, ())  # No reports: nothing atop.

    def test_reports_too_long_for_one_card_go_on_cards_of_their_own_each_one_fold(self):
        facts = dict(inputs=["Claude Code"], outputs=[figure("用时", "1分")], files=FILES)
        notes = [f"第{n}次汇报：" + "进展" * 400 for n in range(1, 41)]
        cut = relay_pages("T43", text=self.stages(notes), **facts)
        total = len(cut.pages)
        reply = [page for page in cut.pages if not self.folds(page.card)]
        reports = cut.pages[len(reply):]
        self.assertGreater(len(reports), 1)
        self.assertTrue(all(len(self.folds(page.card)) == 1 for page in reports))
        self.assertTrue(all(not self.folds(page.card) for page in reply))  # The reply's cards first, the reports after.
        for n, page in enumerate(cut.pages, 1):
            self.assertIn(f"{n}/{total}", row_words(page.card))
            self.assertTrue(pages.fits(page.card))
        words = "".join(json.dumps(self.folds(page.card), ensure_ascii=False) for page in reports)
        self.assertTrue(all(f"第{n}次汇报：" in words for n in range(1, 41)))  # None left out.
        self.assertTrue(all(not self.folds(page.card)[0]["expanded"] for page in reports))
        self.assertEqual(ids(cut.pages[-1].card)[-3:], [ARTIFACTS_ID, FACTS_ID, HINT_ID])  # The parts under the last.
        self.assertFalse(cut.alone)
        self.assertEqual(body_text(cut, FOLD_ID).count("这一节说的是很长的细节，"), 19 * 120)

    def test_a_question_s_long_output_has_its_reports_folded_too(self):
        block = ask_block("问一下要不要部署", who="T44 部署", doing="waiting", url="https://x/t44", at="10:00")
        cut = output_pages(self.stages(["汇报甲" * 200]), "T44", block)
        last = cut.pages[-1].card
        fold, = self.folds(last)
        self.assertEqual((fold["element_id"], fold["expanded"]), (OUTPUT_ID + "_stages", False))
        self.assertNotIn("interactive_container", json.dumps(fold, ensure_ascii=False))  # Not kept: its title closes it.
        self.assertIn(OUTPUT_NEXT, last["body"]["elements"][-1]["content"])
        self.assertTrue(all("汇报甲" not in page.text for page in cut.pages[:-1]))
        cut = output_pages(self.stages([f"第{n}次汇报：" + "进展" * 400 for n in range(1, 41)]), "T44", block)
        total = len(cut.pages)
        self.assertGreater(sum(1 for page in cut.pages if self.folds(page.card)), 1)
        for n, page in enumerate(cut.pages, 1):
            self.assertIn(f"{n}/{total}", row_words(page.card))
            self.assertTrue(pages.fits(page.card))
        self.assertIn(OUTPUT_NEXT, cut.pages[-1].card["body"]["elements"][-1]["content"])
        self.assertEqual(sum(OUTPUT_NEXT in json.dumps(page.card, ensure_ascii=False) for page in cut.pages), 1)

    def test_what_the_last_card_cannot_hold_goes_on_one_of_its_own_numbered_with_them(self):
        draw = pages.drawer("s", tail=[{"tag": "markdown", "content": "尾"}])
        alone = pages.Paged((pages.Page(draw("一", 1, 2, False), "一"), pages.Page(draw("二", 2, 2, False), "二")), True)
        cut = pages.tail_apart(alone, draw, "尾的文字")
        self.assertFalse(cut.alone)
        self.assertEqual([page.text for page in cut.pages], ["一", "二", "尾的文字"])
        self.assertIn("1/3", json.dumps(cut.pages[0].card, ensure_ascii=False))
        self.assertIn("尾", json.dumps(cut.pages[2].card["body"]["elements"], ensure_ascii=False))
        kept = pages.Paged((pages.Page(draw("一", 1, 1, True), "一"),))
        self.assertIs(pages.tail_apart(kept, draw), kept)


class OutputPagesTest(unittest.TestCase):
    def test_a_question_s_long_output_has_the_copy_s_row_and_says_the_question_comes_next(self):
        block = ask_block("问一下要不要部署", who="T44 部署", doing="waiting", url="https://x/t44", at="10:00")
        cut = output_pages(REPLY, "T44", block)
        self.assertGreater(len(cut.pages), 1)
        total = len(cut.pages)
        for n, page in enumerate(cut.pages, 1):
            for said in ("T44", "部署", "等你", f"{n}/{total}"):
                self.assertIn(said, row_words(page.card))
            self.assertTrue(pages.fits(page.card))
        first, last = cut.pages[0].card, cut.pages[-1].card
        self.assertEqual(ids(first)[:3], [ROW_ID, WORDS_ID, OUTPUT_ID])
        self.assertTrue(first["body"]["elements"][2]["content"].startswith("<font color='grey'>这一轮输出</font>"))
        self.assertIn(OUTPUT_NEXT, last["body"]["elements"][-1]["content"])
        self.assertTrue(all(OUTPUT_NEXT not in json.dumps(page.card, ensure_ascii=False) for page in cut.pages[:-1]))
        self.assertEqual(first["config"]["summary"]["content"], f"T44 · 这一轮的输出（1/{total}）")


class TailCardTest(unittest.TestCase):
    def test_after_a_file_the_small_card_has_the_row_and_a_topic_s_line_of_the_owner_s_words(self):
        block = ask_block("把话题里的卡片改一改", who="T43 改看板", doing="done", url="https://x/t43", at="12:31")
        parts = tail(FILES, ["Claude Code"], [figure("用时", "1分")])
        built = tail_card([block, *parts], "T43 · 产物与详情", "回答较长，作为文件发在上面；产物和详情在这里", words=True)
        self.assertEqual(ids(built)[:3], [ROW_ID, WORDS_ID, "markdown"])
        for said in ("T43", "改看板", "有结果"):
            self.assertIn(said, row_words(built))
        self.assertEqual(ids(tail_card([block, *parts], "s", "lead"))[:2], [ROW_ID, "markdown"])  # Words above it.
        butler = ask_block("帮我查一下", who="管家", doing="answer", at="09:00")
        self.assertNotIn(WORDS_ID, ids(tail_card([butler, *parts], "s", "lead", words=True)))
        line = row_words(tail_card([topic_head("T43", "改看板", "waiting_user"), *parts], "s", "lead", words=True))
        self.assertIn("等你", line)


if __name__ == "__main__":
    unittest.main()
