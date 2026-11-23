"""The GitHub face of the repo, drawn again from files in it: the share cover (docs/media/brand/social-preview.png)
and the flow animation in four files (docs/media/demo/flow-{zh,en}-{light,dark}.gif). The SVGs in docs/media/brand
come from scripts/brand_svgs.py.

    <python with Playwright> -B scripts/brand_assets.py social --out /absolute/docs/media [--browser /absolute/chrome]
    <python with Playwright> -B scripts/brand_assets.py panels --work /absolute/dir        [--browser /absolute/chrome]
    <python with Pillow>     -B scripts/brand_assets.py demo   --out /absolute/docs/media --work /absolute/dir
                                                                [--font /absolute/NotoSansCJK-Regular.ttc]
    --out is the docs/media directory to write into (brand/ and demo/ below it); --shots (social) defaults to
    docs/media/screenshots of this checkout, the card sketches that scripts/card_sketches.py --install writes.

The cover is an HTML page (its temp file removed after) shot at 1280x640 with a headless Chromium: the wordmark and the
two-language line on the left, on the right one whole question card and the top of the answer card under it, so no
button is covered and the cards still read as cards in a 600 px thumbnail; under 1 MB.
The animation is cut from the demo page (docs/demo/index.html, regenerate it first with scripts/card_sketches.py
--demo): `panels` shoots the four scenes' chat panels at 1x, all of one scale, 624 px wide, from it; `demo` frames them
in a 640 px canvas of 476 px with a step bar (Chinese or English words, the cards stay Chinese) on a light or a #0d1117
page, the panel with rounded corners and a thin border. Step 1 -> 2 is one scene (T7's row appears in place), the
question card stays about 4.6 seconds, the whole loop about 12 seconds, each file about 100 KB. Demo data only.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BG = "#0d1117"


def mark_svg() -> str:
    return (ROOT / "docs/media/brand/covey-mark.svg").read_text(encoding="utf-8")


def social_html(shots: Path) -> str:
    def tile(name: str, box: tuple[int, int, int, int], scale: float, left: int, top: int, z: int) -> str:
        x0, y0, x1, y1 = box  # the card's box in the sketch, shown whole at one scale
        return (f'<div class="tile" style="left:{left}px;top:{top}px;width:{round((x1 - x0) * scale)}px;'
                f'height:{round((y1 - y0) * scale)}px;z-index:{z};background-image:url(\'{(shots / name).as_uri()}\');'
                f'background-size:{round(1240 * scale)}px auto;background-position:-{round(x0 * scale)}px -{round(y0 * scale)}px"></div>')
    tiles = "".join([  # one question card, whole, and the top of the answer card under it: no button is covered
        tile("06-question-card.png", (133, 215, 1131, 1016), 0.54, 712, 50, 2),
        tile("03-answer-card.png", (133, 153, 1131, 715), 0.54, 712, 504, 1),
    ])
    return f"""<!doctype html><meta charset=utf-8><style>
*{{box-sizing:border-box}}body{{margin:0;width:1280px;height:640px;overflow:hidden;background:{BG};position:relative;
font-family:"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif;color:#EDEEF1}}
.dots{{position:absolute;inset:0;background-image:radial-gradient(#2A2F3D 1.2px,transparent 1.4px);background-size:28px 28px}}
.glow{{position:absolute;inset:0;background:radial-gradient(60% 80% at 78% 50%,rgba(124,131,255,.22),transparent 70%)}}
.fade{{position:absolute;left:0;top:0;bottom:0;width:700px;background:linear-gradient(90deg,{BG} 55%,rgba(13,17,23,0))}}
.brand{{position:absolute;left:80px;top:118px;display:flex;align-items:center;gap:28px}}
.brand svg{{width:112px;height:112px}}.brand b{{font:700 100px/1 "Noto Sans CJK SC","Helvetica Neue",Arial,sans-serif;letter-spacing:-2px}}
.zh{{position:absolute;left:82px;top:290px;font-size:40px;font-weight:600}}
.en{{position:absolute;left:82px;top:352px;font:400 27px "Noto Sans CJK SC","Helvetica Neue",Arial,sans-serif;color:#B3B7C1}}
.sub{{position:absolute;left:82px;bottom:70px;font-size:20px;color:#8A90A0;letter-spacing:.2px}}
.tile{{position:absolute;border-radius:12px;border:1px solid #30363d;box-shadow:0 18px 40px rgba(0,0,0,.55);background-repeat:no-repeat}}
</style><div class=dots></div><div class=glow></div>{tiles}<div class=fade></div>
<div class=brand>{mark_svg()}<b>Covey</b></div>
<div class=zh>在飞书里带一支编程 Agent 小队</div>
<div class=en>Run a small team of coding agents from Feishu</div>
<div class=sub>Claude Code · Codex · Antigravity</div>"""


def make_social(out: Path, shots: Path, browser: str | None) -> Path:
    from playwright.sync_api import sync_playwright
    dest = out / "brand" / "social-preview.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        page_file = Path(tmp) / "social.html"
        page_file.write_text(social_html(shots), encoding="utf-8")
        with sync_playwright() as p:
            b = p.chromium.launch(executable_path=browser) if browser else p.chromium.launch()
            page = b.new_page(viewport={"width": 1280, "height": 640})
            page.goto(page_file.as_uri())
            page.wait_for_timeout(300)
            page.screenshot(path=str(dest))
            b.close()
    try:  # shrink the palette only when the file is over the 1 MB limit of the share cover
        if dest.stat().st_size > 1_000_000:
            from PIL import Image
            Image.open(dest).convert("RGB").quantize(256).save(dest, optimize=True)
    except ImportError:
        pass
    return dest


# ---- the animation -------------------------------------------------------------------------------------------

W, BAR, PANEL_H, PAD = 640, 38, 430, 8
HEIGHT = BAR + PANEL_H + PAD
TITLES = {
    "zh": ["你在私聊里说一句话", "管家接话，开出话题 T7", "T7 遇到分叉，问题卡等你拍板", "点一下选项，就提交了", "结论和产物带回私聊"],
    "en": ["You say one sentence in the chat", "The butler opens topic T7", "T7 hits a fork: a question waits for you",
           "One tap on an option submits it", "The result and artifacts come back"],
}
THEMES = {  # page, text, muted, panel border, accent
    "light": ((255, 255, 255), (31, 35, 41), (110, 119, 129), (208, 215, 222), (75, 82, 224)),
    "dark": ((13, 17, 23), (237, 238, 241), (125, 133, 144), (48, 54, 61), (124, 131, 255)),
}
# What each scene changes on the demo page (docs/demo/index.html) before its panel is shot: the same cards at 1x, one scale.
SCENES = {
    "a": (1, "document.querySelectorAll('#step-1 .page > *').forEach((e, i) => {"
             "if (e.classList.contains('time')) e.style.display = 'none'; else if (i > 0) e.style.visibility = 'hidden'})"),
    "b": (1, "document.querySelectorAll('#step-1 .time, #step-1 .who').forEach(e => e.style.display = 'none')"),
    "c": (2, "document.querySelectorAll('#step-2 .time, #step-2 .who').forEach(e => e.style.display = 'none');"
             "document.querySelectorAll('#step-2 .phead.follow').forEach(e => {"
             "if (e.innerText.includes('怎么回答')) e.parentElement.style.display = 'none'})"),
    "d": (3, "var p = document.querySelector('#step-3 .page');"
             "p.querySelectorAll('.time').forEach(e => e.style.display = 'none'); p.querySelector('.msg').style.display = 'none'"),
}

def make_panels(work: Path, browser: str | None) -> Path:
    """Shoot the four scenes' chat panels (624 x PANEL_H, 1x) from the demo page into work/panels, with the option button's box."""
    from playwright.sync_api import sync_playwright
    dest = work / "panels"
    dest.mkdir(parents=True, exist_ok=True)
    boxes = {}
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=browser) if browser else p.chromium.launch()
        for name, (step, js) in SCENES.items():
            page = b.new_page(viewport={"width": 700, "height": 900})
            page.goto((ROOT / "docs/demo/index.html").as_uri())
            page.add_style_tag(content=f".demo .page{{width:624px;max-width:none;height:{PANEL_H}px;padding:8px 12px 4px;overflow:hidden}}")
            page.evaluate(f"show({step})")
            page.evaluate(js)
            if name in ("a", "b"):  # the card's second fold (本轮请求) stays out of the frame
                page.evaluate("document.querySelectorAll('#step-1 .phead').forEach(e => {"
                              "if (e.innerText.trim() == '本轮请求') e.parentElement.style.display = 'none'})")
            el = page.query_selector(f"#step-{step} .page")
            el.screenshot(path=str(dest / f"{name}.png"))
            if name == "c":
                r, q = el.bounding_box(), page.query_selector("#ask-open .btn.pick").bounding_box()
                boxes["pick"] = [round(q["x"] - r["x"]), round(q["y"] - r["y"]), round(q["x"] - r["x"] + q["width"]),
                                 round(q["y"] - r["y"] + q["height"])]
            page.close()
        b.close()
    (dest / "boxes.json").write_text(json.dumps(boxes), encoding="utf-8")
    return dest


def make_demo(out: Path, work: Path, font_path: str) -> list[Path]:
    """The four GIFs flow-{zh,en}-{light,dark}.gif from the panels `panels` shot."""
    from PIL import Image, ImageDraw, ImageFont
    ttc = font_path.endswith(".ttc")
    title_font = ImageFont.truetype(font_path, 17, index=2) if ttc else ImageFont.truetype(font_path, 17)
    num_font = ImageFont.truetype(font_path, 16, index=2) if ttc else ImageFont.truetype(font_path, 16)
    small = ImageFont.truetype(font_path, 13, index=2) if ttc else ImageFont.truetype(font_path, 13)
    panels = {k: Image.open(work / "panels" / f"{k}.png").convert("RGB") for k in "abcd"}
    box = json.loads((work / "panels" / "boxes.json").read_text(encoding="utf-8"))["pick"]
    (out / "demo").mkdir(parents=True, exist_ok=True)
    written = []
    for lang in ("zh", "en"):
        for theme, (page_bg, ink, muted, edge, accent) in THEMES.items():
            def scene(img: Image.Image, step: int, text: str, hl: bool = False, cursor: tuple[int, int] | None = None) -> Image.Image:
                fr = Image.new("RGB", (W, HEIGHT), page_bg)
                d = ImageDraw.Draw(fr)
                d.rounded_rectangle((PAD, 7, PAD + 24, 7 + 24), 7, fill=accent)
                d.text((PAD + 12, 19), str(step), font=num_font, fill="white" if theme == "light" else (13, 17, 23), anchor="mm")
                d.text((PAD + 36, 19), text, font=title_font, fill=ink, anchor="lm")
                d.text((W - PAD, 19), "Covey · demo", font=small, fill=muted, anchor="rm")
                im = img.copy()
                if hl:
                    ImageDraw.Draw(im, "RGBA").rounded_rectangle(box, 6, fill=(75, 82, 224, 46), outline=(75, 82, 224), width=2)
                mask = Image.new("L", im.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.width - 1, im.height - 1), 12, fill=255)
                fr.paste(im, (PAD, BAR), mask)
                d.rounded_rectangle((PAD - 1, BAR - 1, PAD + im.width, BAR + im.height), 13, outline=edge, width=1)
                if cursor:
                    cx, cy = cursor[0] + PAD, cursor[1] + BAR
                    d.polygon([(cx, cy), (cx, cy + 20), (cx + 5, cy + 15), (cx + 9, cy + 23), (cx + 12, cy + 21), (cx + 8, cy + 14),
                               (cx + 15, cy + 14)], fill=(31, 35, 41), outline="white")
                return fr
            t = TITLES[lang]
            s1, s2 = scene(panels["a"], 1, t[0]), scene(panels["b"], 2, t[1])
            s3 = scene(panels["c"], 3, t[2])
            bx, by = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
            path = [(bx + 260, by + 120), (bx + 150, by + 70), (bx + 60, by + 30), (bx + 10, by + 8)]
            moves = [scene(panels["c"], 3, t[2], cursor=q) for q in path]
            click = scene(panels["c"], 3, t[3], hl=True, cursor=(bx + 10, by + 8))
            s4 = scene(panels["d"], 4, t[4])
            # Step 1 -> 2 is one scene: T7's row appears where it will stay (one half-way frame); the rest are plain cuts.
            frames = [(s1, 1500), (Image.blend(s1, s2, 0.5), 80), (s2, 2200), (s3, 3000)]
            frames += [(m, 120) for m in moves] + [(click, 1100), (s4, 4000)]
            sheet = Image.new("RGB", (W, HEIGHT * 4))
            for k, im in enumerate((s2, s3, click, s4)):
                sheet.paste(im, (0, HEIGHT * k))
            pal = sheet.quantize(colors=192, method=Image.Quantize.FASTOCTREE, kmeans=3)  # orange, red and green keep apart
            quant = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im, _ in frames]
            dest = out / "demo" / f"flow-{lang}-{theme}.gif"
            quant[0].save(dest, save_all=True, append_images=quant[1:], duration=[ms for _, ms in frames], loop=0, optimize=True,
                          disposal=1)
            written.append(dest)
    return written


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["social", "panels", "demo"])
    ap.add_argument("--out", help="absolute docs/media directory to write into (social, demo)")
    ap.add_argument("--work", help="absolute directory the panels are shot into (panels) and read from (demo)")
    ap.add_argument("--shots", default=str(ROOT / "docs/media/screenshots"))
    ap.add_argument("--browser", help="absolute path of a Chromium or headless_shell")
    ap.add_argument("--font", default="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    a = ap.parse_args()
    shots = Path(a.shots)
    if a.what == "panels":
        if not a.work:
            ap.error("panels needs --work")
        print(make_panels(Path(a.work), a.browser))
        return 0
    if not a.out:
        ap.error(f"{a.what} needs --out")
    if a.what == "social":
        written = [make_social(Path(a.out), shots, a.browser)]
    else:
        if not a.work:
            ap.error("demo needs --work (the directory panels shot into)")
        written = make_demo(Path(a.out), Path(a.work), a.font)
    for dest in written:
        print(f"{dest} {dest.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
