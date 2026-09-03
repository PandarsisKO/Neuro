#!/bin/bash
# Double-click `start.command` or run ./start — starts Neuro Search from this folder, restarting itself when the code is updated.
cd "$(dirname "$0")"
if [ ! -x .venv/bin/neurosearch ]; then
  echo "First-time setup: creating .venv and installing…"
  python3 -m venv .venv && .venv/bin/pip install -q -e . || exit 1
fi
.venv/bin/pip install -q -e . 2>/dev/null   # picks up new dependencies after an update (fast when nothing changed)
exec .venv/bin/neurosearch start "$@"
