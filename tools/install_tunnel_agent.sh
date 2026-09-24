#!/bin/bash
# Install the Secure MCP Tunnel as a user LaunchAgent. Idempotent.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/NeuroSearch/tunnel"
# Usage: install_tunnel_agent.sh [profile]   (default local-http = Kyle's tunnel; "gio" = Gio's tunnel)
PROFILE="${1:-local-http}"
if [ "$PROFILE" = "local-http" ]; then LABEL="com.neurosearch.tunnel"; LOGNAME="tunnel"
else LABEL="com.neurosearch.tunnel.$PROFILE"; LOGNAME="tunnel-$PROFILE"; fi
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

mkdir -p "$SUPPORT" "$HOME/Library/LaunchAgents"
PYTHON="${NEUROSEARCH_TUNNEL_PYTHON:-$REPO/.venv/bin/python}"
[ -x "$PYTHON" ] || { echo "python not found at $PYTHON" >&2; exit 1; }
# The profile must carry X-Neuro-Tunnel or Neuro cannot tell this tunnel from the other one and falls back to the
# FIRST configured resource -- for a second tunnel that is someone else's. `tunnel-client init` knows nothing about
# Neuro, so a re-init drops the header; setting it here (idempotent) means installing the agent restores it.
"$PYTHON" "$REPO/tools/tunnel_agent.py" --ensure-profile "$PROFILE" || {
  echo "could not set the X-Neuro-Tunnel header on profile '$PROFILE'" >&2; exit 1; }

sed -e "s|__REPO__|$REPO|g" -e "s|__SUPPORT__|$SUPPORT|g" -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__LABEL__|$LABEL|g" -e "s|__LOGNAME__|$LOGNAME|g" -e "s|__PROFILE__|$PROFILE|g" \
    "$REPO/tools/com.neurosearch.tunnel.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 \
  && echo "installed and loaded: $LABEL" || { echo "agent did not load" >&2; exit 1; }
echo "  plist: $PLIST"
echo "  logs : $SUPPORT/$LOGNAME.{out,err}.log"
