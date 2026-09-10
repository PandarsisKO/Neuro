#!/bin/bash
# Double-click this file to run the Haiku-vs-Sonnet-5 comparison.
# It uses a throwaway temporary database, changes no settings and no contract,
# and touches nothing in your real project data.
#
# Expected cost ~$2.34, hard ceiling $3.51. Runtime 15-40 minutes.
# You can close the window at any time to stop it.

cd "$(dirname "$0")" || exit 1

LOG="evals/haiku-comparison-$(date +%Y%m%d-%H%M%S).log"
mkdir -p evals

echo "======================================================="
echo " Neuro Search - Haiku vs Sonnet 5 comparison"
echo "======================================================="
echo
echo "This will spend real API credit: about \$2.34, at most \$3.51."
echo "It writes to a temporary database and changes nothing in your app."
echo
read -r -p "Type  yes  and press Return to start (anything else cancels): " ok
if [ "$ok" != "yes" ]; then
  echo "Cancelled. Nothing was spent."
  echo
  read -r -p "Press Return to close this window."
  exit 0
fi

echo
echo "Running. Progress appears below and is also saved to:"
echo "  $LOG"
echo

.venv/bin/neurosearch eval --migration-compare --live \
    --candidate-model claude-haiku-4-5 2>&1 | tee "$LOG"

status=${PIPESTATUS[0]}
echo
echo "======================================================="
if [ "$status" -eq 0 ]; then
  echo " Finished. Full results saved to:"
  echo "   $LOG"
  echo " Tell Claude the run finished and it will read that file."
else
  echo " Stopped with an error (exit $status)."
  echo " The log above and $LOG say why. Nothing was charged if it"
  echo " failed during preflight."
fi
echo "======================================================="
echo
read -r -p "Press Return to close this window."
