"""The 设置 card's 记忆 tab (app/memory_panel.py, COVEY_MEMORY=1): the memory's counts, the 待审核 to decide, and the way to the web.

Feishu keeps three things of the memory: looking at the numbers, the light handling of 待审核 (采纳 or 不要, one item at a time),
and the way to the 网页记忆中心 (managing it all is there: editing, moving to another scope, 作废). One layer under the tab row:

- the header's subtitle ``规矩 N · 决定 N · 资料 N · 待审核 N``; a line of counts for each scope (全局, 话题, the projects: the
  first PROJECTS of them, then 另有 N 个专项);
- 待审核: the oldest items (title and a line of text), each with 采纳 and 不要, a page of REVIEW_PAGE with 上一页 / 下一页;
  with the web page on (``url``) a button 打开网页记忆中心 and, under 待审核, one 去网页逐条看 (URL buttons, they carry no kind);
- without the web page: the titles of the 全局 and the projects' rules (short code and title, 超额 marked), each with 收起
  (two steps: 收起, then 确认收起 or 取消; core/memstore.py archive), a page of RULE_PAGE.

The buttons keep the kinds the tab had (the closed set of kinds is frozen, tests/golden/concepts.json): ``ACCEPT`` is
``bridge_memory_pin`` (it was 常驻), ``DELETE`` is 不要 on a 待审核 item (``key`` ``review:…``, ``op`` reject) and 收起 on a rule
(``op`` ask, confirm or cancel), ``OPEN`` pages. ``WORKSPACE`` and ``PROMOTE`` (and 常驻 as the old ``PIN``) stay in KINDS only to
take the click of a card drawn before: they change nothing and say so (app/memory_panel.py).

Each button's value carries its kind, the card's token and the revision drawn. ``view``: revision, notice, review_page,
rules_page, confirm (the key of the rule asking 确认收起); ``data``: app/memory_panel.py ``facts``. A card that would be too much
for CardKit (cards/elements.py CARD_NODES, CARD_BYTES) is drawn again with fewer rows.
"""
from __future__ import annotations

from covey.cards import ui
from covey.cards.elements import (CARD_BYTES, CARD_NODES, element_count, grey, item, json_size, md, note, panel_header, plain,
                                  section, styled_panel, text_button)
from covey.core import web_sync
from covey.core.text import cut, literal

TITLE = "记忆"
ICON = "member_outlined"
WORKSPACE = "bridge_memory_workspace"  # Offline: the 工作区 row of the older tab. A click says so and changes nothing.
OPEN = "bridge_memory_open"  # 上一页 / 下一页: ``scope`` (review or rules) and ``page``.
DELETE = "bridge_memory_delete"  # 不要 (``key`` review:…, ``op`` reject) and 收起 (``key`` of a rule, ``op`` ask, confirm or cancel).
ACCEPT = "bridge_memory_pin"  # 采纳 a 待审核 item (``key`` review:…, ``op`` accept): the kind that was 常驻, kept so no kind is new.
PIN = ACCEPT  # What the older tab's 常驻 carried (``key`` of a principle, ``on``): offline, answered with a line.
PROMOTE = "bridge_memory_to_global"  # Offline: 升为全局 of the older tab.
KINDS = frozenset({WORKSPACE, OPEN, DELETE, ACCEPT, PROMOTE})
REVIEW = "review"  # OPEN's ``scope`` of the 待审核 list.
RULES = "rules"  # OPEN's ``scope`` of the rules list (without the web page).
REVIEW_PAGE = 5  # Items of 待审核 a page shows.
RULE_PAGE = 8  # Rules a page shows.
PROJECTS = 5  # Projects whose counts get a line.
TITLE_CHARS = 30  # Characters of an item's or a rule's title.
TEXT = 60  # Characters of an item's line of text.
URL_LABEL = "打开网页记忆中心"
REVIEW_URL_LABEL = "去网页逐条看"
OFFLINE = "这个选项已下线：记忆按范围管，改动到网页记忆中心"
EMPTY = "还没有记忆：你在话题里说“以后…”“别再…”这类长期要求，那一轮结束后会记下。"


def center_url(tab="") -> str:
    """The 网页记忆中心's address (app/web_memory.py center_url, the same rule: a card may not import app/): ``page_url`` +
    /memory[/tab], '' without the web page."""
    url = web_sync.page_url()
    if not url or "?" in url or "#" in url:
        return url
    return url.rstrip("/") + "/memory" + (f"/{tab}" if tab else "")


def url_button(label, url):
    """A small borderless button that opens ``url`` (it carries no kind: a click never reaches the Bridge)."""
    return {"tag": "button", "text": plain(label), "type": "text", "size": "small",
            "behaviors": [{"type": "open_url", "default_url": url}]}


def counts_words(counts, *, pending=True) -> str:
    """``规矩 N · 决定 N · 资料 N`` and ``· 待审核 N``."""
    counts = counts or {}
    parts = [f"规矩 {counts.get('rule', 0)}", f"决定 {counts.get('decision', 0)}", f"资料 {counts.get('note', 0)}"]
    if pending:
        parts.append(f"待审核 {counts.get('pending', 0)}")
    return " · ".join(parts)


def scope_lines(scopes, projects=PROJECTS) -> list:
    """A line of counts for 全局, 话题 and the first ``projects`` projects, one more line for the rest."""
    scopes = list(scopes or ())
    fixed = [row for row in scopes if row.get("key") in ("global", "topics")]
    each = [row for row in scopes if str(row.get("key") or "").startswith("p:")]
    lines = [md(f"**{literal(cut(row.get('title') or '', 24))}** · {counts_words(row.get('counts'))}", size="notation")
             for row in [*fixed, *each[:projects]]]
    if len(each) > projects:
        lines.append(note(f"另有 {len(each) - projects} 个专项"))
    return lines


def pager(scope, page, pages, value):
    buttons = []
    if page > 0:
        buttons.append(text_button("上一页", value(OPEN, scope=scope, page=page - 1)))
    if page + 1 < pages:
        buttons.append(text_button("下一页", value(OPEN, scope=scope, page=page + 1)))
    return item(note(f"第 {page + 1}/{pages} 页"), *buttons)


def page_of(rows, view, field, size):
    pages = max(1, -(-len(rows) // size))
    page = min(max(int(view.get(field) or 0), 0), pages - 1)
    return rows[page * size:(page + 1) * size], page, pages


def review_elements(review, view, value, data, size=REVIEW_PAGE):
    """待审核: the oldest items with 采纳 and 不要, the way to the web page when there is one."""
    elements = [section(f"待审核（{len(review)}）")]
    if not review:
        return [*elements, note("没有待审核的")]
    shown, page, pages = page_of(review, view, "review_page", size)
    for row in shown:
        key = str(row.get("key") or "")
        line = f"**{literal(cut(row.get('title') or row.get('text') or '', TITLE_CHARS))}**"
        text = literal(cut(row.get("text") or "", TEXT))
        if text and text != literal(cut(row.get("title") or "", TITLE_CHARS)):
            line += "\n" + grey(text)
        elements.append(item(md(line, size="normal_v2"), text_button("采纳", value(ACCEPT, key=key, op="accept")),
                             text_button("不要", value(DELETE, key=key, op="reject"))))
    if pages > 1:
        elements.append(pager(REVIEW, page, pages, value))
    if data.get("review_url"):
        elements.append(item(note("每条的全文、改了再采纳、归到别的范围，在网页上"), url_button(REVIEW_URL_LABEL, data["review_url"])))
    return elements


def rule_line(row, titles) -> str:
    where = "全局" if row.get("scope") == "global" else titles.get(f"p:{row.get('project_key')}", "专项")
    over = " " + grey("· 超额") if row.get("over_cap") else ""
    return (f"{grey(str(row.get('code') or ''))} {literal(cut(row.get('title') or '', TITLE_CHARS))} "
            f"{grey('· ' + literal(cut(where, 12)))}{over}")


def rule_elements(rules, scopes, view, value, size=RULE_PAGE):
    """Without the web page: the titles of the rules in use, each 收起 (two steps)."""
    elements = [section(f"规矩（{len(rules)}）")]
    if not rules:
        return [*elements, note("没有")]
    titles = {str(row.get("key")): str(row.get("title") or "") for row in scopes or ()}
    shown, page, pages = page_of(rules, view, "rules_page", size)
    for row in shown:
        key = str(row.get("key") or "")
        if view.get("confirm") == key:
            buttons = [text_button("确认收起", value(DELETE, key=key, op="confirm"), tone="danger"),
                       text_button("取消", value(DELETE, key=key, op="cancel"))]
        else:
            buttons = [text_button("收起", value(DELETE, key=key, op="ask"))]
        elements.append(item(md(rule_line(row, titles), size="normal_v2"), *buttons))
    if pages > 1:
        elements.append(pager(RULES, page, pages, value))
    return elements


# A card too much for CardKit is drawn again with fewer rows: (items of 待审核, rules, projects).
LESS = ((REVIEW_PAGE, RULE_PAGE, PROJECTS), (3, 4, 3), (2, 2, 1))


def memory_card(token, view, data, *, top=()):
    """The tab for ``view`` over ``data`` (app/memory_panel.py facts)."""
    for review, rules, projects in LESS:
        card = _memory_card(token, view, data, top, review, rules, projects)
        if element_count(card["body"]["elements"]) <= CARD_NODES and json_size(card) <= CARD_BYTES:
            break
    return card


def _memory_card(token, view, data, top, review_size, rule_size, projects):
    def value(kind, **more):
        return {"kind": kind, "token": token, "revision": view.get("revision", 1), **more}

    elements = [*top]
    if view.get("notice"):
        elements.append(ui.receipt(view["notice"]))
    counts = data.get("counts") or {}
    if data.get("error"):
        elements.append(md(literal(data["error"])))
    elif not any(counts.get(name) for name in ("rule", "decision", "note", "pending")):
        elements.append(md(EMPTY))
    if data.get("url"):
        elements.append(item(note("记忆按范围管：看全貌、改、整理，都在网页记忆中心"), url_button(URL_LABEL, data["url"])))
    elements += scope_lines(data.get("scopes"), projects)
    elements += review_elements(data.get("review") or [], view, value, data, review_size)
    if not data.get("url"):
        elements += rule_elements(data.get("rules") or [], data.get("scopes"), view, value, rule_size)
    subtitle = counts_words(counts)
    return styled_panel(panel_header(ICON, TITLE, subtitle), elements, f"{TITLE} · {subtitle}")
