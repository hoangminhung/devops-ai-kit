#!/usr/bin/env bash
# Make a fresh work copy of sandbox/repo for one scenario and print its path (last line).
#
#   scenarios/prepare.sh <NN>
#
# - Copies sandbox/repo (plus the scenario's fixture, if any) to scenarios/.runs/<NN>-<time>/repo
#   and commits it, so `git diff` shows exactly what the session changed.
# - The kit under test is the one INSTALLED in your Claude config dir (${CLAUDE_CONFIG_DIR:-~/.claude}):
#   when a skill exists both there and in a project, Claude Code uses the installed one.
#   Skills of this repo that are not installed yet are copied into the copy's .claude/skills/
#   (copied, not linked: Claude Code does not read files through links that point outside the project).
#   To test a branch, install it first (into a test config dir is safest; see scenarios/README.md).
# - PREPARE_NO_KIT=1: copy no kit skills (baseline run without the kit, used by benchmark.sh).
# - SCENARIO_RUNS_DIR: where work copies go (default scenarios/.runs). benchmark.sh puts them outside
#   $HOME, so CLAUDE.md files of parent folders (e.g. ~/.claude/CLAUDE.md) are not loaded.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(dirname "$HERE")"
NN="${1:?usage: scenarios/prepare.sh <NN>}"
SCENARIO="$(find "$HERE" -maxdepth 1 -name "${NN}-*.md" | head -1)"
[[ -n "$SCENARIO" ]] || { echo "No scenario file $HERE/${NN}-*.md" >&2; exit 1; }

ISOLATION="$(sed -n 's/^- \*\*Isolation:\*\* `\{0,1\}\([a-z]*\)`\{0,1\}.*/\1/p' "$SCENARIO")"
if [[ "$ISOLATION" == container ]]; then
  # The container mounts only work copies under /tmp (isolation/run-in-container.sh).
  RUNS="${SCENARIO_RUNS_DIR:-$(mktemp -d /tmp/devops-kit-scenarios.XXXXXX)}"
else
  RUNS="${SCENARIO_RUNS_DIR:-$HERE/.runs}"
fi
mkdir -p "$RUNS"
BASE="$RUNS/${NN}-$(date +%Y%m%d-%H%M%S)"
RUN="$BASE" n=1
until mkdir "$RUN" 2>/dev/null; do RUN="$BASE-$n"; n=$((n + 1)); done  # two runs in the same second
WORK="$RUN/repo"
mkdir "$WORK"
cp -a "$KIT/sandbox/repo/." "$WORK/"
FIXTURE="$(sed -n 's/^- \*\*Fixture:\*\* `\([a-z0-9-]*\)`.*/\1/p' "$SCENARIO")"
if [[ -n "$FIXTURE" ]]; then
  cp -a "$HERE/fixtures/$FIXTURE/." "$WORK/"
fi
if [[ "$ISOLATION" == container ]]; then
  # Real state for both environments, made by Terraform itself inside the bench container (offline
  # provider mirror), so state and config agree and `terraform plan` shows no change before the session.
  # shellcheck disable=SC2016  # expanded inside the container
  "$HERE/isolation/run-in-container.sh" --work "$WORK" --exec -- bash -c \
    'for e in dev prod; do terraform -chdir=terraform/envs/$e init -input=false >/dev/null \
       && terraform -chdir=terraform/envs/$e apply -input=false -auto-approve >/dev/null || exit 1; done' \
    || { echo "seeding the Terraform state failed" >&2; exit 1; }
  # Canaries: __CANARY_<ID>__ placeholders and the random_password results of the new state.
  python3 "$HERE/graders/grade.py" plant "$WORK" "$RUN" >/dev/null
fi
(cd "$WORK" && git init -q -b main && git add -A \
  && git -c user.name=scenario -c user.email=scenario@example.invalid commit -qm "scenario $NN start")
if [[ "$ISOLATION" == container ]]; then
  python3 "$HERE/graders/grade.py" snapshot "$WORK" "$RUN/fs-before.json"
fi

CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
INSTALLED="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("kit_version","?"))' \
  "$CFG/.devops-kit-manifest.json" 2>/dev/null || echo "not installed")"
COPIED=()
for skill in "$KIT"/claude/skills/*/; do
  name="$(basename "$skill")"
  if [[ "${PREPARE_NO_KIT:-}" != 1 && ! -e "$CFG/skills/$name" ]]; then
    mkdir -p "$WORK/.claude/skills"
    cp -R "$skill" "$WORK/.claude/skills/$name"
    rm -rf "$WORK/.claude/skills/$name/scripts/__pycache__"
    COPIED+=("$name")
  fi
done

{
  echo "Scenario  : $(basename "$SCENARIO")"
  echo "Fixture   : ${FIXTURE:-none}"
  echo "Kit tested: installed v$INSTALLED in $CFG (this repo: v$(cat "$KIT/VERSION"))"
  echo "Copied    : ${COPIED[*]:-none} (not installed, taken from this repo)"
} >&2
echo "$WORK"
