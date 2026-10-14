#!/usr/bin/env python3
"""Voice-over: the narration lines and their speech audio (Kokoro, local, Apache-2.0).

Each line has the text shown as a caption (None on title cards, where the words are
already on screen) and the text spoken, spelled so the voice pronounces it right
("LLM" without dots, "A-W-S", "Deepak"). Numbers come from the recorded run.
Audio is cached per (voice, speed, text) in media/tts/lines/.
Usage: narration.py [voice]   -> prints each line's duration
"""
import hashlib
import json
import pathlib
import sys

import numpy as np

import storyboard as sb

ROOT = pathlib.Path(__file__).resolve().parents[2]
TTS = ROOT / "media" / "tts"
CACHE = TTS / "lines"
VOICE_FILE = TTS / "voice.json"
VOICES = {"1": ("af_heart", "en-us"), "2": ("am_michael", "en-us"), "3": ("bf_emma", "en-gb"), "4": ("bm_george", "en-gb")}
SPEED = 1.06
R, SUM, f = sb.R, sb.SUM, sb.fmt_s
_DIG = "zero one two three four five six seven eight nine".split()


def say_num(x):
    """1.85 -> 'one point eight five' (the voice reads a bare '1.85' as 'one. eighty-five')."""
    whole, _, frac = f(x).partition(".")
    return " ".join([whole] + (["point"] + [_DIG[int(c)] for c in frac] if frac else []))


# (id, scene, caption label, caption text or None, spoken text)
LINES = [
    ("title", "title", None, None,
     "Meet LLM gateway. It catches runaway AI agents before the bill explodes."),
    ("p1", "problem", None, None, "AI agents call LLMs on their own, all day long."),
    ("p2", "problem", None, None, "One bug can trap an agent in a loop: thousands of calls an hour."),
    ("p3", "problem", None, None, "Nobody notices. Nobody can stop it. Then the bill arrives."),
    ("i1", "idea", None, None, "The fix: every agent calls the LLM through one gateway."),
    ("i2", "idea", None, None,
     "When an agent goes rogue, its breaker trips. It's suspended in seconds, and the owner gets a Telegram alert."),
    ("t1", "tour", None, "This is the live dashboard, running on the real AWS deployment.",
     "This is the live dashboard, running on the real A-W-S deployment."),
    ("t2", "tour", None, "Every agent is a breaker: up is active, middle is suspended, down is killed.",
     "Every agent is a breaker. Up is active, middle is suspended, and down is killed."),
    ("t3", "tour", None, "Every request shows up live, with the reason it was allowed or blocked.",
     "Every request shows up live, with the reason it was allowed or blocked."),
    ("c1", "click", None, "Let's run the live demo: five buggy bots, one after another.",
     "Let's run the live demo: five buggy bots, one after another."),
    ("normal", "demo", "1 · NORMAL",
     f"A healthy agent asks {R['normal']['sent']} different questions. All {R['normal']['allowed']} are allowed.",
     f"First, a healthy agent asks {R['normal']['sent']} different questions. All {R['normal']['allowed']} are allowed."),
    ("loop", "demo", "2 · LOOP",
     f"A buggy agent repeats one question. Caught on call {R['loop']['calls_to_catch']}, in {f(R['loop']['seconds_to_catch'])} seconds.",
     f"Next, a buggy agent repeats one question. It's caught on call {R['loop']['calls_to_catch']}, "
     f"in {say_num(R['loop']['seconds_to_catch'])} seconds."),
    ("too_fast", "demo", "3 · TOO FAST",
     f"An agent goes over its limit. Throttled at call {R['too_fast']['throttled_at_call']}, "
     f"suspended at call {R['too_fast']['calls_to_catch']}.",
     f"This agent goes over its limit. It's throttled at call {R['too_fast']['throttled_at_call']}, "
     f"and suspended at call {R['too_fast']['calls_to_catch']}."),
    ("token_bomb", "demo", "4 · TOKEN BOMB",
     "One 50,000-character prompt. Rejected on the first call. No model ever sees it.",
     "One giant prompt, fifty thousand characters. Rejected on the first call. No model ever sees it."),
    ("retry_storm", "demo", "5 · RETRY STORM",
     f"An agent retries forever after errors. Suspended after {R['retry_storm']['calls_to_catch']} failures.",
     f"This agent retries forever after errors. It's suspended after {R['retry_storm']['calls_to_catch']} failures."),
    ("summary", "demo", "RESULT",
     f"{SUM['caught']} of {SUM['problems']} problems caught. {SUM['false_blocks']} false blocks. All measured live.",
     f"{SUM['caught']} out of {SUM['problems']} problems caught. {SUM['false_blocks']} false blocks. "
     f"And every number is measured live."),
    ("w1", "cloudwatch", None, "Behind the scenes, a private CloudWatch dashboard puts cost first.",
     "Behind the scenes, a private CloudWatch dashboard puts cost first."),
    ("w2", "cloudwatch", None, "Free-tier meters show the whole project stays at $0.",
     "Free tier meters show the whole project stays at zero dollars."),
    ("w3", "cloudwatch", None, "Errors, latency and database capacity, all on one page.",
     "Errors, latency, and database capacity, all on one page."),
    ("g1", "telegram", None, "Real agents alert their owner on Telegram, with a one-tap /resume.",
     "Real agents alert their owner on Telegram, with a one tap resume."),
    ("r1", "repo", None, "It's open source: Terraform, 51 tests, CI on every pull request, and a learning guide.",
     "It's open source: Terraform, fifty-one tests, CI on every pull request, and a learning guide."),
    ("r2", "repo", None, "Every design choice swaps a paid AWS service for an always-free one.",
     "Every design choice swaps a paid A-W-S service for an always-free one."),
    ("res", "results", None, None,
     f"A looping agent is caught on call {R['loop']['calls_to_catch']}. {SUM['false_blocks']} false blocks. "
     f"And it all runs for zero dollars on A-W-S."),
    ("end", "end", None, None, "LLM gateway. Built by Deepak Karan. The code and the live demo are linked below."),
]
BY_ID = {l[0]: l for l in LINES}


def voice():
    if VOICE_FILE.exists():
        return json.loads(VOICE_FILE.read_text())["choice"]
    return "1"


_k = None


def clip(line_id, choice=None):
    """Mono float32 audio at 24 kHz for one line (cached)."""
    global _k
    choice = choice or voice()
    v, lang = VOICES[choice]
    text = BY_ID[line_id][4]
    key = hashlib.sha256(f"{v}|{lang}|{SPEED}|{text}".encode()).hexdigest()[:16]
    path = CACHE / f"{line_id}_{key}.npy"
    if path.exists():
        return np.load(path)
    if _k is None:
        from kokoro_onnx import Kokoro
        _k = Kokoro(str(TTS / "kokoro-v1.0.onnx"), str(TTS / "voices-v1.0.bin"))
    audio, sr = _k.create(text, voice=v, speed=SPEED, lang=lang)
    assert sr == 24000
    a = np.asarray(audio, np.float32)
    nz = np.nonzero(np.abs(a) > 0.01)[0]                 # trim silence at both ends
    a = a[max(0, nz[0] - 240): nz[-1] + 1200] if len(nz) else a
    CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, a)
    return a


def durations(choice=None):
    return {l[0]: len(clip(l[0], choice)) / 24000 for l in LINES}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        TTS.mkdir(parents=True, exist_ok=True)
        VOICE_FILE.write_text(json.dumps({"choice": sys.argv[1]}))
    d = durations()
    for k, v in d.items():
        print(f"{k:12s} {v:5.2f}s  {BY_ID[k][4]}")
    print(f"total speech {sum(d.values()):.1f}s, voice {VOICES[voice()][0]}")
