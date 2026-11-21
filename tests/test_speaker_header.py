"""飞书私聊区卡片的第一刀 (docs/ui.md 5.3, docs/cards.md): the card at the private chat's top level says whose it is in its title
bar (cards/ui.py speaker_header), the "你问" block gone from the body and its way back a line at the end; a long relayed reply
folds under its conclusion; a question's copy leads with the question; a draft waiting for the owner is a small card with an
orange 要你确认; the merged relay has a title bar and rows that open their topics."""
from __future__ import annotations

import json
import unittest

from covey.cards.answer_card import ask_block, figure, input_parts, output_parts
from covey.cards.owner_send import BARS, owner_send_card, top_card
from covey.cards.question_cards import mirror_card, settled_lines
from covey.cards.relay_card import (DONE, STOPPED, WAITING, fold_title, foot_line, long_reply, merged_card, relay_card,
                                    size_words)
from covey.cards.review import answer_card
from covey.cards.ui import ASK_META, back_link, speaker_header, split_ask
from test_card_golden import question_record

URL = "https://applink.feishu.cn/client/chat/open?openChatId=oc_x&position=7"
TOPIC_URL = "https://applink.feishu.cn/client/thread/open?open_chat_id=oc_x&open_thread_id=omt_x"


def holders(node, found=None):
    """The dicts of ``node`` that carry ASK_META as a key, at any depth."""
    found = [] if found is None else found
    if isinstance(node, dict):
        if ASK_META in node:
            found.append(node)
        for value in node.values():
            holders(value, found)
    elif isinstance(node, list):
        for value in node:
            holders(value, found)
    return found


def tag(header):
    first = header["text_tag_list"][0]
    return first["text"]["content"], first["color"]


class HeaderTest(unittest.TestCase):
    def meta(self, who, doing, **more):
        return split_ask([ask_block("看板改成彩色块，字大一点，颜色用暖色", at="20:41", url=URL, who=who, doing=doing, **more)])[0]

    def test_the_butler_s_bar_is_indigo_and_quotes_the_first_words(self):
        head = speaker_header(self.meta("管家", "answer"))
        self.assertEqual(("管家", "indigo", "robot_outlined"), (head["title"]["content"], head["template"], head["icon"]["token"]))
        self.assertEqual("回你 20:41「看板改成彩色块，字大一点，颜色用暖色」"[:21], head["subtitle"]["content"][:21])
        self.assertLessEqual(len(head["subtitle"]["content"]), len("回你 20:41「」") + 18)
        self.assertEqual(("答复", "indigo"), tag(head))

    def test_a_lead_s_bar_is_violet_with_a_project_tag_and_says_when_it_asks(self):
        head = speaker_header(self.meta("专项「发布」· 负责人", "answer"))
        self.assertEqual(("violet", "专项「发布」· 负责人"), (head["template"], head["title"]["content"]))
        self.assertEqual(["专项"], [t["text"]["content"] for t in head["text_tag_list"]])
        asking = speaker_header(self.meta("专项「发布」· 负责人", "waiting"))
        self.assertEqual(["专项", "等你"], [t["text"]["content"] for t in asking["text_tag_list"]])
        self.assertEqual("orange", asking["text_tag_list"][1]["color"])

    def test_a_topic_s_bar_is_default_with_its_t_number_first_and_its_state_as_the_tag(self):
        for doing, expected in (("done", ("有结果", "green")), ("waiting", ("等你", "orange")), ("stopped", ("停住了", "red"))):
            head = speaker_header(self.meta("T623 工作台私聊密度", doing))
            self.assertEqual(("default", "T623 工作台私聊密度"), (head["template"], head["title"]["content"]))
            self.assertEqual(expected, tag(head))
        self.assertEqual("做完了你 20:41 交代的事", speaker_header(self.meta("T623 x", "done"))["subtitle"]["content"])

    def test_no_title_bar_is_red_and_only_the_owner_s_turn_is_orange(self):
        for who in ("管家", "专项「发布」· 负责人", "T623 x"):
            for doing in ("answer", "done", "waiting", "stopped", "about", "member"):
                head = speaker_header(self.meta(who, doing))
                self.assertIn(head["template"], ("indigo", "violet", "default"))
                for found in head["text_tag_list"]:
                    if found["color"] == "orange":
                        self.assertEqual("等你", found["text"]["content"])

    def test_the_block_keeps_its_look_where_a_card_keeps_it_and_leaves_the_body_where_it_goes_to_the_bar(self):
        block = ask_block("看板改成彩色块", at="20:41", url=URL, who="管家")
        self.assertEqual(URL, block["behaviors"][0]["default_url"])  # Still the grey block, whole of it opening the message.
        self.assertEqual("管家", block[ASK_META]["who"])
        self.assertNotIn(ASK_META, ask_block("看板改成彩色块", url=URL, who="管家", meta=False))
        self.assertNotIn(ASK_META, ask_block("没有说话人", url=URL))  # No title bar to say it: the block stays one.
        meta, rest = split_ask([block, {"tag": "hr"}])
        self.assertEqual((URL, [{"tag": "hr"}]), (meta["url"], rest))
        legacy = {key: value for key, value in block.items() if key != ASK_META}  # A block sent before the title bar.
        self.assertEqual((None, [legacy]), split_ask([legacy]))
        self.assertEqual(f"[看你那句 ›]({URL})", back_link(meta))
        self.assertEqual("", back_link({}))

    def test_an_answer_card_takes_the_block_into_its_bar_and_keeps_the_way_back(self):
        block = ask_block("看板改成彩色块", at="20:41", url=URL, who="管家", doing="answer")
        built = answer_card("好了", "管家 · 好了", head=[block])
        self.assertEqual("管家", built["header"]["title"]["content"])
        body = built["body"]["elements"]
        self.assertEqual(["markdown", "markdown"], [element["tag"] for element in body])  # No grey block: not taller.
        self.assertIn(f"[看你那句 ›]({URL})", body[-1]["content"])
        self.assertEqual([], holders(built))
        quiet = answer_card("好了", "s", head=[ask_block("看板改成彩色块", who="管家")])  # No link: nothing to link back.
        self.assertEqual(1, len(quiet["body"]["elements"]))


class RelayTest(unittest.TestCase):
    asked = staticmethod(lambda doing="done": ask_block("发布的事", at="20:33", url=URL, who="T623 密度", doing=doing))

    def test_a_short_reply_stays_open_and_a_long_one_or_a_table_folds_under_its_conclusion(self):
        self.assertFalse(long_reply("一行\n两行\n" * 3))
        self.assertTrue(long_reply("行\n" * 7))
        self.assertTrue(long_reply("字" * 181))
        self.assertTrue(long_reply("| a | b |\n| --- | --- |\n| 1 | 2 |"))
        short, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n细节：改了两处。", ask=self.asked())
        # The band, the reply as it is, and the small line with the way back; no fold.
        self.assertEqual(["interactive_container", "markdown", "markdown"],
                         [element["tag"] for element in short["body"]["elements"]])
        long, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n" + "细节很多。" * 60, ask=self.asked())
        band, fold, _ = long["body"]["elements"]
        self.assertEqual(("collapsible_panel", False), (fold["tag"], fold["expanded"]))
        self.assertIn("好了", json.dumps(band, ensure_ascii=False))  # The conclusion stays outside the fold.
        self.assertNotIn("好了", json.dumps(fold["elements"], ensure_ascii=False).replace("好了。", ""))

    def test_the_fold_says_how_much_is_in_it(self):
        table = "| 项 | 结果 |\n| --- | --- |\n| 单测 | 通过 |"
        self.assertEqual("完整回答 · 约 270 字（点开看）", fold_title("字" * 268))
        self.assertEqual("约 1800 字 · 含 1 张表", size_words("字" * 1783 + "\n" + table))  # 1783 and the table's own.
        self.assertIn("含 2 张表", size_words(table + "\n\n" + table))

    def test_the_change_goes_into_the_fold_of_a_long_reply_and_one_line_of_it_stays_on_the_small_line(self):
        change = {"commit": "a6bc148d38ce", "deployed": "第 322 代", "verified": "全量通过",
                  "not_found": ["a6bc148d38ce"]}
        built, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n" + "细节很多。" * 60, change=change,
                              inputs=input_parts("Claude Code", "x", "Opus 5.5"), outputs=[figure("用时", "1分")],
                              url=TOPIC_URL, ask=self.asked())
        text = json.dumps(built["body"], ensure_ascii=False)
        ids = [element.get("element_id") for element in built["body"]["elements"]]
        self.assertNotIn("answer_change", ids)  # No second fold inside or beside it.
        self.assertIn("answer_change_check", ids)  # A commit the repository does not have stays in view.
        self.assertIn("a6bc148d38ce", json.dumps(built["body"]["elements"][1], ensure_ascii=False))  # Inside the fold.
        foot = built["body"]["elements"][-1]
        self.assertEqual("relay_foot", foot["element_id"])
        for words in ("用", "改动 · a6bc148", "看你那句 ›", f"[进话题 ›]({TOPIC_URL})"):
            self.assertIn(words, foot["content"])
        self.assertNotIn("answer_facts", text)

    def test_the_small_line_keeps_the_key_figures_and_none_without_any(self):
        parts = output_parts({"input_tokens": 750_000, "output_tokens": 10_000, "cache_read_tokens": 690_000,
                              "measured_output_tokens": 8_200, "generation_seconds": 200}, 760)
        line = foot_line(input_parts("Claude Code", "Claude 自带", "Opus 5.5", "xhigh", True, "w"), parts)["content"]
        self.assertIn("token", line)
        self.assertIn("用", line)
        self.assertNotIn("缓存", line)  # Not every figure: 用时, token, the model.
        self.assertNotIn("token/s", line)
        self.assertIsNone(foot_line(None, ()))

    def test_a_waiting_and_a_stopped_relay_have_the_bar_too(self):
        built, _ = relay_card("T623", WAITING, question="选 A 还是 B？", ask=self.asked("waiting"))
        self.assertEqual(("等你", "orange"), tag(built["header"]))
        self.assertIn("看你那句 ›", built["body"]["elements"][-1]["content"])
        stopped, _ = relay_card("T623", STOPPED, reason="到了时间上限")
        self.assertEqual(("T623", ("停住了", "red")), (stopped["header"]["title"]["content"], tag(stopped["header"])))
        self.assertNotIn("subtitle", stopped["header"])  # No block, no words to say under it.


class MergedTest(unittest.TestCase):
    def test_the_merged_card_has_a_bar_and_each_row_opens_its_topic(self):
        built, text = merged_card([{"label": "T1", "title": "改看板", "lead": "好了", "url": TOPIC_URL},
                                   {"label": "T2", "title": "", "lead": "", "url": ""}])
        self.assertEqual(("2 个话题做完了", ("有结果", "green")), (built["header"]["title"]["content"], tag(built["header"])))
        first, second = built["body"]["elements"]
        self.assertEqual("interactive_container", first["tag"])
        self.assertEqual({"type": "open_url", "default_url": TOPIC_URL}, first["behaviors"][0])
        self.assertNotIn("behaviors", second)
        self.assertTrue(text.startswith("**2 个话题做完了**"))


class QuestionCopyTest(unittest.TestCase):
    ask = staticmethod(lambda: ask_block("选哪种样式", at="09:12", url=URL, who="T439 改看板", doing="waiting"))

    def test_the_question_leads_and_the_output_is_folded_under_it_with_its_size(self):
        built = mirror_card(question_record(), "T439", "上一轮写了很长很长的输出" * 30, ask=self.ask())
        ids = [element.get("element_id") for element in built["body"]["elements"]]
        self.assertTrue(ids[1].startswith("q_"))  # The band first, then the form.
        self.assertEqual("mirror_output", ids[2])
        fold = built["body"]["elements"][2]
        self.assertIn("T439 这一轮的输出 · 约", fold["header"]["title"]["content"])
        self.assertEqual(("等你", "orange"), tag(built["header"]))
        self.assertIn(f"[看你那句 ›]({URL})", built["body"]["elements"][-1]["content"])
        self.assertNotIn("answer_ask", ids[:-1])

    def test_an_answered_copy_keeps_the_question_and_what_he_chose_in_two_lines(self):
        answered = question_record("answered", continuation_job_id=5, delivery_state="running")
        lines = settled_lines(answered)
        self.assertEqual(2, len(lines))
        self.assertIn("2 道题", lines[0]["content"])
        self.assertIn("你选了「表格 / 无」", lines[1]["content"])
        built = mirror_card(answered, "T439", "输出", ask=self.ask())
        self.assertEqual(("已回答", "grey"), tag(built["header"]))
        self.assertEqual("关于你 09:12 的问题", built["header"]["subtitle"]["content"])  # No longer "要你定".
        self.assertIn("你选了「", json.dumps(built["body"]["elements"][:3], ensure_ascii=False))
        self.assertIn("已取消", settled_lines(question_record("cancelled"))[1]["content"])
        for status in ("pending", "superseded"):
            self.assertIsNone(settled_lines(question_record(status)))
        self.assertIn("你提了反馈", settled_lines(question_record("answered", response_kind="feedback"))[1]["content"])

    def test_a_block_sent_before_the_bar_stays_at_the_top_as_it_was(self):
        legacy = {key: value for key, value in self.ask().items() if key != ASK_META}
        built = mirror_card(question_record(), "T439", "输出", ask=legacy)
        self.assertEqual("answer_ask", built["body"]["elements"][0]["element_id"])
        self.assertNotIn("header", built)


class OwnerSendTest(unittest.TestCase):
    draft = {"id": "d" * 32, "status": "drafted", "topic_label": "T9", "why": "交 key", "text": "key 开好了",
             "recipient": {"name": "张三", "kind": "p2p"}}

    def test_the_draft_waiting_for_the_owner_is_a_small_card_with_an_orange_confirm_tag(self):
        built = top_card("T9", "张三", TOPIC_URL)
        self.assertEqual(("T9 代发草稿", ("要你确认", "orange")), (built["header"]["title"]["content"], tag(built["header"])))
        self.assertIn("张三", built["header"]["subtitle"]["content"])
        self.assertIn(f"[到话题里看 ›]({TOPIC_URL})", built["body"]["elements"][0]["content"])
        self.assertEqual(1, len(top_card("", "", "")["body"]["elements"]))  # No link: still a card, saying where.

    def test_the_card_in_the_topic_says_its_state_in_the_bar_and_the_form_is_unchanged(self):
        built = owner_send_card(self.draft, {"state": "drafted"})
        self.assertEqual(("代发草稿", ("要你确认", "orange")), (built["header"]["title"]["content"], tag(built["header"])))
        self.assertNotIn("**✉️ 代发草稿", json.dumps(built, ensure_ascii=False))  # The heading is the bar.
        self.assertTrue(any(element.get("tag") == "form" for element in built["body"]["elements"]))
        for state, (_, words, color) in BARS.items():
            drawn = owner_send_card({**self.draft, "status": state, "sent_at_text": "18:59"}, {"state": state})
            self.assertEqual((words, color), tag(drawn["header"]))
            self.assertEqual("orange" if words == "要你确认" else drawn["header"]["text_tag_list"][0]["color"], tag(drawn["header"])[1])


class LinkedTest(unittest.TestCase):
    def test_a_t_number_inside_the_reply_s_fold_is_a_link_and_the_artifacts_panel_is_left_alone(self):
        from unittest import mock

        from covey.app.relay_send import linked
        from covey.cards.answer_card import ARTIFACTS_ID
        from covey.cards.elements import markdown_panel

        files = markdown_panel(ARTIFACTS_ID, "产物", "- T7.md", quiet=True)
        built, _ = relay_card("T9", DONE, text="## 结论\n好了\n\n" + "细节见 T7。" * 40, files=files)
        with mock.patch("covey.app.topic_links.linkify", side_effect=lambda text, *a, **k: text.replace("T7", "[T7](u)")):
            built, _ = linked("/state", "oc_x", built, "")
        text = json.dumps(built["body"]["elements"][1], ensure_ascii=False)
        self.assertIn("[T7](u)", text)
        self.assertNotIn("[T7](u)", json.dumps(built["body"]["elements"][2], ensure_ascii=False))


class NoLeakTest(unittest.TestCase):
    def test_no_card_sample_sends_the_block_s_notes(self):
        """ASK_META is for the card that takes the block into its bar: it is stripped there and never sent (CardKit
        refuses properties it does not know)."""
        from test_card_golden import render

        sent = {name: card for name, card in json.loads(json.dumps(render(), ensure_ascii=False)).items()
                if not name.startswith(("task.ask_speaker", "task.ask_"))}
        leaked = [name for name, card in sent.items() if holders(card)]
        self.assertEqual([], leaked)


if __name__ == "__main__":
    unittest.main()
