#!/bin/bash
# Keep this Mac hunting while plugged in — even display off / lid closed (best-effort).
#
# IMPORTANT (Apple Silicon MacBook):
#   Closing the lid usually forces sleep unless you are in "clamshell" mode
#   (power + external display OR HDMI/USB-C dummy plug). Pure software cannot
#   100% override lid-close sleep on all macOS versions.
#
# Recommended for 24/7 hunt:
#   1) Keep power cable plugged in always
#   2) Run this script once (needs sudo for pmset)
#   3) Prefer lid OPEN (or slightly ajar) OR use a cheap HDMI dummy plug
#   4) start_mac_primary.sh already starts caffeinate -dims
#
# Usage:
#   chmod +x mac_always_on.sh
#   ./mac_always_on.sh
set -euo pipefail

echo "=== Mac always-on for seed-hunter-unique ==="
echo "On battery vs charger settings will differ; we optimize for AC power (-c)."

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Requesting sudo for pmset (one-time power policy)..."
  exec sudo "$0" "$@"
fi

# While charging: never idle-sleep, never disk-sleep, short display sleep OK
pmset -c sleep 0
pmset -c disksleep 0
pmset -c displaysleep 10
pmset -c hibernatemode 0
pmset -c standby 0
pmset -c autopoweroff 0
# Soften lid/network sleep on AC (not a guarantee on all models)
pmset -c tcpkeepalive 1 2>/dev/null || true
pmset -c powernap 0 2>/dev/null || true

# Also set "all" mildly so lid-open idle does not sleep
pmset -a sleep 0
pmset -a disksleep 0
pmset -a hibernatemode 0

echo ""
echo "Current pmset:"
pmset -g custom
echo ""
echo "=== Done ==="
echo "Still required:"
echo "  • Power cable plugged in"
echo "  • Hunt:  cd ~/seed-hunter-unique && ./start_mac_primary.sh"
echo "  • Lid: keep OPEN, or use HDMI/USB-C dummy plug for closed-lid clamshell"
echo "  • Optional App Store: Amphetamine → 'Allow system sleep when display is closed' OFF"
echo ""
echo "Verify awake:"
echo "  pmset -g assertions | head -40"
echo "  pgrep -x caffeinate && ./status_shards.sh"
