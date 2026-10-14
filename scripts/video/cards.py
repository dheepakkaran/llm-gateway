#!/usr/bin/env python3
"""Render the redesigned card-scene layers (step 2c) with Chrome at 2x.

Style: deep navy, Geist (sans + mono) with Instrument Serif italic accents,
silver-gradient headlines, glass panels. Every text block is saved with the
box of each word (or letter) so the editor can reveal them one by one.
Output: media/cards/<name>.png + media/cards/layout.json
"""
import json
import pathlib

from playwright.sync_api import sync_playwright

import narration as nar
import storyboard as sb

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "media" / "cards"
FONTS = ('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Geist:wght@300..800'
         '&family=Geist+Mono:wght@400..600&family=Instrument+Serif:ital@0;1&display=swap">')
CSS = """
:root{--ink:#f3f6f9;--mut:#8d9aab;--glass:rgba(255,255,255,.04);--line:rgba(255,255,255,.10);
--cyan:#5ee1f5;--blue:#7aa7ff;--violet:#a78bfa;--warn:#fdba74;--crit:#fb7185;--ok:#6ee7b7}
*{box-sizing:border-box;margin:0}html,body{background:transparent}
body{font-family:Geist,system-ui,sans-serif;color:var(--ink);padding:60px;-webkit-font-smoothing:antialiased}
.blk{display:inline-block}
.h{font-weight:650;letter-spacing:-.035em;line-height:1.06;
   background:linear-gradient(180deg,#fff 35%,#a9b8ca 100%);-webkit-background-clip:text;color:transparent}
em{font-family:"Instrument Serif",serif;font-style:italic;font-weight:400;letter-spacing:-.01em;padding:0 .04em;
   background:linear-gradient(100deg,var(--cyan),var(--blue) 55%,var(--violet));-webkit-background-clip:text;color:transparent}
em.warm{background:linear-gradient(100deg,var(--warn),var(--crit));-webkit-background-clip:text}
.mono{font-family:"Geist Mono",monospace}
.label{font:500 17px/1 "Geist Mono";letter-spacing:.2em;color:#b7c4d4;display:inline-flex;align-items:center;gap:12px}
.label i{width:9px;height:9px;border-radius:50%;background:var(--cyan);box-shadow:0 0 14px var(--cyan)}
.pill{border:1px solid var(--line);background:rgba(255,255,255,.035);border-radius:999px;padding:12px 22px}
.glass{background:linear-gradient(180deg,rgba(255,255,255,.065),rgba(255,255,255,.025));border:1px solid var(--line);
       border-radius:26px;box-shadow:inset 0 1px 0 rgba(255,255,255,.08),0 30px 80px rgba(0,0,0,.45)}
.cap{max-width:1500px;background:rgba(7,10,15,.80);border:1px solid rgba(255,255,255,.10);border-radius:18px;
     padding:18px 30px 20px;font:500 33px/1.38 Geist;letter-spacing:-.01em;text-align:center;text-wrap:balance;
     box-shadow:0 20px 60px rgba(0,0,0,.4)}
.cap .chip{display:block;width:max-content;margin:0 auto 10px;font:600 15px/1 "Geist Mono";letter-spacing:.16em;
           color:var(--cyan);background:rgba(94,225,245,.10);border:1px solid rgba(94,225,245,.35);border-radius:999px;padding:7px 13px}
"""


def words(html_text, cls="w"):
    """Wrap each word (outside tags) in a span, keeping <em> groups intact per word."""
    out, i, buf, in_tag = [], 0, "", None
    import re
    tokens = re.split(r"(<em[^>]*>.*?</em>|\s+)", html_text)
    for t in tokens:
        if not t:
            continue
        if t.isspace():
            out.append(" ")
        elif t.startswith("<em"):
            m = re.match(r"(<em[^>]*>)(.*?)(</em>)", t)
            for k, wd in enumerate(m.group(2).split()):
                out.append(("" if k == 0 else " ") + f'<span class="{cls}">{m.group(1)}{wd}{m.group(3)}</span>')
        else:
            out.append(f'<span class="{cls}">{t}</span>')
    return "".join(out)


def letters(text):
    return "".join(f'<span class="w">{c}</span>' for c in text)


def blocks():
    R, SUM = sb.R, sb.SUM
    b = {}
    b["eyebrow"] = ('<div class="blk pill label"><i></i>OPEN SOURCE &nbsp;/&nbsp; SERVERLESS &nbsp;/&nbsp; $0 ON AWS</div>')
    b["title"] = f'<div class="blk h" style="font-size:190px;font-weight:700;letter-spacing:-.05em">{letters("llm-gateway")}</div>'
    b["subtitle"] = ('<div class="blk" style="font:400 46px/1.25 Geist;color:#c6d1dd;letter-spacing:-.015em">'
                     + words('Catch runaway AI agents <em>before</em> the bill explodes.') + '</div>')
    b["prob_label"] = '<div class="blk label"><i style="background:var(--crit);box-shadow:0 0 14px var(--crit)"></i>THE PROBLEM</div>'
    b["p1"] = '<div class="blk h" style="font-size:58px;width:860px">' + words("AI agents call LLMs on their own, all day long.") + "</div>"
    b["p2"] = ('<div class="blk h" style="font-size:58px;width:860px">'
               + words('One bug can trap an agent in a <em class="warm">loop</em>: thousands of calls an hour.') + "</div>")
    b["p3"] = ('<div class="blk h" style="font-size:58px;width:860px;background:linear-gradient(100deg,var(--warn),var(--crit));'
               '-webkit-background-clip:text">' + words("Nobody notices. Nobody can stop it. Then the bill arrives.") + "</div>")
    b["log_head"] = ('<div class="blk glass" style="width:780px;height:600px;padding:0;overflow:hidden">'
                     '<div style="display:flex;align-items:center;gap:9px;padding:18px 22px;border-bottom:1px solid var(--line)">'
                     '<span style="width:12px;height:12px;border-radius:50%;background:#ff5f57"></span>'
                     '<span style="width:12px;height:12px;border-radius:50%;background:#febc2e"></span>'
                     '<span style="width:12px;height:12px;border-radius:50%;background:#28c840"></span>'
                     '<span class="mono" style="margin-left:14px;font-size:17px;color:var(--mut)">agent.log: loop-bot, no gateway</span></div></div>')
    rows = "".join(
        f'<div class="mono" style="height:36px;display:flex;gap:22px;font-size:19px;white-space:nowrap">'
        f'<span style="color:#5d6b7c">#{i:04d}</span><span style="color:#c6d1dd">loop-bot → LLM</span>'
        f'<span style="color:#e2e8f0">"Solve two-sum"</span><span style="color:var(--ok)">200 OK</span></div>'
        for i in range(1, 161))
    b["log_rows"] = f'<div class="blk" style="width:720px">{rows}</div>'
    b["idea_label"] = '<div class="blk label"><i></i>THE FIX</div>'
    b["idea_head"] = ('<div class="blk h" style="font-size:64px;text-align:center">'
                      + words("Every agent calls the LLM through <em>one gateway</em>.") + "</div>")
    b["idea_foot"] = ('<div class="blk" style="font:500 40px/1.2 Geist;color:#d5dde6;letter-spacing:-.02em">'
                      + words('When an agent goes rogue, its <em class="warm">breaker trips</em>.') + "</div>")
    b["toast"] = ('<div class="blk glass" style="width:560px;padding:20px 22px;border-radius:22px;display:flex;gap:16px;align-items:flex-start">'
                  '<div style="width:52px;height:52px;flex:none;border-radius:14px;background:linear-gradient(135deg,#5ee1f5,#7aa7ff 60%,#a78bfa);'
                  'display:grid;place-items:center;font:700 20px Geist;color:#071018">LG</div>'
                  '<div><div style="display:flex;justify-content:space-between;font:600 21px Geist"><span>LLM Gateway Guard</span>'
                  '<span style="font:400 17px Geist;color:var(--mut)">now</span></div>'
                  '<div style="font:400 20px/1.35 Geist;color:#c6d1dd;margin-top:4px">loop-bot SUSPENDED: same prompt 6x in 2 min. '
                  '<span style="color:var(--cyan)">/resume loop-bot</span></div></div></div>')
    tg = sb.TELEGRAM
    b["tg"] = ('<div class="blk glass" style="width:1040px;padding:34px 36px;border-radius:34px">'
               '<div style="display:flex;gap:22px;align-items:center">'
               '<div style="width:84px;height:84px;border-radius:22px;background:linear-gradient(135deg,#5ee1f5,#7aa7ff 60%,#a78bfa);'
               'display:grid;place-items:center;font:700 32px Geist;color:#071018">LG</div>'
               f'<div style="flex:1"><div style="display:flex;justify-content:space-between;font:600 32px Geist;letter-spacing:-.02em">'
               f'<span>{tg["bot"]}</span><span style="font:400 24px Geist;color:var(--mut)">now</span></div>'
               '<div class="mono" style="font-size:20px;color:var(--mut);letter-spacing:.08em;margin-top:6px">TELEGRAM · ALERT</div></div></div>'
               f'<div style="margin-top:26px;font:400 33px/1.45 Geist;color:#e6ecf2;letter-spacing:-.01em">'
               f'{tg["text"].replace("/resume leetcode-bot", "")}</div>'
               '<div style="margin-top:24px;display:inline-block;font:500 26px Geist Mono;color:var(--cyan);border:1px solid rgba(94,225,245,.4);'
               'background:rgba(94,225,245,.08);border-radius:999px;padding:12px 24px">/resume leetcode-bot</div></div>')
    b["res_label"] = '<div class="blk label"><i style="background:var(--ok);box-shadow:0 0 14px var(--ok)"></i>MEASURED ON THE LIVE DEPLOYMENT</div>'
    b["res_note"] = ('<div class="blk mono" style="font-size:19px;color:var(--mut);letter-spacing:.04em">'
                     'Every number on this screen was measured in a live run, never typed by hand.</div>')
    b["end_title"] = f'<div class="blk h" style="font-size:150px;font-weight:700;letter-spacing:-.05em">{letters("llm-gateway")}</div>'
    for i, link in enumerate(sb.END["links"]):
        b[f"end_link_{i}"] = (f'<div class="blk pill mono" style="font-size:25px;color:#dbe4ee;padding:16px 28px">'
                              f'{link} <span style="color:var(--cyan)">↗</span></div>')
    b["end_by"] = '<div class="blk" style="font:400 28px Geist;color:var(--mut)">Built by <span style="color:#e6ecf2">Dheepak Karan</span></div>'
    b["end_stack"] = ('<div class="blk mono" style="font-size:18px;letter-spacing:.14em;color:#7d8a9a">'
                      'AWS LAMBDA · DYNAMODB · TERRAFORM · PYTHON · GITHUB ACTIONS</div>')
    # count-up frames for the result cards
    def card(num_html, lab):
        return (f'<div class="blk glass" style="width:400px;height:270px;padding:36px 34px">'
                f'<div class="h" style="font-size:92px;font-weight:700;letter-spacing:-.04em">{num_html}</div>'
                f'<div style="font:400 26px/1.3 Geist;color:var(--mut);margin-top:18px">{lab}</div></div>')
    unit = lambda u: f'<span style="font-size:52px;letter-spacing:-.02em;margin-left:6px">{u}</span>'
    calls = R["loop"]["calls_to_catch"]
    secs = SUM["avg_seconds_to_catch"]
    for k in range(1, calls + 1):
        b[f"res0_{k:03d}"] = card(f'<span style="font-size:52px;margin-right:12px">call</span>{k}', sb.RESULTS[0][1])
    steps = 24
    for k in range(steps + 1):
        b[f"res1_{k:03d}"] = card(f"{secs * k / steps:.2f}{unit('s')}", sb.RESULTS[1][1])
    b["res2_000"] = card(str(SUM["false_blocks"]), sb.RESULTS[2][1])
    b["res3_000"] = card("$0", sb.RESULTS[3][1])
    # captions for the screen scenes
    import html as h
    for lid, scene, label, text, _ in nar.LINES:
        if text:
            chip = f'<span class="chip">{h.escape(label)}</span>' if label else ""
            b[f"cap_{lid}"] = f'<div class="blk cap">{chip}{h.escape(text)}</div>'
    return b


DIAGRAM = """
<div id="dg" style="position:relative;width:1600px;height:560px">
  <div class="label" style="position:absolute;left:0;top:40px;font-size:15px">AI AGENTS</div>
  <div class="label" style="position:absolute;left:1240px;top:110px;font-size:15px">LLM PROVIDERS</div>
  <div id="a0" class="glass mono" style="position:absolute;left:0;top:84px;width:330px;height:74px;border-radius:16px;font-size:24px;
       display:flex;align-items:center;gap:14px;padding:0 22px"><span style="width:12px;height:12px;border-radius:50%;background:var(--ok)"></span>support-bot</div>
  <div id="a1" class="glass mono" style="position:absolute;left:0;top:184px;width:330px;height:74px;border-radius:16px;font-size:24px;
       display:flex;align-items:center;gap:14px;padding:0 22px"><span style="width:12px;height:12px;border-radius:50%;background:var(--ok)"></span>code-bot</div>
  <div id="a2" class="glass mono" style="position:absolute;left:0;top:284px;width:330px;height:74px;border-radius:16px;font-size:24px;
       display:flex;align-items:center;gap:14px;padding:0 22px"><span style="width:12px;height:12px;border-radius:50%;background:var(--ok)"></span>loop-bot</div>
  <div id="gw" class="glass" style="position:absolute;left:560px;top:60px;width:470px;height:330px;padding:30px 34px;border-radius:24px;
       border-color:rgba(122,167,255,.45)">
    <div class="h" style="font-size:44px;font-weight:700;letter-spacing:-.04em">llm-gateway</div>
    <div id="c0" class="cr">key and owner</div><div id="c1" class="cr">rate limit</div>
    <div id="c2" class="cr">loop detection</div><div id="c3" class="cr">token budget</div>
  </div>
  <div id="p0" class="glass mono" style="position:absolute;left:1240px;top:150px;width:300px;height:74px;border-radius:16px;font-size:24px;
       display:flex;align-items:center;padding:0 24px">Groq</div>
  <div id="p1" class="glass mono" style="position:absolute;left:1240px;top:250px;width:300px;height:74px;border-radius:16px;font-size:24px;
       display:flex;align-items:center;padding:0 24px">Gemini</div>
</div>
<style>.cr{font:400 25px/1 Geist;color:#c6d1dd;margin-top:22px;display:flex;align-items:center;gap:14px;opacity:var(--co,1)}
.cr:before{content:"";width:22px;height:22px;border-radius:50%;flex:none;
  background:radial-gradient(circle at 50% 50%,#6ee7b7 0 5px,rgba(110,231,183,.18) 6px)}</style>"""


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    layout = {}
    with sync_playwright() as p:
        br = p.chromium.launch(channel="chrome", headless=True)
        page = br.new_context(viewport={"width": 1920, "height": 1300}, device_scale_factor=2).new_page()

        def render(name, inner, extra_css=""):
            page.set_content(f"<!doctype html><html><head>{FONTS}<style>{CSS}{extra_css}</style></head>"
                             f"<body>{inner}</body></html>", wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            el = page.locator("body > *").first
            el.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
            box = page.evaluate("""() => { const r = document.body.firstElementChild.getBoundingClientRect();
              return {x: r.left, y: r.top, w: r.width, h: r.height,
                words: [...document.querySelectorAll('.w')].map(s => { const q = s.getBoundingClientRect();
                  return [q.left - r.left, q.top - r.top, q.width, q.height]; })}; }""")
            layout[name] = box

        for name, inner in blocks().items():
            render(name, inner)
        # diagram: base without checks, check rows, tripped loop-bot, plus anchor boxes
        render("dg_base", DIAGRAM, "#dg{--co:0}")
        render("dg_checks", DIAGRAM, "#dg>*:not(#gw){visibility:hidden} #gw{background:none;border-color:transparent;box-shadow:none}"
                                     " #gw>.h{visibility:hidden}")
        ids = ["a0", "a1", "a2", "gw", "p0", "p1", "c0", "c1", "c2", "c3"]
        layout["dg_anchors"] = page.evaluate("""(ids) => { const r = document.getElementById('dg').getBoundingClientRect();
            return Object.fromEntries(ids.map(i => { const q = document.getElementById(i).getBoundingClientRect();
              return [i, [q.left - r.left, q.top - r.top, q.width, q.height]]; })); }""", ids)
        page.set_content(f"<!doctype html><html><head>{FONTS}<style>{CSS}</style></head><body>"
                         '<div id="t" class="blk glass mono" style="width:330px;height:74px;border-radius:16px;font-size:24px;display:flex;'
                         'align-items:center;gap:14px;padding:0 18px 0 22px;border-color:rgba(251,113,133,.7);'
                         'box-shadow:0 0 40px rgba(251,113,133,.25),inset 0 1px 0 rgba(255,255,255,.08)">'
                         '<span style="width:12px;height:12px;border-radius:50%;background:var(--crit);box-shadow:0 0 12px var(--crit)"></span>loop-bot'
                         '<span style="margin-left:auto;font:600 14px Geist Mono;letter-spacing:.1em;color:#1a0508;background:var(--warn);'
                         'border-radius:7px;padding:6px 9px">SUSPENDED</span></div></body></html>', wait_until="networkidle")
        page.evaluate("document.fonts.ready")
        page.locator("#t").screenshot(path=str(OUT / "dg_tripped.png"), omit_background=True)
        br.close()
    (OUT / "layout.json").write_text(json.dumps(layout))
    print(len(layout), "layers ->", OUT)


if __name__ == "__main__":
    main()
