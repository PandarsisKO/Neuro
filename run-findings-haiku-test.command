#!/bin/bash
# Double-click this file to test Haiku against Sonnet 5 on FINDINGS only.
#
# It runs the same 9 frozen sources twice — once on Sonnet 5, once on Haiku —
# and reports, for each: how many findings it produced, how many of the planted
# facts it actually found (evidence recall), and whether every quote it produced
# really exists in the source (quote validity).
#
# Temporary database. No settings changed, no contract changed, your real
# project data untouched.
#
# Expected cost about $0.45. Runtime roughly 8-15 minutes.

cd "$(dirname "$0")" || exit 1

LOG="evals/findings-haiku-$(date +%Y%m%d-%H%M%S).log"
mkdir -p evals

echo "==============================================================="
echo " Findings: Haiku 4.5  vs  Sonnet 5"
echo "==============================================================="
echo
echo "Same 9 sources, run twice. Measures how many findings each model"
echo "produces, how much of the planted evidence it finds, and whether"
echo "its quotes are real."
echo
echo "This will spend real API credit: about \$0.45."
echo "Temporary database. Nothing in your app changes."
echo
read -r -p "Type  yes  and press Return to start (anything else cancels): " ok
if [ "$ok" != "yes" ]; then
  echo "Cancelled. Nothing was spent."
  echo
  read -r -p "Press Return to close this window."
  exit 0
fi

echo
echo "Running. Progress below, also saved to:"
echo "  $LOG"
echo

.venv/bin/neurosearch eval --findings-compare --live \
    --baseline-model claude-sonnet-5 \
    --candidate-model claude-haiku-4-5 2>&1 | tee "$LOG"

status=${PIPESTATUS[0]}
echo
echo "==============================================================="
if [ "$status" -eq 0 ]; then
  echo " Finished. Results saved to:"
  echo "   $LOG"
  echo " Tell Claude it finished and it will read that file."
else
  echo " Stopped with an error (exit $status). The log above says why."
  echo " If it stopped in preflight, nothing was charged."
fi
echo "==============================================================="
echo
read -r -p "Press Return to close this window."
