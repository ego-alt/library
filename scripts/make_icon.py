"""Shelves app icon: a pane of four covers on a dark wall in a pool of warm lamplight."""

import sys

from PIL import Image, ImageDraw, ImageFilter

N = 2048  # draw large, downsample for crisp edges


def render(scale_cover=1.0):
    im = Image.new("RGB", (N, N), (20, 18, 16))  # night wall #141210
    # The lamp: a warm glow above and behind the cover.
    glow = Image.new("L", (N, N), 0)
    ImageDraw.Draw(glow).ellipse((N * 0.10, N * 0.02, N * 0.90, N * 0.86), fill=255)
    glow = glow.filter(ImageFilter.GaussianBlur(N * 0.16))
    amber = Image.new("RGB", (N, N), (150, 98, 46))
    im = Image.composite(amber, im, glow.point(lambda v: int(v * 0.80)))
    # A pane of four covers, 2x2, each 2:3, centred slightly low (light from above).
    covers = [(45, 91, 138), (164, 62, 48), (196, 150, 64), (52, 92, 72)]  # ink blue, oxblood, ochre, bottle green
    w = N * 0.215 * scale_cover
    h = w * 1.5
    gap = N * 0.05 * scale_cover
    x_left = (N - (2 * w + gap)) / 2
    y_top = (N - (2 * h + gap)) / 2 + N * 0.025
    from PIL import ImageChops

    for i, colour in enumerate(covers):
        x0 = x_left + (i % 2) * (w + gap)
        y0 = y_top + (i // 2) * (h + gap)
        sh = Image.new("L", (N, N), 0)
        ImageDraw.Draw(sh).rectangle((x0 + N * 0.006, y0 + N * 0.03, x0 + w - N * 0.006, y0 + h + N * 0.028), fill=255)
        sh = sh.filter(ImageFilter.GaussianBlur(N * 0.022))
        im = Image.composite(Image.new("RGB", (N, N), (8, 6, 4)), im, sh.point(lambda v: int(v * 0.8)))
        d = ImageDraw.Draw(im)
        d.rectangle((x0, y0, x0 + w, y0 + h), fill=colour)
        # lit from above
        hl = Image.new("L", (N, N), 0)
        ImageDraw.Draw(hl).rectangle((x0, y0, x0 + w, y0 + h * 0.55), fill=255)
        hl = hl.filter(ImageFilter.GaussianBlur(N * 0.025))
        mask = Image.new("L", (N, N), 0)
        ImageDraw.Draw(mask).rectangle((x0, y0, x0 + w, y0 + h), fill=255)
        hl = ImageChops.multiply(hl, mask).point(lambda v: int(v * 0.2))
        im = Image.composite(Image.new("RGB", (N, N), (255, 220, 170)), im, hl)
        d = ImageDraw.Draw(im)
        px = w * 0.17
        d.rectangle((x0 + px, y0 + h * 0.20, x0 + w - px, y0 + h * 0.40), fill=(244, 236, 220))
    return im


out = sys.argv[1]
full = render()
for name, size in (("icon-512.png", 512), ("icon-192.png", 192), ("apple-touch-icon.png", 180)):
    full.resize((size, size), Image.LANCZOS).save(f"{out}/{name}", optimize=True)
# Maskable: platforms crop to a circle, so keep the cover inside the safe zone.
render(0.82).resize((512, 512), Image.LANCZOS).save(f"{out}/icon-maskable-512.png", optimize=True)
# Tab favicon: the cover a little larger, so it reads at 16px.
fav = render(1.12).resize((64, 64), Image.LANCZOS)
fav.save(f"{out}/favicon.png", optimize=True)
fav.save(f"{out}/favicon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64)])
