#!/usr/bin/env bash
# Run scenarios with `claude -p` and grade them with the "check" block of each scenario file.
#
#   scenarios/run-headless.sh 03 05 07        # some scenarios
#   scenarios/run-headless.sh all             # every scenario that has a check block
#
# COSTS TOKENS (each scenario is a full Claude Code session). Run it before a release, not in CI.
# Only single-prompt scenarios with a ```check block run here; the others are manual (see README).
# Env: CLAUDE_BIN (path to claude; default: `claude` on PATH, else the VS Code extension's binary),
#      MODEL (default: the Claude Code default model).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
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
  flags_line="$(sed -n 's/^Headless flags: `\(.*\)`$/\1/p' "$file")"
  flags=()
  [[ -n "$flags_line" ]] && eval "flags=( $flags_line )"
  [[ -n "${MODEL:-}" ]] && flags+=(--model "$MODEL")
  work="$("$HERE/prepare.sh" "$nn")"
  log="$(dirname "$work")/claude.jsonl"
  (cd "$work" && printf '%s\n' "$prompt" | "$CLAUDE_BIN" -p --output-format stream-json --verbose "${flags[@]}" > "$log" 2>&1) || true
  if (cd "$work" && LOG="$log" WORK="$work" bash -c "source '$HERE/lib.sh'; set -e; $check"); then
    echo "$nn PASS  ($log)"; PASSED=$((PASSED + 1))
  else
    echo "$nn FAIL  ($log)"; FAILED=$((FAILED + 1))
  fi
done
echo "passed: $PASSED  failed: $FAILED  skipped: $SKIPPED"
[[ $FAILED -eq 0 ]]
