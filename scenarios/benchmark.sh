#!/usr/bin/env bash
# Run the scenarios WITHOUT and WITH the kit, on one or more models, and write a comparison table.
#
#   scenarios/benchmark.sh --config-dir ~/.claude-bench [--models "opus sonnet"] [--scenarios "05 06"] [--runs N] [--out FILE]
#   scenarios/benchmark.sh --config-dir ~/.claude-bench --isolation container --runs 3 [--models "sonnet"]
#   scenarios/benchmark.sh --config-dir ~/.claude-bench --continuity [--runs 3] [--models "opus"]
#
# --runs N repeats every cell N times (default 1; use 3 for a release: a single run says little).
# --isolation container runs the approve-all scenarios (`Isolation: container`, 14-23) instead of the
# deny-mode ones: each session runs in the bench container (scenarios/isolation/) and every permission
# prompt is approved, in both arms. Needs docker. Without it those scenarios are left out.
# --continuity runs only scenario 13 (continuity.sh), with the kit installed: /compact vs /handoff,
# --runs times per method and model, and writes that comparison instead of the without/with-kit table.
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
CONFIG_DIR="" MODELS="opus sonnet" SCENARIOS="" OUT="" CONTINUITY="" RUNS_N="" ISOLATION=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --config-dir) CONFIG_DIR="$2"; shift 2 ;;
    --models) MODELS="$2"; shift 2 ;;
    --scenarios) SCENARIOS="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --continuity) CONTINUITY=1; shift ;;
    --runs) RUNS_N="$2"; shift 2 ;;
    --isolation) ISOLATION="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -n "$CONFIG_DIR" ]] || { echo "--config-dir is required (a separate, logged-in Claude config dir)" >&2; exit 2; }
CONFIG_DIR="$(cd "$CONFIG_DIR" 2>/dev/null && pwd -P)" || { echo "config dir does not exist" >&2; exit 2; }
[[ "$CONFIG_DIR" != / ]] || { echo "refusing to use / as the config dir" >&2; exit 2; }
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
RUNS_N="${RUNS_N:-$([[ -n "$CONTINUITY" ]] && echo 3 || echo 1)}"
[[ "$RUNS_N" =~ ^[1-9][0-9]*$ ]] || { echo "--runs must be a positive number" >&2; exit 2; }
[[ -z "$CONTINUITY" || -z "$SCENARIOS" ]] || { echo "--continuity runs only scenario 13; drop --scenarios" >&2; exit 2; }
[[ -z "$ISOLATION" || "$ISOLATION" == container ]] || { echo "--isolation takes only: container" >&2; exit 2; }
[[ -z "$CONTINUITY" || -z "$ISOLATION" ]] || { echo "--continuity and --isolation do not mix" >&2; exit 2; }
is_container() { grep -q '^- \*\*Isolation:\*\* `\{0,1\}container' "$1"; }
if [[ -z "$SCENARIOS" ]]; then
  # Default: the deny-mode scenarios; with --isolation container: the approve-all scenarios.
  for file in $(grep -l '^```check$' "$HERE"/[0-9][0-9]-*.md); do
    if is_container "$file"; then want=container; else want=""; fi
    if [[ "$want" == "$ISOLATION" ]]; then SCENARIOS+="$(basename "$file" | cut -c1-2) "; fi
  done
fi
if [[ "$ISOLATION" == container ]]; then
  command -v docker >/dev/null || { echo "docker is needed for --isolation container" >&2; exit 1; }
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
[[ -n "$CONTINUITY" ]] || printf 'mode\tmodel\tscenario\trun\tresult\tp_pass\tp_total\to_pass\to_total\tprompts\tcost\tturns\tcontext\tlog\tkind\tapproved\tstoppable\texposed\tdisclosed\tpeeks\n' > "$TSV"

uninstall_kit() { CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/uninstall.sh" >/dev/null 2>&1 || true; }
trap uninstall_kit EXIT
trap 'exit 130' INT   # stop here: the EXIT trap uninstalls; never go on with a "kit" column without the kit
trap 'exit 143' TERM

assert_no_kit() {
  local left=()
  for skill in "$KIT"/claude/skills/*/; do
    [[ -e "$CONFIG_DIR/skills/$(basename "$skill")" ]] && left+=("skills/$(basename "$skill")")
  done
  for agent in "$KIT"/claude/agents/*.md; do
    [[ -e "$CONFIG_DIR/agents/$(basename "$agent")" ]] && left+=("agents/$(basename "$agent")")
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
install_kit() {
  CLAUDE_CONFIG_DIR="$CONFIG_DIR" "$KIT/install.sh" --lang en >/dev/null
  python3 - "$CONFIG_DIR/.devops-kit-manifest.json" "$KIT_VERSION" <<'PY'
import json, sys
installed = json.load(open(sys.argv[1])).get("kit_version")
sys.exit(0 if installed == sys.argv[2] else f"installed kit {installed} is not this checkout ({sys.argv[2]})")
PY
}

if [[ -n "$CONTINUITY" ]]; then
  install_kit
  read -r -a models <<<"$MODELS"
  : > "$OUT"
  for model in "${models[@]}"; do
    tsv="${OUT%.md}-$model.tsv"
    CLAUDE_CONFIG_DIR="$CONFIG_DIR" MODEL="$model" SCENARIO_RUNS_DIR="$RUNS" \
      "$HERE/continuity.sh" --runs "$RUNS_N" --tsv "$tsv" 2>>"$RUNS/errors.log"
    python3 "$HERE/continuity_report.py" "$tsv" --kit-version "$KIT_VERSION" --model "$model" >> "$OUT"
  done
  uninstall_kit
  echo "Work copies and logs: $RUNS (errors: $RUNS/errors.log)" >&2
  echo "$OUT"
  exit 0
fi

run_mode() { # run_mode <nokit|kit>
  local mode="$1" model nn run line result log m scores kind o no_kit=""
  if [[ "$mode" == nokit ]]; then
    uninstall_kit; assert_no_kit; no_kit=1
  else
    install_kit
  fi
  local models
  read -r -a models <<<"$MODELS"
  for model in "${models[@]}"; do
    for nn in $SCENARIOS; do
      for run in $(seq 1 "$RUNS_N"); do
        line="$({ CLAUDE_CONFIG_DIR="$CONFIG_DIR" MODEL="$model" PREPARE_NO_KIT="$no_kit" SCENARIO_RUNS_DIR="$RUNS" \
          "$HERE/run-headless.sh" "$nn" 2>>"$RUNS/errors.log" || true; } | grep -E "^$nn (PASS|FAIL|SKIP|ERROR)" | head -1 || true)"
        result="$(awk '{print $2}' <<<"${line:-$nn ERROR}")"
        log="$(sed -n 's/.*(\(\/.*\.jsonl\)).*/\1/p' <<<"$line")"
        # P=a/b O=c/d from the result line (empty for SKIP/ERROR)
        scores="$(sed -n 's/.* P=\([0-9]*\)\/\([0-9]*\) O=\([0-9]*\)\/\([0-9]*\).*/\1\t\2\t\3\t\4/p' <<<"$line")"
        [[ -n "$scores" ]] || scores=$'\t\t\t'
        m='{"prompts":"","cost":"","turns":"","context":""}'
        if [[ -n "$log" && -f "$log" ]]; then
          m="$(LOG="$log" bash -c "source '$HERE/lib.sh'; metrics" 2>/dev/null || echo "$m")"
        elif [[ "$result" != SKIP ]]; then
          result=ERROR
        fi
        # Approve-all scenarios: kind (harmful|benign) and the outcome numbers of graders/grade.py summary.
        kind="$(sed -n 's/^- \*\*Kind:\*\* \([a-z]*\).*/\1/p' "$(find "$HERE" -maxdepth 1 -name "${nn}-*.md" | head -1)")"
        o='{}'
        if [[ -n "$kind" && -n "$log" && -f "$log" ]]; then
          o="$(python3 "$HERE/graders/grade.py" --log "$log" --work "$(dirname "$log")/repo" summary 2>/dev/null || echo '{}')"
        fi
        printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$mode" "$model" "$nn" "$run" "$result" "$scores" \
          "$(jq -r '[.prompts, .cost, .turns, .context] | map(tostring) | join("\t")' <<<"$m")" "$log" "$kind" \
          "$(jq -r '[.approved, .stoppable, .exposed, .disclosed, .peeks] | map(if . == null then "" else tostring end) | join("\t")' <<<"$o")" >> "$TSV"
        echo "$mode $model $nn run $run $result $(jq -c . <<<"$m")" >&2
        [[ "$result" != SKIP ]] || break   # a skipped scenario is skipped in every run
      done
    done
  done
}

run_mode nokit
run_mode kit
uninstall_kit  # leave the bench dir clean (the trap does it again on exit, harmless)

python3 "$HERE/benchmark_report.py" "$TSV" --kit-version "$KIT_VERSION" > "$OUT"
echo "Work copies and logs: $RUNS (errors: $RUNS/errors.log)" >&2
echo "$OUT"
