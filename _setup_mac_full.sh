#!/bin/bash
# Full Mac end-to-end for UNIQUE-WORDS hunt: clone seed-hunter-unique → ~/seed-hunter-mac
# Does NOT use or push to SirCharan/seed-hunter (all-words sister repo).
set -euo pipefail

MAC="${SEED_HUNTER_MAC_DIR:-/Users/charandeepkapoor/seed-hunter-mac}"
REPO_URL="https://github.com/SirCharan/seed-hunter-unique.git"
OUT="${TMPDIR:-/tmp}/seed_hunter_unique_mac_setup_out.txt"

exec > >(tee "$OUT") 2>&1

echo "=== $(date) Mac seed-hunter-unique full setup ==="

if ! command -v gh >/dev/null 2>&1; then
  echo "ERROR: gh not found"
  exit 1
fi
gh auth status || { echo "ERROR: gh not authenticated"; exit 1; }

echo "--- prepare $MAC ---"
if [[ -d "$MAC/.git" ]]; then
  cd "$MAC"
  url=$(git remote get-url origin 2>/dev/null || true)
  if [[ "$url" != *seed-hunter-unique* ]]; then
    echo "WARN: $MAC origin is not seed-hunter-unique ($url) — recloning"
    cd /
    rm -rf "$MAC"
    git clone "$REPO_URL" "$MAC"
    cd "$MAC"
  else
    git fetch origin
    git checkout main
    git pull --ff-only origin main || git pull origin main
  fi
else
  rm -rf "$MAC"
  git clone "$REPO_URL" "$MAC"
  cd "$MAC"
fi

# Refuse if somehow pointing at all-words repo
url=$(git remote get-url origin)
if [[ "$url" == *"/seed-hunter.git"* || "$url" == *"/seed-hunter" ]]; then
  if [[ "$url" != *seed-hunter-unique* ]]; then
    echo "FATAL: origin is SirCharan/seed-hunter (all-words). Abort."
    exit 1
  fi
fi

chmod +x start_linux_primary.sh start_mac_primary.sh status_shards.sh kill_shards.sh \
  load_api_keys.sh git_push_capital.py 2>/dev/null || true

echo "--- venv ---"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -U pip
.venv/bin/pip install -r requirements.txt

[[ -f capital_seeds.jsonl ]] || : > capital_seeds.jsonl
[[ -f found_wallets_capital.jsonl ]] || : > found_wallets_capital.jsonl
[[ -f capital_hits.md ]] || printf '# Capital hits\n\nFunded wallets found by seed-hunter-unique.\n\n_(none yet)_\n' > capital_hits.md

echo "--- restart hunters ---"
pkill -f "seed_shard.py --shard" 2>/dev/null || true
sleep 2

FORCE_RESTART=1 WORKERS_PER_SHARD=2 UNIQUE_WORDS=1 BACKEND=rpc \
  ./start_mac_primary.sh

sleep 3
echo ""
echo "=== VERIFY ==="
echo "cwd=$MAC"
echo "origin=$(git remote get-url origin)"
echo "caffeinate PIDs: $(pgrep -x caffeinate | tr '\n' ' ')"
echo "seed_shard PIDs:"
pgrep -lf 'seed_shard.py --shard' || true
count=$(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')
echo "count=$count  EXPECT_SHARD_PROCS=8"
./status_shards.sh || true
echo "DONE (unique-words Mac hunt)"
