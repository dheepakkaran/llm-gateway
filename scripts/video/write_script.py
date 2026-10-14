#!/usr/bin/env python3
"""Write docs/VIDEO_SCRIPT.md: the video's scenes, on-screen text and timed captions."""
import pathlib

import make_video as mv
import narration as nar
import storyboard as sb

ROOT = pathlib.Path(__file__).resolve().parents[2]
P = mv.plan()
scenes, caps = P["scenes"], P["caps"]
total = scenes[-1][2]
DESC = {
    "title": ("Title", f'"{sb.TITLE["title"]}": {sb.TITLE["subtitle"]} ({sb.TITLE["eyebrow"]})'),
    "problem": ("The problem", " / ".join(sb.PROBLEM["lines"])),
    "idea": ("The idea", f'{sb.IDEA["headline"]} An animated diagram builds up: agents, the gateway with its checks, '
                         f'the LLM providers, then loop-bot trips and is suspended. "{sb.IDEA["footer"]}"'),
    "tour": ("Live dashboard tour", "The real GitHub Pages dashboard in a browser window. The camera zooms into the "
                                    "agent breakers, then the live request feed, following the cursor."),
    "click": ("Run Live Demo", "The cursor clicks Run Live Demo; a ripple marks the click and the camera moves to the stage panel."),
    "demo": ("The live demo", "The five stages run live against the AWS deployment, sped up between steps. A spotlight dims "
                              "everything except the stage panel; the camera zooms in on each result."),
    "cloudwatch": ("CloudWatch dashboard", "The private ops dashboard: cost first, free-tier meters, then health."),
    "telegram": ("Telegram alert", f'The alert a real agent\'s owner receives: "{sb.TELEGRAM["text"]}"'),
    "repo": ("Open source", "The GitHub repo: files, README, then the $0 design decisions table."),
    "results": ("Results", " · ".join(f"{a} {b}" for a, b in sb.RESULTS)),
    "end": ("End card", " · ".join([sb.END["title"]] + sb.END["links"] + [sb.END["byline"]])),
}


def mmss(x):
    return f"{int(x // 60)}:{x % 60:04.1f}"


lines = ["# llm-gateway product video: script", "",
         f"Length {mmss(total)} · 1920×1080, 30 fps · voice-over by Kokoro (local AI voice, Apache-2.0, voice "
         f"`{nar.VOICES[nar.voice()][0]}`) · original background music generated in code (`scripts/video/music.py`), "
         "ducked under the voice · captions burned in, also in `media/llm-gateway-demo.srt`.", "",
         "Every number on screen comes from the recorded demo run (`media/raw/capture.json`) or the simulator, not typed by hand.", "",
         "## Scenes", "", "| Time | Scene | What you see |", "|---|---|---|"]
for name, a, b in scenes:
    t, d = DESC[name]
    lines.append(f"| {mmss(a)}–{mmss(b)} | {t} | {d} |")
lines += ["", "## Voice-over (transcript)", "",
          "What the voice says, in order. On the title cards the words are already on screen, so there's no caption there.", "",
          "| Time | Scene | Narration | Caption on screen |", "|---|---|---|---|"]
for a, lid in P["vo"]:
    _, scene, lab, cap, speak = nar.BY_ID[lid]
    shown = f"{(lab + ': ') if lab else ''}{cap}" if cap and scene in mv.CAPTIONED else "(text on screen)"
    lines.append(f"| {mmss(a)} | {DESC[scene][0]} | {speak.replace('L.L.M.', 'LLM').replace('A.W.S.', 'AWS').replace('A.I.', 'AI').replace('C.I.', 'CI')} | {shown} |")
lines += ["", "## How it was made", "",
          "1. `scripts/video/capture.py`: headless Chrome at 2× records the live dashboard, runs the real demo movie and "
          "saves element positions so the cursor and zoom can aim at real buttons and panels.",
          "2. `scripts/video/overlays.py`: Chrome renders every caption, title, diagram and card with the dashboard's own fonts.",
          "3. `scripts/video/music.py`: synthesises the background track (pads, arpeggio, soft beat).",
          "4. `scripts/video/narration.py`: the voice-over lines, spoken by the Kokoro model on this laptop; the editor "
          "times every scene to its narration and lowers the music while the voice speaks.",
          "5. `scripts/video/make_video.py`: composites a rounded browser window on a gradient, an eased camera that "
          "zooms toward the cursor, click ripples, crossfades, a spotlight on the demo panel and the captions, then "
          "encodes H.264 with AAC audio.", ""]
(ROOT / "docs" / "VIDEO_SCRIPT.md").write_text("\n".join(lines))
print("wrote docs/VIDEO_SCRIPT.md")
