#!/usr/bin/env python3
"""Render the social share cover (og-cover.png) with PIL.

Kept as a build asset generator; run manually when the brand copy changes.
Uses macOS system fonts so CJK renders correctly.
"""
import os
from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
OUT = os.path.join(os.path.dirname(__file__), "..", "public", "og-cover.png")

CJK = "/System/Library/Fonts/PingFang.ttc"
SANS = "/System/Library/Fonts/Helvetica.ttc"


def font(path, size, index=0):
    return ImageFont.truetype(path, size, index=index)


img = Image.new("RGB", (W, H), "#000000")
d = ImageDraw.Draw(img)

# Subtle radial-ish vignette using concentric rectangles (top-right lighter).
for i in range(60):
    shade = 10 + int(i * 0.25)
    box = (W - i * 26, -i * 14, W, H)
    d.rectangle(box, fill=(shade, shade, shade))

img = Image.new("RGB", (W, H), "#050505")
d = ImageDraw.Draw(img)

# Dot grid, fading toward bottom-left.
for y in range(40, H, 34):
    for x in range(40, W, 34):
        # fade: brighter toward top-right
        fx = x / W
        fy = 1 - (y / H)
        a = max(0, int(26 * (0.3 + 0.7 * (fx * 0.6 + fy * 0.6))))
        d.ellipse((x, y, x + 3, y + 3), fill=(255, 255, 255, a) if False else (a, a, a))

# Brand mark
d.rounded_rectangle((96, 150, 160, 214), radius=18, fill="#ffffff")
d.rounded_rectangle((122, 176, 134, 188), radius=4, fill="#050505")

d.text((184, 168), "FastAgentFactory", font=font(SANS, 34), fill="#9a9a9a")

d.text((92, 286), "制造真正能", font=font(CJK, 92, index=1), fill="#ffffff")
d.text((92, 398), "工作的 Agent", font=font(CJK, 92, index=1), fill="#ffffff")

d.text((96, 540), "Local-first · Cross-platform · Build · Run · Distribute",
       font=font(SANS, 28), fill="#6f6f6f")

os.makedirs(os.path.dirname(OUT), exist_ok=True)
img.save(OUT, "PNG")
print("wrote", os.path.normpath(OUT))
