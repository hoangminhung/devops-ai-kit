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
# Since 2.1.277 a resumed -p call reports the session's running totals; older versions start at 0, and the
# "last result per session" totals below would be too low (agent-sdk/cost-tracking).
CLAUDE_VERSION="$("$CLAUDE_BIN" --version 2>/dev/null </dev/null | awk '{print $1}')"
[[ "$(printf '%s\n' 2.1.277 "${CLAUDE_VERSION:-0}" | sort -V | head -1)" == 2.1.277 ]] \
  || { echo "Claude Code ${CLAUDE_VERSION:-?} is too old: 2.1.277 or later is needed for the cost totals" >&2; exit 1; }

SCENARIO="$HERE/13-continuity.md"
block() { awk -v name="$1" '$0 == "```" name {inside=1; next} inside && $0 == "```" {exit} inside {print}' "$SCENARIO"; }
PART1="$(block prompt)" NEXT="$(block prompt-next)" CONFIRM="$(block confirm)"
# Headless runs cannot answer a confirm dialog: allow what the task and /handoff need, nothing more.
ALLOWED=(--allowedTools "Bash(tools/bump-tag.sh:*)" "Bash(./tools/bump-tag.sh:*)" "Bash(bash tools/bump-tag.sh:*)"
         "Bash(git:*)" "Bash(sha256sum:*)" "Bash(date:*)" "Bash(wc:*)" "Bash(grep:*)" Read Glob Grep Edit Write)
MODEL_FLAGS=()
[[ -n "${MODEL:-}" ]] && MODEL_FLAGS=(--model "$MODEL")

# ask <label> <session id or ""> <prompt>: one headless call in $WORK, logged to $LOGS/cNN-<label>.jsonl
# (numbered, so the logs sort in call order). Sets SESSION to the session it ran in, or keeps the given one
# if the log has none. Not called in $(...): the call counter must survive.
CALL=0 SESSION=""
ask() {
  local label="$1" session="$2" prompt="$3" resume=() log id
  CALL=$((CALL + 1))
  log="$LOGS/$(printf 'c%02d' "$CALL")-$label.jsonl"
  [[ -n "$session" ]] && resume=(--resume "$session")
  (cd "$WORK" && printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p --output-format stream-json --verbose \
    ${resume[@]+"${resume[@]}"} "${ALLOWED[@]}" ${MODEL_FLAGS[@]+"${MODEL_FLAGS[@]}"} \
    > "$log" 2> "${log%.jsonl}.stderr") || true
  id="$(jq -rR 'fromjson? // empty | select(.type=="system" and .subtype=="init") | .session_id' "$log" | head -1)"
  SESSION="${id:-$session}"
}
log_of() { ls "$LOGS"/c[0-9][0-9]-"$1".jsonl 2>/dev/null | tail -1; }  # newest log with this label
# call_ok <log>: the call ended with a result that is not an error
call_ok() { jq -seR '[split("\n")[] | fromjson? // empty | select(.type=="result")] | last
  | . != null and (.is_error // false) == false and ((.subtype // "success") == "success")' "$1" >/dev/null; }
compacted() { jq -rR 'fromjson? // empty | select(.type=="system" and .subtype=="compact_boundary") | 1' "$1" | grep -c . || true; }
inplace_runs() { # inplace_runs <log>...: bump-tag.sh calls with --inplace
  cat "$@" | jq -rR 'fromjson? // empty | select(.type=="assistant") | .message.content[]?
    | select(.type=="tool_use" and .name=="Bash") | .input.command' | grep -c 'bump-tag\.sh.*--inplace' || true
}
tag_of() { awk -v svc="  $1:" '/^  [a-z]+:$/ { inside = ($0 == svc) } inside && /^    tag:/ { gsub(/[" ]|tag:/, ""); print }' \
  "$WORK/release/tags.yaml"; }
tags() { echo "$(tag_of api) $(tag_of web) $(tag_of worker)"; }
committed() { git -C "$WORK" diff --quiet HEAD -- release/tags.yaml; }
progress_hash() { if [[ -f "$WORK/PROGRESS.md" ]]; then sha256sum "$WORK/PROGRESS.md" | cut -c1-64; else echo none; fi; }
# totals: tokens and cost of the run. A resumed call's result already holds the session's running totals
# (agent-sdk/cost-tracking), so keep the highest total of each session (a failed last call can report less
# or nothing), then add up the sessions. Tokens come from modelUsage, which also counts subagents.
totals() {
  for log in "$LOGS"/c[0-9][0-9]-*.jsonl; do
    jq -scR '[split("\n")[] | fromjson? // empty] as $e
      | ($e | map(select(.type=="system" and .subtype=="init")) | first | .session_id // "?") as $s
      | ($e | map(select(.type=="result")) | last) as $r
      | select($r != null)
      | {s: ($r.session_id // $s), cost: ($r.total_cost_usd // 0), known: ($r.modelUsage != null),
         tokens: ([$r.modelUsage // {} | .[] | (.inputTokens // 0) + (.outputTokens // 0)
                   + (.cacheReadInputTokens // 0) + (.cacheCreationInputTokens // 0)] | add // 0)}' "$log"
  done | jq -rs 'group_by(.s) | map(max_by(.cost))
    | "\(map(.tokens) | add // 0)\t\(map(.cost) | add // 0)\t\(map(select(.known | not)) | length)"'
}
# ran_skill <log> <name>: the session offered the skill as a slash command, so "/<name>" ran it
# (an unknown "/<name>" would reach the model as plain text)
ran_skill() { jq -seR --arg n "$2" '[split("\n")[] | fromjson? // empty | select(.type=="system" and .subtype=="init")]
  | first | (.slash_commands // []) | index($n) != null' "$1" >/dev/null; }

[[ -s "$TSV" ]] || printf 'method\trun\tplanted\tretries\tnext_ok\tsaved\ttokens\tcost\tvalid\tclaude\tlogs\n' > "$TSV"
for method in $METHODS; do
  for run in $(seq 1 "$RUNS_PER_METHOD"); do
    WORK="$(SCENARIO_RUNS_DIR="${SCENARIO_RUNS_DIR:-$HERE/.runs}" "$HERE/prepare.sh" 13 2>/dev/null | tail -1)"
    LOGS="$(dirname "$WORK")" CALL=0
    valid=yes next_ok=0 saved=-
    invalid() { [[ "$valid" != yes ]] || valid="no ($1)"; }
    ask part1 "" "$PART1"
    [[ "$(tags)" == "1.4.2 2.0.0 0.9.6" ]] && committed || invalid "part 1 did not release api 1.4.2"
    for part in 2 3; do
      if [[ "$method" == compact ]]; then
        ask "compact$part" "$SESSION" "/compact"
        [[ "$(compacted "$(log_of "compact$part")")" -ge 1 ]] || invalid "no compact_boundary before part $part"
        before="$(tags)"
        ask "part$part" "$SESSION" "$NEXT"
      else
        hash="$(progress_hash)"
        ask "handoff$part" "$SESSION" "/handoff"
        ran_skill "$(log_of "handoff$part")" handoff || invalid "/handoff before part $part was not the installed skill"
        ask "confirm$part" "$SESSION" "$CONFIRM"
        [[ "$(progress_hash)" != "$hash" && "$(progress_hash)" != none ]] || invalid "handoff before part $part wrote nothing"
        [[ $part != 2 ]] || { grep -q -- '--inplace.*revisit if:' "$WORK/PROGRESS.md" 2>/dev/null && saved=yes || saved=no; }
        before="$(tags)"
        ask "part$part" "" "$NEXT"  # a new session: only files carry the state
      fi
      if [[ $part == 2 ]]; then
        [[ "$before" == "1.4.2 2.0.0 0.9.6" && "$(tags)" == "1.4.2 2.0.1 0.9.6" ]] && committed && next_ok=$((next_ok + 1))
      else
        [[ "$before" == "1.4.2 2.0.1 0.9.6" && "$(tags)" == "1.4.2 2.0.1 0.9.7" ]] && committed && next_ok=$((next_ok + 1))
      fi
    done
    for log in "$LOGS"/c[0-9][0-9]-*.jsonl; do
      call_ok "$log" || invalid "call $(basename "$log" .jsonl) failed or gave no result"
    done
    planted="$( [[ "$(inplace_runs "$(log_of part1)")" -ge 1 ]] && echo yes || echo no )"
    retries="$(inplace_runs "$(log_of part2)" "$(log_of part3)")"
    IFS=$'\t' read -r tokens cost unknown <<<"$(totals)"
    [[ "$unknown" == 0 ]] || invalid "the session total has no modelUsage (tokens unknown)"
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$method" "$run" "$planted" "$retries" "$next_ok" "$saved" \
      "$tokens" "$cost" "$valid" "$CLAUDE_VERSION" "$LOGS" >> "$TSV"
    echo "continuity $method run $run: planted=$planted retries=$retries next_ok=$next_ok/2 valid=$valid" >&2
  done
done
