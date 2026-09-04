#!/bin/bash
# New Terminal session: resume unique-words hunt from saved progress (index + phrase).
# Double-click NEW_SESSION.command or run:  bash ~/seed-hunter-unique/resume_mac.sh
set -euo pipefail
cd "$(dirname "$0")"

echo "=== seed-hunter-unique resume ==="
echo "dir=$(pwd)"
echo "origin=$(git remote get-url origin 2>/dev/null || echo none)"
echo ""

# Never delete shard_*.txt / shard_*.phrase.txt — those are the resume bookmarks
echo "=== Saved progress (will resume here) ==="
for f in shard_*_w*.txt; do
  [[ -f "$f" ]] || continue
  idx=$(cat "$f" 2>/dev/null || echo "?")
  pf="${f%.txt}.phrase.txt"
  if [[ -f "$pf" ]]; then
    phrase=$(sed -n '2p' "$pf" 2>/dev/null || true)
    echo "$f  idx=$idx"
    echo "         phrase: $phrase"
  else
    echo "$f  idx=$idx"
  fi
done
echo ""

if [[ ! -x .venv/bin/python ]]; then
  echo "Creating venv..."
  python3 -m venv .venv
  .venv/bin/pip install -U pip
  .venv/bin/pip install -r requirements.txt
fi

chmod +x *.sh 2>/dev/null || true

# Keep Mac awake (plugged in)
if ! pgrep -x caffeinate >/dev/null 2>&1; then
  nohup caffeinate -dims sleep infinity >/dev/null 2>&1 &
  echo "caffeinate started"
else
  echo "caffeinate already running"
fi

# Start any missing workers; do NOT wipe progress. FORCE_RESTART only if you pass it.
FORCE_RESTART="${FORCE_RESTART:-0}" ./start_mac_primary.sh

sleep 4
echo ""
./status_shards.sh
echo ""
echo "Logs prove resume:  grep RESUME shard_low_fwd_w0.log | tail -3"
grep RESUME shard_*_w*.log 2>/dev/null | tail -16 || true
echo ""
echo "OK — leave this Mac plugged in. Lid open (or HDMI dummy). Check anytime: ./status_shards.sh"
