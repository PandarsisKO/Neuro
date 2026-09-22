#!/bin/bash
# Install the Mac-native git publisher LaunchAgent (user agent, no root, no network listener).
# Idempotent: re-running replaces the plist and reloads the agent.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/NeuroSearch/git-publisher"
PLIST="$HOME/Library/LaunchAgents/com.neurosearch.git-publisher.plist"
PYTHON="${NEUROSEARCH_PUBLISHER_PYTHON:-$REPO/.venv/bin/python}"
LABEL="com.neurosearch.git-publisher"

[ -x "$PYTHON" ] || { echo "python not found at $PYTHON" >&2; exit 1; }

mkdir -p "$SUPPORT/requests" "$SUPPORT/receipts" "$SUPPORT/done"
mkdir -p "$REPO/.git-publisher/requests" "$REPO/.git-publisher/receipts" "$REPO/.git-publisher/done"
mkdir -p "$HOME/Library/LaunchAgents"

sed -e "s|__REPO__|$REPO|g" -e "s|__PYTHON__|$PYTHON|g" -e "s|__SUPPORT__|$SUPPORT|g" \
    "$REPO/tools/com.neurosearch.git-publisher.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
  && echo "installed and loaded: $LABEL" \
  || { echo "agent did not load" >&2; exit 1; }
echo "  plist   : $PLIST"
echo "  queues  : $REPO/.git-publisher/requests  and  $SUPPORT/requests"
echo "  receipts: alongside each queue, plus $SUPPORT/agent.log"
