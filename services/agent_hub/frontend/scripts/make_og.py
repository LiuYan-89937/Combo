#!/usr/bin/env python3
"""Generate Combo's social preview from the canonical PNG brand assets."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


WIDTH, HEIGHT = 1200, 630
ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public" / "og-cover.png"
LOGO = ROOT / "public" / "brand" / "combo" / "logo-mark.png"
MASCOT = ROOT / "public" / "brand" / "combo" / "frames" / "paired" / "idle" / "frame-01.png"
CHINESE_FONT = "/System/Library/Fonts/STHeiti Medium.ttc"
LATIN_FONT = "/System/Library/Fonts/Helvetica.ttc"


def font(path: str, size: int, index: int = 0) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, index=index)


def fit(image: Image.Image, maximum: tuple[int, int]) -> Image.Image:
    copy = image.copy()
    copy.thumbnail(maximum, Image.Resampling.LANCZOS)
    return copy


canvas = Image.new("RGB", (WIDTH, HEIGHT), "#f7f7f5")
draw = ImageDraw.Draw(canvas)

for x in range(40, WIDTH, 32):
    for y in range(38, HEIGHT, 32):
        draw.ellipse((x, y, x + 2, y + 2), fill="#deded9")

draw.rounded_rectangle((56, 52, WIDTH - 56, HEIGHT - 52), radius=44, fill="#ffffff", outline="#ddddda", width=2)

logo = fit(Image.open(LOGO).convert("RGBA"), (58, 58))
canvas.paste(logo, (94, 91), logo)
draw.text((162, 102), "Combo", font=font(LATIN_FONT, 34), fill="#0a0a0a")
draw.text((164, 139), "LOCAL AGENT WORKSPACE", font=font(LATIN_FONT, 11), fill="#777777")

draw.text((92, 232), "说出目标，", font=font(CHINESE_FONT, 74, index=1), fill="#0a0a0a")
draw.text((92, 320), "剩下的让 Combo 组合起来", font=font(CHINESE_FONT, 64, index=1), fill="#0a0a0a")
draw.text((96, 444), "你的模型 · 你的能力 · 你的工作区", font=font(CHINESE_FONT, 27, index=1), fill="#777777")

draw.ellipse((835, 120, 1090, 375), fill="#f1f1ee", outline="#d9d9d4", width=2)
mascot = fit(Image.open(MASCOT).convert("RGBA"), (230, 230))
mascot_x = 962 - mascot.width // 2
mascot_y = 248 - mascot.height // 2
canvas.paste(mascot, (mascot_x, mascot_y), mascot)

for label, position in (("SKILL", (790, 424)), ("TOOL", (910, 462)), ("MCP", (1020, 418))):
    x, y = position
    draw.rounded_rectangle((x, y, x + 80, y + 34), radius=17, fill="#ffffff", outline="#d6d6d2", width=2)
    draw.text((x + 18, y + 10), label, font=font(LATIN_FONT, 11), fill="#444444")

draw.rounded_rectangle((92, 519, 317, 567), radius=24, fill="#090909")
draw.text((135, 533), "Download Combo", font=font(LATIN_FONT, 16), fill="#ffffff")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUTPUT, "PNG", optimize=True)
print(f"wrote {OUTPUT}")
