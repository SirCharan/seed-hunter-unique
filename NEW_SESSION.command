#!/bin/bash
# Double-click after reopening Terminal — resumes from last saved index/phrase.
cd "$(dirname "$0")"
bash ./resume_mac.sh
echo ""
read -r -p "Press Enter to close this window (hunt keeps running in background)..."
