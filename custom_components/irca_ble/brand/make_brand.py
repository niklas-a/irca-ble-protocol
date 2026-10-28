"""Generate the brand assets HACS and home-assistant/brands expect.

Same dial mark as the Android app's launcher icon, so the two read as one
project. HACS looks for custom_components/<domain>/brand/icon.png when the
integration is not (yet) listed in the home-assistant/brands repository.

    python custom_components/irca_ble/brand/make_brand.py
"""
from __future__ import annotations

import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))

BG = (0x17, 0x1B, 0x22, 255)
AMBER = (0xFF, 0xC1, 0x4D, 255)
ORANGE = (0xFF, 0x5E, 0x3A, 255)
WHITE = (0xFF, 0xFF, 0xFF, 255)

START_DEG, END_DEG = 135, 405
SS = 6                      # supersample; PIL's arc is not antialiased


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def draw(size: int) -> Image.Image:
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BG)

    c = s / 2
    r = s * (27 / 108.0)
    w = max(1, int(s * (10 / 108.0)))
    box = (c - r, c - r, c + r, c + r)

    span = END_DEG - START_DEG
    for a in range(START_DEG, END_DEG):
        d.arc(box, a, a + 1.6, fill=lerp(AMBER, ORANGE, (a - START_DEG) / span))
    # round caps, which PIL's arc cannot draw
    cap = w / 2.0
    for ang, col in ((START_DEG, AMBER), (END_DEG, ORANGE)):
        x = c + r * math.cos(math.radians(ang))
        y = c + r * math.sin(math.radians(ang))
        d.ellipse((x - cap, y - cap, x + cap, y + cap), fill=col)

    tx = c + r * math.cos(math.radians(END_DEG))
    ty = c + r * math.sin(math.radians(END_DEG))
    td = w * 0.41
    d.ellipse((tx - td, ty - td, tx + td, ty + td), fill=WHITE)

    return im.resize((size, size), Image.LANCZOS)


# home-assistant/brands wants 256px icon/logo plus optional @2x at 512px.
for name, size in (
    ("icon.png", 256),
    ("icon@2x.png", 512),
    ("logo.png", 256),
    ("logo@2x.png", 512),
):
    path = os.path.join(HERE, name)
    draw(size).save(path, optimize=True)
    print(f"  {name:14s} {size}x{size}  {os.path.getsize(path) / 1024:.0f} KB")
