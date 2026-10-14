# llm-gateway product video: script

Length 2:16.9 · 1920×1080, 30 fps · voice-over by Kokoro (local AI voice, Apache-2.0, voice `am_michael`) · original background music generated in code (`scripts/video/music.py`), ducked under the voice · captions burned in, also in `media/llm-gateway-demo.srt`.

Every number on screen comes from the recorded demo run (`media/raw/capture.json`) or the simulator, not typed by hand.

## Scenes

| Time | Scene | What you see |
|---|---|---|
| 0:00.0–0:07.0 | Title | "llm-gateway": Catch runaway AI agents before the bill explodes. (OPEN SOURCE · SERVERLESS · $0 ON AWS) |
| 0:07.0–0:20.4 | The problem | AI agents call LLMs on their own, all day long. / One bug can trap an agent in a loop: thousands of calls an hour. / Nobody notices. Nobody can stop it. Then the bill arrives. |
| 0:20.4–0:32.3 | The idea | Every agent calls the LLM through one gateway. An animated diagram builds up: agents, the gateway with its checks, the LLM providers, then loop-bot trips and is suspended. "When an agent goes rogue, its breaker trips." |
| 0:32.3–0:50.0 | Live dashboard tour | The real GitHub Pages dashboard in a browser window. The camera zooms into the agent breakers, then the live request feed, following the cursor. |
| 0:50.0–0:54.4 | Run Live Demo | The cursor clicks Run Live Demo; a ripple marks the click and the camera moves to the stage panel. |
| 0:54.4–1:37.4 | The live demo | The five stages run live against the AWS deployment, sped up between steps. A spotlight dims everything except the stage panel; the camera zooms in on each result. |
| 1:37.4–1:43.6 | Telegram alert | The alert a real agent's owner receives: "leetcode-bot (owner dheepak) SUSPENDED: same prompt 6x in 2 min. Blocked 1 call. Est. cost avoided $0.0003. /resume leetcode-bot" |
| 1:43.6–1:58.8 | Open source | The GitHub repo: files, README, then the $0 design decisions table. |
| 1:58.8–2:08.1 | Results | call 6 a looping agent is caught · 2.46 s average time to suspend · 0 false blocks on normal traffic · $0 AWS cost, always-free tier |
| 2:08.1–2:16.9 | End card | llm-gateway · github.com/dheepakkaran/llm-gateway · dheepakkaran.github.io/llm-gateway · Built by Dheepak Karan |

## Voice-over (transcript)

What the voice says, in order. On the title cards the words are already on screen, so there's no caption there.

| Time | Scene | Narration | Caption on screen |
|---|---|---|---|
| 0:00.6 | Title | Meet LLM gateway. It catches runaway AI agents before the bill explodes. | (text on screen) |
| 0:07.4 | The problem | AI agents call LLMs on their own, all day long. | (text on screen) |
| 0:11.1 | The problem | One bug can trap an agent in a loop: thousands of calls an hour. | (text on screen) |
| 0:15.6 | The problem | Nobody notices. Nobody can stop it. Then the bill arrives. | (text on screen) |
| 0:20.9 | The idea | The fix: every agent calls the LLM through one gateway. | (text on screen) |
| 0:24.9 | The idea | When an agent goes rogue, its breaker trips. It's suspended in seconds, and the owner gets a Telegram alert. | (text on screen) |
| 0:32.9 | Live dashboard tour | This is the live dashboard, running on the real A-W-S deployment. | This is the live dashboard, running on the real AWS deployment. |
| 0:38.9 | Live dashboard tour | Every agent is a breaker. Up is active, middle is suspended, and down is killed. | Every agent is a breaker: up is active, middle is suspended, down is killed. |
| 0:44.5 | Live dashboard tour | Every request shows up live, with the reason it was allowed or blocked. | Every request shows up live, with the reason it was allowed or blocked. |
| 0:50.3 | Run Live Demo | Let's run the live demo: five buggy bots, one after another. | Let's run the live demo: five buggy bots, one after another. |
| 0:54.8 | The live demo | First, a healthy agent asks 5 different questions. All 5 are allowed. | 1 · NORMAL: A healthy agent asks 5 different questions. All 5 are allowed. |
| 1:01.8 | The live demo | Next, a buggy agent repeats one question. It's caught on call 6, in 1 point eight five seconds. | 2 · LOOP: A buggy agent repeats one question. Caught on call 6, in 1.85 seconds. |
| 1:09.6 | The live demo | This agent goes over its limit. It's throttled at call 11, and suspended at call 13. | 3 · TOO FAST: An agent goes over its limit. Throttled at call 11, suspended at call 13. |
| 1:17.0 | The live demo | One giant prompt, fifty thousand characters. Rejected on the first call. No model ever sees it. | 4 · TOKEN BOMB: One 50,000-character prompt. Rejected on the first call. No model ever sees it. |
| 1:24.5 | The live demo | This agent retries forever after errors. It's suspended after 10 failures. | 5 · RETRY STORM: An agent retries forever after errors. Suspended after 10 failures. |
| 1:30.9 | The live demo | 4 out of 4 problems caught. 0 false blocks. And every number is measured live. | RESULT: 4 of 4 problems caught. 0 false blocks. All measured live. |
| 1:37.9 | Telegram alert | Real agents alert their owner on Telegram, with a one tap resume. | Real agents alert their owner on Telegram, with a one-tap /resume. |
| 1:44.4 | Open source | It's open source: Terraform, fifty-one tests, CI on every pull request, and a learning guide. | It's open source: Terraform, 51 tests, CI on every pull request, and a learning guide. |
| 1:51.4 | Open source | Every design choice swaps a paid A-W-S service for an always-free one. | Every design choice swaps a paid AWS service for an always-free one. |
| 1:59.3 | Results | A looping agent is caught on call 6. 0 false blocks. And it all runs for zero dollars on A-W-S. | (text on screen) |
| 2:08.9 | End card | LLM gateway. Built by Deepak Karan. The code and the live demo are linked below. | (text on screen) |

## How it was made

1. `scripts/video/capture.py`: headless Chrome at 2× records the live dashboard, runs the real demo movie and saves element positions so the cursor and zoom can aim at real buttons and panels.
2. `scripts/video/overlays.py`: Chrome renders every caption, title, diagram and card with the dashboard's own fonts.
3. `scripts/video/music.py`: synthesises the background track (pads, arpeggio, soft beat).
4. `scripts/video/narration.py`: the voice-over lines, spoken by the Kokoro model on this laptop; the editor times every scene to its narration and lowers the music while the voice speaks.
5. `scripts/video/make_video.py`: composites a rounded browser window on a gradient, an eased camera that zooms toward the cursor, click ripples, crossfades, a spotlight on the demo panel and the captions, then encodes H.264 with AAC audio.
