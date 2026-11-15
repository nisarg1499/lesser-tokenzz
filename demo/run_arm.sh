#!/usr/bin/env bash
# Run one frozen question in one arm, in a fresh Codex session.
# Usage: demo/run_arm.sh <native|evidence> <question_id>
# Saves raw timestamped events, the final answer and run metadata under runs/<question_id>/.
set -euo pipefail

ARM="${1:?arm: native or evidence}"
QID="${2:?question id from demo/questions.json}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/.venv/bin/python"
MODEL="${MODEL:-gpt-6.1-sol}"
EFFORT="${EFFORT:-medium}"
OUT="$ROOT/runs/$QID"
# Solver runs in an empty directory outside the repo, so it does not load this
# project's AGENTS.md or read the repo and grader files.
WORK="$HOME/.cache/lesser-tokenzz-demo/solver-workdir"
mkdir -p "$OUT" "$WORK"

case "$ARM" in
  native)   LABEL="Native web baseline"; SEARCH=(--search) ;;
  evidence) LABEL="Our evidence MCP";    SEARCH=()
            # The key is forwarded by name to the MCP server; it is never printed.
            [ -n "${TELEM_API_KEY:-}" ] || { echo "TELEM_API_KEY is not exported in this shell" >&2; exit 2; } ;;
  *) echo "unknown arm: $ARM" >&2; exit 2 ;;
esac

PROMPT="$("$PY" - "$ROOT/demo/questions.json" "$QID" <<'EOF'
import json, sys
doc = json.load(open(sys.argv[1]))
q = next(q for q in doc["questions"] if q["id"] == sys.argv[2])
print(q["text"] + "\n\n" + doc["prompt_suffix"])
EOF
)"

echo "=== $LABEL | $QID | $MODEL $EFFORT ==="
echo "$PROMPT"
echo

# Never overwrite an earlier run: every attempt is kept, including failures.
if [ -e "$OUT/$ARM.events.jsonl" ]; then
  PREV="$OUT/previous-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$PREV" && mv "$OUT/$ARM".* "$PREV"/
  echo "Earlier $ARM run moved to $PREV"
fi

START_ISO="$(date -u +%FT%TZ)"
START="$("$PY" -c 'import time; print(time.time())')"
set +e
# Each event line is stamped on arrival so tool durations can be read from the trace.
codex ${SEARCH[@]+"${SEARCH[@]}"} exec -p "$ARM" -m "$MODEL" \
  -c model_reasoning_effort="\"$EFFORT\"" \
  -s read-only -C "$WORK" --skip-git-repo-check --ephemeral --json \
  -o "$OUT/$ARM.answer.txt" "$PROMPT" 2> "$OUT/$ARM.stderr.log" \
  | "$PY" -u -c '
import json, sys, time
for line in sys.stdin:
    line = line.strip()
    if line:
        print(json.dumps({"received_at": time.time(), "raw": line}), flush=True)
        # One short progress line per finished step, so the pane is not silent.
        try:
            item = json.loads(line).get("item") or {}
            if json.loads(line).get("type") == "item.completed" and item.get("type") != "agent_message":
                name = item.get("tool") or item.get("query") or item.get("command") or ""
                print("  [" + item.get("type", "?") + "] " + str(name)[:90], file=sys.stderr, flush=True)
        except ValueError:
            pass
' > "$OUT/$ARM.events.jsonl"
CODE="${PIPESTATUS[0]}"
set -e
END="$("$PY" -c 'import time; print(time.time())')"

"$PY" - "$OUT/$ARM.meta.json" <<EOF
import hashlib, json, subprocess, sys
root = "$ROOT"
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({
    "arm": "$ARM", "label": "$LABEL", "question_id": "$QID",
    "model_requested": "$MODEL", "reasoning_effort": "$EFFORT",
    "started_at_utc": "$START_ISO", "wall_seconds": round($END - $START, 2),
    "codex_exit_code": $CODE,
    "codex_version": subprocess.run(["codex", "--version"], capture_output=True, text=True).stdout.strip(),
    "repo_commit": subprocess.run(["git", "-C", root, "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip(),
    "database_sha256": sha(root + "/data/demo.sqlite"),
    "contracts_sha256": sha(root + "/data/contracts.json"),
    "questions_sha256": sha(root + "/demo/questions.json"),
    "native_search_enabled": "$ARM" == "native",
}, open(sys.argv[1], "w"), indent=2)
EOF

echo
echo "--- answer ($LABEL) ---"
cat "$OUT/$ARM.answer.txt" 2>/dev/null || echo "(no answer file; see $OUT/$ARM.stderr.log)"
echo
echo "exit=$CODE wall=$("$PY" -c "print(round($END - $START, 2))")s  events: $OUT/$ARM.events.jsonl"
exit "$CODE"
