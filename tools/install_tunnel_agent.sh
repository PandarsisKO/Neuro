#!/bin/bash
# Install the Secure MCP Tunnel as a user LaunchAgent. Idempotent.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/NeuroSearch/tunnel"
PLIST="$HOME/Library/LaunchAgents/com.neurosearch.tunnel.plist"
LABEL="com.neurosearch.tunnel"

mkdir -p "$SUPPORT" "$HOME/Library/LaunchAgents"
PYTHON="${NEUROSEARCH_TUNNEL_PYTHON:-$REPO/.venv/bin/python}"
[ -x "$PYTHON" ] || { echo "python not found at $PYTHON" >&2; exit 1; }
sed -e "s|__REPO__|$REPO|g" -e "s|__SUPPORT__|$SUPPORT|g" -e "s|__PYTHON__|$PYTHON|g" \
    "$REPO/tools/com.neurosearch.tunnel.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
  && echo "installed and loaded: $LABEL" || { echo "agent did not load" >&2; exit 1; }
echo "  plist: $PLIST"
echo "  logs : $SUPPORT/tunnel.{out,err}.log"
