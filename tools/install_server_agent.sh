#!/bin/bash
# Install the Neuro Search server as a user LaunchAgent (auto-start at login, restart if it exits). Idempotent.
# Stops a copy started by hand (start.command / ./start) first — once, deliberately — because two servers cannot
# share port 8000, and a background job must never kill a hand-started server on its own.
set -euo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SUPPORT="$HOME/Library/Application Support/NeuroSearch/server"
PLIST="$HOME/Library/LaunchAgents/com.neurosearch.server.plist"
LABEL="com.neurosearch.server"
PORT="${NEUROSEARCH_PORT:-8000}"

mkdir -p "$SUPPORT" "$HOME/Library/LaunchAgents"
PYTHON="$REPO/.venv/bin/python"
[ -x "$PYTHON" ] || { echo "python not found at $PYTHON — run ./start once first" >&2; exit 1; }
sed -e "s|__REPO__|$REPO|g" -e "s|__SUPPORT__|$SUPPORT|g" -e "s|__PYTHON__|$PYTHON|g" \
    "$REPO/tools/com.neurosearch.server.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
pids="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$pids" ]; then
  echo "Stopping the hand-started server on port ${PORT} (pids: $pids) so the agent can own it…"
  kill $pids 2>/dev/null || true
  for i in $(seq 1 15); do sleep 1; [ -z "$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true)" ] && break; done
  left="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null || true)"
  [ -n "$left" ] && { echo "port ${PORT} still held by $left — not installing" >&2; exit 1; }
fi
launchctl bootstrap "gui/$(id -u)" "$PLIST"
for i in $(seq 1 30); do
  sleep 1
  curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/" && { echo "installed and serving: $LABEL (http://127.0.0.1:${PORT})"; break; }
done
curl -fsS -o /dev/null "http://127.0.0.1:${PORT}/" || { echo "agent loaded but Neuro is not answering yet — see $REPO/data/server.log" >&2; exit 1; }
echo "  plist: $PLIST"
echo "  logs : $REPO/data/server.log"
echo "  stop : launchctl bootout gui/$(id -u)/$LABEL"
