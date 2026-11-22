"""The 网页登录确认 card (app/web_login.py, COVEY_WEB=1 with a self-hosted page, docs/web.md 网页登录确认): a browser asks to sign in
to the 网页工作台 and the owner says 允许 or 不是我 in the private chat.

One card, redrawn whole (``update_multi``) as it goes: ``pending_card`` with the browser, system, where the request came from (本机
or an address), the 4-digit code the page shows and the time, and the two buttons (``failed``: why the last click did not reach the page, buttons kept, so it can be clicked again);
``result_card`` once the page took the decision (已允许 · time, or 已拒绝); ``void_card`` when the page answered but took nothing (its request
no longer waits); ``expired_card`` past ``VALID_SECONDS`` of the request.
"""
from __future__ import annotations

import time

from covey.cards.elements import item, md, note, panel_header, styled_panel, text_button

ICON = "safe_outlined"
TITLE = "网页登录确认"
ALLOW = "bridge_web_login_allow"  # 允许
DENY = "bridge_web_login_deny"  # 不是我
KINDS = frozenset({ALLOW, DENY})
VALID_SECONDS = 300  # A request older than this (its ``at``) is not decided any more.
SHOWN = 60  # Characters of the browser and system as the page reported them.


def clock(seconds) -> str:
    """``seconds`` (epoch) as 月-日 时:分:秒, local time."""
    return time.strftime("%m-%d %H:%M:%S", time.localtime(float(seconds)))


def clean(text, limit=SHOWN) -> str:
    """What a browser reported (or an error said), as one short plain line: no markup, no line breaks."""
    text = " ".join(str(text or "").split())[:limit]
    return "".join(ch for ch in text if ch not in "<>`*_[]()") or "未知"


def source(ip) -> str:
    """Where the request came from, as the page saw it: 本机 for this machine's loopback (a browser here, or one through an ssh
    forward), else the address (a Tailscale or reverse proxy's client); '' when the page did not say."""
    ip = clean(ip, 64) if ip else ""
    if not ip:
        return ""
    return "本机" if ip == "::1" or ip.startswith("127.") or ip.lower().startswith("::ffff:127.") else ip


def facts(view) -> str:
    lines = [f"**浏览器**　{clean(view.get('browser'))}", f"**系统**　{clean(view.get('os'))}"]
    if source(view.get("ip")):
        lines.append(f"**来源**　{source(view.get('ip'))}")
    return "\n".join([*lines, f"**对照码**　**{clean(view.get('code'))}**", f"**发起时间**　{clock(view.get('at') or 0)}"])


def pending_card(view, failed=""):
    """The request and 允许 / 不是我; ``failed`` (why the page did not take the last click) is said above the buttons."""
    value = {"request_id": view["request_id"]}
    elements = [md("有浏览器要登录你的网页工作台。请核对网页上显示的对照码，**是你本人**再点允许。"), md(facts(view))]
    if failed:
        elements.append(md(f"<font color='red'>没有送到网页：{clean(failed, 120)}。可以再点一次。</font>"))
    elements.append(item(md(" "), text_button("允许", {"kind": ALLOW, **value}, tone="primary"),
                         text_button("不是我", {"kind": DENY, **value}, tone="danger")))
    elements.append(note(f"{VALID_SECONDS // 60} 分钟内有效；不是你发起的，点「不是我」。"))
    return styled_panel(panel_header(ICON, TITLE, "", [("等你确认", "blue")]), elements, f"{TITLE} · 等你确认")


def result_card(view, approved, decided_at):
    """After the page took the decision."""
    words = f"已允许 · {clock(decided_at)}" if approved else f"已拒绝 · {clock(decided_at)}"
    tag = ("已允许", "green") if approved else ("已拒绝", "grey")
    return styled_panel(panel_header(ICON, TITLE, "", [tag], color=tag[1]), [md(facts(view)), md(words)], f"{TITLE} · {words}")


def void_card(view, approved):
    """The page answered but took nothing: its request no longer waits (expired or decided over there). No login came of the click."""
    said = "允许" if approved else "不是我"
    return styled_panel(panel_header(ICON, TITLE, "", [("已失效", "neutral")], color="grey"),
                        [md(facts(view)), md(f"你点了「{said}」，但网页上这次登录已经失效（过期或已处理），没有登录。需要的话在网页上重新点「用飞书登录」。")],
                        f"{TITLE} · 已失效")


def expired_card(view):
    """Past the five minutes: nothing is sent to the page any more."""
    return styled_panel(panel_header(ICON, TITLE, "", [("已过期", "neutral")], color="grey"),
                        [md(facts(view)), md("已过期，没有处理。需要的话在网页上重新点「用飞书登录」。")], f"{TITLE} · 已过期")


def text(view) -> str:
    """The card as Markdown, for when Feishu refuses the card: no buttons, so it says how to go on."""
    return (f"**{TITLE}**：有浏览器要登录网页工作台（{clean(view.get('browser'))} · {clean(view.get('os'))}），对照码 "
            f"**{clean(view.get('code'))}**。卡片发不出来，请在网页上取消这次登录再重试。")
