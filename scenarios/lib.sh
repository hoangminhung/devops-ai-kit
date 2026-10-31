# Helpers for the "check" blocks of the scenario files. Sourced by run-headless.sh.
# $LOG is the stream-json output of `claude -p --output-format stream-json --verbose`; $WORK is the work copy.
# shellcheck shell=bash

tool_uses()     { jq -c 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | {name, input}' "$LOG"; }
bash_commands() { tool_uses | jq -r 'select(.name=="Bash") | .input.command'; }
skills_used()   { tool_uses | jq -r 'select(.name=="Skill") | .input.skill // .input.command // empty'; }
agents_used()   { tool_uses | jq -r 'select(.name=="Agent" or .name=="Task") | .input.subagent_type // empty'; }
final_text()    { jq -r 'select(.type=="result") | .result // empty' "$LOG"; }
denied_tools()  { jq -c 'select(.type=="result") | .permission_denials[]? | {tool_name, input: (.tool_input.command // .tool_input.file_path // "")}' "$LOG"; }

# fail "<message>": print and return 1 (use as: condition || fail "why")
fail() { echo "  FAIL: $*" >&2; return 1; }
