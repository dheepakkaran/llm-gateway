"""Redesigned card scenes: aurora background, word-by-word blur-in, light sweep,
flowing packets in the architecture diagram, count-up result cards.
All layers come from media/cards (cards.py); timings come from the narration cues."""
import json
import math
import pathlib
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[2]
CARDS = ROOT / "media" / "cards"
LAYOUT = json.loads((CARDS / "layout.json").read_text())
OW, OH = 1920, 1080


def ease(x):
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def out_cubic(x):
    x = min(1.0, max(0.0, x))
    return 1 - (1 - x) ** 3


def spring(x):
    """0 -> 1 with a small overshoot (damped)."""
    x = max(0.0, x)
    return 1 - math.exp(-6 * x) * math.cos(9 * x)


@lru_cache(maxsize=None)
def layer(name):
    im = Image.open(CARDS / f"{name}.png").convert("RGBA")
    return im.resize((im.width // 2, im.height // 2), Image.Resampling.LANCZOS)


@lru_cache(maxsize=None)
def pieces(name):
    """Per-word (or per-letter) crops of a block, with their offsets (1x px)."""
    im = layer(name)
    out = []
    for x, y, w, h in LAYOUT[name]["words"]:
        pad = 6
        box = (max(0, int(x) - pad), max(0, int(y) - pad), min(im.width, int(x + w) + pad), min(im.height, int(y + h) + pad))
        out.append((box[0], box[1], im.crop(box)))
    return out


def fade(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def put(base, im, x, y, a=1.0, blur=0.0):
    if a <= 0.003:
        return
    if blur > 0.4:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    base.alpha_composite(fade(im, a), (int(round(x)), int(round(y))))


def reveal(base, name, x, y, t, t0, stagger=0.07, dur=0.55, rise=18, blur=9):
    """Word-by-word: each word rises, sharpens from blur and fades in."""
    if t < t0 - 0.05:
        return
    for i, (dx, dy, im) in enumerate(pieces(name)):
        p = out_cubic((t - t0 - i * stagger) / dur)
        if p <= 0:
            continue
        put(base, im, x + dx, y + dy + rise * (1 - p), p, blur * (1 - p))


def block_in(base, name, x, y, t, t0, dur=0.7, rise=24, blur=10, scale_from=1.0):
    p = out_cubic((t - t0) / dur)
    if p <= 0:
        return
    im = layer(name)
    if scale_from != 1.0:
        s = scale_from + (1 - scale_from) * p
        im = im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))), Image.Resampling.BICUBIC)
        x += (layer(name).width - im.width) / 2
        y += (layer(name).height - im.height) / 2
    put(base, im, x, y + rise * (1 - p), p, blur * (1 - p))


def sweep(base, name, x, y, t, t0, dur=1.3):
    """A soft diagonal light band crossing the block, masked to its letters."""
    p = (t - t0) / dur
    if not 0 < p < 1:
        return
    im = layer(name)
    w, h = im.size
    band = np.zeros((h, w), np.float32)
    xx = np.arange(w)[None, :] + np.arange(h)[:, None] * 0.35
    c = -0.2 * w + p * 1.5 * w
    band = np.exp(-((xx - c) / (0.07 * w)) ** 2) * 0.85
    a = np.asarray(im.getchannel("A"), np.float32) / 255 * band
    glow = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    glow.putalpha(Image.fromarray((a * 255).astype(np.uint8)))
    base.alpha_composite(glow, (int(x), int(y)))


# ---------------------------------------------------------------- background

_rng = np.random.default_rng(11)
GRAIN = Image.fromarray(np.clip(_rng.normal(0, 3.2, (OH, OW)) + 128, 0, 255).astype(np.uint8))


def _grid():
    g = Image.new("RGBA", (OW, OH), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    for gx in range(22, OW, 44):
        for gy in range(22, OH, 44):
            r = math.hypot((gx - OW / 2) / OW, (gy - OH * 0.45) / OH)
            a = int(max(0.0, 1 - r * 1.7) * 30)
            if a > 1:
                d.ellipse((gx - 1.3, gy - 1.3, gx + 1.3, gy + 1.3), fill=(170, 200, 255, a))
    return g


GRID = _grid()
_yy, _xx = np.mgrid[0:135, 0:240].astype(np.float32)
_u, _v = _xx / 240, _yy / 135


def background(t, warm=0.0):
    img = np.zeros((135, 240, 3), np.float32) + np.array([5, 7, 11], np.float32)
    blobs = [(0.24 + 0.07 * math.sin(0.21 * t), 0.18 + 0.06 * math.cos(0.17 * t), 0.42, (58, 104, 255), 0.42),
             (0.82 + 0.05 * math.cos(0.19 * t), 0.80 + 0.06 * math.sin(0.23 * t), 0.48, (24, 196, 236), 0.20),
             (0.56 + 0.09 * math.sin(0.13 * t + 1), 0.02 + 0.05 * math.sin(0.2 * t), 0.34, (139, 92, 246), 0.26)]
    if warm > 0:
        blobs.append((0.78, 0.35, 0.45, (251, 113, 133), 0.28 * warm))
    for cx, cy, r, col, s in blobs:
        d2 = (((_u - cx) * 16 / 9) ** 2 + (_v - cy) ** 2) / (r * r)
        img += (np.array(col, np.float32) - img) * (s * np.exp(-2.2 * d2))[..., None]
    bg = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((OW, OH), Image.Resampling.BICUBIC)
    bg = Image.blend(bg, Image.merge("RGB", (GRAIN, GRAIN, GRAIN)), 0.035).convert("RGBA")
    bg.alpha_composite(GRID)
    return bg


def push(img, L, dur, amount=0.035):
    """Slow camera push-in over the scene."""
    s = 1 + amount * ease(L / max(dur, 0.1))
    w, h = OW / s, OH / s
    return img.resize((OW, OH), Image.Resampling.BICUBIC, box=((OW - w) / 2, (OH - h) / 2, (OW + w) / 2, (OH + h) / 2))


def cx(name):
    return (OW - layer(name).width) / 2


# ---------------------------------------------------------------- scenes

def title(L, cue, D, dur):
    b = background(L)
    c0 = cue["title"]
    block_in(b, "eyebrow", cx("eyebrow"), 352, L, 0.15, dur=0.8, rise=14)
    reveal(b, "title", cx("title"), 400, L, c0 - 0.1, stagger=0.045, dur=0.7, rise=34, blur=14)
    sweep(b, "title", cx("title"), 400, L, c0 + 1.6)
    reveal(b, "subtitle", cx("subtitle"), 672, L, c0 + 1.25, stagger=0.085, dur=0.6)
    return push(b, L, dur)


def problem(L, cue, D, dur):
    warm = ease((L - cue["p3"]) / 0.8)
    b = background(L + 5, warm=warm)
    X = 130
    block_in(b, "prob_label", X, 210, L, 0.1, rise=10)
    y = 262
    for k in ("p1", "p2", "p3"):
        reveal(b, k, X, y, L, cue[k] - 0.05, stagger=0.055, dur=0.5)
        y += layer(k).height + 26
    # live log: the same request again and again, faster and faster
    head = layer("log_head")
    lx, ly = 1040, 210
    a = out_cubic((L - (cue["p1"] + 0.3)) / 0.8)
    if a > 0:
        card = head.copy()
        rows = layer("log_rows")
        t1, t2 = cue["p1"] + 0.6, cue["p2"]
        n = 0.0
        if L > t1:
            n = (min(L, t2) - t1) / 0.55
        if L > t2:
            x = L - t2
            n += 1.8 * x + 3.2 * x * x      # accelerating
        rh, vis_top, vis_h = 36, 74, 600 - 74 - 16
        shown = min(int(n), 160)
        off = max(0, shown * rh - vis_h)
        crop = rows.crop((0, off, rows.width, off + min(vis_h, shown * rh)))
        if crop.height > 0:
            card.alpha_composite(crop, (30, vis_top + max(0, vis_h - crop.height) if shown * rh < vis_h else vis_top))
        if warm > 0:
            glow = Image.new("RGBA", card.size, (0, 0, 0, 0))
            ImageDraw.Draw(glow).rounded_rectangle((1, 1, card.width - 2, card.height - 2), 26,
                                                   outline=(251, 113, 133, int(200 * warm)), width=3)
            card.alpha_composite(glow)
        put(b, card, lx, ly + 30 * (1 - a), a, 8 * (1 - a))
        # spend bar under the log (no numbers: it just keeps growing)
        bar_y = ly + head.height + 34
        frac = min(1.0, math.log1p(n) / math.log1p(160))
        d = ImageDraw.Draw(b)
        d.rounded_rectangle((lx, bar_y, lx + 780, bar_y + 12), 6, fill=(255, 255, 255, int(22 * a)))
        if frac > 0:
            col = (int(253 - 2 * frac * 0), int(186 - 73 * frac), int(116 + 17 * frac), int(255 * a))
            d.rounded_rectangle((lx, bar_y, lx + int(780 * frac), bar_y + 12), 6, fill=col)
    return push(b, L, dur, 0.025)


def _line_pts(A):
    """Connection lines (1x px, relative to the diagram) from the measured anchor boxes."""
    gx, gy, gw, gh = A["gw"]
    pts = []
    for i, k in enumerate(("a0", "a1", "a2")):
        x, y, w, h = A[k]
        pts.append(((x + w + 8, y + h / 2), (gx - 8, gy + gh * (0.32 + 0.18 * i))))
    for i, k in enumerate(("p0", "p1")):
        x, y, w, h = A[k]
        pts.append(((gx + gw + 8, gy + gh * (0.42 + 0.2 * i)), (x - 8, y + h / 2)))
    return pts


@lru_cache(maxsize=4)
def _dot(rgb, r=5):
    s = r * 6
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((s / 2 - r * 2.2, s / 2 - r * 2.2, s / 2 + r * 2.2, s / 2 + r * 2.2), fill=rgb + (90,))
    im = im.filter(ImageFilter.GaussianBlur(r))
    ImageDraw.Draw(im).ellipse((s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r), fill=rgb + (255,))
    return im


def idea(L, cue, D, dur):
    b = background(L + 9)
    A = LAYOUT["dg_anchors"]
    block_in(b, "idea_label", cx("idea_label"), 104, L, 0.1, rise=10)
    reveal(b, "idea_head", cx("idea_head"), 146, L, cue["i1"] - 0.05, stagger=0.06)
    ox, oy = (OW - layer("dg_base").width) / 2, 318
    t_dg = cue["i1"] + 0.35
    a = out_cubic((L - t_dg) / 0.8)
    trip = cue["i2"] + 0.2
    tripped = ease((L - trip) / 0.5)
    if a > 0:
        dg = layer("dg_base").copy()
        d = ImageDraw.Draw(dg)
        lines = _line_pts(A)
        for i, (p, q) in enumerate(lines):
            red = i == 2 and tripped > 0
            col = (251, 113, 133, int(150 * tripped)) if red else (122, 167, 255, 90)
            d.line([p, q], fill=col, width=2)
        # flowing packets
        flow_t = max(0.0, L - t_dg)
        for i, (p, q) in enumerate(lines):
            for k in range(3):
                ph = (flow_t / 1.25 + k / 3 + i * 0.13) % 1.0
                if i == 2 and L > trip:                 # loop-bot: packets die at the gateway
                    ph = min(ph, 0.93)
                    rgb = (251, 113, 133)
                else:
                    rgb = (94, 225, 245) if i < 3 else (167, 139, 250)
                x = p[0] + (q[0] - p[0]) * ph
                y = p[1] + (q[1] - p[1]) * ph
                al = min(1.0, ph * 6, (1 - ph) * 6) if not (i == 2 and L > trip) else (1.0 if ph < 0.93 else 0.55)
                dot = _dot(rgb)
                dg.alpha_composite(fade(dot, al * min(1.0, flow_t * 2)), (int(x - dot.width / 2), int(y - dot.height / 2)))
        # check rows tick in one by one
        checks = layer("dg_checks")
        for k in range(4):
            x, y, w, h = A[f"c{k}"]
            pk = out_cubic((L - (t_dg + 0.5 + 0.32 * k)) / 0.35)
            if pk > 0:
                crop = checks.crop((int(x) - 4, int(y) - 4, int(x + w) + 4, int(y + h) + 4))
                dg.alpha_composite(fade(crop, pk), (int(x) - 4 + int(10 * (1 - pk)), int(y) - 4))
        if tripped > 0:
            x, y, w, h = A["a2"]
            dg.alpha_composite(fade(layer("dg_tripped"), tripped), (int(x), int(y)))
            sx, sy = lines[2][1]
            r = 16
            dd = ImageDraw.Draw(dg)
            dd.ellipse((sx - r - 10, sy - r, sx + r - 10, sy + r), fill=(40, 10, 16, int(230 * tripped)),
                       outline=(251, 113, 133, int(255 * tripped)), width=3)
            dd.line((sx - 17, sy - 7, sx - 3, sy + 7), fill=(251, 113, 133, int(255 * tripped)), width=3)
            dd.line((sx - 17, sy + 7, sx - 3, sy - 7), fill=(251, 113, 133, int(255 * tripped)), width=3)
        put(b, dg, ox, oy + 26 * (1 - a), a, 8 * (1 - a))
    # Telegram-style toast slides in
    ts = cue["i2"] + D["i2"] * 0.55
    st = spring((L - ts) / 0.9)
    if L > ts:
        toast = layer("toast")
        put(b, toast, 1190 + (1 - min(st, 1)) * 140, 716, min(1.0, (L - ts) * 3))
    reveal(b, "idea_foot", cx("idea_foot"), 938, L, cue["i2"] + 0.1, stagger=0.06)
    return push(b, L, dur, 0.025)


def telegram(L, cue, D, dur):
    b = background(L + 13)
    c = layer("tg")
    st = spring((L - 0.15) / 1.1)
    a = min(1.0, max(0.0, (L - 0.15) * 2.5))
    put(b, c, cx("tg"), 300 - 90 * (1 - st), a, 6 * (1 - a))
    return push(b, L, dur, 0.02)


def results(L, cue, D, dur):
    b = background(L + 17)
    block_in(b, "res_label", cx("res_label"), 330, L, 0.15, rise=10)
    gap, w = 30, layer("res0_001").width
    x0 = (OW - (4 * w + 3 * gap)) / 2
    calls = len([n for n in LAYOUT if n.startswith("res0_")])
    steps = len([n for n in LAYOUT if n.startswith("res1_")]) - 1
    for i in range(4):
        t0 = 0.45 + 0.17 * i
        p = out_cubic((L - t0) / 0.7)
        if p <= 0:
            continue
        cnt = ease((L - t0 - 0.2) / 0.9)
        name = {0: f"res0_{max(1, round(cnt * calls)):03d}", 1: f"res1_{round(cnt * steps):03d}",
                2: "res2_000", 3: "res3_000"}[i]
        put(b, layer(name), x0 + i * (w + gap), 400 + 30 * (1 - p), p, 9 * (1 - p))
    block_in(b, "res_note", cx("res_note"), 740, L, 1.6, rise=8)
    return push(b, L, dur, 0.025)


def end(L, cue, D, dur):
    b = background(L + 21)
    reveal(b, "end_title", cx("end_title"), 360, L, 0.3, stagger=0.04, dur=0.7, rise=30, blur=14)
    sweep(b, "end_title", cx("end_title"), 360, L, 1.6)
    block_in(b, "end_link_0", cx("end_link_0"), 585, L, 1.0)
    block_in(b, "end_link_1", cx("end_link_1"), 670, L, 1.2)
    block_in(b, "end_by", cx("end_by"), 775, L, 1.6, rise=10)
    block_in(b, "end_stack", cx("end_stack"), 835, L, 1.9, rise=8)
    img = push(b, L, dur, 0.03)
    f = ease((L - (dur - 1.3)) / 1.3)
    if f > 0:
        img = Image.blend(img.convert("RGB"), Image.new("RGB", (OW, OH)), f).convert("RGBA")
    return img
