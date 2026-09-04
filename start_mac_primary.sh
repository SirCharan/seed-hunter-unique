#!/bin/bash
# Mac primary hunter — UNIQUE-WORDS only (seed-hunter-unique).
# Full 4-shard hunt with Mac-safe worker count.
#
# Keeps Mac awake (while plugged in / lid policy allowing) via caffeinate,
# then launches the same RPC-first pipeline as Linux primary with lighter
# concurrency for Mac RAM safety.
#
# Defaults:
#   WORKERS_PER_SHARD=2   # 4 shards × 2 = 8 processes
#   EXPECT_SHARD_PROCS=8  # Mac: 2 workers × 4 shards
#   UNIQUE_WORDS=1       # unique-words only (this repo)
#   BACKEND=rpc
#   FORCE_RESTART optional
#
# Usage:
#   ./start_mac_primary.sh
#   FORCE_RESTART=1 ./start_mac_primary.sh
#   WORKERS_PER_SHARD=3 ./start_mac_primary.sh
set -euo pipefail
cd "$(dirname "$0")"

export WORKERS_PER_SHARD="${WORKERS_PER_SHARD:-2}"
export UNIQUE_WORDS="${UNIQUE_WORDS:-1}"
export BACKEND="${BACKEND:-rpc}"
export CHECK_MODE="${CHECK_MODE:-both}"
export CHAINS="${CHAINS:-ethereum}"
export BATCH_SIZE="${BATCH_SIZE:-20}"
export MAX_CONCURRENT="${MAX_CONCURRENT:-6}"
export RPC_RPS="${RPC_RPS:-15}"
export SAVE_ACTIVITY="${SAVE_ACTIVITY:-1}"
export ENRICH_ETHERSCAN="${ENRICH_ETHERSCAN:-1}"

# Prevent idle sleep / disk sleep / system sleep while hunting (caffeinate -dims).
# Background forever-sleep so workers are not children of caffeinate (easier kill).
if ! pgrep -x caffeinate >/dev/null 2>&1; then
  nohup caffeinate -dims sleep infinity >/dev/null 2>&1 &
  echo "caffeinate started pid $!"
else
  echo "caffeinate already running: $(pgrep -x caffeinate | tr '\n' ' ')"
fi

EXPECT=$((WORKERS_PER_SHARD * 4))
echo "=== Mac primary (seed-hunter-unique / unique-words) ==="
echo "WORKERS_PER_SHARD=$WORKERS_PER_SHARD  UNIQUE_WORDS=$UNIQUE_WORDS  BACKEND=$BACKEND"
echo "EXPECT_SHARD_PROCS=$EXPECT  (default Mac: 2 workers × 4 shards = 8)"
echo "dir=$(pwd)  repo=seed-hunter-unique"
exec ./start_linux_primary.sh
