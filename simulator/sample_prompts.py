"""Sample 200 Dolly-15k instructions (fixed seed) into simulator/prompts.jsonl
and an identical copy in src/ (bundled into the Lambda zip for the demo runner).

Dataset: databricks/databricks-dolly-15k (CC BY-SA 3.0), downloaded to data/
(gitignored). Only instructions that need no extra context are used, so each
one is a self-contained question an agent might ask.

Usage: python -I simulator/sample_prompts.py data/dolly/databricks-dolly-15k.jsonl
"""
import json
import pathlib
import random
import sys

SEED, N = 42, 200
NO_CONTEXT = {"open_qa", "general_qa", "brainstorming", "creative_writing", "classification"}

root = pathlib.Path(__file__).resolve().parent.parent
rows = []
with open(sys.argv[1]) as f:
    for line in f:
        r = json.loads(line)
        ins = " ".join(r["instruction"].split())
        if r["category"] in NO_CONTEXT and not r["context"].strip() and 15 <= len(ins) <= 300:
            rows.append({"category": r["category"], "instruction": ins})
rows = sorted({r["instruction"]: r for r in rows}.values(), key=lambda r: r["instruction"])
sample = random.Random(SEED).sample(rows, N)
out = "".join(json.dumps({"id": i, **r}, ensure_ascii=False) + "\n" for i, r in enumerate(sample))
for p in (root / "simulator" / "prompts.jsonl", root / "src" / "prompts.jsonl"):
    p.write_text(out)
print(f"{len(rows)} eligible -> sampled {N} (seed {SEED})")
