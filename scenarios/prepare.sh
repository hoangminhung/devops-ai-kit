#!/usr/bin/env bash
# Make a fresh work copy of sandbox/repo for one scenario and print its path (last line).
#
#   scenarios/prepare.sh <NN>
#
# - Copies sandbox/repo (plus the scenario's fixture, if any) to scenarios/.runs/<NN>-<time>/repo
#   and commits it, so `git diff` shows exactly what the session changed.
# - The kit under test is the one INSTALLED in your Claude config dir (${CLAUDE_CONFIG_DIR:-~/.claude}):
#   when a skill exists both there and in a project, Claude Code uses the installed one.
#   Skills of this repo that are not installed yet are linked into the copy's .claude/skills/.
#   To test a branch, install it first (into a test config dir is safest; see scenarios/README.md).
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KIT="$(dirname "$HERE")"
NN="${1:?usage: scenarios/prepare.sh <NN>}"
SCENARIO="$(find "$HERE" -maxdepth 1 -name "${NN}-*.md" | head -1)"
[[ -n "$SCENARIO" ]] || { echo "No scenario file $HERE/${NN}-*.md" >&2; exit 1; }

WORK="$HERE/.runs/${NN}-$(date +%Y%m%d-%H%M%S)/repo"
mkdir -p "$WORK"
cp -a "$KIT/sandbox/repo/." "$WORK/"
FIXTURE="$(sed -n 's/^- \*\*Fixture:\*\* `\([a-z0-9-]*\)`.*/\1/p' "$SCENARIO")"
if [[ -n "$FIXTURE" ]]; then
  cp -a "$HERE/fixtures/$FIXTURE/." "$WORK/"
fi
(cd "$WORK" && git init -q -b main && git add -A \
  && git -c user.name=scenario -c user.email=scenario@example.invalid commit -qm "scenario $NN start")

CFG="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
INSTALLED="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("kit_version","?"))' \
  "$CFG/.devops-kit-manifest.json" 2>/dev/null || echo "not installed")"
LINKED=()
for skill in "$KIT"/claude/skills/*/; do
  name="$(basename "$skill")"
  if [[ ! -e "$CFG/skills/$name" ]]; then
    mkdir -p "$WORK/.claude/skills"
    ln -s "$skill" "$WORK/.claude/skills/$name"
    LINKED+=("$name")
  fi
done

{
  echo "Scenario  : $(basename "$SCENARIO")"
  echo "Fixture   : ${FIXTURE:-none}"
  echo "Kit tested: installed v$INSTALLED in $CFG (this repo: v$(cat "$KIT/VERSION"))"
  echo "Linked    : ${LINKED[*]:-none} (not installed, taken from this repo)"
} >&2
echo "$WORK"
