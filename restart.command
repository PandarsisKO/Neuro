#!/bin/bash
# Double-click `restart.command` when the app will not load, or looks stuck, or the window said
# "Address already in use".
#
# 0.63.32 — why this file exists. A crash inside the server leaves uvicorn's PARENT process alive and still
# holding port 8000, so the port is bound and nothing answers: requests time out instead of being refused, the app
# looks "stuck loading" for ever, and the next `start.command` dies immediately on [Errno 48]. That happened to
# Kyle twice on 2026-09-11 and the second launch failed one minute after he was told to relaunch. `start.command`
# deliberately does NOT do this on its own — taking over a port nobody asked about is the kind of thing that
# silently kills the wrong program — so freeing it is its own deliberate, clearly named action.
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
