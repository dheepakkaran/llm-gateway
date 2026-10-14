#!/usr/bin/env python3
"""Record the live demo movie from the public dashboard and build docs/demo.gif.

Drives your installed Chrome headlessly (Playwright, no browser download) at
2x device scale, clicks "Run Live Demo" on the real GitHub Pages site, and
screenshots the demo area while the movie runs against the deployed gateway.
Frames are then cropped, downscaled with Lanczos and written as a GIF with a
per-frame adaptive palette and no dithering, so UI text stays sharp.

Usage: .venv/bin/python scripts/record_demo.py [--theme dark|light] [--width 1200]
The movie can run once every 20 minutes (global demo limit).
"""
import argparse
import pathlib
import tempfile
import time

from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parent.parent
URL = "https://dheepakkaran.github.io/llm-gateway/"
VIEW_W, VIEW_H, SCALE = 1440, 900, 2


def record(frames_dir, theme):
    shots = []
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_context(viewport={"width": VIEW_W, "height": VIEW_H},
                                   device_scale_factor=SCALE, color_scheme=theme).new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_function("document.getElementById('conn-text').textContent.startsWith('live')",
                               timeout=30000)
        box = page.evaluate("""() => {
            const w = document.querySelector('.wrap').getBoundingClientRect();
            const h = document.querySelector('.hero').getBoundingClientRect();
            return {x: w.left, width: w.width, top: 0, heroTop: h.top};
        }""")

        def snap(tag):
            path = frames_dir / f"{len(shots):04d}.png"
            page.screenshot(path=str(path))
            shots.append((path, time.time(), tag))

        for _ in range(4):
            snap("idle")
            time.sleep(0.5)
        page.click("#run-btn")
        time.sleep(1.0)
        if not page.locator("#lock-msg").is_hidden():
            raise SystemExit("Demo is locked: " + page.locator("#lock-msg").inner_text())
        t0 = time.time()
        while time.time() - t0 < 240:
            snap("run")
            done = page.evaluate("() => !!(demo && !demo.is_running && demo.summary && demo.status === 'done')")
            if done:
                break
            time.sleep(0.45)
        time.sleep(1.0)
        for _ in range(6):
            snap("done")
            time.sleep(0.5)
        bottom = page.evaluate("() => document.querySelector('.hero').getBoundingClientRect().bottom")
        browser.close()
    box["bottom"] = min(VIEW_H, bottom + 14)
    return shots, box


def build_gif(shots, box, out, width):
    left = max(0, int((box["x"] - 8) * SCALE))
    right = min(VIEW_W * SCALE, int((box["x"] + box["width"] + 8) * SCALE))
    crop = (left, 0, right, int(box["bottom"] * SCALE))
    frames, times = [], []
    for path, t, _ in shots:
        im = Image.open(path).convert("RGB").crop(crop)
        h = round(im.height * width / im.width)
        im = im.resize((width, h), Image.Resampling.LANCZOS)
        if frames and not ImageChops.difference(im, frames[-1]).getbbox():
            continue  # identical to previous frame: just hold it longer
        frames.append(im)
        times.append(t)
    durations = []
    for i in range(len(frames)):
        real = (times[i + 1] - times[i]) if i + 1 < len(frames) else 0
        durations.append(int(max(250, min(1800, real * 1000 / 1.4))))  # ~1.4x speed
    durations[-1] = 6000  # hold the final summary
    pal = [f.quantize(colors=256, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
           for f in frames]
    pal[0].save(out, save_all=True, append_images=pal[1:], duration=durations, loop=0,
                optimize=False, disposal=1)
    return len(frames), frames[0].size


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--width", type=int, default=1200)
    ap.add_argument("--out", default=str(ROOT / "docs" / "demo.gif"))
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as d:
        shots, box = record(pathlib.Path(d), a.theme)
        n, size = build_gif(shots, box, a.out, a.width)
    mb = pathlib.Path(a.out).stat().st_size / 1e6
    print(f"{len(shots)} screenshots -> {n} unique frames, {size[0]}x{size[1]}, {mb:.1f} MB -> {a.out}")


if __name__ == "__main__":
    main()
