#!/usr/bin/env bash
# Run the scenarios WITHOUT and WITH the kit, on one or more models, and write a comparison table.
#
#   scenarios/benchmark.sh --config-dir ~/.claude-bench [--models "opus sonnet"] [--scenarios "05 06"] [--out FILE]
#
# --config-dir is a SEPARATE Claude config dir that you logged in to once:
#   CLAUDE_CONFIG_DIR=~/.claude-bench claude     # then /login, then /exit
# The script uninstalls the kit there (baseline), checks that nothing of the kit is left, runs,
# installs this checkout there, runs again, and uninstalls at the end (also on Ctrl-C).
# It refuses a dir that is, contains or is inside your real config dir (symlinks resolved).
# Work copies go to a temp folder outside $HOME, so no parent CLAUDE.md is loaded.
# COSTS TOKENS: every cell is a full Claude Code session. Cluster scenarios run only while the
# sandbox is up (sandbox/up.sh).
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
CONFIG_DIR="$(cd "$CONFIG_DIR" 2>/dev/null && pwd -P)" || { echo "config dir does not exist" >&2; exit 2; }
for real in "$HOME/.claude" "${CLAUDE_CONFIG_DIR:-}"; do
  [[ -n "$real" && -d "$real" ]] || continue
  real="$(cd "$real" && pwd -P)"
  if [[ "$CONFIG_DIR" == "$real" || "$CONFIG_DIR/" == "$real/"* || "$real/" == "$CONFIG_DIR/"* ]]; then
    echo "refusing to use your real Claude config dir or a folder in/around it ($CONFIG_DIR): pass a separate one" >&2
    exit 2
  fi
done
for tool in jq python3; do
  command -v "$tool" >/dev/null || { echo "$tool is needed" >&2; exit 1; }
done
if [[ -z "$SCENARIOS" ]]; then
  SCENARIOS="$(grep -l '^```check$' "$HERE"/[0-9][0-9]-*.md | xargs -n1 basename | cut -c1-2 | tr '\n' ' ')"
fi
for nn in $SCENARIOS; do
  [[ "$nn" =~ ^[0-9][0-9]$ ]] && compgen -G "$HERE/${nn}-*.md" >/dev/null \
    || { echo "unknown scenario: $nn" >&2; exit 2; }
done
STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="${OUT:-$HERE/.runs/benchmark-$STAMP.md}"
mkdir -p "$(dirname "$OUT")"
TSV="${OUT%.md}.tsv"
RUNS="$(mktemp -d /tmp/devops-kit-bench.XXXXXX)"
printf 'mode\tmodel\tscenario\tresult\tprompts\tcost\tturns\tcontext\tlog\n' > "$TSV"

uninstall_kit() { CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/uninstall.sh" >/dev/null 2>&1 || true; }
trap uninstall_kit EXIT INT TERM

assert_no_kit() {
  local left=()
  for skill in "$KIT"/claude/skills/*/; do
    [[ -e "$CONFIG_DIR/skills/$(basename "$skill")" ]] && left+=("skills/$(basename "$skill")")
  done
  for path in rules/devops-kit hooks/devops-kit .devops-kit-manifest.json; do
    [[ -e "$CONFIG_DIR/$path" ]] && left+=("$path")
  done
  grep -q 'infra-context-guard' "$CONFIG_DIR/settings.json" 2>/dev/null && left+=("hook in settings.json")
  if [[ ${#left[@]} -gt 0 ]]; then
    echo "baseline is not clean, kit files left in $CONFIG_DIR: ${left[*]}" >&2; exit 1
  fi
}

KIT_VERSION="$(cat "$KIT/VERSION")"
run_mode() { # run_mode <nokit|kit>
  local mode="$1" model nn line result log m no_kit=""
  if [[ "$mode" == nokit ]]; then
    uninstall_kit; assert_no_kit; no_kit=1
  else
    CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/install.sh" --lang en >/dev/null
    python3 - "$CONFIG_DIR/.devops-kit-manifest.json" "$KIT_VERSION" <<'PY'
import json, sys
installed = json.load(open(sys.argv[1])).get("kit_version")
sys.exit(0 if installed == sys.argv[2] else f"installed kit {installed} is not this checkout ({sys.argv[2]})")
PY
  fi
  for model in $MODELS; do
    for nn in $SCENARIOS; do
      line="$({ CLAUDE_CONFIG_DIR="$CONFIG_DIR" MODEL="$model" PREPARE_NO_KIT="$no_kit" SCENARIO_RUNS_DIR="$RUNS" \
        "$HERE/run-headless.sh" "$nn" 2>>"$RUNS/errors.log" || true; } | grep -E "^$nn (PASS|FAIL|SKIP)" | head -1 || true)"
      result="$(awk '{print $2}' <<<"${line:-$nn ERROR}")"
      log="$(sed -n 's/.*(\(\/.*\.jsonl\)).*/\1/p' <<<"$line")"
      m='{"prompts":"","cost":"","turns":"","context":""}'
      if [[ -n "$log" && -f "$log" ]]; then
        m="$(LOG="$log" bash -c "source '$HERE/lib.sh'; metrics" 2>/dev/null || echo "$m")"
      elif [[ "$result" != SKIP ]]; then
        result=ERROR
      fi
      printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$mode" "$model" "$nn" "$result" \
        "$(jq -r '[.prompts, .cost, .turns, .context] | map(tostring) | join("\t")' <<<"$m")" "$log" >> "$TSV"
      echo "$mode $model $nn $result $(jq -c . <<<"$m")" >&2
    done
  done
}

run_mode nokit
run_mode kit
uninstall_kit  # leave the bench dir clean (the trap does it again on exit, harmless)

python3 "$HERE/benchmark_report.py" "$TSV" --kit-version "$KIT_VERSION" > "$OUT"
echo "Work copies and logs: $RUNS (errors: $RUNS/errors.log)" >&2
echo "$OUT"
