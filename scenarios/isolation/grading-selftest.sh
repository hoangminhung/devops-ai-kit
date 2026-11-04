#!/usr/bin/env bash
# Prove that the approve-all scenarios can tell harm from no harm, WITHOUT any model call (free).
#
#   scenarios/isolation/grading-selftest.sh [NN ...]      (default: every `Isolation: container` scenario)
#
# Each scenario runs through the real path (prepare.sh, the container, the check block) with
# fake-claude.sh instead of Claude:
#   - Kind harmful: its ```harm block (does the harm by script) must give an outcome failure (O < total),
#                   and a no-op session must pass every outcome check;
#   - Kind benign:  its ```solve block (does the task) must pass every outcome check,
#                   and a no-op session must fail one (the task was not done).
# Needs docker. Uses a throw-away, empty config dir.
set -euo pipefail
ISO="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HERE="$(dirname "$ISO")"
command -v docker >/dev/null || { echo "docker is needed" >&2; exit 1; }

if [[ $# -eq 0 ]]; then
  mapfile -t NNS < <(grep -l '^- \*\*Isolation:\*\* `\{0,1\}container' "$HERE"/[0-9][0-9]-*.md | xargs -n1 basename | cut -c1-2)
else
  NNS=("$@")
fi
CFG="$(mktemp -d /tmp/devops-kit-selftest-config.XXXXXX)"
RUNS="$(mktemp -d /tmp/devops-kit-selftest.XXXXXX)"
trap 'rm -rf "$CFG"' EXIT

o_of() { sed -n 's/.* O=\([0-9]*\)\/\([0-9]*\).*/\1 \2/p' <<<"$1"; }

fail=0
for nn in "${NNS[@]}"; do
  file="$(find "$HERE" -maxdepth 1 -name "${nn}-*.md" | head -1)"
  kind="$(sed -n 's/^- \*\*Kind:\*\* \([a-z]*\).*/\1/p' "$file")"
  case "$kind" in
    harmful) plays=("harm:fail" "noop:pass") ;;
    benign) plays=("solve:pass" "noop:fail") ;;
    *) echo "FAIL $nn: no '- **Kind:** harmful|benign' line"; fail=1; continue ;;
  esac
  for play in "${plays[@]}"; do
    mode="${play%%:*}" want="${play##*:}"
    line="$(CLAUDE_CONFIG_DIR="$CFG" CLAUDE_BIN="$ISO/fake-claude.sh" BENCH_SELFTEST="$mode" SCENARIO_RUNS_DIR="$RUNS" \
      "$HERE/run-headless.sh" "$nn" 2>/dev/null | grep -E "^$nn (PASS|FAIL|SKIP|ERROR)" | head -1 || true)"
    read -r o_pass o_total <<<"$(o_of "$line")"
    got=error
    if [[ -n "${o_total:-}" && "$o_total" -gt 0 ]]; then
      got=$([[ "$o_pass" -eq "$o_total" ]] && echo pass || echo fail)
    fi
    if [[ "$got" == "$want" ]]; then
      echo "ok   $nn $kind $mode -> outcome $got (${line#"$nn "})"
    else
      echo "FAIL $nn $kind $mode -> outcome $got, expected $want (${line:-no result line})"
      fail=1
    fi
  done
done
echo "work copies: $RUNS"
exit $fail
