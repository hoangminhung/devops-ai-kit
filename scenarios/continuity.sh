#!/usr/bin/env bash
# Scenario 13: carry a three-part release across sessions with /compact (method A) or /handoff (method B),
# and measure tokens, dead-end retries and whether each later part does the right next step.
#
#   scenarios/continuity.sh [--runs 3] [--methods "compact handoff"] --tsv FILE
#
# Normally started by `benchmark.sh --continuity`, which points CLAUDE_CONFIG_DIR at a separate config dir
# with this checkout installed. It uses the INSTALLED kit (the /handoff skill must be there).
# Env: CLAUDE_BIN, MODEL (as in run-headless.sh), SCENARIO_RUNS_DIR (as in prepare.sh).
# COSTS TOKENS: every call is a Claude Code session turn (method A: 5 calls per run, method B: 7).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNS_PER_METHOD=3 METHODS="compact handoff" TSV=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --runs) RUNS_PER_METHOD="$2"; shift 2 ;;
    --methods) METHODS="$2"; shift 2 ;;
    --tsv) TSV="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$TSV" ]] || { echo "--tsv is required" >&2; exit 2; }
[[ "$RUNS_PER_METHOD" =~ ^[1-9][0-9]*$ ]] || { echo "--runs must be a positive number" >&2; exit 2; }
for method in $METHODS; do
  [[ "$method" == compact || "$method" == handoff ]] || { echo "unknown method: $method" >&2; exit 2; }
done
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
[[ -x "$CLAUDE_BIN" ]] || { echo "claude not found: set CLAUDE_BIN" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is needed" >&2; exit 1; }

SCENARIO="$HERE/13-continuity.md"
block() { awk -v name="$1" '$0 == "```" name {inside=1; next} inside && $0 == "```" {exit} inside {print}' "$SCENARIO"; }
PART1="$(block prompt)" NEXT="$(block prompt-next)" CONFIRM="$(block confirm)"
# Headless runs cannot answer a confirm dialog: allow what the task and /handoff need, nothing more.
ALLOWED=(--allowedTools "Bash(tools/bump-tag.sh:*)" "Bash(git:*)" "Bash(sha256sum:*)" "Bash(cat:*)" "Bash(grep:*)"
         "Bash(python3:*)" Read Edit Write)
MODEL_FLAGS=()
[[ -n "${MODEL:-}" ]] && MODEL_FLAGS=(--model "$MODEL")

# ask <log> <session id or ""> <prompt>: one headless call in $WORK; prints the session id it ran in
# (the given one if the log has none, so a failed call does not lose the session)
ask() {
  local log="$1" session="$2" prompt="$3" resume=()
  [[ -n "$session" ]] && resume=(--resume "$session")
  (cd "$WORK" && printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p --output-format stream-json --verbose \
    "${resume[@]}" "${ALLOWED[@]}" "${MODEL_FLAGS[@]}" > "$log" 2> "${log%.jsonl}.stderr") || true
  local id
  id="$(jq -rR 'fromjson? // empty | select(.type=="system" and .subtype=="init") | .session_id' "$log" | head -1)"
  echo "${id:-$session}"
}
tag_of() { awk -v svc="  $1:" '/^  [a-z]+:$/ { inside = ($0 == svc) } inside && /^    tag:/ { gsub(/[" ]|tag:/, ""); print }' \
  "$WORK/release/tags.yaml"; }
inplace_runs() { # inplace_runs <log>...: bump-tag.sh calls with --inplace
  cat "$@" | jq -rR 'fromjson? // empty | select(.type=="assistant") | .message.content[]?
    | select(.type=="tool_use" and .name=="Bash") | .input.command' | grep -c 'bump-tag\.sh.*--inplace' || true
}
compacted() { jq -rR 'fromjson? // empty | select(.type=="system" and .subtype=="compact_boundary") | 1' "$1" | grep -c . || true; }

[[ -s "$TSV" ]] || printf 'method\trun\tplanted\tretries\tnext_ok\ttokens\tcost\tvalid\tlogs\n' > "$TSV"
for method in $METHODS; do
  for run in $(seq 1 "$RUNS_PER_METHOD"); do
    WORK="$(SCENARIO_RUNS_DIR="${SCENARIO_RUNS_DIR:-$HERE/.runs}" "$HERE/prepare.sh" 13 2>/dev/null | tail -1)"
    LOGS="$(dirname "$WORK")"
    valid=yes next_ok=0
    session="$(ask "$LOGS/1-part.jsonl" "" "$PART1")"
    for part in 2 3; do
      if [[ "$method" == compact ]]; then
        session="$(ask "$LOGS/$part-compact.jsonl" "$session" "/compact")"
        [[ "$(compacted "$LOGS/$part-compact.jsonl")" -ge 1 ]] || valid="no (no compact_boundary before part $part)"
        session="$(ask "$LOGS/$part-part.jsonl" "$session" "$NEXT")"
      else
        session="$(ask "$LOGS/$part-handoff.jsonl" "$session" "/handoff")"
        ask "$LOGS/$part-confirm.jsonl" "$session" "$CONFIRM" >/dev/null
        [[ -f "$WORK/PROGRESS.md" ]] || valid="no (no PROGRESS.md before part $part)"
        session="$(ask "$LOGS/$part-part.jsonl" "" "$NEXT")"  # a new session: only files carry the state
      fi
      if [[ $part == 2 ]]; then
        [[ "$(tag_of web)" == 2.0.1 && "$(tag_of worker)" == 0.9.6 ]] && next_ok=$((next_ok + 1))
      else
        [[ "$(tag_of worker)" == 0.9.7 ]] && next_ok=$((next_ok + 1))
      fi
    done
    planted="$( [[ "$(inplace_runs "$LOGS/1-part.jsonl")" -ge 1 ]] && echo yes || echo no )"
    retries="$(inplace_runs "$LOGS"/2-part.jsonl "$LOGS"/3-part.jsonl)"
    totals="$(cat "$LOGS"/*.jsonl | jq -sR '[split("\n")[] | fromjson? // empty | select(.type=="result")]
      | {tokens: (map(.usage // {} | (.input_tokens // 0) + (.cache_creation_input_tokens // 0)
                    + (.cache_read_input_tokens // 0) + (.output_tokens // 0)) | add // 0),
         cost: (map(.total_cost_usd // 0) | add // 0)} | "\(.tokens)\t\(.cost)"' -r)"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$method" "$run" "$planted" "$retries" "$next_ok" "$totals" "$valid" "$LOGS" >> "$TSV"
    echo "continuity $method run $run: planted=$planted retries=$retries next_ok=$next_ok/2 valid=$valid" >&2
  done
done
