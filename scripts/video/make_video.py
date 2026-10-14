#!/usr/bin/env python3
"""Edit and encode the product video (step 3).

Composes captured footage (media/raw), overlays (media/overlays) and music
(media/build/music.wav) into media/llm-gateway-demo.mp4 (1920x1080, 30 fps):
rounded browser window on a gradient, eased camera zoom/pan that follows the
cursor, click ripples, crossfades, time-compressed live demo and captions.

Usage: make_video.py [--from S --to S] [--preview]   (preview = every 6th frame)
"""
import argparse
import bisect
import json
import math
import pathlib
import subprocess
from functools import lru_cache

import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

import storyboard as sb

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW, OVL, BUILD = ROOT / "media" / "raw", ROOT / "media" / "overlays", ROOT / "media" / "build"
OW, OH, FPS = 1920, 1080, 30
CW, CH = 3840, 2160
CONT_W, CONT_H = 3200, 1800
WX = (CW - CONT_W) // 2
BAR_H = 76
WY = (CH - CONT_H - BAR_H) // 2
CY0 = WY + BAR_H
ACCENT = (82, 180, 226)
CAP = json.loads((RAW / "capture.json").read_text())
T0 = CAP["demo"][0]["t"]
FRAMES = [(d["t"] - T0, d["file"]) for d in CAP["demo"]]
FRAME_TS = [f[0] for f in FRAMES]
CLICK = CAP["click_t"] - T0


# ---------------------------------------------------------------- helpers

def ease(x):
    x = min(1.0, max(0.0, x))
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def keyed(keys, t):
    """keys: [(t, v1, v2, ...)] -> eased interpolation of the values at t."""
    if t <= keys[0][0]:
        return keys[0][1:]
    for (ta, *a), (tb, *b) in zip(keys, keys[1:]):
        if t <= tb:
            p = ease((t - ta) / (tb - ta)) if tb > ta else 1
            return tuple(x + (y - x) * p for x, y in zip(a, b))
    return keys[-1][1:]


def css(xc, yc, sy=0):
    """CSS px on the captured page -> 4K canvas px (sy = scroll in source px)."""
    return WX + 2 * xc, CY0 + 2 * yc - sy


def gradient(w, h, seed=3):
    y, x = np.mgrid[0:h, 0:w].astype(np.float32)
    u, v = x / w, y / h
    img = np.zeros((h, w, 3), np.float32)
    top, bot = np.array([10, 15, 22]), np.array([15, 27, 40])
    img += top + (bot - top) * ((u + v) / 2)[..., None]
    for (gx, gy, r, col, a) in [(0.16, 0.08, 0.55, ACCENT, 0.20), (0.88, 0.95, 0.6, (96, 104, 210), 0.13),
                                 (0.55, 0.5, 0.9, (40, 90, 120), 0.06)]:
        d = np.sqrt(((u - gx) * w / h) ** 2 + (v - gy) ** 2) / r
        img += (np.array(col) - img) * (a * np.clip(1 - d, 0, 1) ** 2)[..., None]
    img += np.random.default_rng(seed).normal(0, 1.2, img.shape)  # grain: no banding
    return Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))


@lru_cache(maxsize=None)
def ovl(name, scale=0.5):
    im = Image.open(OVL / f"{name}.png").convert("RGBA")
    return im.resize((round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS)


def with_alpha(im, a):
    if a >= 0.999:
        return im
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: int(v * a)))
    return im


def place(base, im, x, y, a):
    if a <= 0.001:
        return
    base.alpha_composite(with_alpha(im, a), (int(x), int(y)))


def appear(t, t_in, dur=0.6, t_out=None, out_dur=0.4):
    a = ease((t - t_in) / dur)
    if t_out is not None:
        a *= 1 - ease((t - t_out) / out_dur)
    return a


# ---------------------------------------------------------------- static layers

BG4K = gradient(CW, CH)
BGCARD = gradient(2000, 1125, seed=5)
SHADOW = Image.new("RGBA", (CW, CH), (0, 0, 0, 0))
_d = ImageDraw.Draw(SHADOW)
_d.rounded_rectangle((WX, WY + 30, WX + CONT_W, WY + BAR_H + CONT_H + 40), 40, fill=(0, 0, 0, 170))
SHADOW = SHADOW.filter(ImageFilter.GaussianBlur(55))
BG_WIN = Image.alpha_composite(BG4K.convert("RGBA"), SHADOW).convert("RGB")
WIN_MASK = Image.new("L", (CONT_W, CONT_H + BAR_H), 0)
ImageDraw.Draw(WIN_MASK).rounded_rectangle((0, 0, CONT_W - 1, CONT_H + BAR_H - 1), 34, fill=255)


def cursor_sprite(size=64):
    s = 4
    pts = [(0, 0), (0, 46), (11, 35), (19, 53), (27, 50), (19, 32), (34, 32)]
    im = Image.new("RGBA", (40 * s, 58 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.polygon([(x * s + 3 * s, y * s + 3 * s) for x, y in pts], fill=(0, 0, 0, 90))
    im = im.filter(ImageFilter.GaussianBlur(2 * s))
    d = ImageDraw.Draw(im)
    d.polygon([(x * s, y * s) for x, y in pts], fill=(255, 255, 255, 255), outline=(20, 20, 20, 255), width=2 * s)
    return im.resize((round(40 * size / 58), size), Image.Resampling.LANCZOS)


CURSOR = cursor_sprite(64)


@lru_cache(maxsize=6)
def load(path):
    return Image.open(path).convert("RGB")


@lru_cache(maxsize=4)
def bar(name):
    return Image.open(OVL / f"{name}.png").convert("RGB").resize((CONT_W, BAR_H), Image.Resampling.LANCZOS)


# ---------------------------------------------------------------- screen scene renderer

@lru_cache(maxsize=8)
def spot_mask(rect):
    m = Image.new("L", (CW // 4, CH // 4), 0)
    x0, y0, x1, y1 = (v // 4 for v in rect)
    ImageDraw.Draw(m).rounded_rectangle((x0, y0, x1, y1), 10, fill=255)
    return m.filter(ImageFilter.GaussianBlur(14)).resize((CW, CH), Image.Resampling.BILINEAR)


DARK = Image.new("RGB", (CW, CH), (6, 9, 13))


def screen(content, bar_name, cam, cursor=None, clicks=(), t=0.0, spot=None):
    """content: RGB 3200x1800; cam: (cx, cy, z) canvas coords; cursor: (x, y, alpha);
    spot: (rect, strength) dims everything outside rect, to focus the eye."""
    canvas = BG_WIN.copy()
    win = Image.new("RGB", (CONT_W, CONT_H + BAR_H))
    win.paste(bar(bar_name), (0, 0))
    win.paste(content, (0, BAR_H))
    canvas.paste(win, (WX, WY), WIN_MASK)
    if spot and spot[1] > 0.01:
        rect, k = spot
        inv = spot_mask(rect).point(lambda v: int((255 - v) * 0.62 * k))
        canvas = Image.composite(DARK, canvas, inv)
    if cursor and cursor[2] > 0.01:
        cv = canvas.convert("RGBA")
        for (ct, cxp, cyp) in clicks:
            p = (t - ct) / 0.6
            if 0 <= p <= 1:
                ring = Image.new("RGBA", (300, 300), (0, 0, 0, 0))
                r = 18 + 110 * ease(p)
                ImageDraw.Draw(ring).ellipse((150 - r, 150 - r, 150 + r, 150 + r), outline=ACCENT + (int(200 * (1 - p)),), width=8)
                cv.alpha_composite(ring, (int(cxp - 150), int(cyp - 150)))
        press = min((abs(t - ct) for ct, *_ in clicks), default=9)
        sc = 0.82 if press < 0.12 else 1.0
        cur = CURSOR if sc == 1 else CURSOR.resize((int(CURSOR.width * sc), int(CURSOR.height * sc)))
        place(cv, cur, cursor[0], cursor[1], cursor[2])
        canvas = cv.convert("RGB")
    cx, cy, z = cam
    w, h = CW / z, CH / z
    cx = min(max(cx, w / 2), CW - w / 2)
    cy = min(max(cy, h / 2), CH - h / 2)
    box = (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
    return canvas.resize((OW, OH), Image.Resampling.LANCZOS, box=box, reducing_gap=2.0)


def page_crop(path, sy):
    im = load(path)
    sy = int(max(0, min(sy, im.height - CONT_H)))
    return im.crop((0, sy, CONT_W, sy + CONT_H))


def demo_frame(src_t):
    i = max(0, bisect.bisect_right(FRAME_TS, src_t) - 1)
    return load(RAW / FRAMES[i][1])


# ---------------------------------------------------------------- card scenes

def card_bg(t):
    dx, dy = 40 + 38 * math.sin(t * 0.25), 22 + 20 * math.cos(t * 0.21)
    return BGCARD.crop((int(dx), int(dy), int(dx) + OW, int(dy) + OH)).convert("RGBA")


def center_x(im):
    return (OW - im.width) / 2


def scene_title(L):
    b = card_bg(L)
    e, m, s = ovl("title_eyebrow"), ovl("title_main"), ovl("title_sub")
    y = 340
    place(b, e, center_x(e), y + 30 * (1 - appear(L, 0.2)), appear(L, 0.2))
    place(b, m, center_x(m), y + 50 + 40 * (1 - appear(L, 0.35, 0.8)), appear(L, 0.35, 0.8))
    place(b, s, center_x(s), y + 250 + 30 * (1 - appear(L, 0.9)), appear(L, 0.9))
    lw = int(560 * ease((L - 1.1) / 0.9))
    if lw > 2:
        ImageDraw.Draw(b).rounded_rectangle(((OW - lw) / 2, y + 225, (OW + lw) / 2, y + 229), 2, fill=ACCENT + (255,))
    return b


def scene_problem(L, cue):
    b = card_bg(L + 5)
    lab = ovl("prob_label")
    place(b, lab, 170, 250, appear(L, 0.15))
    y = 310
    for i, t_in in enumerate((cue["p1"] - 0.15, cue["p2"] - 0.15, cue["p3"] - 0.15)):
        im = ovl(f"prob_{i}")
        place(b, im, 170, y + 26 * (1 - appear(L, t_in, 0.7)), appear(L, t_in, 0.7))
        y += im.height + 34
    return b


def scene_idea(L, cue):
    b = card_bg(L + 9)
    lab, head, foot = ovl("idea_label"), ovl("idea_headline"), ovl("idea_footer")
    place(b, lab, center_x(lab), 120, appear(L, 0.1))
    place(b, head, center_x(head), 160 + 24 * (1 - appear(L, 0.3)), appear(L, 0.3))
    d1 = D["i1"]
    times = [0.6, cue["i1"] + d1 * 0.42, cue["i1"] + d1 * 0.78, cue["i2"] + 0.25]
    for s, t_in in enumerate(times):
        d = ovl(f"diagram_{s}")
        nxt = times[s + 1] if s + 1 < len(times) else None
        a = appear(L, t_in, 0.5) * (1 - appear(L, nxt, 0.5) if nxt else 1)
        place(b, d, center_x(d), 330, a)
    tf = cue["i2"] + D["i2"] * 0.32
    place(b, foot, center_x(foot), 925 + 20 * (1 - appear(L, tf)), appear(L, tf))
    return b


def scene_telegram(L):
    b = card_bg(L + 13)
    c = ovl("tg_card")
    a = appear(L, 0.15, 0.7)
    sc = 0.94 + 0.06 * a
    cc = c.resize((int(c.width * sc), int(c.height * sc)), Image.Resampling.LANCZOS)
    place(b, cc, center_x(cc), 250 + (c.height - cc.height) / 2 + 40 * (1 - a), a)
    return b


def scene_results(L):
    b = card_bg(L + 17)
    lab = ovl("res_label")
    place(b, lab, center_x(lab), 300, appear(L, 0.1))
    tiles = [ovl(f"res_{i}") for i in range(4)]
    total = sum(t.width for t in tiles) + 3 * 34
    x = (OW - total) / 2
    for i, im in enumerate(tiles):
        a = appear(L, 0.35 + 0.22 * i, 0.6)
        place(b, im, x, 370 + 40 * (1 - a), a)
        x += im.width + 34
    return b


def scene_end(L, dur):
    b = card_bg(L + 21)
    t, l0, l1, by = ovl("end_title"), ovl("end_link_0"), ovl("end_link_1"), ovl("end_byline")
    place(b, t, center_x(t), 330 + 30 * (1 - appear(L, 0.15, 0.8)), appear(L, 0.15, 0.8))
    place(b, l0, center_x(l0), 530, appear(L, 0.8))
    place(b, l1, center_x(l1), 600, appear(L, 1.1))
    place(b, by, center_x(by), 720, appear(L, 1.5))
    fade = ease((L - (dur - 1.2)) / 1.2)
    if fade > 0:
        b = Image.blend(b, Image.new("RGBA", (OW, OH), (0, 0, 0, 255)), fade)
    return b


# ---------------------------------------------------------------- screen scenes

BOX = CAP["site"]["full_boxes"]
TOP = CAP["site"]["top_boxes"]


def cxy(sel, boxes=BOX):
    b = boxes[sel]
    return b["x"] + b["w"] / 2, b["y"] + b["h"] / 2


TOUR_SCROLL = [(0, 0), (2.6, 0), (3.8, 1640), (7.3, 1640), (8.3, 3120), (11, 3120)]
bc = cxy(".breakers")
fc = cxy("#feed")
TOUR_CAM = [(0, CW / 2, CH / 2, 1.08), (1.2, CW / 2, CH / 2, 1.0), (3.9, CW / 2, CH / 2, 1.0),
            (4.8, *css(bc[0], bc[1] - 60, 1640), 1.5), (7.2, *css(bc[0], bc[1] - 60, 1640), 1.5),
            (8.2, CW / 2, CH / 2, 1.0), (9.1, *css(fc[0], fc[1] - 120, 3120), 1.45), (11, *css(fc[0], fc[1] - 120, 3120), 1.45)]
TOUR_CUR = [(0.6, 1150, 560), (2.4, 640, 300), (3.9, 640, 1180 - 0), (5.2, 360, 1120), (6.2, 760, 1120),
            (7.0, 1140, 1300), (8.6, 420, 1730), (10.8, 420, 1990)]


def tour_cursor(L):
    sy = keyed(TOUR_SCROLL, L)[0]
    x, y = keyed(TOUR_CUR, L)
    X, Y = css(x, y, sy)
    a = appear(L, 0.6, 0.4)
    return X, Y, a, sy


def scene_tour(L):
    X, Y, a, sy = tour_cursor(L)
    return screen(page_crop(RAW / "site_full.jpg", sy), "bar_site", keyed(TOUR_CAM, L), (X, Y, a), t=L)


btn = cxy("#run-btn", TOP)
stg = cxy(".stage", TOP)
# Demo framing: the stage panel fills the view and the caption (~200 canvas px at
# this zoom) never covers the numbers. A = steps + bot ticker, B = guard + result,
# S = result + summary card.
_ptop = css(0, TOP[".stage"]["y"])[1]
PANEL_X = css(TOP[".stage"]["x"] + TOP[".stage"]["w"] / 2 + 30, 0)[0]
CAM_A = (PANEL_X, _ptop - 40 + CH / 1.75 / 2, 1.75)
CAM_B = (PANEL_X, css(0, TOP[".stage"]["y"] + 610)[1] + 214 - CH / 1.85 / 2, 1.85)
CAM_S = (PANEL_X, css(0, TOP[".stage"]["y"] + 745)[1] + 214 - CH / 1.75 / 2, 1.75)
CLICK_L = 1.9
CLICK_KEYS = [(0, CW / 2, CH / 2, 1.0), (0.4, CW / 2, CH / 2, 1.0), (1.7, *css(btn[0] + 120, btn[1] - 40), 1.32),
              (2.1, *css(btn[0] + 120, btn[1] - 40), 1.32), (3.0, *CAM_A)]
CLICK_CUR = [(0.2, 980, 560), (1.7, btn[0] + 10, btn[1] + 4)]


def scene_click(L):
    if L < CLICK_L:
        content = load(RAW / FRAMES[0][1]) if L < 0 else demo_frame(CLICK - 0.3)
    else:
        content = demo_frame(CLICK + (L - CLICK_L))
    x, y = keyed(CLICK_CUR, L)
    a = appear(L, 0.2, 0.3) * (1 - appear(L, 2.3, 0.3))
    X, Y = css(x, y)
    return screen(content, "bar_site", keyed(CLICK_KEYS, L), (X, Y, a), clicks=[(CLICK_L, X, Y)], t=L,
                  spot=(RECT_TOP, ease((L - 2.1) / 0.8)))


# time remap for the live demo: (output seconds, source from, source to, camera)
SEGS_BASE = [
    (1.6, CLICK + 1.1, 11.1, "A", "normal"), (3.0, 11.1, 15.5, "A", "normal"), (2.4, 15.5, 18.3, "B", "normal"),
    (1.2, 27.7, 33.4, "A", "loop"), (2.4, 33.4, 35.8, "A", "loop"), (3.0, 35.8, 39.0, "B", "loop"),
    (1.2, 47.7, 53.4, "A", "too_fast"), (3.6, 53.4, 59.5, "A", "too_fast"), (2.6, 59.5, 62.5, "B", "too_fast"),
    (1.2, 73.8, 77.4, "A", "token_bomb"), (3.3, 77.4, 80.9, "B", "token_bomb"),
    (1.2, 91.6, 97.1, "A", "retry_storm"), (2.4, 97.1, 99.5, "A", "retry_storm"), (5.4, 99.5, 103.9, "S", "summary"),
]
SEGS = list(SEGS_BASE)            # replaced by plan() so stages fit their narration
SEG_START = np.cumsum([0] + [s[0] for s in SEGS])
CAMS = {"A": CAM_A, "B": CAM_B, "S": CAM_S}


def demo_src(L):
    i = min(len(SEGS) - 1, max(0, bisect.bisect_right(SEG_START, L) - 1))
    d, a, b, cam, stage = SEGS[i]
    p = min(1.0, max(0.0, (L - SEG_START[i]) / d))
    return i, a + (b - a) * p


def demo_cam(L):
    keys = []
    for i, s in enumerate(SEGS):
        c = CAMS[s[3]]
        keys.append((SEG_START[i] + (0.0 if i == 0 else 0.55), *c))
        keys.append((SEG_START[i] + s[0], *c))
    return keyed(keys, L)


def panel_rect(boxes, pad=26):
    b = boxes[".stage"]
    x0, y0 = css(b["x"], b["y"])
    x1, y1 = css(b["x"] + b["w"], b["y"] + b["h"])
    return (int(x0 - pad), int(y0 - pad), int(x1 + pad), int(y1 + pad))


RECT_TOP = panel_rect(TOP)
RECT_END = panel_rect(CAP["site"]["end_boxes"])


def scene_demo(L):
    i, src = demo_src(L)
    content = demo_frame(src)
    j = SEG_START[i]
    if i > 0 and abs(SEGS[i - 1][2] - SEGS[i][1]) > 0.5 and L - j < 0.3:  # jump in source time: soft cut
        prev = demo_frame(SEGS[i - 1][2])
        content = Image.blend(prev, content, ease((L - j) / 0.3))
    rect = RECT_END if SEGS[i][3] == "S" else RECT_TOP
    return screen(content, "bar_site", demo_cam(L), None, t=L, spot=(rect, 1.0))


def stage_captions(t0):
    out = {}
    for i, s in enumerate(SEGS):
        st = s[4]
        a, b = t0 + SEG_START[i], t0 + SEG_START[i] + s[0]
        lo, hi = out.get(st, (a, b))
        out[st] = (min(lo, a), max(hi, b))
    caps = []
    for st, (a, b) in out.items():
        label, text = sb.STAGES[st]
        start, end = a + 0.4, b - 0.15
        if st == "retry_storm":
            end += 1.2          # long caption: let it run into the summary shot
        if st == "summary":
            start += 1.4
        caps.append((start, end, label, text))
    return caps


CW_IMG = RAW / "cloudwatch.png"


def scene_cloudwatch(L):
    im = load(CW_IMG)
    sc = CONT_W / im.width
    tall = im.resize((CONT_W, int(im.height * sc)), Image.Resampling.LANCZOS) if abs(sc - 1) > 0.01 else im
    span = max(0, tall.height - CONT_H)
    sy = keyed([(0, 0), (3.2, 0), (6.0, span * 0.55), (9, span)], L)[0]
    content = tall.crop((0, int(sy), CONT_W, int(sy) + CONT_H)) if span else tall.crop((0, 0, CONT_W, CONT_H))
    cam = keyed([(0, CW / 2, CH / 2, 1.06), (1.0, CW / 2, CH / 2, 1.0), (1.8, CW * 0.38, CH * 0.36, 1.45),
                 (3.4, CW * 0.62, CH * 0.36, 1.45), (4.2, CW / 2, CH / 2, 1.0), (5.0, CW * 0.5, CH * 0.55, 1.3),
                 (7.6, CW * 0.5, CH * 0.62, 1.3), (9, CW / 2, CH / 2, 1.0)], L)
    return screen(content, "bar_cw", cam, None, t=L)


def repo_y(heading):
    return CAP["repo"]["boxes"][heading]["y"]


def scene_repo(L):
    sy1 = (repo_y("$0 design decisions") - 70) * 2
    sy = keyed([(0, 0), (3.6, 0), (4.8, sy1), (8, sy1)], L)[0]
    content = page_crop(RAW / "repo.jpg", sy)
    cam = keyed([(0, CW / 2, CH / 2, 1.06), (1.0, CW / 2, CH / 2, 1.0), (1.9, *css(560, 420), 1.35),
                 (3.5, *css(560, 420), 1.35), (4.4, CW / 2, CH / 2, 1.0), (5.2, *css(560, 300), 1.4),
                 (8, *css(560, 380), 1.4)], L)
    return screen(content, "bar_repo", cam, None, t=L)


# ---------------------------------------------------------------- timeline (driven by the narration)

import narration as nar  # noqa: E402

D = nar.durations()
BASE = {"tour": 11.0, "click": 3.0, "cloudwatch": 9.0, "repo": 8.0}
WINDOWS = {"tour": [("t1", 0.4, 3.9), ("t2", 4.1, 7.4), ("t3", 7.6, 10.8)], "click": [("c1", 0.2, 2.9)],
           "cloudwatch": [("w1", 0.4, 3.4), ("w2", 3.6, 6.4), ("w3", 6.6, 8.8)], "repo": [("r1", 0.4, 3.9), ("r2", 4.1, 7.8)]}
ORDER = ["title", "problem", "idea", "tour", "click", "demo", "cloudwatch", "telegram", "repo", "results", "end"]
CAPTIONED = {"tour", "click", "demo", "cloudwatch", "telegram", "repo"}


def plan():
    global SEGS, SEG_START
    cues, dur, scale = {}, {}, {}
    cues["title"] = {"title": 0.55}
    dur["title"] = max(4.5, 0.55 + D["title"] + 0.9)
    t, c = 0.45, {}
    for k in ("p1", "p2", "p3"):
        c[k] = t
        t += D[k] + 0.35
    cues["problem"], dur["problem"] = c, t - 0.35 + 1.0
    c = {"i1": 0.45}
    c["i2"] = c["i1"] + D["i1"] + 0.45
    cues["idea"], dur["idea"] = c, c["i2"] + D["i2"] + 0.9
    for sc, wins in WINDOWS.items():
        s = max([1.0] + [(D[l] + 0.3) / (b - a) for l, a, b in wins])
        scale[sc] = s
        cues[sc] = {l: a * s for l, a, b in wins}
        dur[sc] = BASE[sc] * s
    segs = [list(x) for x in SEGS_BASE]
    lead = {"summary": 0.6}
    for st in ["normal", "loop", "too_fast", "token_bomb", "retry_storm", "summary"]:
        idx = [i for i, x in enumerate(segs) if x[4] == st]
        need = lead.get(st, 0.45) + D[st] + 0.75
        have = sum(segs[i][0] for i in idx)
        if need > have:
            segs[idx[-1]][0] += need - have
    SEGS = [tuple(x) for x in segs]
    SEG_START = np.cumsum([0] + [x[0] for x in SEGS])
    first = {}
    for i, x in enumerate(SEGS):
        first.setdefault(x[4], SEG_START[i])
    cues["demo"] = {st: first[st] + lead.get(st, 0.45) for st in first}
    dur["demo"] = float(SEG_START[-1])
    cues["telegram"], dur["telegram"] = {"g1": 0.5}, max(6.0, 0.5 + D["g1"] + 1.4)
    cues["results"], dur["results"] = {"res": 0.55}, max(6.0, 0.55 + D["res"] + 1.0)
    cues["end"], dur["end"] = {"end": 0.8}, max(6.0, 0.8 + D["end"] + 2.2)
    order = [s for s in ORDER if s != "cloudwatch" or CW_IMG.exists()]
    scenes, t = [], 0.0
    for s in order:
        scenes.append((s, t, t + dur[s]))
        t += dur[s]
    start = {s: a for s, a, b in scenes}
    vo = sorted((start[s] + loc, lid) for s in order for lid, loc in cues[s].items())
    caps = []
    for k, (a, lid) in enumerate(vo):
        line = nar.BY_ID[lid]
        if line[1] in CAPTIONED and line[3]:
            nxt = vo[k + 1][0] if k + 1 < len(vo) else a + 99
            caps.append((a - 0.1, min(a + D[lid] + 0.4, nxt - 0.12), line[2], line[3], f"cap_{lid}"))
    return {"scenes": scenes, "cues": cues, "scale": scale, "dur": dur, "vo": vo, "caps": caps}


import card_scenes as cs  # noqa: E402


def render_scene(name, L, P):
    cue, s, dur = P["cues"].get(name, {}), P["scale"].get(name, 1.0), P["dur"].get(name, 1.0)
    cards = {"title": cs.title, "problem": cs.problem, "idea": cs.idea, "telegram": cs.telegram,
             "results": cs.results, "end": cs.end}
    if name in cards:
        return cards[name](L, cue, D, dur)
    return {"tour": lambda: scene_tour(L / s), "click": lambda: scene_click(L / s), "demo": lambda: scene_demo(L),
            "cloudwatch": lambda: scene_cloudwatch(L / s), "repo": lambda: scene_repo(L / s)}[name]()


def frame_at(t, P):
    X, scenes = sb.XFADE, P["scenes"]
    act = [(n, a, b) for n, a, b in scenes if a - X / 2 <= t < b + X / 2] or [scenes[-1]]
    imgs = [render_scene(n, max(-X / 2, t - a), P).convert("RGB") for n, a, b in act]
    img = Image.blend(imgs[0], imgs[1], ease((t - (act[1][1] - X / 2)) / X)) if len(imgs) == 2 else imgs[0]
    img = img.convert("RGBA")
    for a, b, lab, text, name in P["caps"]:
        if a - 0.3 <= t <= b + 0.3:
            al = appear(t, a, 0.25, b, 0.25)
            c = cs.layer(name)
            place(img, c, center_x(c), OH - 64 - c.height + 14 * (1 - al), al)
    return img.convert("RGB")


# ---------------------------------------------------------------- audio: voice + ducked music

def resample(x, sr_in, sr_out):
    n_out = int(round(len(x) * sr_out / sr_in))
    X = np.fft.rfft(x)
    Y = np.zeros(n_out // 2 + 1, complex)
    m = min(len(X), len(Y))
    Y[:m] = X[:m]
    return np.fft.irfft(Y, n_out) * (n_out / len(x))


def build_audio(P, total, out):
    import wave
    import music as mus
    SR = mus.SR
    demo = next((a, b) for n, a, b in P["scenes"] if n == "demo")
    idea = next(a for n, a, b in P["scenes"] if n == "idea")
    m = mus.render(total, demo=demo, arp_from=idea)
    n = len(m)
    voice = np.zeros(n)
    active = np.zeros(n // 441 + 2)                     # 100 Hz voice-activity envelope
    for a, lid in P["vo"]:
        x = resample(nar.clip(lid).astype(np.float64), 24000, SR)
        x *= 0.13 / (np.sqrt(np.mean(x ** 2)) + 1e-9)   # same loudness for every line
        i = int(a * SR)
        j = min(n, i + len(x))
        voice[i:j] += x[: j - i]
        active[int(a * 100): int((a + len(x) / SR) * 100) + 1] = 1
    k = np.hanning(41) / np.hanning(41).sum()           # ~0.4 s smooth attack/release
    env = np.clip(np.convolve(active, k, mode="same") * 1.6, 0, 1)
    gain = np.interp(np.arange(n) / 441, np.arange(len(env)), 1 - 0.7 * env)
    mix = m * (0.85 * gain)[:, None] + voice[:, None]
    mix = np.tanh(mix * 1.1) / 1.1                       # gentle safety limiter
    mix *= 0.95 / max(0.95, np.max(np.abs(mix)))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((mix * 32767).astype("<i2").tobytes())


def srt(caps):
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"
    return "\n".join(f"{i + 1}\n{ts(a)} --> {ts(b)}\n{(lab + ': ') if lab else ''}{text}\n"
                     for i, (a, b, lab, text, _) in enumerate(caps))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--still", type=float, nargs="*", help="write PNG stills at these times and exit")
    a = ap.parse_args()
    P = plan()
    total = P["scenes"][-1][2]
    BUILD.mkdir(parents=True, exist_ok=True)
    if a.still is not None:
        for t in a.still:
            frame_at(t, P).save(BUILD / f"still_{t:05.1f}.png")
        print("stills ->", BUILD, f"(total {total:.1f}s)")
        return
    (ROOT / "media" / "llm-gateway-demo.srt").write_text(srt(P["caps"]))
    audio = BUILD / "mix.wav"
    build_audio(P, total, audio)
    step = 6 if a.preview else 1
    silent = BUILD / "video_silent.mp4"
    w = imageio_ffmpeg.write_frames(str(silent), (OW, OH), fps=FPS / step, codec="libx264", pix_fmt_out="yuv420p",
                                    output_params=["-crf", "16", "-preset", "slow", "-movflags", "+faststart"],
                                    macro_block_size=8)
    w.send(None)
    for f in range(0, int(total * FPS), step):
        w.send(np.asarray(frame_at(f / FPS, P)).tobytes())
        if f % (FPS * 10) == 0:
            print(f"  {f / FPS:6.1f}s / {total:.1f}s", flush=True)
    w.close()
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error", "-i", str(silent), "-i", str(audio),
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    str(ROOT / "media" / "llm-gateway-demo.mp4")], check=True)
    print(f"wrote media/llm-gateway-demo.mp4 ({total:.1f}s) and media/llm-gateway-demo.srt")


if __name__ == "__main__":
    main()
