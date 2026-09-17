#!/bin/bash
# Double-click `start.command` or run ./start — starts Neuro Search from this folder, restarting itself when the code is updated.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/neurosearch ]; then
  echo "First-time setup: creating .venv and installing…"
  python3 -m venv .venv && .venv/bin/pip install -q -e . || exit 1
fi
.venv/bin/pip install -q -e . 2>/dev/null   # picks up new dependencies after an update (fast when nothing changed)
# 0.63.31 — keep the server's own output on disk. Kyle's app hung and there was NOTHING to read: no log file
# anywhere, so a crash at startup, a traceback in a worker and a silent deadlock all look identical from outside.
# The same rule this codebase applies to every ladder rung ("a failure indistinguishable from its answer is worse
# than not having the rung") applies to the app's own front door. Bounded at ~5 MB with one previous generation
# kept, so it can never grow into the problem it exists to diagnose.
mkdir -p data
LOG=data/server.log
# 0.63.32, revised 0.63.92 — say what is wrong AND recover from it automatically. A crash leaves uvicorn's parent
# holding the port, so the next launch used to fail immediately with "[Errno 48] Address already in use" and
# scroll away, or (worse) hang forever answering nothing while Kyle waited for a page that would never load. This
# used to require Kyle to notice, close the window, and separately double-click restart.command. He should not
# have to run a recovery script by hand every time this codebase or an update to it crashes — so start.command now
# does exactly what restart.command has always done (ask the stale process to stop, then force it if it won't),
# and only asks a human to intervene when that genuinely fails, meaning something OTHER than a stale copy of this
# app owns the port.
PORT="${NEUROSEARCH_PORT:-8000}"
free_stuck_port() {
  local pids
  pids="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
  [ -z "$pids" ] && return 0
  printf '\n===== %s  port %s already held — attempting automatic recovery =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PORT" >> "$LOG"
  echo "Port ${PORT} is already in use — likely a crashed copy of this server still holding it. Freeing it automatically…"
  ps -o pid=,comm= -p $pids 2>/dev/null | tee -a "$LOG"
  # Ask politely first: a server asked to stop closes the database cleanly, which matters when a write-ahead log
  # is waiting to check in.
  kill $pids 2>/dev/null
  local i still
  for i in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    still="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
    [ -z "$still" ] && break
  done
  still="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$still" ]; then
    echo "It did not stop on request. Forcing: $still"
    printf 'SIGKILL required for %s\n' "$still" >> "$LOG"
    kill -9 $still 2>/dev/null
    sleep 1
  fi
  if [ -n "$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)" ]; then
    return 1
  fi
  echo "Port ${PORT} is free — starting Neuro Search."
  printf 'port %s freed automatically — continuing to start\n' "$PORT" >> "$LOG"
  return 0
}
if [ -n "$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)" ]; then
  if ! free_stuck_port; then
    printf '\n===== %s  port %s still held after automatic recovery — not starting =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$PORT" >> "$LOG"
    echo
    echo "Neuro Search is NOT starting: something is still holding port ${PORT} even after trying to free it."
    echo
    echo "  That is NOT a crashed copy of this server — those get cleared automatically now. Something else on"
    echo "  this Mac owns the port. Open Activity Monitor, search for 'neurosearch' or 'python', select it and"
    echo "  press the X to quit it, then try again."
    echo
    ps -o pid=,comm= -p $(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null) 2>/dev/null
    echo
    echo "Press any key to close this window."
    read -r -n 1 -s
    exit 1
  fi
fi
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG" 2>/dev/null || echo 0)" -gt 5000000 ]; then mv -f "$LOG" "$LOG.1"; fi
printf '\n===== %s  starting Neuro Search =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"
.venv/bin/neurosearch start "$@" 2>&1 | tee -a "$LOG"
