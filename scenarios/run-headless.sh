#!/usr/bin/env bash
# Run scenarios with `claude -p` and grade them with the "check" block of each scenario file.
#
#   scenarios/run-headless.sh 03 05 07        # some scenarios
#   scenarios/run-headless.sh all             # every scenario that has a check block
#   scenarios/run-headless.sh --grade-only <run folder>/claude.jsonl <NN>
#                                             # grade an existing log again (no model call, free);
#                                             # the work copy is <run folder>/repo
#
# Every check line runs (one failure does not hide the next). Each line ends in `fail_o` (outcome) or
# `fail_p`/`fail` (process); the result line is `NN PASS|FAIL P=<passed>/<total> O=<passed>/<total> (log)`
# and the failed checks are in checks.tsv next to the log. PASS = every check passed.
#
# COSTS TOKENS (each scenario is a full Claude Code session). Run it before a release, not in CI.
# Only single-prompt scenarios with a ```check block run here; the others are manual (see README).
# Env: CLAUDE_BIN (path to claude; default: `claude` on PATH, else the VS Code extension's binary),
#      MODEL (default: the Claude Code default model).
# A scenario may set environment for the session with a line `Headless env: \`KEY=VALUE ...\``;
# `{sandbox}` in it is replaced by the sandbox folder. Such a scenario is skipped while the sandbox is down.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT_DIR="$(dirname "$HERE")"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
if [[ -z "$CLAUDE_BIN" ]]; then
  # One of these folders usually does not exist: find then fails, which must not stop the script.
  CLAUDE_BIN="$( { find "$HOME/.vscode-server/extensions" "$HOME/.vscode/extensions" \
    -path '*anthropic.claude-code-*/native-binary/claude' 2>/dev/null || true; } | sort | tail -1)"
fi
[[ -x "$CLAUDE_BIN" ]] || { echo "claude not found: set CLAUDE_BIN" >&2; exit 1; }
command -v jq >/dev/null || { echo "jq is needed to grade the scenarios" >&2; exit 1; }

block() { # block <file> <fence name>: print the content of the first ```<name> block
  awk -v name="$2" '$0 == "```" name {inside=1; next} inside && $0 == "```" {exit} inside {print}' "$1"
}

# grade_block <check> <log> <work> <nn>: run every check line, print the result line, return 0 if all passed
grade_block() {
  local check="$1" log="$2" work="$3" nn="$4" out p_total o_total p_fail o_fail
  out="$(dirname "$log")/checks.tsv"
  : > "$out"
  o_total="$(grep -cE '\bfail_o\b' <<<"$check" || true)"
  p_total="$(grep -cE '\bfail(_p)?\b' <<<"$check" || true)"
  (cd "$work" && LOG="$log" WORK="$work" CHECKS_OUT="$out" bash -c "source '$HERE/lib.sh'; $check") >&2 || true
  o_fail="$(grep -c '^O' "$out" || true)"
  p_fail="$(grep -c '^P' "$out" || true)"
  local verdict=PASS
  [[ -s "$out" ]] && verdict=FAIL
  echo "$nn $verdict P=$((p_total - p_fail))/$p_total O=$((o_total - o_fail))/$o_total  ($log)"
  [[ "$verdict" == PASS ]]
}

if [[ "${1:-}" == "--grade-only" ]]; then
  log="${2:?usage: run-headless.sh --grade-only <log> <NN>}"; nn="${3:?usage: run-headless.sh --grade-only <log> <NN>}"
  file="$(find "$HERE" -maxdepth 1 -name "${nn}-*.md" | head -1)"
  [[ -n "$file" && -f "$log" ]] || { echo "no scenario $nn or no log $log" >&2; exit 2; }
  log="$(cd "$(dirname "$log")" && pwd)/$(basename "$log")"
  grade_block "$(block "$file" check)" "$log" "$(dirname "$log")/repo" "$nn"
  exit
fi

if [[ "${1:-}" == "all" || $# -eq 0 ]]; then
  mapfile -t FILES < <(grep -l '^```check$' "$HERE"/[0-9][0-9]-*.md)
else
  FILES=()
  for nn in "$@"; do FILES+=("$(find "$HERE" -maxdepth 1 -name "${nn}-*.md" | head -1)"); done
fi

PASSED=0; FAILED=0; SKIPPED=0
for file in "${FILES[@]}"; do
  nn="$(basename "$file" | cut -c1-2)"
  prompt="$(block "$file" prompt)"
  check="$(block "$file" check)"
  if [[ -z "$prompt" || -z "$check" ]]; then
    echo "$nn SKIP (manual only)"; SKIPPED=$((SKIPPED + 1)); continue
  fi
  env_line="$(sed -n 's/^Headless env: `\(.*\)`$/\1/p' "$file")"
  run_env=()
  if [[ -n "$env_line" ]]; then
    if [[ "$env_line" == *"{sandbox}"* && ! -f "$KIT_DIR/sandbox/.kubeconfig" ]]; then
      echo "$nn SKIP (needs the sandbox: sandbox/up.sh)"; SKIPPED=$((SKIPPED + 1)); continue
    fi
    read -r -a run_env <<<"${env_line//\{sandbox\}/$KIT_DIR/sandbox}"
  fi
  flags_line="$(sed -n 's/^Headless flags: `\(.*\)`$/\1/p' "$file")"
  flags=()
  [[ -n "$flags_line" ]] && eval "flags=( $flags_line )"
  [[ -n "${MODEL:-}" ]] && flags+=(--model "$MODEL")
  work="$("$HERE/prepare.sh" "$nn")"
  log="$(dirname "$work")/claude.jsonl"
  (cd "$work" && printf '%s\n' "$prompt" | env "${run_env[@]}" "$CLAUDE_BIN" -p --output-format stream-json --verbose "${flags[@]}" > "$log" 2> "${log%.jsonl}.stderr") || true
  if grade_block "$check" "$log" "$work" "$nn"; then
    PASSED=$((PASSED + 1))
  else
    FAILED=$((FAILED + 1))
  fi
done
echo "passed: $PASSED  failed: $FAILED  skipped: $SKIPPED"
[[ $FAILED -eq 0 ]]
