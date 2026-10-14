#!/usr/bin/env python3
"""Render every text/graphic layer of the video as transparent PNGs (step 2a).

Chrome renders them with the dashboard's own fonts (Archivo, Public Sans,
IBM Plex Mono via Google Fonts) at 2x, so captions, cards and the diagram are
sharp and on-brand. Output: media/overlays/<name>.png
"""
import html
import pathlib

from playwright.sync_api import sync_playwright

import storyboard as sb

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "media" / "overlays"

CSS = """
:root { --ink:#e8eef3; --muted:#9aa8b5; --line:#2a3744; --panel:#151d25; --accent:#52b4e2;
        --ok:#43c07a; --warn:#f0973d; --crit:#f06560; }
* { box-sizing: border-box; margin: 0; }
html, body { background: transparent; }
body { font-family: "Public Sans", system-ui, sans-serif; color: var(--ink); padding: 40px; }
.blk { display: inline-block; }
.display { font-family: "Archivo", sans-serif; font-stretch: 118%; font-weight: 800; letter-spacing: -0.01em; }
.mono { font-family: "IBM Plex Mono", monospace; }
.eyebrow { font: 600 22px/1 "Public Sans"; letter-spacing: .18em; color: var(--accent); }
.cap { max-width: 1480px; background: rgba(9,14,20,.80); border: 1px solid rgba(255,255,255,.09);
       border-radius: 20px; padding: 20px 34px 22px; font: 600 34px/1.38 "Public Sans";
       box-shadow: 0 18px 50px rgba(0,0,0,.35); text-align: center; text-wrap: balance; }
.cap .chip { display: block; width: max-content; margin: 0 auto 10px; font: 700 17px/1 "IBM Plex Mono";
             letter-spacing: .12em; color: #06202e; background: var(--accent); border-radius: 999px; padding: 7px 14px; }
.node { background: var(--panel); border: 2px solid var(--line); border-radius: 18px; padding: 18px 22px; }
.chipn { font: 600 24px/1 "IBM Plex Mono"; background: #0f161d; border: 2px solid var(--line); border-radius: 12px;
         padding: 14px 18px; display: flex; align-items: center; gap: 12px; }
.dot { width: 14px; height: 14px; border-radius: 50%; background: var(--ok); }
.lab { font: 700 18px/1 "Public Sans"; letter-spacing: .16em; color: var(--muted); margin-bottom: 16px; }
"""

FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@62..125,500..800'
         '&family=IBM+Plex+Mono:wght@400;500;600;700&family=Public+Sans:wght@400;500;600;700&display=swap">')


def diagram(state):
    """state 0: agents · 1: + gateway · 2: + providers · 3: loop-bot tripped + alert."""
    def agent(name, bad=False):
        col = "var(--crit)" if bad else "var(--ok)"
        badge = ('<span style="margin-left:auto;font:700 15px/1 \'IBM Plex Mono\';letter-spacing:.08em;'
                 'color:#2a0b0a;background:var(--warn);border-radius:6px;padding:6px 8px">SUSPENDED</span>') if bad else ""
        border = "var(--crit)" if bad else "var(--line)"
        return (f'<div class="chipn" style="border-color:{border};width:340px"><span class="dot" style="background:{col}"></span>'
                f'{name}{badge}</div>')
    vis = lambda s: "1" if state >= s else "0"
    checks = "".join(f'<div style="font:500 23px/1.6 \'Public Sans\';color:var(--muted)"><span style="color:var(--ok)">✓</span> {c}</div>'
                     for c in ["key and owner", "rate limit", "loop detection", "token budget"])
    arrow = lambda x1, y1, x2, y2, s, bad=False: (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{"#f06560" if bad else "#52b4e2"}" stroke-width="4" '
        f'stroke-dasharray="{"10 10" if bad else "0"}" marker-end="url(#{"ah2" if bad else "ah"})" opacity="{vis(s)}"/>')
    tripped = state >= 3
    return f"""
<div id="d" style="position:relative;width:1560px;height:560px">
  <svg width="1560" height="560" style="position:absolute;left:0;top:0">
    <defs><marker id="ah" markerUnits="userSpaceOnUse" markerWidth="20" markerHeight="20" refX="17" refY="10" orient="auto"><path d="M0,2 L18,10 L0,18 z" fill="#52b4e2"/></marker>
          <marker id="ah2" markerUnits="userSpaceOnUse" markerWidth="20" markerHeight="20" refX="17" refY="10" orient="auto"><path d="M0,2 L18,10 L0,18 z" fill="#f06560"/></marker></defs>
    {arrow(372, 132, 556, 190, 1)}{arrow(372, 210, 556, 215, 1)}{arrow(372, 288, 556, 240, 1, tripped)}
    {arrow(1004, 200, 1176, 182, 2)}{arrow(1004, 232, 1176, 260, 2)}
  </svg>
  <div style="position:absolute;left:12px;top:56px"><div class="lab">AI AGENTS</div>
    <div style="display:grid;gap:22px">{agent("support-bot")}{agent("code-bot")}{agent("loop-bot", tripped)}</div></div>
  <div class="node" style="position:absolute;left:570px;top:95px;width:420px;border-color:var(--accent);opacity:{vis(1)}">
    <div class="display" style="font-size:40px;margin-bottom:12px">llm-gateway</div>{checks}</div>
  <div style="position:absolute;left:1190px;top:120px;opacity:{vis(2)}"><div class="lab" style="margin-bottom:16px">LLM PROVIDERS</div>
    <div style="display:grid;gap:22px"><div class="chipn" style="width:300px">Groq</div><div class="chipn" style="width:300px">Gemini</div></div></div>
  <div style="position:absolute;left:380px;top:420px;width:800px;opacity:{vis(3)};font:600 26px/1.3 'Public Sans';
       color:var(--warn);text-align:center">Suspended in seconds. The owner gets a Telegram alert.</div>
</div>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    items = {}
    import narration as nar
    for lid, scene, label, text, _speak in nar.LINES:
        if text:
            chip = f'<span class="chip">{html.escape(label)}</span>' if label else ""
            items[f"cap_{lid}"] = f'<div class="blk cap">{chip}{html.escape(text)}</div>'
    t = sb.TITLE
    items["title_eyebrow"] = f'<div class="blk eyebrow">{t["eyebrow"]}</div>'
    items["title_main"] = f'<div class="blk display" style="font-size:150px;line-height:1">{t["title"]}</div>'
    items["title_sub"] = f'<div class="blk" style="font:500 46px/1.3 \'Public Sans\';color:var(--muted)">{t["subtitle"]}</div>'
    items["prob_label"] = f'<div class="blk eyebrow" style="color:var(--crit)">{sb.PROBLEM["label"]}</div>'
    for i, line in enumerate(sb.PROBLEM["lines"]):
        size = 64 if i < 2 else 64
        color = "var(--ink)" if i < 2 else "var(--warn)"
        items[f"prob_{i}"] = (f'<div class="blk display" style="font-size:{size}px;line-height:1.15;max-width:1600px;'
                              f'color:{color};text-wrap:balance">{html.escape(line)}</div>')
    items["idea_label"] = f'<div class="blk eyebrow">{sb.IDEA["label"]}</div>'
    items["idea_headline"] = f'<div class="blk display" style="font-size:62px;line-height:1.1">{sb.IDEA["headline"]}</div>'
    items["idea_footer"] = f'<div class="blk" style="font:600 40px/1.2 \'Public Sans\';color:var(--warn)">{sb.IDEA["footer"]}</div>'
    for s in range(4):
        items[f"diagram_{s}"] = f'<div class="blk">{diagram(s)}</div>'
    tg = sb.TELEGRAM
    items["tg_card"] = f"""<div class="blk" style="width:900px;background:#17212b;border:1px solid #2b3a48;border-radius:34px;
        padding:30px 30px 34px;box-shadow:0 40px 90px rgba(0,0,0,.5)">
      <div style="display:flex;align-items:center;gap:18px;padding-bottom:22px;border-bottom:1px solid #26323d">
        <div style="width:64px;height:64px;border-radius:50%;background:linear-gradient(135deg,#52b4e2,#2f7fb0);display:grid;place-items:center;
             font:800 26px 'Archivo'">LG</div>
        <div><div style="font:700 28px/1.2 'Public Sans'">{tg['bot']}</div><div style="font:500 20px 'Public Sans';color:var(--muted)">bot · Telegram</div></div>
      </div>
      <div style="margin-top:26px;background:#22303d;border-radius:22px 22px 22px 6px;padding:24px 26px;font:500 29px/1.45 'Public Sans'">
        {html.escape(tg['text']).replace('/resume leetcode-bot', '<span style="color:var(--accent)">/resume leetcode-bot</span>')}
        <div style="text-align:right;font:500 18px 'Public Sans';color:var(--muted);margin-top:8px">{tg['time']}</div></div>
    </div>"""
    items["res_label"] = '<div class="blk eyebrow">MEASURED ON THE LIVE DEPLOYMENT</div>'
    for i, (num, lab) in enumerate(sb.RESULTS):
        items[f"res_{i}"] = f"""<div class="blk" style="width:400px;height:250px;background:#151d25;border:2px solid #26323d;border-radius:24px;padding:34px 30px">
          <div class="mono" style="font-size:78px;font-weight:600;line-height:1;color:{'var(--ok)' if i >= 2 else 'var(--accent)'}">{num.replace(' s', '<span style="font-size:46px;margin-left:6px">s</span>').replace('call ', '<span style="font-size:46px;margin-right:10px">call</span>')}</div>
          <div style="font:600 27px/1.3 'Public Sans';color:var(--muted);margin-top:22px">{lab}</div></div>"""
    e = sb.END
    items["end_title"] = f'<div class="blk display" style="font-size:132px;line-height:1">{e["title"]}</div>'
    for i, link in enumerate(e["links"]):
        items[f"end_link_{i}"] = f'<div class="blk mono" style="font-size:40px;color:var(--accent)">{link}</div>'
    items["end_byline"] = f'<div class="blk" style="font:500 30px \'Public Sans\';color:var(--muted)">{e["byline"]}</div>'

    bars = {"bar_site": "dheepakkaran.github.io/llm-gateway", "bar_repo": "github.com/dheepakkaran/llm-gateway",
            "bar_cw": "console.aws.amazon.com/cloudwatch · llmgw"}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=True)
        page = b.new_context(viewport={"width": 1920, "height": 1200}, device_scale_factor=2).new_page()
        for name, inner in items.items():
            page.set_content(f"<!doctype html><html><head>{FONTS}<style>{CSS}</style></head><body>{inner}</body></html>",
                             wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            page.locator("body > *").first.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
        bp = b.new_context(viewport={"width": 1600, "height": 60}, device_scale_factor=2).new_page()
        for name, url in bars.items():
            bp.set_content(f"""<!doctype html><html><head>{FONTS}<style>{CSS} body{{padding:0}}</style></head><body>
              <div id="bar" style="width:1600px;height:38px;background:#1d2630;display:flex;align-items:center;padding:0 16px;gap:8px">
                <span style="width:12px;height:12px;border-radius:50%;background:#ff5f57"></span>
                <span style="width:12px;height:12px;border-radius:50%;background:#febc2e"></span>
                <span style="width:12px;height:12px;border-radius:50%;background:#28c840"></span>
                <div style="margin:0 auto;transform:translateX(-30px);background:#0f161d;border-radius:8px;padding:5px 18px;
                     font:500 14px 'Public Sans';color:#9aa8b5">🔒 {url}</div></div></body></html>""", wait_until="networkidle")
            bp.evaluate("document.fonts.ready")
            bp.locator("#bar").screenshot(path=str(OUT / f"{name}.png"))
        b.close()
    print(len(items) + len(bars), "overlays ->", OUT)


if __name__ == "__main__":
    main()
