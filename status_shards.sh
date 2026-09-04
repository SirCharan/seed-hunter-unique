#!/bin/bash
set -uo pipefail
cd "$(dirname "$0")"

# Mac default: 4 shards × WORKERS_PER_SHARD(2) = 8. Architecture is always 4 shards.
WPS="${WORKERS_PER_SHARD:-2}"
EXPECT=$((WPS * 4))

echo "TIME: $(date '+%Y-%m-%d %H:%M %Z')"
echo "DISK: $(df -h . | awk 'NR==2 {print $4}') free"
echo "SHARD_PROCS: $(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')"
echo "EXPECT_SHARD_PROCS: $EXPECT  (${WPS} workers × 4 shards)"
echo "SHARDS: always 4 (low_fwd low_rev high_fwd high_rev) — fixed by design"
echo "WORKERS_PER_SHARD: $WPS  (do NOT change after first run — reshuffles coverage)"
echo "MAC_SAFE_MAX: WORKERS_PER_SHARD=3→12 procs, or 4→16 (Air: prefer 2–3). Never >6."
echo "OLD_STREAM: $(pgrep -f 'seed_stream.py --workers' 2>/dev/null | wc -l | tr -d ' ')"
echo "RANDOM: $(pgrep -f 'seed_hunter_random.py' 2>/dev/null | wc -l | tr -d ' ')"
echo "CAFFEINATE: $(pgrep -x caffeinate 2>/dev/null | tr '\n' ' ' || echo none)"

if [[ -f found_wallets_capital.jsonl ]]; then
  echo "CAPITAL_HITS: $(wc -l < found_wallets_capital.jsonl | tr -d ' ')"
else
  echo "CAPITAL_HITS: 0"
fi
if [[ -f found_wallets_activity.jsonl ]]; then
  echo "ACTIVITY_HITS: $(wc -l < found_wallets_activity.jsonl | tr -d ' ')"
else
  echo "ACTIVITY_HITS: 0"
fi
if [[ -f activity_seeds.jsonl ]]; then
  echo "ACTIVITY_SEEDS: $(wc -l < activity_seeds.jsonl | tr -d ' ')"
else
  echo "ACTIVITY_SEEDS: 0"
fi
if [[ -f capital_seeds.jsonl ]]; then
  echo "CAPITAL_SEEDS: $(wc -l < capital_seeds.jsonl | tr -d ' ')"
else
  echo "CAPITAL_SEEDS: 0"
fi

PY="${PYTHON:-.venv/bin/python}"
if [[ ! -x "$PY" ]]; then
  PY=python3
fi

"$PY" - <<'PY'
import json
import os
import re
import subprocess
from collections import defaultdict

from seed_hunter_async import entropy_index_to_phrase

SHARDS = ("low_fwd", "low_rev", "high_fwd", "high_rev")

walk_rates = defaultdict(float)
rpc_rates = defaultdict(float)
# fallback from old log format rate=
legacy_rates = defaultdict(float)

for name in sorted(os.listdir(".")):
    if not (name.startswith("shard_") and name.endswith(".log")):
        continue
    try:
        o = subprocess.check_output(["tail", "-c", "1200", name], stderr=subprocess.DEVNULL)
    except Exception:
        continue
    text = o.decode("utf-8", errors="ignore")
    m_walk = re.findall(r"walk_rate=([0-9.]+)", text)
    m_rpc = re.findall(r"rpc_rate=([0-9.]+)", text)
    m_legacy = re.findall(r"(?<![_\w])rate=([0-9.]+)", text)
    key = name.split("_w")[0]
    if m_walk:
        walk_rates[key] += float(m_walk[-1])
    if m_rpc:
        rpc_rates[key] += float(m_rpc[-1])
    if m_legacy and not m_walk:
        legacy_rates[key] += float(m_legacy[-1])

agg_walk = sum(walk_rates.values()) or sum(legacy_rates.values())
agg_rpc = sum(rpc_rates.values())
print(f"AGG_WALK_RATE: {agg_walk:.2f} indices/s  (includes unique-word skips)")
print(f"AGG_RPC_RATE:  {agg_rpc:.2f} phrases/s   (actually checked on-chain)")
if legacy_rates and not walk_rates:
    print(f"AGG_RATE (legacy log): {sum(legacy_rates.values()):.2f}/s")
for k in sorted(set(walk_rates) | set(rpc_rates) | set(legacy_rates)):
    w = walk_rates.get(k) or legacy_rates.get(k) or 0.0
    r = rpc_rates.get(k, 0.0)
    print(f"  {k}: walk={w:.2f}/s  rpc={r:.2f}/s")

print("")
print("=== LIVE WORKERS (index + phrase currently at progress tip) ===")

statuses = []
for shard in SHARDS:
    for i in range(64):
        st = f"shard_{shard}_w{i}.status.json"
        pt = f"shard_{shard}_w{i}.txt"
        if os.path.exists(st):
            try:
                statuses.append(json.load(open(st, encoding="utf-8")))
                continue
            except Exception:
                pass
        if os.path.exists(pt):
            try:
                idx = int(open(pt, encoding="utf-8").read().strip())
            except Exception:
                continue
            try:
                phrase = entropy_index_to_phrase(idx, 12)
            except Exception as e:
                phrase = f"(decode error: {e})"
            statuses.append(
                {
                    "shard": shard,
                    "worker_id": i,
                    "idx": idx,
                    "phrase": phrase,
                    "rpc_checked": None,
                    "walked": None,
                    "skipped_unique": None,
                    "rpc_rate": None,
                    "walk_rate": None,
                }
            )

# Sort for stable display
statuses.sort(key=lambda d: (d.get("shard") or "", d.get("worker_id") or 0))

total_rpc = 0
total_walk = 0
total_skip = 0
for d in statuses:
    shard = d.get("shard")
    wid = d.get("worker_id")
    idx = d.get("idx")
    phrase = d.get("phrase") or "?"
    rpc_n = d.get("rpc_checked")
    walk_n = d.get("walked")
    skip_n = d.get("skipped_unique")
    if isinstance(rpc_n, int):
        total_rpc += rpc_n
    if isinstance(walk_n, int):
        total_walk += walk_n
    if isinstance(skip_n, int):
        total_skip += skip_n
    extra = ""
    if rpc_n is not None:
        extra = (
            f"  walked={walk_n:,} rpc_checked={rpc_n:,} skipped={skip_n:,} "
            f"walk_rate={d.get('walk_rate')} rpc_rate={d.get('rpc_rate')}"
        )
    print(f"[{shard} w{wid}] idx={idx:,}{extra}")
    print(f"         phrase: {phrase}")

if total_walk or total_rpc:
    print("")
    print(
        f"SESSION_TOTALS (since last worker start): "
        f"walked={total_walk:,}  rpc_checked={total_rpc:,}  skipped_unique={total_skip:,}"
    )

print("")
print("=== PROGRESS FILES ===")
for shard in SHARDS:
    vals = []
    for i in range(64):
        p = f"shard_{shard}_w{i}.txt"
        if os.path.exists(p):
            try:
                vals.append(int(open(p, encoding="utf-8").read().strip()))
            except Exception:
                pass
    if vals:
        print(f"PROGRESS {shard}: n={len(vals)} min={min(vals):,} max={max(vals):,}")
PY
