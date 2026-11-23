"""The SVGs of the repo's face, written from the code below: the mark (docs/media/brand/covey-mark.svg), the hero
banners (hero-{zh,en}-{dark,light}.svg) and the workflow diagrams (workflow-{zh,en}-{dark,light}.svg).

    python3 -B scripts/brand_svgs.py [/absolute/out/dir]      # default: docs/media/brand of this checkout

Change a word or a colour here and run it again; do not edit the SVGs by hand, the four variants of each must stay
alike. Text is SVG text in the reader's system fonts (no font files, no external references), so GitHub shows it in
an <img>. Demo data only. scripts/brand_assets.py draws the PNG cover and the GIF from these and the card sketches.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SANS = '-apple-system,"Segoe UI","Helvetica Neue",Arial,"PingFang SC","Microsoft YaHei","Noto Sans CJK SC",sans-serif'
MONO = '"SF Mono","DejaVu Sans Mono",Menlo,Consolas,monospace'
T = {
    "dark": dict(
        bg="#0d1117",
        panel="#12141B",
        panel2="#0C0E13",
        stroke="#232733",
        text="#EDEEF1",
        text2="#B3B7C1",
        muted="#8A90A0",
        brand="#7C83FF",
        brand2="#4B52E0",
        orange="#F5A524",
        green="#3DD68C",
        blue="#4C9AFF",
        badge="#3B4455",
        dot="#2A2F3D",
        pillbg=0.16,
        arrow="#6B7285",
        mark_bg=("#5B62F0", "#8C93FF"),
    ),
    "light": dict(
        bg="#ffffff",
        panel="#F6F7FB",
        panel2="#EEF0F6",
        stroke="#D6D9E3",
        text="#1F2329",
        text2="#4A4F5A",
        muted="#667085",
        brand="#4B52E0",
        brand2="#4B52E0",
        orange="#C97F00",
        green="#168A55",
        blue="#2461D6",
        badge="#47536A",
        dot="#D3D7E2",
        pillbg=0.13,
        arrow="#8A90A0",
        mark_bg=("#4B52E0", "#7C83FF"),
    ),
}


def mark_group(x, y, s, th, uid):
    k = s / 64
    a, b = T[th]["mark_bg"]
    return (
        f'<g transform="translate({x} {y}) scale({k})"><defs><linearGradient id="mg{uid}" x1="0" y1="0" x2="1" y2="1">'
        f'<stop offset="0" stop-color="{a}"/><stop offset="1" stop-color="{b}"/></linearGradient></defs>'
        f'<rect width="64" height="64" rx="16" fill="url(#mg{uid})"/>'
        '<path d="M42.6 21.4A15 15 0 1 0 42.6 42.6" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/>'
        '<circle cx="31" cy="32" r="4.6" fill="#fff"/><circle cx="41.5" cy="32" r="2.6" fill="#fff" fill-opacity=".7"/></g>'
    )


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;")


def txt(x, y, s, size, fill, weight=400, anchor="start", font=SANS, extra=""):
    return f'<text x="{x}" y="{y}" font-family=\'{font}\' font-size="{size}" font-weight="{weight}" fill="{fill}" text-anchor="{anchor}" {extra}>{esc(s)}</text>'


def rect(x, y, w, h, r, fill, stroke=None, sw=1, extra=""):
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke else ""
    return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}"{st} {extra}/>'


def pill(x, y, label, color, th, size=14, w=None):
    c = T[th]
    w = w or int(len(label) * size * (1.0 if any(ord(ch) > 255 for ch in label) else 0.58) + 20)
    return rect(x, y, w, size + 10, (size + 10) / 2, color, extra=f'fill-opacity="{c["pillbg"]}"') + txt(
        x + w / 2, y + size + 1, label, size, color, 600, "middle"
    ), w


def badge(x, y, label, th, size=14, w=34):
    c = T[th]
    return rect(x, y, w, 24, 7, c["badge"]) + txt(x + w / 2, y + 17, label, size, "#fff", 700, "middle", MONO)


# ---------------- hero ----------------
def hero(lang, th):
    c = T[th]
    W, H = 1280, 360
    zh = lang == "zh"
    tag = "在飞书里带一支编程 Agent 小队" if zh else "Run a small team of coding agents from Feishu"

    def L(a, b):
        return a if zh else b

    sub = (
        "管家分活 · 每个话题独立会话 · 专项有负责人"
        if zh
        else "A butler hands out the work · one session per topic · a lead for long projects"
    )
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="Covey: {esc(tag)}">'
    ]
    s.append(
        f'<defs><pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1.1" fill="{c["dot"]}"/></pattern>'
        f'<radialGradient id="glow" cx="0.78" cy="0.45" r="0.6"><stop offset="0" stop-color="{c["brand"]}" stop-opacity="{0.20 if th == "dark" else 0.10}"/><stop offset="1" stop-color="{c["brand"]}" stop-opacity="0"/></radialGradient>'
        f'<linearGradient id="fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="{c["bg"]}" stop-opacity="1"/><stop offset=".55" stop-color="{c["bg"]}" stop-opacity=".92"/><stop offset="1" stop-color="{c["bg"]}" stop-opacity="0"/></linearGradient></defs>'
    )
    s.append(rect(0.5, 0.5, W - 1, H - 1, 18, c["bg"], c["stroke"]))
    s.append(rect(1, 1, W - 2, H - 2, 18, "url(#dots)"))
    s.append(rect(1, 1, W - 2, H - 2, 18, "url(#glow)"))
    s.append(rect(1, 1, 760, H - 2, 18, "url(#fade)"))

    # cards on the right: three topics in three states, the middle one waiting on the question of the other pictures
    def card(x, y, w, h, rot, topic, label, color, body):
        p, pw = pill(0, 0, label, color, th, 14)
        return (
            f'<g transform="rotate({rot} {x + w / 2} {y + h / 2})">'
            + rect(x, y, w, h, 14, c["panel"], c["stroke"])
            + badge(x + 16, y + 16, topic, th)
            + rect(x + 58, y + 23, 86, 9, 4.5, c["muted"], extra='fill-opacity=".55"')
            + f'<g transform="translate({x + w - pw - 16} {y + 14})">{p}</g>'
            + body
            + "</g>"
        )

    def bars(x, y, widths, opacity):
        return "".join(
            rect(x, y + i * 15, w, 7, 3.5, c["text2"], extra=f'fill-opacity="{opacity}"') for i, w in enumerate(widths)
        )

    first, second = ("首页（推荐）", "登录前打开的页面") if zh else ("Home (rec.)", "Page before login")
    question = (
        rect(916, 190, 230, 8, 4, c["text2"], extra='fill-opacity=".28"')
        + rect(916, 212, 112, 34, 9, "none", c["stroke"], 1.2)
        + txt(972, 234, first, 14, c["text"], 500, "middle")
        + rect(1036, 212, 148, 34, 9, c["brand"], extra='fill-opacity=".2"')
        + rect(1036, 212, 148, 34, 9, "none", c["brand"], 1.2)
        + txt(1110, 234, second, 14, c["text"], 500, "middle")
    )
    s.append(card(850, 24, 300, 104, -2, "T8", L("在做", "Working"), c["blue"], bars(866, 74, (250, 200, 150), ".28")))
    s.append(card(900, 140, 300, 120, 1.5, "T7", L("等你", "Your call"), c["orange"], question))
    s.append(card(840, 274, 300, 96, -1, "T6", L("有结果", "Done"), c["green"], bars(856, 324, (220, 160), ".25")))
    # left content
    s.append(mark_group(72, 86, 104, th, "h"))
    s.append(txt(200, 164, "Covey", 86, c["text"], 700, extra='letter-spacing="-1.5"'))
    s.append(txt(74, 236, tag, 34 if zh else 30, c["text"], 600))
    s.append(txt(74, 282, sub, 19 if zh else 18, c["muted"], 400))
    s.append("</svg>")
    return "\n".join(s)


# ---------------- workflow ----------------
def workflow(lang, th):
    c = T[th]
    zh = lang == "zh"
    W, H = 1280, 650
    L = lambda a, b: a if zh else b
    s = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-label="{esc(L("Covey 工作流：一句话到结论", "Covey workflow: one sentence to a conclusion"))}">'
    ]
    s.append(
        f'<defs><marker id="ar" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{c["arrow"]}"/></marker>'
        f'<marker id="ao" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{c["orange"]}"/></marker>'
        f'<marker id="ag" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M1 1L9 5L1 9z" fill="{c["green"]}"/></marker></defs>'
    )
    s.append(rect(0.5, 0.5, W - 1, H - 1, 18, c["bg"], c["stroke"]))

    def step(x, y, n, color=None):
        col = color or c["brand"]
        return f'<circle cx="{x}" cy="{y}" r="13" fill="{col}"/>' + txt(
            x, y + 5.5, str(n), 15, "#fff" if th == "light" or True else "#fff", 700, "middle"
        )

    def box(x, y, w, h, stroke=None):
        return rect(x, y, w, h, 14, c["panel"], stroke or c["stroke"])

    def line(d, color=None, dash=False, mk="ar"):
        dashes = ' stroke-dasharray="6 6"' if dash else ""
        return (
            f'<path d="{d}" fill="none" stroke="{color or c["arrow"]}" stroke-width="2" stroke-linecap="round"{dashes}'
            f' marker-end="url(#{mk})"/>'
        )

    # 1 you
    s.append(box(40, 160, 230, 150))
    s.append(txt(60, 196, L("你", "You"), 17, c["muted"], 600))
    s.append(txt(60, 220, L("飞书私聊里说一句", "One line in the Feishu chat"), 15, c["muted"]))
    s.append(rect(56, 236, 198, 60, 12, c["brand"], extra='fill-opacity=".18"'))
    if zh:
        s += [txt(66, 262, "给 demo-app 加个登录页，", 15, c["text"]), txt(66, 283, "邮箱加密码就行", 15, c["text"])]
    else:
        s += [
            txt(66, 260, "Login page for demo-app,", 14, c["text"]),
            txt(66, 280, "email + password is fine", 14, c["text"]),
        ]
    s.append(step(40, 160, 1))
    # 2 butler
    s.append(box(320, 140, 220, 190))
    s.append(mark_group(338, 158, 34, th, "w"))
    s.append(txt(382, 181, L("管家", "Butler"), 19, c["text"], 700))
    s.append(txt(382, 201, L("私聊里的总管", "the one you talk to"), 14, c["muted"]))
    for i, t in enumerate(
        [
            L("接话，听懂要做什么", "Takes your message"),
            L("拆成话题，分给 Agent", "Splits it into topics"),
            L("记得你的约定", "Remembers your rules"),
        ]
    ):
        s.append(
            f'<circle cx="342" cy="{236 + i * 30}" r="3" fill="{c["brand"]}"/>'
            + txt(354, 241 + i * 30, t, 16, c["text2"])
        )
    s.append(step(320, 140, 2))
    # 3 topics
    for y, tn, name in [(40, "T7", L("登录页", "Login page")), (142, "T8", L("补组件测试", "Component tests"))]:
        s.append(box(590, y, 340, 92))
        s.append(badge(606, y + 16, tn, th))
        s.append(txt(652, y + 34, name, 18, c["text"], 700))
        p, pw = pill(0, 0, L("在做", "Working"), c["blue"], th, 14)
        s.append(f'<g transform="translate({930 - pw - 16} {y + 14})">{p}</g>')
        s.append(
            txt(606, y + 68, L("独立会话 · 每轮在自己的进程里跑", "Own session · a process per turn"), 15, c["muted"])
        )
    s.append(rect(590, 244, 340, 44, 12, c["panel2"], c["stroke"]))
    s.append(txt(604, 272, L("跑在", "Runs on"), 14, c["muted"], 600))
    cx = L(644, 662)
    for lab in ["Claude Code", "Codex", "Antigravity"]:
        w = int(len(lab) * 7.1 + 17)
        s.append(
            rect(cx, 254, w, 24, 12, c["brand"], extra='fill-opacity=".16"')
            + txt(cx + w / 2, 271, lab, 14, c["text"], 600, "middle")
        )
        cx += w + 8
    s.append(box(590, 306, 340, 128, c["brand"]))
    s.append(txt(606, 336, L("专项负责人", "Project lead"), 18, c["text"], 700))
    p, pw = pill(0, 0, L("在跟进", "Tracking"), c["brand"], th, 14)
    s.append(f'<g transform="translate({930 - pw - 16} 318)">{p}</g>')
    for i, t in enumerate(
        [
            L("拆活、开话题、跟进、汇报", "Splits the work, opens topics"),
            L("话题的问题先过它", "Sees the topics' questions first"),
            L("停住了问你：继续、收尾还是停", "Asks you when the project stops"),
        ]
    ):
        s.append(
            f'<circle cx="612" cy="{361 + i * 24}" r="3" fill="{c["brand"]}"/>'
            + txt(624, 366 + i * 24, t, 15, c["text2"])
        )
    s.append(step(590, 40, 3))
    # 4 question card
    s.append(box(980, 40, 260, 206, c["orange"]))
    s.append(badge(996, 56, "T7", th))
    p, pw = pill(0, 0, L("等你", "Your call"), c["orange"], th, 14)
    s.append(f'<g transform="translate({1240 - pw - 16} 54)">{p}</g>')
    s.append(txt(996, 112, L("登录后跳到哪里？", "Where to go after login?"), 17, c["text"], 700))
    s.append(txt(996, 136, L("问题卡：停在这里等你拍板", "A question card; the topic waits"), 14, c["muted"]))
    s.append(
        rect(996, 156, 92, 38, 10, "none", c["stroke"], 1.4)
        + txt(1042, 180, L("首页（推荐）", "Home (rec.)"), 13, c["text"], 500, "middle")
    )
    s.append(
        rect(1096, 156, 124, 38, 10, c["brand"], extra='fill-opacity=".2"')
        + rect(1096, 156, 124, 38, 10, "none", c["brand"], 1.4)
        + txt(1158, 180, L("登录前打开的页面", "Page before login"), 13, c["text"], 500, "middle")
    )
    s.append(txt(996, 225, L("点选项就提交", "One click answers"), 14, c["muted"]))
    s.append(step(980, 40, 4, c["orange"]))
    # 5 result
    s.append(box(980, 296, 260, 138, c["green"]))
    s.append(badge(996, 312, "T7", th))
    p, pw = pill(0, 0, L("有结果", "Done"), c["green"], th, 14)
    s.append(f'<g transform="translate({1240 - pw - 16} 310)">{p}</g>')
    s.append(txt(996, 366, L("登录页做完了，测试通过", "Login page done, tests pass"), 16, c["text"], 700))
    s.append(txt(996, 392, L("答案卡带着产物回到私聊", "Answer card returns to the chat"), 14, c["muted"]))
    s.append(txt(996, 414, L("回复它，就是接着说", "Reply to it to carry on"), 14, c["muted"]))
    s.append(step(980, 296, 5, c["green"]))
    # arrows
    s.append(line("M272 235H316"))
    s.append(line("M542 200C566 200 566 86 586 86"))
    s.append(line("M542 235C566 235 566 188 586 188"))
    s.append(line("M542 270C566 270 566 370 586 370"))
    s.append(
        f'<path d="M934 86H956V370H934M956 143H976" fill="none" stroke="{c["arrow"]}" stroke-width="2" stroke-linecap="round"/>'
    )
    s.append(line("M956 143H976", mk="ar"))
    s.append(line("M1110 248V292", c["orange"], mk="ao"))
    s.append(txt(1124, 276, L("你拍板", "you decide"), 14, c["orange"], 600))
    s.append(line("M1110 436V462H155V316", c["green"], True, "ag"))
    lab = L("结论回到私聊", "The conclusion comes back to the chat")
    lw = int(len(lab) * (16 if zh else 8.6) + 24)
    s.append(
        rect(640 - lw / 2, 449, lw, 26, 13, c["bg"], c["stroke"]) + txt(640, 467, lab, 15, c["green"], 600, "middle")
    )
    # across band
    s.append(rect(40, 500, 1200, 118, 16, "none", c["stroke"], 1.4, extra='stroke-dasharray="7 6"'))
    s.append(
        rect(64, 488, L(110, 150), 24, 12, c["bg"], c["stroke"])
        + txt(64 + L(110, 150) / 2, 505, L("贯穿每一步", "Across every step"), 14, c["muted"], 600, "middle")
    )
    s.append(box(64, 528, 300, 76))
    s.append(txt(84, 558, L("网页工作台（可选）", "Web workbench (optional)"), 18, c["text"], 700))
    s.append(txt(84, 584, L("看板、专项、手机上也能看", "Board, projects, phone-friendly"), 14, c["muted"]))
    s.append(
        txt(396, 562, L("记忆", "Memory"), 17, c["text"], 700)
        + txt(396, 584, L("每轮都带", "in every turn"), 13, c["muted"])
    )
    mems = [
        (L("长期要求", "Standing rules"), L("你说过的偏好和规矩", "what you always want")),
        (L("记一下", "Remember this"), L("让它记住的事", "what you asked it to keep")),
        (L("专项约定", "Project decisions"), L("专项里定下的", "what a project settled")),
    ]
    x = L(500, 520)
    mw = L(220, 216)
    for i, (a, b) in enumerate(mems):
        xx = x + i * (mw + 14)
        s.append(box(xx, 528, mw, 76))
        s.append(rect(xx, 528, 5, 76, 2.5, [c["brand"], c["blue"], c["muted"]][i]))
        s.append(txt(xx + 20, 558, a, 17, c["text"], 700))
        s.append(txt(xx + 20, 584, b, 14, c["muted"]))
    s.append("</svg>")
    return "\n".join(s)


def write_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for lang in ("zh", "en"):
        for th in ("dark", "light"):
            (out / f"hero-{lang}-{th}.svg").write_text(hero(lang, th), encoding="utf-8")
            (out / f"workflow-{lang}-{th}.svg").write_text(workflow(lang, th), encoding="utf-8")
    (out / "covey-mark.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64" role="img" aria-label="Covey"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#4B52E0"/><stop offset="1" stop-color="#7C83FF"/></linearGradient></defs><rect width="64" height="64" rx="16" fill="url(#g)"/><path d="M42.6 21.4A15 15 0 1 0 42.6 42.6" fill="none" stroke="#fff" stroke-width="6" stroke-linecap="round"/><circle cx="31" cy="32" r="4.6" fill="#fff"/><circle cx="41.5" cy="32" r="2.6" fill="#fff" fill-opacity=".7"/></svg>\n',
        encoding="utf-8",
    )


def main() -> int:
    write_all(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs/media/brand")
    return 0


if __name__ == "__main__":
    sys.exit(main())
