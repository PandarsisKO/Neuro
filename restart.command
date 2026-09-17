#!/bin/bash
# Double-click `restart.command` any time you want to force a fresh start of the app — for example, if it
# will not load, looks stuck, or the window said "Address already in use".
#
# 0.63.32, revised 0.63.92 — why this file still exists. A crash inside the server leaves uvicorn's PARENT
# process alive and still holding port 8000, so the port is bound and nothing answers: requests time out instead
# of being refused, and the app looks "stuck loading" for ever. That happened to Kyle twice on 2026-09-11.
# `start.command` now detects and frees exactly this situation on its own at launch (0.63.92) — a crash no longer
# requires this script to recover from. This file is kept as an explicit, always-available "just restart it" — it
# also stops a server that is currently running and healthy, which start.command's own automatic recovery
# deliberately does not do (it only acts when a launch finds the port already stuck, never on a running server).
cd "$(dirname "$0")"
mkdir -p data
LOG=data/server.log
printf '\n===== %s  restart.command: freeing port 8000 =====\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG"

PORT="${NEUROSEARCH_PORT:-8000}"
PIDS="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
if [ -z "$PIDS" ]; then
  echo "Nothing is holding port ${PORT} — starting normally."
  printf 'nothing was holding port %s\n' "$PORT" >> "$LOG"
else
  # Only ever the listeners on OUR port, and only ever this user's own processes. Ask politely first: a server
  # asked to stop closes the database cleanly, which matters when a 27 MB write-ahead log is waiting to check in.
  echo "Port ${PORT} is held by: $PIDS — asking it to stop…"
  ps -o pid=,comm= -p $PIDS 2>/dev/null | tee -a "$LOG"
  kill $PIDS 2>/dev/null
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    sleep 1
    STILL="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
    [ -z "$STILL" ] && break
  done
  STILL="$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)"
  if [ -n "$STILL" ]; then
    echo "It did not stop on request. Forcing: $STILL"
    printf 'SIGKILL required for %s\n' "$STILL" >> "$LOG"
    kill -9 $STILL 2>/dev/null
    sleep 1
  fi
  if [ -n "$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)" ]; then
    echo
    echo "Port ${PORT} is STILL held and I could not free it. Something outside this app owns it."
    echo "Open Activity Monitor, search for 'neurosearch' or 'python', select it and press the X to quit it."
    printf 'could not free port %s\n' "$PORT" >> "$LOG"
    echo; echo "Press any key to close this window."; read -r -n 1 -s; exit 1
  fi
  echo "Port ${PORT} is free."
fi

exec ./start.command "$@"   # the same launch Kyle always gets — `start` adds dev extras his Mac does not want
