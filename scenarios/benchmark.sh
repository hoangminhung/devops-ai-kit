#!/usr/bin/env bash
# Run the scenarios WITHOUT and WITH the kit, on one or more models, and write a comparison table.
#
#   scenarios/benchmark.sh --config-dir ~/.claude-bench [--models "opus sonnet"] [--scenarios "05 06"] [--out FILE]
#
# --config-dir is a SEPARATE Claude config dir that you logged in to once:
#   CLAUDE_CONFIG_DIR=~/.claude-bench claude     # then /login, then /exit
# The script uninstalls the kit there (baseline), runs, installs this checkout there, runs again.
# It refuses to touch your real config dir. COSTS TOKENS: every cell is a full Claude Code session.
# Cluster scenarios run only while the sandbox is up (sandbox/up.sh).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(dirname "$HERE")"
CONFIG_DIR="" MODELS="opus sonnet" SCENARIOS="" OUT=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --scenarios) SCENARIOS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$CONFIG_DIR" ]] || { echo "--config-dir is required (a separate, logged-in Claude config dir)" >&2; exit 2; }
CONFIG_DIR="$(cd "$CONFIG_DIR" 2>/dev/null && pwd)" || { echo "config dir does not exist" >&2; exit 2; }
for real in "$HOME/.claude" "${CLAUDE_CONFIG_DIR:-}"; do
  if [[ -n "$real" && -d "$real" && "$CONFIG_DIR" == "$(cd "$real" && pwd)" ]]; then
    echo "refusing to use your real Claude config dir ($CONFIG_DIR): pass a separate one" >&2; exit 2
  fi
done
command -v jq >/dev/null || { echo "jq is needed" >&2; exit 1; }
if [[ -z "$SCENARIOS" ]]; then
  SCENARIOS="$(grep -l '^```check$' "$HERE"/[0-9][0-9]-*.md | xargs -n1 basename | cut -c1-2 | tr '\n' ' ')"
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${OUT:-$HERE/.runs/benchmark-$STAMP.md}"
mkdir -p "$(dirname "$OUT")"
TSV="${OUT%.md}.tsv"
printf 'mode\tmodel\tscenario\tresult\tprompts\tcost\tturns\tcontext\tlog\n' > "$TSV"

run_mode() { # run_mode <nokit|kit>
  local mode="$1" model nn line result log m
  if [[ "$mode" == nokit ]]; then
    CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/uninstall.sh" >/dev/null 2>&1 || true
  else
    CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/install.sh" --lang en >/dev/null
  fi
  for model in $MODELS; do
    for nn in $SCENARIOS; do
      line="$({ CLAUDE_CONFIG_DIR="$CONFIG_DIR" MODEL="$model" PREPARE_NO_KIT="$([[ $mode == nokit ]] && echo 1 || true)" \
        "$HERE/run-headless.sh" "$nn" 2>/dev/null || true; } | grep -E "^$nn (PASS|FAIL|SKIP)" | head -1 || true)"
      line="${line:-$nn FAIL (no output)}"
      result="$(awk '{print $2}' <<<"$line")"
      log="$(sed -n 's/.*(\(\/.*\.jsonl\)).*/\1/p' <<<"$line")"
      if [[ -n "$log" && -f "$log" ]]; then
        m="$(LOG="$log" bash -c "source '$HERE/lib.sh'; metrics")"
      else
        m='{"prompts":"","cost":"","turns":"","context":""}'
      fi
      printf '%s\t%s\t%s\t%s\t%s\n' "$mode" "$model" "$nn" "$result" \
        "$(jq -r '[.prompts, .cost, .turns, .context] | map(tostring) | join("\t")' <<<"$m")	$log" >> "$TSV"
      echo "$mode $model $nn $result $(jq -c . <<<"$m")" >&2
    done
  done
}

run_mode nokit
run_mode kit
CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/uninstall.sh" >/dev/null 2>&1 || true  # leave the bench dir clean

python3 "$HERE/benchmark_report.py" "$TSV" > "$OUT"
echo "$OUT"
