"""The video's script: scenes, timings and simple-English captions in one place.

Numbers in captions come from media/raw/capture.json (the run that was
recorded), never typed by hand, so the video always matches its footage.
"""
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
CAP = json.loads((ROOT / "media" / "raw" / "capture.json").read_text())
R = CAP["results"]["results"]
SUM = CAP["results"]["summary"]


def fmt_s(x):
    return f"{x:.2f}".rstrip("0").rstrip(".")


# (start, end) in output seconds
SCENES = [
    ("title", 0.0, 4.5),
    ("problem", 4.5, 11.0),
    ("idea", 11.0, 18.5),
    ("tour", 18.5, 29.5),
    ("click", 29.5, 32.5),
    ("demo", 32.5, 67.0),
    ("cloudwatch", 67.0, 76.0),
    ("telegram", 76.0, 82.0),
    ("repo", 82.0, 90.0),
    ("results", 90.0, 96.0),
    ("end", 96.0, 102.0),
]
DURATION = SCENES[-1][2]
XFADE = 0.5

TITLE = {
    "eyebrow": "OPEN SOURCE · SERVERLESS · $0 ON AWS",
    "title": "llm-gateway",
    "subtitle": "Catch runaway AI agents before the bill explodes.",
}
PROBLEM = {
    "label": "THE PROBLEM",
    "lines": [
        "AI agents call LLMs on their own, all day long.",
        "One bug can trap an agent in a loop: thousands of calls an hour.",
        "Nobody notices. Nobody can stop it. Then the bill arrives.",
    ],
}
IDEA = {
    "label": "THE IDEA",
    "headline": "Every agent calls the LLM through one gateway.",
    "footer": "When an agent goes rogue, its breaker trips.",
}

# demo stage captions, filled from the recorded run
STAGES = {
    "normal": ("1 · NORMAL",
               f"A healthy agent asks {R['normal']['sent']} different questions. "
               f"All {R['normal']['allowed']} allowed, {R['normal']['false_blocks']} blocked."),
    "loop": ("2 · LOOP",
             f"A buggy agent repeats one question. Caught on call {R['loop']['calls_to_catch']}, "
             f"in {fmt_s(R['loop']['seconds_to_catch'])} seconds."),
    "too_fast": ("3 · TOO FAST",
                 f"An agent goes over its limit. Throttled at call {R['too_fast']['throttled_at_call']}, "
                 f"suspended at call {R['too_fast']['calls_to_catch']}."),
    "token_bomb": ("4 · TOKEN BOMB",
                   "One 50,000-character prompt. Rejected on the first call. No model ever sees it."),
    "retry_storm": ("5 · RETRY STORM",
                    f"An agent retries forever after errors. Suspended after "
                    f"{R['retry_storm']['calls_to_catch']} failures, in {fmt_s(R['retry_storm']['seconds_to_catch'])} s."),
    "summary": ("RESULT",
                f"{SUM['caught']} of {SUM['problems']} problems caught. {SUM['false_blocks']} false blocks. "
                f"Average catch time {fmt_s(SUM['avg_seconds_to_catch'])} s. All measured live."),
}

# (start, end, label, text) in output seconds; demo-stage captions are added by the editor
CAPTIONS = [
    (18.9, 22.4, None, "This is the live dashboard, running on the real AWS deployment."),
    (22.6, 25.9, None, "Every agent is a breaker: up is active, middle is suspended, down is killed."),
    (26.1, 29.3, None, "Every request shows up live, with why it was allowed or blocked. Never the prompt."),
    (29.7, 32.4, None, "Let's run the live demo: five buggy bots, one after another."),
    (67.4, 70.4, None, "Behind the scenes, a private CloudWatch dashboard puts cost first."),
    (70.6, 73.4, None, "Free-tier meters show the whole project stays at $0."),
    (73.6, 75.8, None, "Errors, latency and database capacity, all on one page."),
    (76.4, 81.8, None, "Real agents alert their owner on Telegram, with a one-tap /resume."),
    (82.4, 85.9, None, "It's open source: Terraform, 51 tests, CI on every PR, and a learning guide."),
    (86.1, 89.8, None, "Every design choice swaps a paid AWS service for an always-free one."),
]

TELEGRAM = {
    "bot": "LLM Gateway Guard",
    "text": "leetcode-bot (owner dheepak) SUSPENDED: same prompt 6x in 2 min. Blocked 1 call. "
            "Est. cost avoided $0.0003. /resume leetcode-bot",
    "time": "now",
}

RESULTS = [
    (f"call {R['loop']['calls_to_catch']}", "a looping agent is caught"),
    (f"{fmt_s(SUM['avg_seconds_to_catch'])} s", "average time to suspend"),
    (f"{SUM['false_blocks']}", "false blocks on normal traffic"),
    ("$0", "AWS cost, always-free tier"),
]

END = {
    "title": "llm-gateway",
    "links": ["github.com/dheepakkaran/llm-gateway", "dheepakkaran.github.io/llm-gateway"],
    "byline": "Built by Dheepak Karan",
}
