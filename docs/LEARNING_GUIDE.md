# llm-gateway: the learning guide

This guide explains the whole project from zero. Read it like a textbook: each part says **what** a piece is, **why** we built it that way, **what we did not choose and why**, and answers the questions a beginner would ask. At the end there are interview questions with answers you can say out loud.

You don't need to read it in one go. Parts 1–3 give the big picture. Parts 4–9 explain the guard itself. Parts 10–15 cover everything around it. Parts 16–21 prepare you for interviews.

---

## Contents

1. [The story in two minutes](#1-the-story-in-two-minutes)
2. [The big picture](#2-the-big-picture)
3. [Follow one request from start to end](#3-follow-one-request-from-start-to-end)
4. [The AWS building blocks](#4-the-aws-building-blocks)
5. [The guard, step by step](#5-the-guard-step-by-step)
6. [The detection rules with examples](#6-the-detection-rules-with-examples)
7. [The agent state machine](#7-the-agent-state-machine)
8. [The data layer: tables, the window item and concurrency](#8-the-data-layer-tables-the-window-item-and-concurrency)
9. [Keys and secrets](#9-keys-and-secrets)
10. [Providers and fallback](#10-providers-and-fallback)
11. [The Telegram bot](#11-the-telegram-bot)
12. [The dashboard, the demo movie and the stats snapshot](#12-the-dashboard-the-demo-movie-and-the-stats-snapshot)
13. [The simulator: measuring instead of claiming](#13-the-simulator-measuring-instead-of-claiming)
14. [Terraform and deployment](#14-terraform-and-deployment)
15. [Tests, CI and the PR workflow](#15-tests-ci-and-the-pr-workflow)
16. [Monitoring and cost](#16-monitoring-and-cost)
17. [Problems we hit and how we solved them](#17-problems-we-hit-and-how-we-solved-them)
18. [Honest limitations](#18-honest-limitations)
19. [What would change in production](#19-what-would-change-in-production)
20. [Interview questions and answers](#20-interview-questions-and-answers)
21. [Glossary](#21-glossary)
22. [Hands-on exercises](#22-hands-on-exercises)
23. [Command cheat sheet](#23-command-cheat-sheet)

---

## 1. The story in two minutes

### The problem

A company runs many **AI agents**. An agent is just a program that calls an LLM (Groq, Gemini, OpenAI…) again and again to finish a task: answer support tickets, write code, summarise documents.

Now imagine one agent gets a bug. It gets stuck asking the **same question again and again**, thousands of times an hour. Three bad things happen:

1. **Nobody notices.** There's no alarm; the agent doesn't crash, it just keeps calling.
2. **Nobody can stop it quickly.** There's no off switch between the agent and the LLM.
3. **Nobody knows who owns it.** When the bill arrives, nobody knows which team's bot did it.

Every call costs money, so the bill at month end can be huge.

### The solution

Put a **gateway** in the middle. Every agent must call the LLM **through** the gateway, never directly. The gateway is like the **watchman at an apartment gate**:

| Watchman at the gate | Our gateway |
|---|---|
| Every visitor shows an ID card | Every agent sends its own key |
| The watchman's book says whose visitor it is | Every agent is registered with an **owner** |
| Rules: no entry after 11pm, no big trucks | Rules: max requests per minute, max prompt size, daily budget |
| Notices the same person coming back 50 times | Notices the same prompt repeated (a **loop**) |
| Stops them and calls the flat owner | **Suspends** the agent and sends a **Telegram alert** to the owner |
| Emergency: lock the gate for everyone | **Kill switch**: stop all agents in one command |

The extra pieces show it working:

- A **public dashboard** (GitHub Pages) shows everything live, plus a **"demo movie"** where five buggy bots get caught one by one.
- A **simulator** measures how fast each bug is caught, with real numbers.
- It all runs on the **AWS free tier**, so it costs **$0**.

### The one-line pitch

> "Every AI agent goes through my gateway. If one gets stuck in a loop, the gateway catches it within seconds, suspends it and tells the owner, before the bill explodes. It's serverless on AWS and costs $0."

### The 30-second interview version

> "Companies run many AI agents, and a buggy one can loop and fire thousands of LLM calls an hour with no owner and no off switch. I built a serverless LLM gateway on AWS Lambda and DynamoDB. Every agent calls models through it with its own key. It enforces per-agent limits and detects loops, retry storms and oversized prompts. When a rule fires, it suspends the agent like a circuit breaker and alerts the owner on Telegram. I measured it with a simulator: a looping agent is caught on its 6th call in about 2 seconds, with zero false blocks on normal traffic. A public dashboard plays a live demo, and the whole thing runs on the AWS always-free tier."

---

## 2. The big picture

```mermaid
flowchart LR
  A[AI agents] -->|"Bearer gw_agent_secret"| GW[Gateway Lambda<br/>Function URL]
  D[Dashboard<br/>GitHub Pages] -->|/stats, /demo/*| GW
  GW -->|1 read + 2 writes per request| DDB[(DynamoDB<br/>agents, counters,<br/>usage, incidents)]
  GW -->|secrets, kill switch| SSM[SSM Parameter Store]
  GW -->|fallback chain| P1[Groq] & P2[Gemini] & M[mock model]
  GW -.async alert.-> BOT[Telegram bot Lambda]
  GW -.async start.-> DR[Demo runner Lambda]
  DR -->|HTTPS like a real agent| GW
  BOT <-->|webhook + alerts| TG[Telegram]
  SCH[EventBridge Scheduler] -->|every 15 min traffic| DR
  SCH -->|daily report| BOT
```

There are **three Lambda functions**:

| Lambda | Job | File |
|---|---|---|
| `llmgw-gateway` | The guard. Every request goes here. Also serves the admin and dashboard routes. | `src/gateway_handler.py` |
| `llmgw-demo` | Plays the demo movie (fake buggy bots) and the background traffic every 15 min. | `src/demo_handler.py` |
| `llmgw-bot` | The Telegram bot: alerts, commands (`/kill`, `/status`…), daily report. | `src/bot_handler.py` |

All three are built from **one zip of the `src/` folder**. Each Lambda just starts a different file.

### How the code is organised

The most important design choice in the code is **pure logic separated from AWS calls**:

| Pure logic (no AWS, easy to test) | Thin AWS wrappers |
|---|---|
| `detection.py`: the rules (is this a loop?) | `store.py`: DynamoDB, SSM, Lambda calls |
| `state_machine.py`: ACTIVE / SUSPENDED / KILLED | `telegram.py`: sends Telegram messages |
| `guard.py`: runs the pipeline on the per-agent window | |
| `keys.py`, `incidents.py`, `demo_lock.py`, `stats.aggregate` | |

**Why?** Pure functions take input and give output, nothing else. You can test them in milliseconds with pytest, without AWS, without the internet, without money. That's why there are 51 tests that run in 0.3 seconds. The AWS wrapper files are small and "boring", so there's less that can go wrong there.

**Beginner question:** *"What does pure function mean?"*
A function whose result depends only on its inputs and which changes nothing outside itself. `check_repeat([1,2,3,4,5,6], limits)` always gives the same answer. It doesn't read a database or the clock. So a test can call it with fake times like `1000, 1001, 1002` and check the answer.

---

## 3. Follow one request from start to end

Let's follow a real example. `leetcode-bot` (owner: dheepak) sends:

```bash
curl -s $GW/v1/chat/completions \
  -H "authorization: Bearer gw_leetcode-bot_Xk3...secret" \
  -d '{"model":"fast","max_tokens":100,"messages":[{"role":"user","content":"Solve two-sum"}]}'
```

```mermaid
sequenceDiagram
  participant A as leetcode-bot
  participant G as Gateway Lambda
  participant S as SSM
  participant D as DynamoDB
  participant P as Groq / Gemini
  A->>G: POST /v1/chat/completions (Bearer key)
  G->>S: kill switch on? (cached 15 s)
  G->>D: GetItem agents/leetcode-bot (cached 10 s)
  Note over G: check key hash, check status
  G->>D: GetItem counters/w#leetcode-bot (strongly consistent)
  Note over G: token bomb? rate? loop? spike? budget?
  G->>D: UpdateItem window, only if version unchanged
  G->>P: chat completion (fallback if 429/5xx/timeout)
  P-->>G: answer + token usage
  G->>D: PutItem usage record
  G-->>A: OpenAI-style answer + x_gateway info
```

Step by step, in plain words:

1. **Kill switch.** Is the emergency switch on? The value lives in SSM and is remembered for 15 seconds, so we don't ask SSM every time. If it's on: `503`.
2. **Who are you?** The key starts with `gw_leetcode-bot_`, so the agent ID is `leetcode-bot`. Load that agent from DynamoDB (remembered for 10 s), hash the key with SHA-256 and compare with the stored hash. Wrong key: `401`.
3. **Are you allowed?** If the agent is KILLED: `403`. If SUSPENDED and the cooldown isn't over: `403` plus how many seconds remain.
4. **Read the agent's "window".** This is one small DynamoDB item with this agent's recent activity: requests this minute, recent prompt fingerprints, recent failures.
5. **Run the rules** on the window: prompt too big? too many this minute? same prompt repeated? too many tokens? daily budget used up?
6. **Save the updated window**, but only if nobody else changed it since we read it (the version check; see Part 8).
7. **Call the model.** `fast` means Groq first; if Groq fails, Gemini.
8. **Write a usage record**: tokens, time taken, estimated cost, outcome. Never the prompt text.
9. **Reply** in the normal OpenAI format, plus an extra `x_gateway` object:

```json
"x_gateway": {"provider": "groq", "model": "qwen/qwen3.8-27b", "latency_ms": 373,
              "est_cost": 0.00004, "agent_status": "ACTIVE", "fallback_used": false}
```

(Example values; the real ones depend on the prompt and the provider.)

Now imagine `leetcode-bot` has a bug and sends "Solve two-sum" again and again. Calls 1 to 5 succeed. On **call 6**, step 5 sees the same prompt fingerprint **6 times within 2 minutes**, so it:

- returns `429 loop_detected` and doesn't call the model,
- changes the agent to **SUSPENDED for 15 minutes**,
- writes an **incident** record,
- sends the owner a **Telegram alert**: `leetcode-bot (owner dheepak) SUSPENDED: same prompt 6x in 2 min. Blocked 1 call. Est. cost avoided $0.0003. /resume leetcode-bot`

Call 7 gets `403 agent_suspended` at step 3, the cheapest possible rejection.

We did exactly this test on the real deployment, and it happened exactly like this.

---

## 4. The AWS building blocks

For each service: what it is, why we used it, and what we avoided.

### AWS Lambda: our code runs here

**What:** you upload code; AWS runs it **only when a request comes**. No server to manage. You pay per request and per millisecond, and the always-free tier gives **1,000,000 requests and 400,000 GB-seconds every month**.

**Analogy:** owning a car vs taking a taxi. A server is a car: you pay even when it's parked. Lambda is a taxi: you pay only for the ride.

**Beginner questions:**
- *"What's a cold start?"* When no copy of your function is running, AWS must start one (load Python, load the code). The first request is slower, about 0.5–1 s. Later requests reuse the warm copy and are fast. This is why our p95 latency is higher than p50.
- *"What's GB-second?"* Memory × time. Our gateway uses 256 MB = 0.25 GB. A 0.2 s request costs 0.25 × 0.2 = 0.05 GB-s. 400,000 GB-s ≈ 8 million such requests.
- *"Why is memory remembered between requests?"* A warm Lambda copy keeps its Python variables. We use that for small caches (agent for 10 s, kill switch for 15 s). Each copy has its own memory, so caches aren't shared.

**Why ARM (`arm64`)?** Graviton processors are cheaper per millisecond and the free tier is the same, so it's free extra headroom.

### Lambda Function URL: the public HTTPS address

**What:** a built-in `https://...lambda-url.us-east-1.on.aws/` address for a Lambda. **No extra cost.**

**Why not API Gateway?** API Gateway adds features (usage plans, WAF, throttling, API keys), but it's **paid per request** after its 12-month trial. We do key checks and rate limits ourselves, inside the Lambda, for $0.

**Beginner question:** *"auth type NONE? Isn't that unsafe?"* NONE means AWS doesn't check who's calling; **our code checks**. Every chat request needs a valid gateway key, admin routes need the admin key, and only the dashboard routes are public (and they never return secrets or prompts). We had to add **two permissions**: `lambda:InvokeFunctionUrl` and, a newer AWS rule, `lambda:InvokeFunction` limited to "only when called via the Function URL".

### DynamoDB: our database

**What:** a NoSQL key-value database. You read and write items by key; no SQL server to run.

**Our tables:**

| Table | Key | What's inside | Auto-delete (TTL) |
|---|---|---|---|
| `llmgw-agents` | `agent_id` | owner, team, key hash, status, cooldown, limits | never |
| `llmgw-counters` | `pk` | per-agent window (`w#agent`), registry, stats snapshot, demo state | windows after 35 days |
| `llmgw-usage` | `agent_id` + `sk` (time#id) | one row per request: outcome, tokens, latency, cost | 30 days |
| `llmgw-incidents` | `agent_id` + `sk` | every suspend / kill / resume with evidence | 90 days |

**Provisioned vs on-demand.** This is the most important cost decision.

- **On-demand:** pay per request. Unlimited, but every request costs money. ❌
- **Provisioned:** you reserve a fixed speed, X reads/sec and Y writes/sec. The always-free tier gives **25 read units + 25 write units in total**. We use **24 + 24**. ✅

**Analogy:** a toll road with exactly 24 free lanes. If more cars come than the lanes allow, cars must wait (AWS calls this **throttling**), but you are **never charged extra**. That's why DynamoDB here **can't overspend**.

**Units, simply:**
- 1 **WCU** (write unit) = writing an item up to **1 KB**, once per second.
- 1 **RCU** (read unit) = one strongly consistent read of up to **4 KB** per second (or two eventually consistent reads).

That's why we keep the window item **under 1 KB**: then every write costs exactly 1 WCU.

**TTL (time to live):** like the expiry date on milk. We store an expiry timestamp in the `ttl` field, and DynamoDB deletes the item for free after that time. Old usage rows disappear after 30 days on their own.

**Why no GSI (secondary index)?** A GSI is a second copy of the table sorted differently. It would let us look agents up by key hash, but it **uses its own capacity units**, which eats our 25. Instead, we put the agent ID inside the key itself (Part 9), so no index is needed.

**Why no scans?** A scan reads every item in a table, which is slow and costs capacity proportional to table size. For the dashboard we keep a small **registry** item with the list of agent IDs, then fetch exactly those items with `BatchGetItem`, and the last 20 rows per agent with `Query`.

### SSM Parameter Store: the locker for secrets

**What:** a key-value store for configuration. **SecureString** parameters are encrypted with KMS. **Standard** parameters are **free**.

**What's inside:** Groq key, Gemini key, Telegram token, Telegram chat ID, webhook secret, demo secret, the admin key **hash**, and the `kill_all` switch (plain String).

**Why not Secrets Manager?** It's nicer (automatic rotation), but costs **$0.40 per secret per month**. 7 secrets would be $2.80/month.

**Why not environment variables?** Anyone who can view the Lambda's configuration in the console could read them, and they end up in Terraform state. SSM keeps secrets encrypted, and only the Lambdas whose IAM role allows it can read them.

**KMS:** the encryption service. We use the **AWS-managed key** `aws/ssm`, which has no monthly fee. A **customer-managed key** would cost $1/month. KMS gives 20,000 free requests a month, and we cache secrets for 5 minutes, so we use very few.

### IAM: who is allowed to do what

**What:** permissions. Each Lambda has its **own role** with **only the permissions it needs** ("least privilege").

| Role | Can do | Can't do |
|---|---|---|
| gateway | read/write the 4 tables, read 4 SSM params, write `kill_all`, invoke bot and demo Lambdas | read the Telegram token |
| demo | write demo agents + demo state, read the demo secret | read usage, read provider keys |
| bot | read tables, read Telegram params, invoke the gateway | write any table |
| scheduler | invoke demo and bot | anything else |

**Beginner question:** *"Why not give everyone admin to keep it simple?"* If one function has a bug or a leaked token, the damage stays small. The bot can't delete your tables; the demo can't read your Groq key.

### EventBridge Scheduler: the alarm clock

Runs a target on a schedule. We have two:
- every **15 minutes**: the demo Lambda sends 3 normal questions as `good-bot`, so the live feed is never empty;
- every day at **9:00 New York time**: the bot sends the daily report to Telegram.

It gives 14 million free invocations a month; we use about 3,000.

### CloudWatch: logs, metrics, dashboard

- **Logs:** everything a Lambda prints. We create the log groups ourselves with **7-day retention**, so old logs are deleted and storage stays tiny.
- **Metrics:** numbers over time (invocations, errors, duration). AWS services send basic metrics for free.
- **Metric filters:** turn log lines into numbers. Our gateway prints `BLOCKED {...}` or `STATE_CHANGE {...}`, and two filters count those lines.
- **Dashboard:** `llmgw` shows cost first, then free-tier meters, then health.

### Things we deliberately did NOT use

| Avoided | Why |
|---|---|
| API Gateway | per-request cost; Function URLs are free |
| Secrets Manager | $0.40/secret/month |
| Customer-managed KMS keys | $1/key/month |
| NAT Gateway / Lambda in a VPC | NAT costs ~$32/month; we don't need a private network |
| EC2 / RDS / ElastiCache | always-on servers cost money |
| S3 | not needed; dashboard is on GitHub Pages |
| DynamoDB on-demand / autoscaling | can overspend; provisioned can't |
| Step Functions | the demo runs inside one Lambda instead |
| X-Ray active tracing | not needed for this size |
| Logs Insights dashboard widgets | they scan logs on every refresh |

---

## 5. The guard, step by step

The pipeline, from `src/gateway_handler.py` (`chat()`):

| # | Check | Result if it fails | Counts as |
|---|---|---|---|
| 1 | Global kill switch (SSM, cached 15 s) | `503 kill_all` | — |
| 2 | Parse key → load agent (cached 10 s) → compare SHA-256 | `401 invalid_key` | — |
| 3 | Agent status | `403 agent_killed` / `403 agent_suspended` | blocked |
| 4 | Token bomb: estimated prompt tokens > `max_prompt_tokens` (8,000) | `413 token_bomb` | **violation** |
| 5 | Rate limit: requests this minute > `rpm` (20) | `429 rate_limit` | **violation** |
| 6 | Loop: same prompt > 5 times in 2 min, or token spike | `429 loop_detected` / `token_spike` + **suspend** | detection |
| 7 | Daily token budget (200,000) | `429 daily_budget` | blocked |
| 8 | Call the provider with fallback | `502 provider_error` if all fail | failure |
| 9 | Write the usage record | — | — |

### Why this order?

**Cheapest checks first.** Step 1 needs no database at all, since it's cached. Step 2 usually hits the cache. Step 3 uses data we already loaded. Only from step 4 do we need the window item. The most expensive thing, calling a real LLM, is last.

A runaway agent that's already suspended gets rejected at **step 3**, without touching the database. That matters: if it fires 100 calls per second, we don't want 100 database writes per second. See "coalescing" in Part 8.

### How do we estimate tokens before calling the model?

`tokens ≈ characters / 4`. It's a rough rule of thumb for English text. It's good enough to catch a 50,000-character prompt (~12,500 tokens) against a limit of 8,000.

### "Reserve tokens up front": why?

The token-spike and daily-budget rules need "tokens used". But we only know the real token count **after** the model answers, and recording it then would need **another database write**.

So we **reserve** tokens before the call: `prompt estimate + max_tokens` (the most the model may write; default 256, capped at 1,024). It's like a **hotel blocking an amount on your card** at check-in. The real number goes into the usage record. The window always has a slightly high (safe) estimate, and we keep **2 writes per request**.

**Beginner question:** *"Isn't the reserved number wrong?"* It's an **upper bound**. For protection, being a little strict is better than being too loose. The exact numbers are still in the usage table for reports.

---

## 6. The detection rules with examples

All defaults live in `src/config.py`. Every agent can override them (`limits` when registering).

### Rule 1: repeat prompt (loop)

**Fires when** the same normalized prompt is seen **more than 5 times within 2 minutes**, i.e. on the **6th** time.

**Normalized** means: lowercase, collapse all whitespace, and include **all messages** (system + user + history). So `"Hello   World"` and `"hello world"` count as the same.

We don't store the prompt. We store a **fingerprint (hash)** of it, `sha256(...)`, keeping only the first 8 hex characters in the window.

```
time:   0s   0.3s  0.7s  1.0s  1.3s  1.7s
call:   1     2     3     4     5     6
same?   ✔     ✔     ✔     ✔     ✔     ✔ → 6 > 5 → SUSPEND
```

Measured: caught on the **6th call** in about **2.0 s**, 3 out of 3 runs.

**Beginner questions:**
- *"What if a normal agent repeats a question, like a status check every 30 s?"* In 2 minutes that's 4 times, below 6, so it's fine. We tested exactly this (`test_repeats_spread_beyond_2_minutes_are_fine`).
- *"Why 8 characters of the hash?"* To keep the window item under 1 KB (1 write unit). Two different prompts getting the same 8-char fingerprint is about a 1-in-100-million chance among 40 recent prompts.
- *"Will it catch an agent that rephrases slightly each time?"* No. This rule only catches **exact** repeats. That's a known limitation (Part 18); the fix would be embedding-based similarity.

### Rule 2: rate limit

**Fires when** requests in the **current minute** > `rpm` (default 20). Returns `429` and counts as a **violation**.

We use **fixed minute buckets**: minute 12:00–12:01, then 12:01–12:02. Simple and cheap: one counter that resets when the minute changes.

**Beginner question:** *"What's the downside of fixed buckets?"* An agent can send 20 at 12:00:59 and 20 at 12:01:00, which is 40 in 2 seconds. A **sliding window** or **token bucket** is fairer but needs more state. Good interview point.

### Rule 3: token bomb

**Fires when** the estimated prompt tokens > `max_prompt_tokens` (8,000). Returns `413` on the **first** call and counts as a **violation**.

The demo's bomb-bot sends 50,000 characters (≈12,500 tokens). Measured: rejected on call 1 in about 0.25 s, and **0 calls reached a model**.

### Rule 4: repeated violations

**Fires when** there are **3 or more** violations (token bomb or rate limit) within 5 minutes, and **suspends** the agent.

This turns "you're going too fast" into "you're misbehaving, stop". speedy-bot (rpm 10): calls 1–10 OK, call 11 gets `429` (violation 1), call 12 (violation 2), call 13 (violation 3), so it's suspended. Measured: **throttled at call 11, suspended at call 13, ~4.5 s**.

### Rule 5: retry storm

**Fires when** there are **10 or more failed or blocked** requests in 1 minute, and **suspends** the agent.

A failing agent that retries instantly forever is a classic runaway pattern. retry-bot's provider always fails (`mock_error_rate = 1.0`). Measured: suspended after the **10th failure**, ~3.6 s.

**Beginner question:** *"Why does retry-bot retry each task 3 times and then move to the next task?"* If it retried the **same** prompt forever, **Rule 1 (loop)** would catch it on the 6th call first. We wanted the demo to show the **retry-storm** rule specifically, so it behaves like a realistic agent: "try a task 3 times, then give up and take the next task".

### Rule 6: token spike

**Fires when** reserved tokens in the current minute > `max_tokens_per_min` (40,000), and **suspends** the agent.

It catches an agent burning tokens fast even with different prompts and under the rpm limit.

---

## 7. The agent state machine

```mermaid
stateDiagram-v2
  [*] --> ACTIVE
  ACTIVE --> SUSPENDED: a rule fires (15 min, demo 2 min)
  SUSPENDED --> ACTIVE: cooldown over (on next request)
  ACTIVE --> KILLED: rule fires again within 24 h (not demo agents)
  ACTIVE --> KILLED: manual kill
  SUSPENDED --> KILLED: manual kill
  KILLED --> ACTIVE: manual resume (clears history)
  SUSPENDED --> ACTIVE: manual resume
```

**Analogy:** the **MCB (circuit breaker) in a house**. Overload trips it. After a while you can switch it back on. If it keeps tripping, you call the electrician (KILLED, manual only). That's why this pattern is called a **circuit breaker**.

The rules (`src/state_machine.py`):

- **ACTIVE → SUSPENDED** when any detection fires. Cooldown is **15 minutes** for real agents, **2 minutes** for demo agents (so visitors can rerun the demo).
- **SUSPENDED → ACTIVE** happens **lazily**: there's no timer. The next request after the cooldown flips it back. That means no extra Lambda and no extra schedule.
- **Second detection within 24 h → KILLED**. A bug that comes back right after cooldown needs a human. Demo agents are exempt.
- **Manual kill → KILLED. Manual resume → ACTIVE**, and it clears the violation history and the current-minute counter (a clean slate).

Every change writes an **incident**: agent, owner, rule, evidence numbers (e.g. `repeats: 6, time_to_detect_s: 1.8`), calls blocked so far, estimated cost avoided, who did it, and when.

**Beginner questions:**
- *"Why does a demo agent never get killed?"* Because visitors press the demo button again and again. If the second run killed loop-bot, the demo would break.
- *"How does 'lazy' reactivation work?"* The agent item stores `cooldown_until` (a timestamp). On each request we check: is now past `cooldown_until`? If yes, set it ACTIVE again (with a conditional write, so only one request does it) and continue.
- *"Two Lambda copies detect a loop at the same moment. Couldn't the agent go SUSPENDED and then immediately KILLED?"* Good catch, and we handle it. The status change is a **conditional write**: "set SUSPENDED **only if** the status is currently ACTIVE". The second copy's write fails, and it simply blocks the request. Without this, the second detection would look like "detected again within 24 h" and wrongly kill the agent.

---

## 8. The data layer: tables, the window item and concurrency

### The per-agent "window" item

Each agent has **one** small item in the counters table, `w#<agent_id>`. It holds everything the rules need (`src/guard.py`):

| Field | Meaning |
|---|---|
| `st`, `cu` | status mirror, cooldown_until |
| `m`, `mr`, `mt` | current minute, requests in it, tokens in it |
| `h`, `hc`, `hb` | current hour, calls, blocked (for dashboard cards) |
| `dy`, `dt` | today, tokens today (daily budget) |
| `p` | `{prompt fingerprint: [times]}` for the last 2 min |
| `f` | times of failed/blocked calls in the last minute |
| `v` | times of violations in the last 5 min |
| `bl`, `tc`, `tb` | blocked since last state change, lifetime calls, lifetime blocked |

It's stored as one compact JSON string. Times are stored as **deciseconds since the oldest time in the item**, small numbers instead of 10-digit timestamps, to stay **under 1 KB** even with 40 different prompts. A test checks this (`test_encode_roundtrip_and_size_under_1kb`).

**Why one item and not many counters?** Every extra counter would be an extra write per request. With one item: **1 read + 1 write** for all the rules.

### The 2-writes rule

A normal request does exactly:
1. **write** the updated window,
2. **write** the usage record.

A provider failure adds a third write (to record the failure for the retry-storm rule). The tightest limit is the usage table's 8 write units, so the whole system handles about **8 requests per second** sustained (more in short bursts, because DynamoDB saves up unused capacity for a few minutes). That's plenty for this project.

### Optimistic locking: two requests at the same time

**Problem:** two requests from the same agent arrive at the same moment on two Lambda copies. Both read the window ("5 requests this minute"), both add 1, and both write "6". One request was **lost**. That's a **race condition**.

**Solution:** the window has a **version number** `ver`.

```
Copy A reads  (ver 7, count 5)      Copy B reads (ver 7, count 5)
Copy A writes count 6  IF ver == 7  → OK, now ver 8
Copy B writes count 6  IF ver == 7  → FAILS (it's 8 now)
Copy B re-reads (ver 8, count 6) → writes count 7 IF ver == 8 → OK
```

**Analogy:** two people editing the same cell in a shared spreadsheet. Before saving, you check "is it still the version I opened?" If not, you reload and redo your change.

It's called **optimistic** because we assume conflicts are rare and only retry when one happens (up to 4 times). The opposite, **pessimistic** locking, would take a lock first and make everyone wait.

**Beginner questions:**
- *"Why not DynamoDB's atomic counter (`ADD`)?"* `ADD count 1` is perfect for one number. But our rules need lists of timestamps (last 2 minutes of prompts), pruning, and decisions based on all of them together. That's a read-modify-write, so we need the version check.
- *"Why a strongly consistent read?"* DynamoDB's default (eventually consistent) read may return data that's a fraction of a second old. For counting, we want the latest. It costs 1 RCU instead of 0.5.

### Fail closed

If DynamoDB is **throttled** (we used more than our 24 units), the wrapper raises `Busy`, and the gateway returns **`429 gateway_busy`** and **does not call the model**.

**Analogy:** an ATM whose bank connection is down **doesn't give cash**. It doesn't give unlimited cash either. For a protection system, "when unsure, block" is correct: we never send a request to a paid model that we couldn't count. The opposite, **fail open**, keeps the service up but loses protection.

**Beginner question:** *"Won't that block good agents when the system is busy?"* Yes, briefly, and they get `429` with a clear message to retry. That's a trade-off we chose on purpose: availability vs safety. For a cost guard, safety wins.

### Coalescing blocked calls

When a suspended agent keeps calling, each call is rejected at step 3. We still want to count "calls blocked" for the dashboard and incidents. Writing to the database **for every blocked call** would let a runaway agent eat everyone's write capacity, a **noisy neighbour** problem.

So each Lambda copy **counts blocked calls in memory** and writes the total **at most once every 5 seconds** per agent (`_count_blocked`).

**Analogy:** the watchman doesn't write in the register for every rejected person. He counts on his fingers and writes "turned away 37 people" every few minutes.

**Trade-off:** if a Lambda copy shuts down, up to 5 seconds of counts are lost. That's fine for a dashboard number.

### The stats snapshot

The public dashboard asks `/stats` every 20 seconds per open tab. If every request rebuilt the stats from the tables, many visitors would burn our read units.

So:
1. Each Lambda copy keeps the last answer **in memory for 10 s**.
2. Otherwise it reads **one item**, the snapshot, from DynamoDB.
3. If that snapshot is older than **20 s**, it rebuilds it and saves it with a **conditional write**, "only if the saved one is still old". So even with many Lambda copies, **at most one rebuild every 20 seconds** happens.
4. The snapshot is **compressed with zlib** before saving, so a ~10 KB JSON becomes ~2–3 KB (fewer write units).

---

## 9. Keys and secrets

### Gateway keys: `gw_<agent_id>_<secret>`

Example: `gw_leetcode-bot_Xk3fQ...` (the secret is 24 random bytes from Python's `secrets` module).

**Why put the agent ID in the key?** To find the agent with **one GetItem by key**, with no index. Then we **verify** the whole key against the stored hash. The agent ID isn't secret; the random part is.

**Why store only the SHA-256 hash?** If someone steals a copy of the database, they get hashes, not keys. A hash is like a **fingerprint**: easy to make from the finger, impossible to rebuild the finger from it. The key is **shown once** at registration and never stored.

**Why `hmac.compare_digest` and not `==`?** A normal `==` stops at the first different character, so a smart attacker could measure response times to guess characters one by one (a **timing attack**). `compare_digest` always takes the same time.

**Agent IDs can't contain `_`**, so splitting `gw_<id>_<secret>` on the first two underscores is always correct. The secret part can contain underscores.

### The admin key

Generated by our script, saved to `~/.llm-gateway/admin_key` (readable only by you), and only its **SHA-256 hash** goes to SSM. It's never printed and never in the repo.

### Demo agent keys: derived, never stored

The demo runner needs keys for good-bot, loop-bot and the others. Instead of storing six keys, we **derive** them: `HMAC-SHA256(demo_key_secret, "loop-bot")`. The secret is in SSM. The runner and the background-traffic job compute the same key every time, and the gateway checks it like any other key.

**Analogy:** a secret rubber stamp. Anyone with the stamp can make the same mark, nobody without it can, and you don't need to keep copies of the marks.

### Webhook secret (Telegram)

When we register the webhook, we give Telegram a random secret. Telegram sends it back in the header `X-Telegram-Bot-Api-Secret-Token` on every update. Our bot rejects anything without the right header, so random people can't send fake commands to our Function URL. And even then, the bot only obeys **your chat ID**.

### How secrets were created safely

- `scripts/put_secrets.sh`, `put_secret.sh` and `put_chat_id.sh` read input **hidden** (`read -s`), store it as SSM SecureString, and **never print** it.
- `.gitignore` excludes `.terraform/`, `*.tfstate*`, `*.tfvars`, `.env`, `data/`, `reports/raw/`.
- Before publishing, we **scanned the repo** for key patterns (`gsk_`, `AIza`, Telegram token shape, `adm_`, `gw_…`) and found none.

---

## 10. Providers and fallback

`src/providers.py` and `config.PROVIDERS` / `config.MODEL_ALIASES`.

| Model name | Means |
|---|---|
| `mock` | fake model inside the Lambda; no key, no cost; used by tests, demo, simulator |
| `mock-fallback` | `mock-1` then `mock-2`, used to test fallback |
| `fast` | Groq `qwen/qwen3.8-27b`, then Gemini `gemini-flash-lite-latest` |
| `smart` | Groq `openai/gpt-oss-120b`, then Gemini `gemini-flash-latest` |
| `groq/<model>` | one specific provider and model |

Both Groq and Gemini offer an **OpenAI-compatible** endpoint (same request and response shape), so one small function talks to both, using only Python's `urllib`, with no SDK.

**Fallback rules:**
- Try the next provider on **429** (rate limited), **5xx** (server error), **timeout (10 s)**, and also **401/403/404** (bad key or retired model, since the next provider may still work).
- **Don't** fall back on **400/413/422**: the request itself is bad, and another provider won't fix it.
- A provider with **no key configured** is simply skipped.

**Real story:** the model IDs in the original plan were already **outdated**. Groq had retired its Llama models, and Gemini 2.5 returned "no longer available to new users". We found this by calling each provider's `/models` endpoint with the real keys before writing the config. And when the Groq key was broken (pasted 3 times), fallback quietly sent requests to Gemini, which is exactly the point of fallback.

Measured with real providers: 20/20 succeeded, gateway-measured latency **p50 373 ms, p95 971 ms**; Groq served 16, and Gemini served the other 4 through fallback.

**Beginner question:** *"What are p50 and p95?"* Sort all response times. **p50** (median) is the middle one: half were faster. **p95**: 95% were faster than this; it shows the slow tail (cold starts, slow provider moments). Averages hide tails, which is why engineers use percentiles.

---

## 11. The Telegram bot

`src/bot_handler.py`, Lambda `llmgw-bot`, with its own Function URL used as the **webhook**.

**Webhook vs polling:** instead of our code asking Telegram "any new messages?" every few seconds (polling, which needs something always running), Telegram **calls our URL** when a message arrives. Lambda only runs when you actually send a command. That's free.

The bot does four jobs:

| Event | What happens |
|---|---|
| Telegram message (via webhook) | check the secret header, check it's **your chat ID**, then run the command |
| `{"type": "alert"}` from the gateway | send the alert text to you |
| `{"type": "daily_report"}` from the scheduler | send the last 24 hours' numbers for real agents |
| `{"type": "register_webhook"}` (run once by us) | tell Telegram the webhook URL and secret |

**Commands:** `/status`, `/agents`, `/kill <id>`, `/resume <id>`, `/killall`, `/unkillall`, `/incidents`.

**Why does the bot call the gateway Lambda for `/kill`?** So the state-change logic (agent item + window mirror + incident + alert) lives in **one place**. The bot invokes the gateway **directly** (IAM-authorised, not through the public URL) with `{"internal_admin": "/admin/agents/x/kill"}`. The gateway only accepts this when the event has **no `requestContext`**, which every public URL request has, so nobody on the internet can use this path.

**Why do alerts go through an async invoke and not straight from the gateway?** The gateway doesn't need the Telegram token at all (least privilege), and an async invoke returns immediately, so a slow Telegram never slows down an agent's request.

**Real story:** your Wi-Fi **blocks `api.telegram.org`**, so the setup script couldn't reach Telegram from your laptop. We moved those calls **into AWS**: the webhook is registered by invoking the bot Lambda, and until a chat ID is saved, the bot replies with your chat ID ("setup mode").

---

## 12. The dashboard, the demo movie and the stats snapshot

### The public dashboard

`dashboard/index.html`, **one static file**, no build step, hosted on GitHub Pages: https://dheepakkaran.github.io/llm-gateway/

- **Agent breakers:** a switch per agent. Up means ACTIVE (green), middle means SUSPENDED (orange, with a cooldown countdown), down means KILLED (red).
- **Live request feed:** last 20 requests, showing time, agent, result, reason and latency. **Never prompt text.**
- **Incident timeline**, plus **counters** (total requests, blocked calls, est. cost avoided, average time-to-suspend).
- **Polling:** `/stats` every 20 s; `/demo/status` every 2 s **only while a demo is running**; **no polling when the tab is hidden** (`visibilitychange`). That saves Lambda invocations.

**CORS, simply:** a browser only lets JavaScript from `dheepakkaran.github.io` read a response from our Lambda URL if the response says it's allowed (`Access-Control-Allow-Origin`). We add that header **only on the 3 public routes**, and only for your Pages origin (set in `infra/terraform.tfvars`, which is gitignored).

### The demo movie

You press **Run Live Demo** and five stages play, each showing: the problem, what the bot is doing (live ticker), what the guard did, and the measured result.

1. **Normal:** good-bot asks 5 different questions, and all are allowed.
2. **Loop:** loop-bot repeats one question and gets suspended on call 6.
3. **Too fast:** speedy-bot (rpm 10) is throttled at 11 and suspended at 13.
4. **Token bomb:** bomb-bot's 50,000-char prompt gets `413` on call 1.
5. **Retry storm:** retry-bot is suspended after 10 failures.

Then the summary: problems caught **4/4**, false blocks **0**, average catch time **~2.4 s**, **41 requests**. Every number is **measured in that run**, never hardcoded.

**How it works behind the button:**

```mermaid
sequenceDiagram
  participant V as Visitor's browser
  participant G as Gateway Lambda
  participant D as DynamoDB (demo item)
  participant R as Demo runner Lambda
  V->>G: POST /demo/start {"mode":"movie"}
  G->>D: write "running" IF version unchanged
  G-->>R: async invoke (returns immediately)
  G-->>V: 202 started
  loop each stage
    R->>G: HTTPS calls as loop-bot, speedy-bot...
    R->>D: write progress + results (max 1/s)
    V->>G: GET /demo/status every 2 s
  end
```

The **demo runner calls the public gateway over HTTPS exactly like a real agent**, so the demo proves the real system, not a fake.

### Global demo limits (`src/demo_lock.py`)

The button is public, so anyone could spam it. Limits apply **to all visitors together**, enforced with a conditional write:
- only **one run at a time** (others **watch** the current run);
- the **full movie** at most **once every 20 minutes**;
- **single scenarios** at most **6 per hour**;
- caps: 120 requests per movie, 40 per scenario;
- a run older than 330 s counts as dead (the runner's timeout is 300 s).

**Beginner question:** *"Why a conditional write for the lock?"* If two visitors click at the same moment, both read "idle", and both try to write "running". The write includes "only if the version is still N", so exactly one wins. The other gets "already running, watch it". This is the same optimistic-locking idea as the window item.

---

## 13. The simulator: measuring instead of claiming

`simulator/buggy_agent.py` runs every scenario against the **deployed** gateway with its own `sim-*` agents, capped at **300 requests** and about **3 requests/second**, and writes `reports/results.md` and `dashboard/results.json` **only from the measurements**.

| Scenario | Caught | Calls before suspension | Seconds | Calls that reached a model |
|---|---|---|---|---|
| loop | 3/3 | 6 | 2.04 (1.98–2.16) | 5 |
| too_fast (rpm 10) | 3/3 | 13 (throttled from 11) | 4.50 | 10 |
| token_bomb | 3/3 | 1 (413) | 0.25 | 0 |
| retry_storm | 3/3 | 10 | 3.56 | 10 |

- **False positives:** 0 of 20 normal requests (different prompts, one every ~3 s).
- **Fallback:** 30/30 succeeded; 15 were served by the backup after a 429.
- **Real providers:** 20/20, p50 373 ms, p95 971 ms.

### The simulator found real bugs

The first run showed `too_fast` "caught at call 3" and `fallback` "only 67% success". Those numbers looked wrong, and they were:

1. **Resume didn't reset the current-minute counter.** Back-to-back test runs in the same minute started already over the limit. **Fix:** resume = clean slate (also reset `mr`, `mt`).
2. **The fallback test agent sent 30 requests a minute with a limit of 20**, so the gateway correctly rate-limited it. **Fix:** give that test agent rpm 60 (a normal per-agent override) so the test measures fallback only.

After the fixes, all runs were consistent. **Lesson for interviews:** measuring found bugs that unit tests didn't, because the tests checked one run, not many runs in a row.

### Why never invent numbers?

A number in the README that nobody measured is a lie that an interviewer can expose with one question ("how did you measure that?"). Every number here comes from a script you can rerun.

---

## 14. Terraform and deployment

### What Terraform is

**Infrastructure as code.** Instead of clicking in the AWS console, you **describe** resources in `.tf` files, and Terraform makes AWS match the description.

**Analogy:** a recipe. `plan` shows what will be cooked. `apply` cooks it. The **state file** is Terraform's memory of what it already cooked.

| Command | Meaning |
|---|---|
| `terraform init` | download the AWS provider plugin |
| `terraform plan` | show what would be created, changed or deleted; changes nothing |
| `terraform apply plan-file` | do exactly that plan |
| `terraform destroy` | delete everything it created |

We run them through `scripts/tf.sh`, which exports your **short-lived `aws login` credentials** for Terraform. No permanent access keys exist anywhere.

### Our files (`infra/`)

| File | Creates |
|---|---|
| `dynamodb.tf` | 4 tables (24/24 units), TTL, plus a `check` block that **warns during plan** if total capacity goes over 25 |
| `gateway.tf` | shared zip, gateway Lambda, its role, log group, Function URL + 2 permissions, `kill_all` parameter |
| `bot.tf`, `demo.tf` | the other two Lambdas, roles, log groups, bot Function URL |
| `scheduler.tf` | the two schedules and the scheduler role |
| `monitoring.tf` | the CloudWatch dashboard and 2 metric filters |

**Beginner questions:**
- *"What's `archive_file`?"* It zips `src/` during `plan`. When the code changes, the zip's hash changes, and Terraform updates the Lambdas.
- *"Why is the state local and gitignored?"* State can contain sensitive details. For one person it's fine locally. A team would store it in S3 with locking (Part 19).
- *"Why `ignore_changes = [value]` on `kill_all`?"* Terraform creates it as "off". After that, **the gateway and you** change it. Without this line, every `apply` would turn the kill switch off again.
- *"What's `maximum_retry_attempts = 0`?"* AWS retries failed async invocations twice by default. A failed demo retried would burn requests twice, so we turned retries off.

### The $0 check before every apply

Before every `apply` we listed each resource and checked it against the allowed list (Lambda, provisioned DynamoDB, SSM Standard, Scheduler, CloudWatch logs and dashboards within free limits, IAM, Budgets). Nothing paid was ever created.

---

## 15. Tests, CI and the PR workflow

### Tests (`tests/`, 51 tests, ~0.3 s)

- `test_detection.py`: each rule at its exact threshold (5 is OK, 6 fires).
- `test_state_machine.py`: cooldowns, 24 h escalation, demo exemption.
- `test_guard.py`: the pipeline over simulated time: normal agent never blocked, loop on the 6th call, rate limit then suspension, token bomb, retry storm, spike, budget, window under 1 KB.
- `test_keys_providers.py`: key parsing and hashing, mock provider without keys, fallback with a **fake transport** (tests never call real providers).
- `test_scenarios.py`: every demo scenario run against an **in-memory gateway built from the same pure functions**, so we knew the demo would work before deploying.
- `test_demo_lock_stats.py`: demo limits, stats contain no secrets, alert text format.

**A unit test caught a real logic bug:** the first-movie lock. When no movie had ever run, `last_movie_at` was `0`, and the code treated that as "a movie ran at time 0", so the next one was allowed at `0 + 20 min`. The test used small fake times and was correctly locked out. In production that time is 1970, so it would have worked by luck, but the logic was wrong. We fixed it to treat `0` as "never ran" before it reached AWS.

### CI (`.github/workflows/ci.yml`)

On every push and PR: `pytest`, `terraform fmt -check`, `terraform init -backend=false`, `terraform validate`. No AWS credentials in CI.

### The PR workflow

The history is a set of **feature branches, each merged through a pull request**: core detection → providers → gateway → CI → bot → demo → simulator → dashboard → README → GIF → monitoring → cost dashboard → ticker fix → HQ GIF. Before publishing, we checked that **each stage passes tests and Terraform validation on its own**, so every PR from the CI one onward has green checks.

---

## 16. Monitoring and cost

### Three places to look

| Where | Shows | Who |
|---|---|---|
| **Public dashboard** (GitHub Pages) | what the guard does: agents, incidents, demo | visitors, recruiters |
| **CloudWatch dashboard `llmgw`** | how AWS runs it: cost, free-tier meters, errors, latency, capacity | you |
| **Telegram** | alerts, `/status`, daily report | you, on your phone |

This split is how real teams work: a **product dashboard** and an **ops dashboard**.

### The CloudWatch dashboard, top to bottom

1. **Cost:** estimated bill this month, and charges per service. These need "Receive CloudWatch billing alerts" turned on once.
2. **Free-tier meters (30 days):** Lambda requests vs 1M, Lambda GB-s vs 400k, logs vs 5 GB, KMS requests vs 20k.
3. **Health:** invocations, errors and throttles (should be 0), gateway p50/p95 latency.
4. **Guard and database:** blocked-by-rule and state-change counts (from the 2 metric filters), DynamoDB capacity vs 24, throttles.

### Cost alerts

- Budget **`zero-spend`**: email when actual spend > **$0.01**, with **credits excluded**, so even a charge your credits would cover alerts you.
- AWS Free Tier alerts: email at **85%** of any free limit.

### Free-tier facts (checked against AWS's official pages)

- Lambda, DynamoDB, CloudWatch, KMS, Data Transfer, Budgets are labelled **Always Free** in AWS's own table. Function URLs cost nothing extra. Standard SSM parameters have no charge. EventBridge Scheduler gives 14M invocations/month.
- Your account is on the **Free plan**: it lasts 6 months (until Feb 17, 2027). On the Free plan, AWS says you won't be charged unless you convert to a paid plan. At the end, the account is **suspended**, and data is kept for **90 days** for you to upgrade. Sign-up credits expire 6 months after account creation; earned credits last 12 months.
- After upgrading, Always Free offers continue, so this project stays at about $0. The only real risk is someone flooding the public URL with millions of requests (about $1 per extra million), and the budget alert would warn you.

---

## 17. Problems we hit and how we solved them

These are your **"tell me about a challenge"** stories. Each one is real.

| # | Problem | What we did | What it shows |
|---|---|---|---|
| 1 | The laptop had **no admin (sudo)**, so Homebrew couldn't install | installed Python (via uv), AWS CLI, Terraform and gh **into the home folder** with a script | adapting to constraints |
| 2 | **IAM Identity Center** would create an AWS Organization, which **ends the Free plan**, and defaults to a **paid KMS key** | read the warning, cancelled, used an **IAM user + `aws login`** (short-lived credentials, no access keys) | reading the fine print, cost awareness |
| 3 | The system Python had **no SSL certificates** | used the project's Python 3.12 virtual environment | debugging environment issues |
| 4 | The Groq key returned **401**; it was 190 characters instead of ~56 | hidden input means people paste several times; the script now strips whitespace and prints the **length** (never the value) | debugging without exposing secrets |
| 5 | Wi-Fi **blocked Telegram's API** | moved Telegram calls into Lambda; added a bot "setup mode" | working around network limits |
| 6 | Planned **model IDs were retired** | verified with each provider's `/models` endpoint before configuring | never trust old docs |
| 7 | The window item was **1,170 bytes** (2 write units per write) | shortened prompt fingerprints to 8 chars, stored times as small offsets | cost-aware data design |
| 8 | **First demo was locked** (bug in the 20-min rule) | a unit test caught it before deploy | value of tests |
| 9 | Simulator showed odd numbers (caught at call 3, fallback 67%) | found the **resume didn't reset the minute counter** bug and a wrongly configured test agent | value of measurement |
| 10 | The **dashboard showed "connecting…"** in the first screenshot | it was just the first fetch's cold start (~1 s); verified with a direct fetch from the page | check before "fixing" |
| 11 | **myApplications** couldn't create apps anymore | AWS retired it; used Resource Groups + a CloudWatch dashboard | adapting to platform changes |
| 12 | **Billing pages said "Access denied"** for the IAM user | only root can allow IAM access to billing, once | AWS account model |
| 13 | The 1-cent budget wouldn't fire while credits paid | the budget included credits; excluded the Credit charge type | understanding the tools |
| 14 | The demo GIF was **blurry** | re-recorded with headless Chrome at 2× scale, Lanczos downscale, 256 colours per frame, no dithering; fixed a ticker glitch first | caring about presentation |

---

## 18. Honest limitations

Saying these yourself makes you look **more** senior, not less.

1. **Loop detection catches exact repeats only.** An agent that rephrases ("Solve two-sum", "Please solve two sum") escapes Rule 1. Next step: **embedding-based near-duplicate detection** (compare meaning, not exact text).
2. **Fixed minute buckets** allow up to 2× rpm across a minute boundary. A token bucket or sliding window is fairer.
3. **Caches mean small delays.** A manual kill can take up to ~10 s to reach every Lambda copy (the window mirror shortens this for the next request), and the global kill switch up to 15 s.
4. **Blocked-call counts can lose up to 5 s** of data when a Lambda copy stops.
5. **Token use is reserved, not reconciled.** The window keeps the upper-bound estimate; exact numbers are only in the usage table.
6. **Capacity ceiling:** about 8 requests/second sustained for the whole system (the usage table's 8 write units) before it fails closed.
7. **The public URL has no WAF.** Someone could flood it; protection is app-level checks plus the budget alert.
8. **One region, one admin key, local Terraform state.**
9. **The demo uses a mock model.** It proves the guard logic and the real AWS path, not the behaviour of real agents. The MAST-Data evaluation (next milestone) tests against **real failure traces**.

---

## 19. What would change in production

If a company used this for 1,000 agents and millions of calls a day:

| Today ($0 version) | Production version | Why |
|---|---|---|
| Function URL + app checks | **API Gateway + AWS WAF** (or CloudFront + WAF) | per-IP throttling, bot protection, request size limits before Lambda |
| Provisioned 24/24 DynamoDB | **on-demand or autoscaling**, or **Redis/ElastiCache** for hot counters | handle bursts; Redis `INCR` + sliding windows are very fast |
| Usage write inside the request | **SQS + DLQ** for async usage logging | lower latency; nothing lost if the database is slow |
| SSM SecureString | **Secrets Manager with rotation** | automatic key rotation |
| IAM user + `aws login` | **IAM Identity Center (SSO)** with an Organization | central access for a team |
| Local Terraform state | **S3 backend with locking** | team-safe deploys |
| Exact-hash loops | **embeddings** + similarity threshold | catch rephrased loops |
| Telegram alerts | **PagerDuty / Slack / email** via SNS | on-call routing |
| Basic dashboard | **OpenTelemetry tracing**, alarms with actions | find slow paths across services |
| One region | **multi-region**, Lambda aliases + **canary deploys** | resilience, safe releases |
| Per-agent budget | **per-team budgets and chargeback** reports | finance can bill each team |
| No content checks | **PII / secret redaction** before prompts leave the company | data-leak protection |
| Simulator | **load tests** (e.g. thousands of agents) | know the real limits |

---

## 20. Interview questions and answers

Answer in your own words, using these as a base. Short, clear answers beat long ones.

### About the project

**1. Tell me about this project.**
"Companies run many AI agents, and a buggy one can loop and fire thousands of LLM calls with no owner and no off switch. I built a serverless gateway on AWS: every agent calls models through it with its own key. It enforces limits, detects loops, retry storms and token bombs, suspends the agent like a circuit breaker, and alerts the owner on Telegram. I measured it: a loop is caught on the 6th call in about 2 seconds, with zero false blocks. It runs on the AWS free tier."

**2. Why not just use LiteLLM or Portkey?**
"They're great for routing, budgets and rate limits. My focus was narrower: behaviour-based runaway detection plus an automatic circuit breaker, measured with a simulator, built serverless at $0. I also wanted to understand how such a gateway works inside: concurrency, cost and failure modes."

**3. What was the hardest part?**
"Keeping correctness under concurrency inside a tiny write budget. Two requests from the same agent can arrive at once on different Lambda copies. I used one window item per agent with optimistic locking, a version check on every write, retries on conflict, and kept the item under 1 KB so each write costs one unit. I also had to stop two copies from both suspending an agent, which would wrongly escalate it to KILLED; that's handled with a conditional status update."

**4. What would you do differently?**
"Use a sliding window or token bucket instead of fixed minute buckets, add embedding-based near-duplicate detection for rephrased loops, and move usage logging to SQS so the request path does only one write."

### Design

**5. Why serverless?**
"The traffic is bursty and mostly idle. Lambda costs nothing when idle and scales per request. A server would cost money 24/7 and need patching."

**6. Why DynamoDB and not a SQL database?**
"Every access is by key: agent by ID, window by agent, recent usage by agent and time. That's exactly what a key-value store is good at, with single-digit-millisecond reads, and it has an always-free tier. RDS would cost money and need connection management from Lambda."

**7. Why provisioned capacity?**
"It's in the always-free tier at 25/25, and it **can't overspend**: extra load is throttled instead of billed. On-demand would charge per request."

**8. Why is the order of checks important?**
"Cheapest first. The kill switch and key checks use cached data; a suspended agent is rejected before any database write; the expensive model call is last. A runaway agent costs almost nothing once it's suspended."

**9. Explain "fail closed".**
"If the gateway can't count a request (DynamoDB throttled), it returns 429 and doesn't call the model. For a cost guard, missing one count is worse than briefly refusing a request."

**10. How do you keep writes to 2 per request?**
"All rule state lives in one window item, updated once. Tokens are reserved up front (prompt estimate plus max_tokens) so there's no second window write after the model answers. The second write is the usage record. Only a provider failure adds a third."

**11. What is optimistic locking? Why here?**
"Read the item with its version, compute the new value, write only if the version is unchanged; if someone else wrote first, re-read and retry. Conflicts are rare, so this is cheaper than taking locks."

**12. Why not DynamoDB atomic counters?**
"`ADD` is perfect for a single number, but the rules need lists of timestamps that are pruned and evaluated together. That's read-modify-write, so I need a version check."

**13. What's a circuit breaker?**
"A pattern that stops calls to something failing or misbehaving, waits for a cooldown, then tries again. Like a house MCB. Here, the 'circuit' is the agent's access to the LLM."

**14. Why lazy reactivation?**
"No timer, no extra Lambda or schedule. The next request after the cooldown flips the agent back to ACTIVE with a conditional write. Simpler and free."

**15. How does the dashboard avoid expensive reads?**
"A snapshot item rebuilt at most every 20 s, enforced by a conditional write, compressed with zlib, plus a 10 s in-memory cache. A registry item lists agent IDs, so there are no scans: just BatchGet and small Queries."

### AWS

**16. What's a cold start and how did it show up?**
"The first request to a new Lambda copy loads the runtime and code. It showed up in p95 latency and in a dashboard screenshot that said 'connecting' for a second."

**17. How do your Lambdas get secrets?**
"From SSM Parameter Store SecureStrings, encrypted with the AWS-managed KMS key, read at runtime and cached 5 minutes. Each role can read only its own parameters."

**18. Why not Secrets Manager?**
"It costs $0.40 per secret per month and adds rotation, which I didn't need here. In production I'd use it for rotation."

**19. Why one IAM role per Lambda?**
"Least privilege. If the bot is compromised, it can't write tables or read provider keys."

**20. Is a public Function URL with auth NONE safe?**
"AWS doesn't authenticate, but the app does: every chat call needs a valid key, admin routes need the admin key, and only read-only dashboard routes are public, with CORS limited to my site. In production I'd add WAF in front."

**21. How do you deploy?**
"Terraform. `plan` shows exactly what changes; I checked every new resource against a $0 allowed list before `apply`. Credentials are short-lived from `aws login`."

### Security

**22. How are gateway keys stored?**
"Only their SHA-256 hash. The key is shown once at registration. The agent ID is part of the key so I can find the agent without an index, then compare hashes with a constant-time function."

**23. What's a timing attack?**
"Measuring how long a comparison takes to learn how many characters matched. `hmac.compare_digest` takes the same time regardless."

**24. How do demo agents get keys without storing them?**
"HMAC of the agent ID with a secret in SSM. The runner derives the same key each time; nothing to store or leak."

**25. How is the Telegram bot protected?**
"A secret header Telegram sends on every webhook call, and it only obeys my chat ID. Admin actions go through a direct IAM-authorised Lambda invoke, which a public HTTP request can't reach."

**26. Do you log prompts?**
"No. Logs and usage records contain agent, outcome, reason, tokens, latency and cost, never prompt text. The dashboard is public, so this matters."

### Testing and measurement

**27. How did you test it?**
"51 pytest tests on pure functions, with simulated time, so each rule is tested at its exact threshold. Providers use an injected fake transport, so tests never hit real APIs. Every demo scenario also runs against an in-memory gateway built from the same functions."

**28. How did you measure detection speed?**
"A simulator plays each buggy agent against the deployed gateway, three runs each, about 3 requests per second, and records calls and seconds until suspension, plus false positives on a normal agent."

**29. Did measuring find anything?**
"Yes: resume didn't reset the per-minute counter, so back-to-back runs started already over the limit. The unit tests missed it because they tested one run at a time."

**30. What's a false positive here? How many?**
"Blocking a healthy agent. 0 of 20 normal requests in the simulator, and 0 in every demo run."

**31. (For M3b) What are precision and recall?**
"Precision: of the agents I suspended, how many were really stuck. Recall: of the really stuck agents, how many I caught. F1 combines both. The MAST-Data evaluation will measure these on real multi-agent failure traces."

### Cost

**32. How do you know it's $0?**
"Every service is in AWS's Always Free category within limits I calculated: Lambda 1M requests, DynamoDB 25/25 provisioned, CloudWatch 3 dashboards and 10 custom metrics, KMS 20k requests. I verified against AWS's official pages, and a budget emails me at one cent, with credits excluded."

**33. What's the worst case?**
"Someone flooding the public URL. Beyond the free million, that's about $1 per extra million Lambda requests; DynamoDB can't overspend because it's provisioned. The budget alert and the kill switch cover it."

### Behavioural

**34. Tell me about a time you had to adapt.**
"No admin rights on the laptop, a Wi-Fi network that blocked Telegram, and AWS's newer Free plan rules. I installed tools into my home folder, moved Telegram calls into Lambda, and avoided Identity Center because it would have ended the Free plan and created a paid KMS key."

**35. How did you make sure the project was honest?**
"Every number in the README and dashboard comes from a measurement script that can be rerun. Limitations are listed in the README, like exact-match loop detection."

---

## 21. Glossary

| Word | Simple meaning |
|---|---|
| **Agent** | a program that calls an LLM repeatedly to do a task |
| **LLM gateway** | a service in the middle that every LLM call must pass through |
| **Token** | a piece of text a model reads or writes (~4 characters of English) |
| **Lambda** | code that runs only when called; pay per call |
| **Cold start** | the slower first call when a new Lambda copy starts |
| **Function URL** | a free HTTPS address for a Lambda |
| **DynamoDB** | AWS's key-value NoSQL database |
| **Partition key / sort key** | the item's address; sort key orders items under the same partition key |
| **RCU / WCU** | read / write capacity units (speed you reserve) |
| **Provisioned / on-demand** | reserved fixed speed vs pay per request |
| **Throttling** | AWS refusing requests above your reserved speed |
| **TTL** | an expiry timestamp; DynamoDB deletes the item after it |
| **GSI** | a second index of a table, with its own capacity |
| **Scan / Query / GetItem** | read everything / read by key range / read one item |
| **Strongly consistent read** | always returns the latest written value |
| **Conditional write** | "write only if this condition is still true" |
| **Optimistic locking** | version check on write; retry on conflict |
| **Race condition** | a bug when two things happen at the same time and one is lost |
| **Atomic counter** | `ADD` that increments safely without reading first |
| **SSM Parameter Store** | AWS's config and secrets store; Standard tier is free |
| **SecureString** | an encrypted SSM parameter |
| **KMS** | AWS's encryption key service |
| **IAM role / policy** | an identity for a service / what it's allowed to do |
| **Least privilege** | give only the permissions that are needed |
| **Terraform / IaC** | describe infrastructure as code; tools create it |
| **State file** | Terraform's record of what it created |
| **EventBridge Scheduler** | runs things on a timetable |
| **CloudWatch** | AWS logs, metrics, dashboards and alarms |
| **Metric filter** | turns matching log lines into a number |
| **CORS** | browser rule about which websites may read an API's response |
| **Webhook** | the other service calls your URL when something happens |
| **Hash (SHA-256)** | a fingerprint of data; can't be reversed |
| **HMAC** | a hash made with a secret key; proves who made it |
| **Circuit breaker** | stop calls when something misbehaves; retry after cooldown |
| **Rate limiting** | maximum requests per time window |
| **Fail closed / fail open** | when unsure: block / allow |
| **Async invoke** | start a Lambda and don't wait for it to finish |
| **p50 / p95** | the median / the value 95% of requests are faster than |
| **False positive** | blocking something that was actually fine |
| **Precision / recall** | how many flagged were truly bad / how many bad were flagged |
| **CI** | automatic tests on every push |
| **GitHub Pages** | free static website hosting from a GitHub repo |

---

## 22. Hands-on exercises

Doing these will make you able to answer any follow-up question. Work in the project folder.

1. **Run the tests:** `.venv/bin/python -m pytest -q`. Then change `repeat_threshold` in `src/config.py` from 5 to 3 and see which tests fail, and why. Change it back.
2. **Read one rule end to end:** open `src/detection.py`, `check_repeat`, then find where it's called in `src/guard.py` (`evaluate`). Explain to yourself why the 6th call fires.
3. **Make the guard catch a loop yourself:** register a demo agent and send the same prompt 7 times:
   ```bash
   .venv/bin/python scripts/gw.py register test-bot dheepak "my test" --demo
   for i in 1 2 3 4 5 6 7; do .venv/bin/python scripts/gw.py chat test-bot "same question" | head -1; done
   ```
   You'll see `200` five times, then `429`, then `403`.
4. **Change a limit for one agent:** give `test-bot` rpm 5, then send 8 different prompts quickly and watch it get throttled at call 6:
   ```bash
   GW=$(cd infra && terraform output -raw gateway_url)
   curl -s -X POST "${GW}admin/agents/test-bot/limits" -H "authorization: Bearer $(cat ~/.llm-gateway/admin_key)" -d '{"limits":{"rpm":5}}'
   for i in 1 2 3 4 5 6 7 8; do .venv/bin/python scripts/gw.py chat test-bot "question $i" | head -1; done
   ```
5. **Watch the logs live while you do it:** `aws logs tail /aws/lambda/llmgw-gateway --follow`. Find the `BLOCKED` and `STATE_CHANGE` lines.
6. **Use the kill switch from Telegram:** `/killall`, try a call (expect `503`), then `/unkillall`.
7. **Read a Terraform plan without applying:** change `memory_size` of the bot to 192 in `infra/bot.tf`, run `./scripts/tf.sh plan`, read the diff, then undo the change.
8. **Explain the window item:** run the guard test `test_encode_roundtrip_and_size_under_1kb` and print `guard.encode(w)` to see the real JSON.
9. **Draw the request flow on paper** from memory (Part 3). If you can draw it, you can explain it.

---

## 23. Command cheat sheet

```bash
# log in (credentials last ~12 h)
aws login --profile llm-gateway

# tests
.venv/bin/python -m pytest -q

# deploy (always plan first, read it, then apply that plan)
./scripts/tf.sh plan -out=build/plan
./scripts/tf.sh apply build/plan

# agents and kill switches (admin key read from ~/.llm-gateway/admin_key)
.venv/bin/python scripts/gw.py agents
.venv/bin/python scripts/gw.py register <id> <owner> "<purpose>" [--team T] [--demo]
.venv/bin/python scripts/gw.py kill <id>
.venv/bin/python scripts/gw.py resume <id>
.venv/bin/python scripts/gw.py kill-all
.venv/bin/python scripts/gw.py unkill-all

# simulator (writes reports/results.md and dashboard/results.json)
.venv/bin/python simulator/buggy_agent.py --repeat 3

# re-record the demo GIF (movie allowed once every 20 min)
.venv/bin/python scripts/record_demo.py

# live logs
aws logs tail /aws/lambda/llmgw-gateway --follow

# replace one secret (hidden input)
bash scripts/put_secret.sh groq_api_key

# remove everything Terraform created
./scripts/tf.sh destroy
```
