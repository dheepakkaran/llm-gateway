#!/usr/bin/env python3
"""Capture footage for the product video (step 1 of 2).

Headless Chrome (Playwright, your installed Chrome) at 1600x900, 2x scale:
  - the live dashboard: full page, then the demo movie running live
  - element positions (CSS px) so the editor can aim the cursor and zoom
  - the GitHub repo page
Writes media/raw/*.jpg and media/raw/capture.json. Movie limit: once per 20 min.
"""
import json
import pathlib
import time

from playwright.sync_api import sync_playwright

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "media" / "raw"
SITE = "https://dheepakkaran.github.io/llm-gateway/"
REPO = "https://github.com/dheepakkaran/llm-gateway"
VW, VH, DPR = 1600, 900, 2

BOXES_JS = """(sels) => Object.fromEntries(sels.map(s => {
  const e = document.querySelector(s); if (!e) return [s, null];
  const r = e.getBoundingClientRect();
  return [s, {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}];
}))"""
SITE_SELS = ["#run-btn", ".stage", "#steps", "#stage-body", ".breakers", "#feed", "#timeline",
             ".counters", "#scen-row", ".thesis h2", ".top", "#results", ".faq"]


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    for f in RAW.glob("*"):
        f.unlink()
    meta = {"viewport": [VW, VH], "dpr": DPR, "demo": [], "site": {}, "repo": {}}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        ctx = b.new_context(viewport={"width": VW, "height": VH}, device_scale_factor=DPR,
                            color_scheme="dark")
        page = ctx.new_page()
        page.goto(SITE, wait_until="networkidle")
        page.wait_for_function("document.getElementById('conn-text').textContent.startsWith('live')",
                               timeout=30000)
        time.sleep(1.5)
        page.screenshot(path=str(RAW / "site_full.jpg"), full_page=True, type="jpeg", quality=95)
        meta["site"]["full_boxes"] = page.evaluate(BOXES_JS, SITE_SELS)
        meta["site"]["full_height"] = page.evaluate("document.documentElement.scrollHeight")
        page.evaluate("window.scrollTo(0, 0)")
        time.sleep(0.5)
        meta["site"]["top_boxes"] = page.evaluate(BOXES_JS, SITE_SELS)

        def shot(tag):
            i = len(meta["demo"])
            path = RAW / f"demo_{i:04d}.jpg"
            page.screenshot(path=str(path), type="jpeg", quality=95)
            meta["demo"].append({"file": path.name, "t": time.time(), "tag": tag,
                                 "stage": page.evaluate("() => demo && demo.current_stage"),
                                 "phase": page.evaluate("() => demo && demo.stage_phase")})

        for _ in range(6):
            shot("idle")
            time.sleep(0.4)
        meta["click_t"] = time.time()
        page.click("#run-btn")
        time.sleep(0.8)
        if not page.locator("#lock-msg").is_hidden():
            raise SystemExit("demo locked: " + page.locator("#lock-msg").inner_text())
        t0 = time.time()
        while time.time() - t0 < 240:
            shot("run")
            if page.evaluate("() => !!(demo && !demo.is_running && demo.status === 'done')"):
                break
            time.sleep(0.25)
        time.sleep(0.8)
        for _ in range(8):
            shot("done")
            time.sleep(0.4)
        meta["site"]["end_boxes"] = page.evaluate(BOXES_JS, SITE_SELS)
        meta["results"] = page.evaluate("() => ({summary: demo.summary, results: demo.results})")
        page.screenshot(path=str(RAW / "site_full_after.jpg"), full_page=True, type="jpeg", quality=95)
        meta["site"]["after_boxes"] = page.evaluate(BOXES_JS, SITE_SELS)

        g = ctx.new_page()
        g.goto(REPO, wait_until="networkidle")
        time.sleep(4)
        g.screenshot(path=str(RAW / "repo.jpg"), full_page=True, type="jpeg", quality=95)
        meta["repo"]["height"] = g.evaluate("document.documentElement.scrollHeight")
        meta["repo"]["boxes"] = g.evaluate("""() => Object.fromEntries([...document.querySelectorAll('article h2, article h1')]
            .map(h => { const r = h.getBoundingClientRect(); return [h.textContent.trim(), {x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height}]; }))""")
        b.close()
    (RAW / "capture.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(meta['demo'])} demo frames; summary: {meta['results']['summary']}")


if __name__ == "__main__":
    main()
