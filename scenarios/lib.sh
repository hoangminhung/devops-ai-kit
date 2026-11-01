# Helpers for the "check" blocks of the scenario files. Sourced by run-headless.sh.
# $LOG is the stream-json output of `claude -p --output-format stream-json --verbose`; $WORK is the work copy.
# shellcheck shell=bash

# events: the JSON lines of $LOG (a non-JSON line, e.g. a warning, is skipped instead of breaking jq)
events()        { jq -cR 'fromjson? // empty' "$LOG"; }
tool_uses()     { events | jq -c 'select(.type=="assistant") | .message.content[]? | select(.type=="tool_use") | {name, input}'; }
bash_commands() { tool_uses | jq -r 'select(.name=="Bash") | .input.command'; }
skills_used()   { tool_uses | jq -r 'select(.name=="Skill") | .input.skill // .input.command // empty'; }
agents_used()   { tool_uses | jq -r 'select(.name=="Agent" or .name=="Task") | .input.subagent_type // empty'; }
written_text()  { tool_uses | jq -r 'select(.name=="Write") | .input.content // empty'; }
final_text()    { events | jq -r 'select(.type=="result") | .result // empty'; }
denied_tools()  { events | jq -c 'select(.type=="result") | .permission_denials[]? | {tool_name, input: (.tool_input.command // .tool_input.file_path // "")}'; }

# metrics: one JSON line — prompts (tool calls blocked or waiting for a person, in the main session
# AND in subagents: in -p every would-be confirm dialog becomes a denial; the result's
# permission_denials list misses the subagents' ones), cost in USD, turns, and context tokens of the
# first request.
metrics() {
  events | jq -sc '(map(select(.type=="user") | .message.content[]? | select(.type=="tool_result" and .is_error == true)
        | (.content | tostring) | select(test("Permission to use .* has been denied|^devops-ai-kit: blocked"))) | length) as $blocked
    | (map(select(.type=="result")) | last // {}) as $r
    | (map(select(.type=="assistant" and (.parent_tool_use_id // null) == null)) | first | .message.usage // {}) as $u
    | {prompts: ([$blocked, ($r.permission_denials // [] | length)] | max), cost: ($r.total_cost_usd // 0), turns: ($r.num_turns // 0),
       context: (($u.input_tokens // 0) + ($u.cache_creation_input_tokens // 0) + ($u.cache_read_input_tokens // 0))}' 
}

# fail "<message>": print and return 1 (use as: condition || fail "why")
fail() { echo "  FAIL: $*" >&2; return 1; }
