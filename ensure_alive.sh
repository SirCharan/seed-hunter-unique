#!/bin/bash
# Cron every 5 min: restart Mac unique-words hunt if workers died.
#   crontab -e
#   */5 * * * * EXPECT_SHARD_PROCS=8 /Users/charandeepkapoor/seed-hunter-unique/ensure_alive.sh >>/Users/charandeepkapoor/seed-hunter-unique/ensure_alive.log 2>&1
set -uo pipefail
cd "$(dirname "$0")"
EXPECT="${EXPECT_SHARD_PROCS:-8}"
n=$(pgrep -f 'seed_shard.py --shard' 2>/dev/null | wc -l | tr -d ' ')
if [[ "$n" -lt "$EXPECT" ]]; then
  echo "$(date -Iseconds) ensure_alive: have=$n expect=$EXPECT — restarting"
  if ! pgrep -x caffeinate >/dev/null 2>&1; then
    nohup caffeinate -dims sleep infinity >/dev/null 2>&1 &
  fi
  FORCE_RESTART=0 ./start_mac_primary.sh
else
  echo "$(date -Iseconds) ensure_alive: ok procs=$n"
fi
