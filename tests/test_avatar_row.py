"""飞书私聊区卡片的头像行 (docs/ui.md 5.3, docs/cards.md): the card at the private chat's top level opens with a row, the speaker's
picture, its name bold and what it did with the owner's words grey (cards/ui.py speaker_row), no coloured title bar; the "你问"
block is gone from the body and its way back is on the 输出 line; 输入 and 输出 are two small lines, none of their parts
left out; a long relayed reply folds under its conclusion; a question's copy leads with the question; a draft waiting for
the owner is a small card with an orange 要你确认; the merged relay has a row and rows that open their topics. The avatars
(core/avatars.py, feishu/avatars.py): a lead's picture is stable and not shared, an upload that fails leaves the card
without its picture."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from covey.cards.answer_card import ask_block, facts_element, figure, input_parts, put_back, tail, tail_card
from covey.cards.owner_send import BARS, owner_send_card, top_card
from covey.cards.question_cards import mirror_card, settled_lines
from covey.cards.relay_card import DONE, STOPPED, WAITING, fold_title, foot, long_reply, merged_card, relay_card, size_words
from covey.cards.review import answer_card
from covey.cards.ui import ASK_META, back_link, speaker_row, split_ask
from covey.core import avatars
from covey.feishu import avatars as uploads
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


def text_of(row):
    """The line of a speaker's row: the markdown of its second column, or the row itself without a picture."""
    return row["columns"][1]["elements"][0]["content"] if row["tag"] == "column_set" else row["content"]


def tag(row):
    """(word, colour) of the row's first state tag, None without one."""
    import re

    found = re.search(r"<text_tag color='(\w+)'>(.*?)</text_tag>", text_of(row))
    return (found.group(2), found.group(1)) if found else None


def first(built):
    return built["body"]["elements"][0]


class RowTest(unittest.TestCase):
    def meta(self, who, doing, **more):
        return split_ask([ask_block("看板改成彩色块，字大一点，颜色用暖色，再把图例挪到右边去", at="20:41", url=URL, who=who, doing=doing, **more)])[0]

    def test_the_butler_s_row_is_its_picture_its_name_and_the_first_words_of_the_message(self):
        row = speaker_row(self.meta("管家", "answer", avatar="img_butler"))
        self.assertEqual("column_set", row["tag"])
        picture, line = row["columns"]
        self.assertEqual(("auto", "img", "img_butler", "28px 28px", "crop_center"),
                         (picture["width"], picture["elements"][0]["tag"], picture["elements"][0]["img_key"],
                          picture["elements"][0]["size"], picture["elements"][0]["scale_type"]))
        content = text_of(row)
        self.assertTrue(content.startswith("**管家** <font color='grey'>回你 20:41「"))
        self.assertIn("「看板改成彩色块，字大一点", content)
        self.assertNotIn("图例", content)  # Only the first 18 characters, then "…".
        self.assertTrue(content.endswith("…」</font>"))
        self.assertIsNone(tag(row))  # The butler's answer has no state to tag.

    def test_a_lead_s_row_names_its_project_and_asks_with_an_orange_tag(self):
        row = speaker_row(self.meta("专项「发布」· 负责人", "answer", avatar="img_g1"))
        self.assertTrue(text_of(row).startswith("**发布 · 负责人** <font color='grey'>回你 20:41「"))
        self.assertIsNone(tag(row))
        self.assertTrue(text_of(speaker_row(self.meta("专项「发布」· 负责人", "done"))).startswith(
            "**发布 · 负责人** <font color='grey'>汇报你 20:41 交代的事"))
        self.assertEqual(("等你", "orange"), tag(speaker_row(self.meta("专项「发布」· 负责人", "waiting"))))

    def test_a_topic_s_row_has_its_t_number_first_and_its_state_as_the_tag(self):
        for doing, expected in (("done", ("有结果", "green")), ("waiting", ("等你", "orange")), ("stopped", ("停住了", "red"))):
            row = speaker_row(self.meta("T623 工作台私聊密度", doing, avatar="img_topic"))
            self.assertEqual(expected, tag(row))
            self.assertTrue(text_of(row).startswith("**T623 工作台私聊密度** <text_tag"))
        self.assertTrue(text_of(speaker_row(self.meta("T623 x", "done"))).endswith("做完了你 20:41 交代的事</font>"))

    def test_without_a_picture_the_row_is_its_line_alone_and_a_given_one_wins_over_the_block_s(self):
        row = speaker_row(self.meta("管家", "answer"))
        self.assertEqual("markdown", row["tag"])
        self.assertEqual("img_b", speaker_row(self.meta("管家", "answer", avatar="img_a"), avatar="img_b")["columns"][0]
                         ["elements"][0]["img_key"])
        label = speaker_row(None, outcome="stopped", label="T623")  # No block: the T number and the state.
        self.assertEqual((("停住了", "red")), tag(label))
        self.assertTrue(text_of(label).startswith("**T623** <text_tag"))

    def test_no_row_is_red_and_only_the_owner_s_turn_is_orange(self):
        for who in ("管家", "专项「发布」· 负责人", "T623 x"):
            for doing in ("answer", "done", "waiting", "stopped", "about", "member"):
                found = tag(speaker_row(self.meta(who, doing)))
                if found and found[1] == "orange":
                    self.assertEqual("等你", found[0])

    def test_the_block_keeps_its_look_where_a_card_keeps_it_and_carries_what_the_row_says(self):
        block = ask_block("看板改成彩色块", at="20:41", url=URL, who="管家", avatar="img_b")
        self.assertEqual(URL, block["behaviors"][0]["default_url"])  # Still the grey block, whole of it opening the message.
        self.assertEqual(("管家", "img_b"), (block[ASK_META]["who"], block[ASK_META]["avatar"]))
        self.assertNotIn("avatar", ask_block("看板改成彩色块", url=URL, who="管家")[ASK_META])
        self.assertNotIn(ASK_META, ask_block("看板改成彩色块", url=URL, who="管家", meta=False))
        self.assertNotIn(ASK_META, ask_block("没有说话人", url=URL))  # No row to say it: the block stays one.
        meta, rest = split_ask([block, {"tag": "hr"}])
        self.assertEqual((URL, [{"tag": "hr"}]), (meta["url"], rest))
        legacy = {key: value for key, value in block.items() if key != ASK_META}  # A block sent before the row.
        self.assertEqual((None, [legacy]), split_ask([legacy]))
        self.assertEqual(f"[看你那句 ›]({URL})", back_link(meta))
        self.assertEqual("", back_link({}))

    def test_an_answer_card_takes_the_block_into_its_row_and_puts_the_way_back_on_the_output_line(self):
        block = ask_block("看板改成彩色块", at="20:41", url=URL, who="管家", doing="answer", avatar="img_b")
        facts = facts_element(input_parts("Claude Code", "Claude 自带", "Opus 5.5", "xhigh", False, "covey"),
                              [figure("用时", "12分40秒")], link="T9")
        built = answer_card("好了", "管家 · 好了", tail=[facts], head=[block])
        self.assertNotIn("header", built)
        self.assertEqual(("6px", "10px 12px 10px 12px"), (built["body"]["vertical_spacing"], built["body"]["padding"]))
        body = built["body"]["elements"]
        self.assertEqual(["column_set", "markdown", "markdown"], [element["tag"] for element in body])  # No grey block.
        out = [line for line in body[-1]["content"].split("\n") if "输出" in line][0]
        self.assertTrue(out.endswith(f"[看你那句 ›]({URL})"))
        self.assertEqual([], holders(built))
        quiet = answer_card("好了", "s", head=[ask_block("看板改成彩色块", who="管家")])  # No link: nothing to link back.
        self.assertEqual(2, len(quiet["body"]["elements"]))
        self.assertEqual("markdown", quiet["body"]["elements"][0]["tag"])  # The row without a picture.

    def test_a_card_without_facts_keeps_the_way_back_as_a_line_of_its_own(self):
        meta = self.meta("管家", "answer")
        rest = put_back([{"tag": "markdown", "content": "好了"}], meta)
        self.assertEqual(f"[看你那句 ›]({URL})", rest[-1]["content"])
        self.assertEqual([{"tag": "markdown", "content": "好了"}], put_back([{"tag": "markdown", "content": "好了"}], {}))

    def test_a_tail_card_after_a_long_answer_has_the_row_too(self):
        block = ask_block("看板改成彩色块", at="20:41", url=URL, who="管家", avatar="img_b")
        built = tail_card([block, *tail(None, ["Claude Code"], [figure("用时", "1分")])], "s", "上面是回答")
        self.assertEqual("column_set", first(built)["tag"])
        self.assertNotIn("header", built)


class FactsTest(unittest.TestCase):
    parts = input_parts("Claude Code", "Claude 自带", "Opus 5.5", "xhigh", False, "covey")
    out = [figure("用时", "12分40秒"), "**41** <font color='grey'>token/s</font>", figure("token", "76万"),
           figure("缓存命中", "92%")]

    def test_the_two_lines_keep_every_part_and_the_box_is_gone(self):
        element = facts_element(self.parts, self.out)
        self.assertEqual(("markdown", "notation", "answer_facts"), (element["tag"], element["text_size"], element["element_id"]))
        lines = element["content"].split("\n")
        self.assertEqual(2, len(lines))
        self.assertTrue(lines[0].startswith("<font color='grey'>输入</font> "))
        self.assertTrue(lines[1].startswith("<font color='grey'>输出</font> "))
        plain = element["content"].replace(" ", " ").replace("⁠", "")
        for words in ("Claude Code", "Claude 自带", "Opus 5.5", "思考 xhigh", "脱敏关", "covey", "用时", "12分40秒", "41", "token/s",
                      "76万", "缓存命中", "92%"):
            self.assertIn(words, plain)
        self.assertNotIn("background", json.dumps(element))

    def test_the_change_is_a_third_line_and_the_links_end_the_output_line(self):
        element = facts_element(self.parts, self.out, change={"commit": "a6bc148d38ce", "deployed": "第 322 代",
                                                              "verified": "全量通过"}, links=("[进话题 ›](u)", "[看你那句 ›](v)"))
        lines = element["content"].split("\n")
        self.assertEqual(3, len(lines))
        plain = lines[2].replace(" ", " ").replace("⁠", "")
        for words in ("改动", "a6bc148", "第 322 代", "已自检"):
            self.assertIn(words, plain)
        self.assertTrue(lines[1].endswith("[进话题 ›](u)" + " <font color='grey'>｜</font> [看你那句 ›](v)"))

    def test_nothing_to_say_is_no_element(self):
        self.assertIsNone(facts_element())
        self.assertEqual(1, len(facts_element(self.parts, ())["content"].split("\n")))


class RelayTest(unittest.TestCase):
    asked = staticmethod(lambda doing="done": ask_block("发布的事", at="20:33", url=URL, who="T623 密度", doing=doing,
                                                        avatar="img_topic"))

    def test_a_short_reply_stays_open_and_a_long_one_or_a_table_folds_under_its_conclusion(self):
        self.assertFalse(long_reply("一行\n两行\n" * 3))
        self.assertTrue(long_reply("行\n" * 7))
        self.assertTrue(long_reply("字" * 181))
        self.assertTrue(long_reply("| a | b |\n| --- | --- |\n| 1 | 2 |"))
        short, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n细节：改了两处。", ask=self.asked())
        # The row, the band, the reply as it is, and the line with the way back; no fold.
        self.assertEqual(["column_set", "interactive_container", "markdown", "markdown"],
                         [element["tag"] for element in short["body"]["elements"]])
        long, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n" + "细节很多。" * 60, ask=self.asked())
        _, band, fold, _ = long["body"]["elements"]
        self.assertEqual(("collapsible_panel", False), (fold["tag"], fold["expanded"]))
        self.assertIn("好了", json.dumps(band, ensure_ascii=False))  # The conclusion stays outside the fold.
        self.assertNotIn("好了", json.dumps(fold["elements"], ensure_ascii=False).replace("好了。", ""))

    def test_the_fold_says_how_much_is_in_it(self):
        table = "| 项 | 结果 |\n| --- | --- |\n| 单测 | 通过 |"
        self.assertEqual("完整回答 · 约 270 字（点开看）", fold_title("字" * 268))
        self.assertEqual("约 1800 字 · 含 1 张表", size_words("字" * 1783 + "\n" + table))  # 1783 and the table's own.
        self.assertIn("含 2 张表", size_words(table + "\n\n" + table))

    def test_the_foot_has_the_whole_input_and_output_the_change_line_and_the_links(self):
        change = {"commit": "a6bc148d38ce", "deployed": "第 322 代", "verified": "全量通过", "not_found": ["a6bc148d38ce"]}
        parts = input_parts("Claude Code", "Claude 自带", "Opus 5.5", "xhigh", False, "covey")
        built, _ = relay_card("T623", DONE, text="## 结论\n好了\n\n" + "细节很多。" * 60, change=change, inputs=parts,
                              outputs=[figure("用时", "1分"), figure("token", "76万"), figure("缓存命中", "92%")],
                              url=TOPIC_URL, ask=self.asked())
        ids = [element.get("element_id") for element in built["body"]["elements"]]
        self.assertNotIn("answer_change", ids)  # No fold: the change is a line.
        self.assertIn("answer_change_check", ids)  # A commit the repository does not have stays in view.
        self.assertNotIn("a6bc148d38ce", json.dumps(built["body"]["elements"][2], ensure_ascii=False))  # Not in the reply's fold.
        facts = built["body"]["elements"][-1]
        self.assertEqual("answer_facts", facts["element_id"])
        plain = facts["content"].replace(" ", " ").replace("⁠", "")
        for words in ("输入", "Claude Code", "Claude 自带", "Opus 5.5", "思考 xhigh", "脱敏关", "covey", "输出", "用时", "token",
                      "缓存命中", "改动", "a6bc148", "看你那句 ›", f"[进话题 ›]({TOPIC_URL})"):
            self.assertIn(words, plain)

    def test_a_relay_without_figures_keeps_its_links_on_a_small_line(self):
        self.assertIsNone(foot(None, ()))
        self.assertEqual("relay_foot", foot(None, (), links=("[进话题 ›](u)",))["element_id"])

    def test_a_waiting_and_a_stopped_relay_have_the_row_too(self):
        built, _ = relay_card("T623", WAITING, question="选 A 还是 B？", ask=self.asked("waiting"))
        self.assertEqual(("等你", "orange"), tag(first(built)))
        self.assertNotIn("header", built)
        self.assertIn("看你那句 ›", built["body"]["elements"][-1]["content"])
        stopped, _ = relay_card("T623", STOPPED, reason="到了时间上限", avatar="img_topic")
        self.assertEqual(("停住了", "red"), tag(first(stopped)))
        self.assertTrue(text_of(first(stopped)).startswith("**T623** <text_tag"))
        self.assertEqual("img_topic", first(stopped)["columns"][0]["elements"][0]["img_key"])  # Given beside the block.


class MergedTest(unittest.TestCase):
    def test_the_merged_card_has_a_row_and_each_block_opens_its_topic(self):
        built, text = merged_card([{"label": "T1", "title": "改看板", "lead": "好了", "url": TOPIC_URL},
                                   {"label": "T2", "title": "", "lead": "", "url": ""}], avatar="img_topic")
        head, one, two = built["body"]["elements"]
        self.assertEqual(("有结果", "green"), tag(head))
        self.assertTrue(text_of(head).startswith("**2 个话题做完了**"))
        self.assertEqual("img_topic", head["columns"][0]["elements"][0]["img_key"])
        self.assertEqual({"type": "open_url", "default_url": TOPIC_URL}, one["behaviors"][0])
        self.assertNotIn("behaviors", two)
        self.assertTrue(text.startswith("**2 个话题做完了**"))


class QuestionCopyTest(unittest.TestCase):
    ask = staticmethod(lambda: ask_block("选哪种样式", at="09:12", url=URL, who="T439 改看板", doing="waiting"))

    def test_the_question_leads_and_the_output_is_folded_under_it_with_its_size(self):
        built = mirror_card(question_record(), "T439", "上一轮写了很长很长的输出" * 30, ask=self.ask())
        ids = [element.get("element_id") for element in built["body"]["elements"]]
        self.assertEqual("speaker_row", ids[0])
        self.assertTrue(ids[2].startswith("q_"))  # The row, the band, then the form.
        self.assertEqual("mirror_output", ids[3])
        fold = built["body"]["elements"][3]
        self.assertIn("T439 这一轮的输出 · 约", fold["header"]["title"]["content"])
        self.assertEqual(("等你", "orange"), tag(first(built)))
        self.assertNotIn("header", built)
        self.assertIn(f"[看你那句 ›]({URL})", built["body"]["elements"][-1]["content"])
        self.assertNotIn("answer_ask", ids[:-1])

    def test_an_answered_copy_keeps_the_question_and_what_he_chose_in_two_lines(self):
        answered = question_record("answered", continuation_job_id=5, delivery_state="running")
        lines = settled_lines(answered)
        self.assertEqual(2, len(lines))
        self.assertIn("2 道题", lines[0]["content"])
        self.assertIn("你选了「表格 / 无」", lines[1]["content"])
        built = mirror_card(answered, "T439", "输出", ask=self.ask())
        self.assertEqual(("已回答", "grey"), tag(first(built)))
        self.assertIn("关于你 09:12 的问题", text_of(first(built)))  # No longer "要你定".
        self.assertIn("你选了「", json.dumps(built["body"]["elements"][:4], ensure_ascii=False))
        self.assertIn("已取消", settled_lines(question_record("cancelled"))[1]["content"])
        for status in ("pending", "superseded"):
            self.assertIsNone(settled_lines(question_record(status)))
        self.assertIn("你提了反馈", settled_lines(question_record("answered", response_kind="feedback"))[1]["content"])

    def test_a_block_sent_before_the_row_stays_at_the_top_as_it_was(self):
        legacy = {key: value for key, value in self.ask().items() if key != ASK_META}
        built = mirror_card(question_record(), "T439", "输出", ask=legacy)
        self.assertEqual("answer_ask", built["body"]["elements"][0]["element_id"])
        self.assertNotIn("header", built)


class OwnerSendTest(unittest.TestCase):
    draft = {"id": "d" * 32, "status": "drafted", "topic_label": "T9", "why": "交 key", "text": "key 开好了",
             "recipient": {"name": "张三", "kind": "p2p"}}

    def test_the_draft_waiting_for_the_owner_is_a_small_card_with_an_orange_confirm_tag(self):
        built = top_card("T9", "张三", TOPIC_URL)
        header = built["header"]
        self.assertEqual(("T9 代发草稿", "要你确认", "orange"), (header["title"]["content"], header["text_tag_list"][0]["text"]["content"],
                                                          header["text_tag_list"][0]["color"]))
        self.assertIn("张三", header["subtitle"]["content"])
        self.assertIn(f"[到话题里看 ›]({TOPIC_URL})", built["body"]["elements"][0]["content"])
        self.assertEqual(1, len(top_card("", "", "")["body"]["elements"]))  # No link: still a card, saying where.

    def test_the_card_in_the_topic_says_its_state_in_the_bar_and_the_form_is_unchanged(self):
        built = owner_send_card(self.draft, {"state": "drafted"})
        found = built["header"]["text_tag_list"][0]
        self.assertEqual(("代发草稿", "要你确认", "orange"), (built["header"]["title"]["content"], found["text"]["content"], found["color"]))
        self.assertNotIn("**✉️ 代发草稿", json.dumps(built, ensure_ascii=False))  # The heading is the bar.
        self.assertTrue(any(element.get("tag") == "form" for element in built["body"]["elements"]))
        for state, (_, words, color) in BARS.items():
            drawn = owner_send_card({**self.draft, "status": state, "sent_at_text": "18:59"}, {"state": state})
            self.assertEqual((words, color), (drawn["header"]["text_tag_list"][0]["text"]["content"],
                                              drawn["header"]["text_tag_list"][0]["color"]))


class LinkedTest(unittest.TestCase):
    def test_a_t_number_inside_the_reply_s_fold_is_a_link_and_the_artifacts_panel_is_left_alone(self):
        from covey.app.relay_send import linked
        from covey.cards.answer_card import ARTIFACTS_ID
        from covey.cards.elements import markdown_panel

        files = markdown_panel(ARTIFACTS_ID, "产物", "- T7.md", quiet=True)
        built, _ = relay_card("T9", DONE, text="## 结论\n好了\n\n" + "细节见 T7。" * 40, files=files)
        with mock.patch("covey.app.topic_links.linkify", side_effect=lambda text, *a, **k: text.replace("T7", "[T7](u)")):
            built, _ = linked("/state", "oc_x", built, "")
        text = json.dumps(built["body"]["elements"][2], ensure_ascii=False)
        self.assertIn("[T7](u)", text)
        self.assertNotIn("[T7](u)", json.dumps(built["body"]["elements"][3], ensure_ascii=False))


class NoLeakTest(unittest.TestCase):
    def test_no_card_sample_sends_the_block_s_notes(self):
        """ASK_META is for the card that takes the block into its row: it is stripped there and never sent (CardKit
        refuses properties it does not know)."""
        from test_card_golden import render

        sent = {name: card for name, card in json.loads(json.dumps(render(), ensure_ascii=False)).items()
                if not name.startswith(("task.ask_speaker", "task.ask_"))}
        leaked = [name for name, card in sent.items() if holders(card)]
        self.assertEqual([], leaked)


class AvatarsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)

    def test_the_pool_is_twenty_files_that_are_there_and_the_butler_and_the_topic_have_theirs(self):
        self.assertEqual(20, len(set(avatars.POOL)))
        for name in (*avatars.POOL, avatars.BUTLER, avatars.TOPIC):
            self.assertTrue(avatars.asset(name).is_file(), name)
        self.assertIsNone(avatars.asset("../x"))
        self.assertIsNone(avatars.asset("nobody"))
        self.assertEqual({"G": 6, "M": 6, "s": 8}, {k: sum(n[0] == k for n in avatars.POOL) for k in "GMs"})

    def test_a_lead_keeps_its_picture_and_the_leads_of_one_chat_do_not_share_one(self):
        with mock.patch("covey.core.avatars.projects.read_record", return_value={"id": "x"}):
            first_run = {pid: avatars.lead_name(self.state, "oc_1", pid) for pid in (f"p{n:02d}" for n in range(20))}
            self.assertEqual(20, len(set(first_run.values())))  # Twenty projects, twenty pictures: pushed on past a taken one.
            again = {pid: avatars.lead_name(self.state, "oc_1", pid) for pid in first_run}
            self.assertEqual(first_run, again)  # Kept in <state>/avatars.json: the same next time.
            self.assertEqual(first_run, {pid: avatars.lead_name(self.state, "oc_1", pid) for pid in first_run})
            other = avatars.lead_name(self.state, "oc_2", "p00")
            self.assertEqual(avatars.pick("p00"), other)  # Another chat: the id's own place again.
            self.assertEqual(avatars.pick("p00"), avatars.pick("p00"))  # A stable hash, not Python's per-process one.
        self.assertTrue((self.state / "avatars.json").is_file())

    def test_a_project_that_is_gone_lets_go_of_its_picture(self):
        with mock.patch("covey.core.avatars.projects.read_record", return_value={"id": "x"}):
            gone = avatars.lead_name(self.state, "oc_1", "a")
        with mock.patch("covey.core.avatars.projects.read_record", return_value={}):
            self.assertEqual(gone, avatars.pick("a"))
            # "b" wanted the same place: with "a" no longer on record, it has it.
            clash = next(pid for pid in (f"c{n}" for n in range(500)) if avatars.pick(pid) == gone)
            self.assertEqual(gone, avatars.lead_name(self.state, "oc_1", clash))

    def test_nothing_without_a_state_a_chat_or_a_project(self):
        self.assertEqual("", avatars.lead_name(None, "oc_1", "p"))
        self.assertEqual("", avatars.lead_name(self.state, "", "p"))
        self.assertEqual("", avatars.lead_name(self.state, "oc_1", ""))


class UploadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name)
        patch = mock.patch.dict(os.environ, {"COVEY_AVATARS": "1"})
        patch.start()
        self.addCleanup(patch.stop)
        uploads._failed.clear()
        self.addCleanup(uploads._failed.clear)

    def test_the_first_use_uploads_and_the_key_is_kept_by_the_file_s_content(self):
        calls = []
        upload = lambda path, profile: calls.append((path.name, profile)) or "img_v3_butler"
        self.assertEqual("img_v3_butler", uploads.image_key(self.state, "covey", "butler", upload=upload))
        self.assertEqual("img_v3_butler", uploads.image_key(self.state, "covey", "butler", upload=upload))
        self.assertEqual([("butler.png", "covey")], calls)  # Once.
        kept = json.loads((self.state / "avatars.json").read_text())["keys"]["covey"]
        self.assertEqual({avatars.digest("butler"): "img_v3_butler"}, kept)
        self.assertEqual("", avatars.cached_key(self.state, "another-app", "butler"))  # A key belongs to its app.
        self.assertEqual("", avatars.cached_key(self.state, "covey", "topic"))

    def test_a_failed_upload_leaves_the_card_without_the_picture_and_is_tried_again_later(self):
        logs = []
        results = iter([None, "img_v3_late"])
        upload = lambda path, profile: next(results)
        self.assertEqual("", uploads.image_key(self.state, "covey", "topic", logs.append, upload=upload))
        self.assertTrue(logs and "topic" in logs[0])
        self.assertEqual("", uploads.image_key(self.state, "covey", "topic", upload=upload))  # Not at once: it would wait again.
        with mock.patch("covey.feishu.avatars.time.monotonic", return_value=10 ** 9):
            self.assertEqual("img_v3_late", uploads.image_key(self.state, "covey", "topic", upload=upload))

    def test_an_upload_that_raises_or_a_missing_picture_is_no_key_and_the_switch_turns_it_all_off(self):
        def boom(path, profile):
            raise OSError("no lark-cli")
        self.assertEqual("", uploads.image_key(self.state, "covey", "butler", upload=boom))
        self.assertEqual("", uploads.image_key(self.state, "covey", "nobody", upload=lambda *_: "img"))
        self.assertEqual("", uploads.image_key(None, "covey", "butler", upload=lambda *_: "img"))
        with mock.patch.dict(os.environ, {"COVEY_AVATARS": "0"}):
            self.assertEqual("", uploads.image_key(self.state, "covey", "topic", upload=lambda *_: "img"))

    def test_the_speaker_s_key_comes_from_who_speaks(self):
        from covey.app import answer_cards

        with mock.patch("covey.core.board_read.avatar_of", return_value="butler"), \
                mock.patch("covey.feishu.avatars.upload_image", return_value="img_b"):
            self.assertEqual("img_b", answer_cards.avatar(self.state, "topic", "oc_1", "covey"))
        with mock.patch("covey.core.board_read.avatar_of", return_value=""):
            self.assertEqual("", answer_cards.avatar(self.state, "topic", "oc_1", "covey"))  # No speaker, no picture.
        with mock.patch("covey.core.board_read.avatar_of", side_effect=OSError):
            self.assertEqual("", answer_cards.avatar(self.state, "topic", "oc_1", "covey"))
        self.assertEqual("", answer_cards.avatar(self.state, "", "oc_1", "covey"))


if __name__ == "__main__":
    unittest.main()
