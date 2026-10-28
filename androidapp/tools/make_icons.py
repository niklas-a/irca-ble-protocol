"""Generate legacy launcher-icon PNGs matching the adaptive vector icon.

The adaptive icon in res/mipmap-anydpi-v26 is what Android 8+ actually uses.
These bitmaps exist as the default-configuration fallback so the mipmap
resource is never config-less.

Run from the androidapp directory:  python tools/make_icons.py
"""
import math
import os

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(HERE, "res")

BG = (0x17, 0x1B, 0x22, 255)
AMBER = (0xFF, 0xC1, 0x4D, 255)
ORANGE = (0xFF, 0x5E, 0x3A, 255)
WHITE = (0xFF, 0xFF, 0xFF, 255)

# density bucket -> icon edge in px
DENSITIES = {
    "mdpi": 48, "hdpi": 72, "xhdpi": 96, "xxhdpi": 144, "xxxhdpi": 192,
}

# Supersample then downscale; PIL's arc is not antialiased.
SS = 8


START_DEG, END_DEG = 135, 405


def lerp(a, b, t):
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))


def draw_icon(size, round_shape):
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    if round_shape:
        d.ellipse((0, 0, s - 1, s - 1), fill=BG)
    else:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.22), fill=BG)

    # Same geometry as the vector: centre, radius 27/108, stroke 10/108.
    c = s / 2
    r = s * (27 / 108.0)
    w = max(1, int(s * (10 / 108.0)))
    box = (c - r, c - r, c + r, c + r)

    # Ramp the colour degree by degree. PIL has no gradient stroke and no
    # round caps, so the arc is drawn as overlapping one-degree slices and the
    # caps are added as circles.
    span = END_DEG - START_DEG
    for a in range(START_DEG, END_DEG):
        t = (a - START_DEG) / float(span)
        d.arc(box, a, a + 1.6, fill=lerp(AMBER, ORANGE, t), width=w)

    cap = w / 2.0
    for ang, col in ((START_DEG, AMBER), (END_DEG, ORANGE)):
        x = c + r * math.cos(math.radians(ang))
        y = c + r * math.sin(math.radians(ang))
        d.ellipse((x - cap, y - cap, x + cap, y + cap), fill=col)

    # thumb, centred on the hot end
    tx = c + r * math.cos(math.radians(END_DEG))
    ty = c + r * math.sin(math.radians(END_DEG))
    td = w * 0.41
    d.ellipse((tx - td, ty - td, tx + td, ty + td), fill=WHITE)

    return im.resize((size, size), Image.LANCZOS)


written = 0
for bucket, size in DENSITIES.items():
    outdir = os.path.join(RES, f"mipmap-{bucket}")
    os.makedirs(outdir, exist_ok=True)
    for name, round_shape in (("ic_launcher", False), ("ic_launcher_round", True)):
        p = os.path.join(outdir, f"{name}.png")
        draw_icon(size, round_shape).save(p, optimize=True)
        written += 1
        print(f"  {bucket:8s} {name:18s} {size}x{size}  "
              f"{os.path.getsize(p)/1024:.1f} KB")

# A big one purely so the design can be eyeballed; not shipped in the APK.
preview = os.path.join(HERE, "tools", "icon-preview.png")
draw_icon(432, False).save(preview)
print(f"\nwrote {written} icons, plus a 432px preview at {preview}")
