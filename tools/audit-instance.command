#!/bin/bash
# Audit instance — a second Neuro Search that cannot spend money or touch your research.
#
# Double-click this file (it lives in the design worktree, so the code it serves is the pinned baseline commit,
# not whatever main is doing). It:
#   1. copies the newest VERIFIED backup from the main checkout's data/backups/ into ./data-audit/ (gitignored),
#      only if ./data-audit/ is empty — re-running keeps the copy you already inspected;
#   2. starts the app on port 8788 with NEUROSEARCH_FAKE_AI=1, both budgets at $0, no API keys, and the login
#      token `audit`;
#   3. writes its own log to ./data-audit/server.log.
#
# Nothing here reads or writes the live data directory. `AUDIT.md` §3 is the rule this file implements; keep it
# to one screen — it is a procedure, not a framework.
set -e
cd "$(dirname "$0")/.."                                   # worktree root (this file lives in tools/)
HERE="$(pwd)"
MAIN="$(cd "$(git rev-parse --git-common-dir)/.." && pwd)"   # the main checkout, wherever this worktree sits
PORT=8788

if [ -n "$(lsof -ti "tcp:${PORT}" -sTCP:LISTEN 2>/dev/null)" ]; then
  echo "Port ${PORT} is already in use — an audit instance is probably still running. Close its window first."
  echo; echo "Press any key to close."; read -r -n 1 -s; exit 1
fi

mkdir -p data-audit
if [ ! -f data-audit/neurosearch.db ]; then
  SRC="$(ls -t "$MAIN"/data/backups/neurosearch-*.db 2>/dev/null | head -1)"
  if [ -z "$SRC" ]; then echo "No verified backup found in $MAIN/data/backups — start the live app once first."; read -r -n 1 -s; exit 1; fi
  echo "Copying $(basename "$SRC") ($(du -h "$SRC" | cut -f1)) into data-audit/ …"
  cp "$SRC" data-audit/neurosearch.db
  echo "$(basename "$SRC")  copied $(date '+%Y-%m-%d %H:%M')  baseline $(git rev-parse --short HEAD 2>/dev/null || echo unknown)" > data-audit/PROVENANCE.txt
else
  echo "Using existing data-audit/ ($(cat data-audit/PROVENANCE.txt 2>/dev/null))"
fi

PY="$MAIN/.venv/bin/python"
[ -x "$PY" ] || { echo "No .venv in $MAIN — run start.command there once."; read -r -n 1 -s; exit 1; }

# Explicit exports win over .env (python-dotenv never overrides a variable that is already set — including empty).
export NEUROSEARCH_DATA_DIR="$HERE/data-audit"
export NEUROSEARCH_FAKE_AI=1
export NEUROSEARCH_DAILY_BUDGET_USD=0
export NEUROSEARCH_MONTHLY_BUDGET_USD=0
export NEUROSEARCH_APP_TOKEN=audit
export ANTHROPIC_API_KEY= OPENAI_API_KEY= NEUROSEARCH_COOKIES_FILE=
export NEUROSEARCH_LOCAL_API_FALLBACK=0

echo
echo "Audit instance  →  http://localhost:${PORT}   (login token: audit)"
echo "Baseline commit: $(git rev-parse --short HEAD 2>/dev/null || echo unknown)   data: $HERE/data-audit   fake AI, \$0 budgets"
echo "Close this window to stop it."
echo
# `python -m` puts THIS directory first on sys.path, so the pinned worktree code runs — not the editable install
# that the main checkout's venv points at. No --reload: the baseline must not move underneath the audit.
exec "$PY" -m neurosearch.cli serve --port "$PORT" 2>&1 | tee -a data-audit/server.log
