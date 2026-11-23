"""The GitHub face of the repo, drawn again from files in it: the share cover (docs/media/brand/social-preview.png)
and the flow animation (docs/media/demo/covey-flow.gif). The SVGs in docs/media/brand come from
scripts/brand_svgs.py.

    <python with Playwright> -B scripts/brand_assets.py social --out /absolute/dir [--browser /absolute/chrome]
    <python with Pillow>     -B scripts/brand_assets.py demo   --out /absolute/dir [--font /absolute/NotoSansCJK-Regular.ttc]
    --out is the docs/media directory to write into (brand/ and demo/ below it); --shots defaults to
    docs/media/screenshots of this checkout, the card sketches that scripts/card_sketches.py --install writes.

The cover is an HTML page (kept next to the PNG's temp output, removed after) shot at 1280x640 with a headless
Chromium. The animation cuts the sketches into four steps (one sentence, T7 opened, a question answered, the answer
back), fades between them through the empty page and saves a looping GIF of about 12 seconds, 720 px wide, under
1.5 MB. Demo data only.
"""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BG = "#0d1117"


def mark_svg() -> str:
    return (ROOT / "docs/media/brand/covey-mark.svg").read_text(encoding="utf-8")


def social_html(shots: Path) -> str:
    def tile(name: str, x: int, y: int, w: int, h: int, scale: float, left: int, top: int, rot: float, z: int) -> str:
        return (f'<div class="tile" style="left:{left}px;top:{top}px;width:{int(w * scale)}px;height:{int(h * scale)}px;'
                f'transform:rotate({rot}deg);z-index:{z};background-image:url(\'{(shots / name).as_uri()}\');'
                f'background-size:{int(1240 * scale)}px auto;background-position:-{int(x * scale)}px -{int(y * scale)}px"></div>')
    tiles = "".join([
        tile("02-task-card.png", 120, 190, 1020, 640, 0.36, 880, 44, 2.0, 1),
        tile("06-question-card.png", 120, 195, 1020, 890, 0.36, 790, 150, -1.6, 2),
        tile("03-answer-card.png", 120, 150, 1020, 560, 0.36, 900, 410, 1.2, 3),
    ])
    return f"""<!doctype html><meta charset=utf-8><style>
*{{box-sizing:border-box}}body{{margin:0;width:1280px;height:640px;overflow:hidden;background:{BG};position:relative;
font-family:"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif;color:#EDEEF1}}
.dots{{position:absolute;inset:0;background-image:radial-gradient(#2A2F3D 1.2px,transparent 1.4px);background-size:28px 28px}}
.glow{{position:absolute;inset:0;background:radial-gradient(60% 80% at 78% 50%,rgba(124,131,255,.22),transparent 70%)}}
.fade{{position:absolute;left:0;top:0;bottom:0;width:760px;background:linear-gradient(90deg,{BG} 55%,rgba(13,17,23,0))}}
.brand{{position:absolute;left:80px;top:118px;display:flex;align-items:center;gap:28px}}
.brand svg{{width:112px;height:112px}}.brand b{{font:700 100px/1 "Noto Sans CJK SC","Helvetica Neue",Arial,sans-serif;letter-spacing:-2px}}
.zh{{position:absolute;left:82px;top:290px;font-size:40px;font-weight:600}}
.en{{position:absolute;left:82px;top:352px;font:400 27px "Noto Sans CJK SC","Helvetica Neue",Arial,sans-serif;color:#B3B7C1}}
.sub{{position:absolute;left:82px;bottom:70px;font-size:20px;color:#8A90A0;letter-spacing:.2px}}
.tile{{position:absolute;border-radius:14px;border:1px solid #232733;box-shadow:0 18px 40px rgba(0,0,0,.55);background-repeat:no-repeat}}
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

W, H, CAP = 720, 600, 56
PAGE = (242, 243, 245)
INDIGO = (75, 82, 224)
SCALE = 0.56


def make_demo(out: Path, shots: Path, font_path: str) -> Path:
    from PIL import Image, ImageDraw, ImageFont
    font = ImageFont.truetype(font_path, 22, index=2) if font_path.endswith(".ttc") else ImageFont.truetype(font_path, 22)
    small = ImageFont.truetype(font_path, 16, index=2) if font_path.endswith(".ttc") else ImageFont.truetype(font_path, 16)

    def crop(name: str, box: tuple[int, int, int, int], scale: float = SCALE) -> Image.Image:
        im = Image.open(shots / name).convert("RGB").crop(box)
        return im if scale == 1 else im.resize((int(im.width * scale), int(im.height * scale)), Image.LANCZOS)

    opened = crop("01-butler.png", (560, 40, 1240, 330), 1)  # the chat's right half, full size: the sentence, T7 under it
    user = opened.copy()                                     # the sentence alone: T7's row (from y 190) painted over
    ImageDraw.Draw(user).rectangle((0, 190 - 40, user.width, user.height), fill=user.getpixel((4, user.height - 4)))
    question = crop("06-question-card.png", (20, 165, 1240, 1090))
    answer = crop("01-butler.png", (20, 380, 1240, 1060))
    btn = tuple(int((v - o) * SCALE) for v, o in zip((158, 519, 357, 573), (20, 165, 20, 165)))

    def scene(img: Image.Image, step: int, text: str, hl: bool = False, cursor: tuple[int, int] | None = None) -> Image.Image:
        fr = Image.new("RGB", (W, H), PAGE)
        d = ImageDraw.Draw(fr)
        d.rounded_rectangle((20, 14, 20 + 30, 14 + 30), 8, fill=INDIGO)
        d.text((35, 29), str(step), font=font, fill="white", anchor="mm")
        d.text((64, 29), text, font=font, fill=(31, 35, 41), anchor="lm")
        d.text((W - 20, 29), "Covey · demo", font=small, fill=(143, 149, 158), anchor="rm")
        x, y = (W - img.width) // 2, CAP + max(4, (H - CAP - img.height) // 2)
        im = img.copy()
        if hl:
            od = ImageDraw.Draw(im, "RGBA")
            od.rounded_rectangle(btn, 6, fill=(75, 82, 224, 46), outline=INDIGO, width=2)
        fr.paste(im, (x, y))
        if cursor:
            cx, cy = cursor[0] + x, cursor[1] + y
            d.polygon([(cx, cy), (cx, cy + 20), (cx + 5, cy + 15), (cx + 9, cy + 23), (cx + 12, cy + 21), (cx + 8, cy + 14),
                       (cx + 15, cy + 14)], fill=(31, 35, 41), outline="white")
        return fr

    s1 = scene(user, 1, "你在私聊里说一句话")
    s2 = scene(opened, 2, "管家接话，开出话题 T7")
    s3 = scene(question, 3, "T7 遇到分叉，问题卡等你拍板")
    bx, by = (btn[0] + btn[2]) // 2, (btn[1] + btn[3]) // 2
    path = [(bx + 260, by + 120), (bx + 150, by + 70), (bx + 60, by + 30), (bx + 10, by + 8)]
    moves = [scene(question, 3, "T7 遇到分叉，问题卡等你拍板", cursor=p) for p in path]
    click = scene(question, 3, "点一下选项，就提交了", hl=True, cursor=(bx + 10, by + 8))
    s4 = scene(answer, 4, "结论和产物带回私聊")
    timeline: list[tuple[Image.Image, int]] = [(s1, 1500), (s2, 2200), (s3, 1500)]
    timeline += [(m, 120) for m in moves] + [(click, 1100), (s4, 4000)]
    blank = Image.new("RGB", (W, H), PAGE)
    frames: list[tuple[Image.Image, int]] = []
    for i, (im, ms) in enumerate(timeline):
        frames.append((im, ms))
        nxt = timeline[(i + 1) % len(timeline)][0]
        if im is s1:  # the same picture: T7's row fades in under the sentence
            frames += [(Image.blend(im, nxt, a), 70) for a in (0.33, 0.66)]
        elif any(im is x for x in (s2, click, s4)):  # another picture: through the empty page, never two cards at once
            frames += [(Image.blend(im, blank, 0.6), 60), (Image.blend(blank, nxt, 0.6), 60)]
    # One palette for every frame, taken from all the scenes so the tags' orange, green and blue keep their colours.
    sheet = Image.new("RGB", (W, H * 4))
    for k, im in enumerate((s2, s3, click, s4)):
        sheet.paste(im, (0, H * k))
    pal = sheet.quantize(colors=128, method=Image.Quantize.FASTOCTREE, kmeans=3)
    quant = [im.quantize(palette=pal, dither=Image.Dither.NONE) for im, _ in frames]
    dest = out / "demo" / "covey-flow.gif"
    dest.parent.mkdir(parents=True, exist_ok=True)
    quant[0].save(dest, save_all=True, append_images=quant[1:], duration=[ms for _, ms in frames], loop=0, optimize=True,
                  disposal=1)
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["social", "demo"])
    ap.add_argument("--out", required=True, help="absolute docs/media directory to write into")
    ap.add_argument("--shots", default=str(ROOT / "docs/media/screenshots"))
    ap.add_argument("--browser", help="absolute path of a Chromium or headless_shell")
    ap.add_argument("--font", default="/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
    a = ap.parse_args()
    out, shots = Path(a.out), Path(a.shots)
    dest = make_social(out, shots, a.browser) if a.what == "social" else make_demo(out, shots, a.font)
    print(f"{dest} {dest.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
