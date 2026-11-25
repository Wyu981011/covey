"""The 批量换配置 card (app/batch_switch.py, T786): the topics the butler or a project's lead would switch to another Harness, model
or budget, each from what to what, with 确认更换 and 取消, in the owner's private chat. Nothing is switched before the owner's click.

One card, redrawn whole (``update_multi``) as its record goes (``card``): 等你确认 (the rows, why, the two buttons), 正在换, 已换
(each row's outcome; 再试没换的 while a row was refused for a reason that can pass, a task still running, say), 已取消. A row a
plan could not switch (no such model, the same configuration already) is listed under the others with why, and never switched.
"""
from __future__ import annotations

from covey.cards.elements import item, md, note, panel_header, styled_panel, text_button

ICON = "switch"
TITLE = "批量换配置"
CONFIRM = "bridge_batch_switch_confirm"  # 确认更换
CANCEL = "bridge_batch_switch_cancel"  # 取消
RETRY = "bridge_batch_switch_retry"  # 再试没换的
KINDS = frozenset({CONFIRM, CANCEL, RETRY})
LABELS = {CONFIRM: "确认批量换配置", CANCEL: "取消批量换配置", RETRY: "再试没换的话题"}  # app/card_actions.py ACTIONS.
# A row's state (app/batch_switch.py): ready (to switch at the click), skip (the plan found it cannot), switching (the click took it;
# a restart in between is settled at the next click), done, failed (refused for a reason that can pass: 再试), stale (the topic's
# configuration changed since the card was drawn: never switched from this card).
WORDS = {"done": "已换", "failed": "没换", "stale": "没换", "skip": "不换", "switching": "正在换"}
COLORS = {"done": "green", "failed": "red", "stale": "grey", "skip": "grey", "switching": "blue"}


def clean(text, limit=80) -> str:
    """A label or reason as one short plain line in the card's Markdown."""
    text = " ".join(str(text or "").split())[:limit]
    return "".join(ch for ch in text if ch not in "<>`*[]") or "—"


def heading(row) -> str:
    title = clean(row.get("title"), 24)
    return f"**{clean(row.get('label') or '话题', 12)}**" + (f" {title}" if row.get("title") else "")


def change(row) -> str:
    return f"{clean(row['from'].get('label'))} → **{clean(row['to'].get('label'))}**" if row.get("to") else clean(
        row["from"].get("label"))


def line(row, *, decided=False) -> str:
    """One row: T号 标题：from → to, with its outcome once decided (or why a plan cannot switch it)."""
    state = row.get("state") or "ready"
    text = f"{heading(row)}：{change(row)}"
    if state == "ready" and not decided:
        return text
    word = WORDS.get(state, "")
    why = f"（{clean(row.get('why'), 100)}）" if row.get("why") and state != "done" else ""
    return f"{text}　<font color='{COLORS.get(state, 'grey')}'>{word}</font>{why}" if word else text


def counted(record) -> dict:
    found = {}
    for row in record.get("rows") or ():
        found[row.get("state") or "ready"] = found.get(row.get("state") or "ready", 0) + 1
    return found


def who(record) -> str:
    lead = record.get("lead") or {}
    return f"专项「{clean(lead.get('name') or '专项', 20)}」的负责人" if lead else "管家"


def card(record):
    """The card of the batch ``record`` as it stands (app/batch_switch.py ``Batch``'s record)."""
    status, rows, value = record.get("status") or "pending", record.get("rows") or [], {"batch": record["token"]}
    numbers = counted(record)
    planned = [row for row in rows if row.get("state") != "skip"]
    skipped = [row for row in rows if row.get("state") == "skip"]
    decided = status in ("done", "running")
    elements = []
    if record.get("basis"):
        elements.append(md(f"主人说：「{clean(record['basis'], 60)}」"))
    if planned:
        elements.append(md("\n".join(line(row, decided=decided) for row in planned)))
    if skipped:
        elements.append(md("**不换的**\n" + "\n".join(line(row) for row in skipped)))
    if status == "pending":
        elements.append(md("确认后逐个换：每个话题下一条消息起由新会话接手，带上交接摘要；"
                           "正在跑任务的话题这次不换，卡上会写明，停了之后可以再试。"))
        elements.append(item(md(" "), text_button("确认更换", {"kind": CONFIRM, **value}, tone="primary"),
                             text_button("取消", {"kind": CANCEL, **value})))
        elements.append(note(f"{who(record)}提议的；只有你点「确认更换」才会换。"))
        tag = ("等你确认", "blue")
    elif status == "running":
        elements.append(md("正在逐个换…"))
        tag = ("正在换", "blue")
    elif status == "cancelled":
        elements.append(md("已取消，一个都没换。"))
        tag = ("已取消", "neutral")
    else:
        done, left = numbers.get("done", 0), numbers.get("failed", 0)
        words = f"换好 {done} 个" + (f"，{left} 个没换" if left else "") + (f"，{numbers['stale']} 个配置已变、没动" if numbers.get("stale") else "")
        elements.append(md(words + "。换好的话题下一条消息起由新会话接手。"))
        if left:
            elements.append(item(md(" "), text_button("再试没换的", {"kind": RETRY, **value}, tone="primary")))
        tag = ("已换", "green") if done and not left else ("部分没换", "orange") if done else ("没换", "neutral")
    subtitle = f"{len(planned)} 个话题" + (f"，{len(skipped)} 个不换" if skipped else "")
    return styled_panel(panel_header(ICON, TITLE, subtitle, [tag], color="grey" if status == "cancelled" else "blue"),
                        elements, f"{TITLE} · {subtitle} · {tag[0]}")


def text(record) -> str:
    """The card as Markdown, for when Feishu refuses the card: nothing can be clicked, so nothing will be switched."""
    rows = "\n".join(f"- {line(row)}" for row in record.get("rows") or ())
    return f"**{TITLE}**（卡片发不出来，没有换）：\n{rows}"
