#!/usr/bin/env bash
# Run every frozen question in both arms, sequentially, alternating which arm goes first.
# Usage: demo/run_all.sh [--skip-existing]
# Failures are kept and reported by demo/compare.py; they do not stop the batch.
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
SKIP="${1:-}"

i=0
for QID in $("$PY" -c "import json; print(' '.join(q['id'] for q in json.load(open('$ROOT/demo/questions.json'))['questions']))"); do
  if [ $((i % 2)) -eq 0 ]; then ORDER="native evidence"; else ORDER="evidence native"; fi
  i=$((i + 1))
  for ARM in $ORDER; do
    if [ "$SKIP" = "--skip-existing" ] && [ -e "$ROOT/runs/$QID/$ARM.events.jsonl" ]; then
      echo "skip $QID $ARM (already run)"
      continue
    fi
    "$ROOT/demo/run_arm.sh" "$ARM" "$QID" || echo "!! $QID $ARM exited non-zero (kept for the report)"
  done
done
"$PY" "$ROOT/demo/compare.py"
