"""露一截 (T638, docs/ui.md 4 ``peek``): a long text on a private-chat card shows its opening, the rest a click away and
going on from there (cards/review.py opening, cards/ui.py peek); a topic's badge carries its T number on the topic's own
colour (cards/ui.py topic_badge, core/look.py topic_color)."""
from __future__ import annotations

import unittest

from covey.cards.review import PEEK_LINES, PEEK_WIDTH, drop_part_heading, fits, opening
from covey.cards.ui import badge_colors, peek, read_more, split_number, topic_badge
from covey.core import look


def width(text):
    return sum(2 if ord(char) > 0x2e7f else 1 for char in text)


class OpeningTest(unittest.TestCase):
    def test_a_short_text_is_all_opening(self):
        self.assertEqual(("短短一句。", ""), opening("短短一句。"))
        self.assertEqual(("", ""), opening(""))

    def test_a_heading_that_only_names_a_part_is_left_out_and_the_rest_stays_as_written(self):
        head, rest = opening("## 结论\n看板的颜色还没换成：深色那套还没有。\n\n## 原因\n1. 对比度不够。")
        self.assertEqual(("看板的颜色还没换成：深色那套还没有。\n\n## 原因\n1. 对比度不够。", ""), (head, rest))
        self.assertEqual(("## 卡片改版\n已经改好了。\n\n- a\n- b", ""), opening("## 卡片改版\n已经改好了。\n\n- a\n- b"))
        self.assertEqual("好了", drop_part_heading("**总结**\n好了"))
        self.assertEqual("## 结论", drop_part_heading("## 结论"))  # Nothing after it: kept.

    def test_a_long_line_is_cut_at_a_sentence_end_and_the_rest_goes_on_from_there(self):
        text = "第一句话说清楚了结论，后面跟着理由。" * 3 + "第四句。" * 20
        head, rest = opening(text)
        self.assertTrue(head.endswith("。"))
        self.assertLessEqual(width(head), PEEK_WIDTH)
        self.assertEqual(text, head + rest)  # Nothing lost, nothing twice.

    def test_without_a_sentence_end_the_cut_is_at_a_pause_then_anywhere_with_an_ellipsis(self):
        text = "按新办法重排，每页把三组草图和参考图放在一起，先看每张草图的配色对不对，再看各组之间是否一致，最后写进文件，" * 12
        head, rest = opening(text)
        self.assertTrue(head.endswith("…"))
        self.assertEqual(text, head[:-1] + "，" + rest)  # The pause went for the "…".
        head, rest = opening("字" * (PEEK_WIDTH // 2 + 200))
        self.assertEqual(("字" * (PEEK_WIDTH // 2) + "…", "字" * 200), (head, rest))

    def test_a_cut_never_falls_inside_bold_code_or_a_link(self):
        text = ("前面先写一些铺垫的话把宽度用掉一些再说，" * 2 + "**这一段是加粗的重点内容不能切开**" + "，后面还有很多字"
                + "，`code_that_must_stay_whole_xx`" + "，[链接文字](https://example.invalid/a)" * 3)
        head, rest = opening(text)
        for part in (head, rest):
            self.assertEqual(0, part.count("**") % 2, part)
            self.assertEqual(0, part.count("`") % 2, part)
            self.assertEqual(part.count("["), part.count("]("), part)

    def test_tables_code_and_rules_end_the_opening_and_a_text_that_starts_with_one_has_none(self):
        self.assertEqual(("改好了。", "| a | b |\n| --- | --- |\n| 1 | 2 |"), opening("改好了。\n| a | b |\n| --- | --- |\n| 1 | 2 |"))
        self.assertEqual(("改好了。", "```\nx\n```"), opening("改好了。\n```\nx\n```"))
        self.assertEqual(("", "| a |\n| --- |"), opening("| a |\n| --- |"))

    def test_at_most_a_few_lines_and_a_numbered_list_is_not_split_after_words(self):
        head, rest = opening("改好了：\n" + "\n".join(f"- 第 {n} 项" for n in range(20)))
        self.assertEqual(PEEK_LINES, len(head.split("\n")))
        self.assertTrue(rest.startswith(f"- 第 {PEEK_LINES - 1} 项"))
        head, rest = opening("改好了，已合进 main。\n\n" + "\n".join(f"{n}. 卡片 {n} 改好了" for n in range(1, 21)))
        self.assertEqual("改好了，已合进 main。", head)  # Not "1. … 2. …" with the rest starting at "3.".
        self.assertTrue(rest.startswith("1. 卡片 1"))

    def test_a_short_opening_goes_on_past_a_blank_line_its_paragraphs_kept_apart(self):
        head, rest = opening("先说结论。\n\n第二段继续说，" + "细节。" * 200)
        self.assertTrue(head.startswith("先说结论。\n\n第二段继续说，"))
        self.assertTrue(rest.startswith("细节。"))
        self.assertEqual(("先说结论，后面有一个列表要看。\n\n- a\n- b", ""), opening("先说结论，后面有一个列表要看。\n\n- a\n- b"))


class PeekTest(unittest.TestCase):
    def test_the_fold_s_title_is_the_opening_and_its_body_the_rest_without_a_frame(self):
        built = peek("relay_reply", "开头两行", "后面的内容", hint="全文约 300 字", label="这一轮输出")
        self.assertEqual(("collapsible_panel", "relay_reply", False), (built["tag"], built["element_id"], built["expanded"]))
        self.assertEqual("<font color='grey'>这一轮输出</font> 开头两行 <font color='grey'>全文约 300 字</font>",
                         built["header"]["title"]["content"])
        self.assertEqual("markdown", built["header"]["title"]["tag"])
        self.assertEqual("right", built["header"]["icon_position"])
        self.assertNotIn("border", built)
        self.assertEqual([{"tag": "markdown", "content": "后面的内容"}], built["elements"])
        self.assertEqual([{"tag": "hr"}], peek("x", "头", [{"tag": "hr"}])["elements"])  # Elements as they are.


class ReadMoreTest(unittest.TestCase):
    def test_the_opening_is_card_text_and_the_fold_under_it_goes_on(self):
        opened, fold = read_more("relay_reply", "- 第一项\n- 第二项", "后面的内容", hint="展开全文 · 还有约 900 字",
                                 label="这一轮输出")
        self.assertEqual(("markdown", "relay_reply_open"), (opened["tag"], opened["element_id"]))
        self.assertEqual("<font color='grey'>这一轮输出</font>\n- 第一项\n- 第二项", opened["content"])  # A list stays one.
        self.assertEqual(("collapsible_panel", "relay_reply", False), (fold["tag"], fold["element_id"], fold["expanded"]))
        self.assertEqual("<font color='blue'>**展开全文 · 还有约 900 字**</font>", fold["header"]["title"]["content"])
        self.assertEqual([{"tag": "markdown", "content": "后面的内容"}], fold["elements"])
        self.assertEqual("bottom", fold["header"]["position"])  # Opened, the rest follows the opening as one text.
        self.assertNotIn("border", fold)
        self.assertTrue(fits("短短一句。\n\n| a | b |\n| --- | --- |\n| 1 | 2 |"))  # A short reply with a table: whole.
        self.assertFalse(fits("字" * (PEEK_WIDTH // 2 + 1)))


class BadgeTest(unittest.TestCase):
    def test_the_number_picks_the_colour_and_neighbours_differ(self):
        self.assertEqual(12, len(look.TOPIC_COLORS))
        self.assertEqual(437 * 5 % 12, look.topic_color("T437"))
        self.assertEqual(look.topic_color("T437"), look.topic_color(437))
        self.assertEqual(-1, look.topic_color("话题"))
        for start in (1, 99, 1000, 12340):
            places = [look.topic_color(f"T{n}") for n in range(start, start + 12)]
            self.assertEqual(12, len(set(places)))  # Twelve in a row: every colour once.

    def test_every_colour_reads_white_words_at_aa_contrast(self):
        def luminance(color):
            channels = [int(color[n:n + 2], 16) / 255 for n in (1, 3, 5)]
            linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
            return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]
        for color in look.TOPIC_COLORS:
            self.assertGreaterEqual(1.05 / (luminance(color) + 0.05), 4.5, color)

    def test_the_badge_is_its_number_in_white_on_its_colour_and_the_card_gets_that_colour(self):
        for label in ("T7", "T1234", "T12345"):
            badge = topic_badge(label)
            self.assertEqual(f"<font color='white'>**{label}**</font>", badge["elements"][0]["content"])
            self.assertEqual(("auto", "28px"), (badge["width"], badge["height"]))
            self.assertNotIn("behaviors", badge)
        self.assertIsNone(topic_badge(""))
        self.assertEqual("https://x", topic_badge("T7", url="https://x")["behaviors"][0]["default_url"])
        colors = badge_colors({"elements": [topic_badge("T1"), {"tag": "column_set", "columns": [
            {"tag": "column", "elements": [topic_badge("T13"), topic_badge("T2")]}]}]})
        self.assertEqual({"topic-5", "topic-10"}, set(colors))  # T1 and T13 share one: 5 and 65 mod 12.
        self.assertEqual({"light_mode": "rgba(15,118,110,1)", "dark_mode": "rgba(15,118,110,1)"}, colors["topic-5"])
        self.assertEqual({}, badge_colors({"tag": "column", "background_style": "topic-3"}))  # Only a badge's.

    def test_a_speaker_s_words_split_into_number_and_title(self):
        self.assertEqual(("T437", "统一 卡片配色"), split_number("T437  统一 卡片配色"))
        self.assertEqual(("T7", ""), split_number("T7"))
        self.assertEqual(("", "管家"), split_number("管家"))
        self.assertEqual(("", "3 个话题做完了"), split_number("3 个话题做完了"))


if __name__ == "__main__":
    unittest.main()
