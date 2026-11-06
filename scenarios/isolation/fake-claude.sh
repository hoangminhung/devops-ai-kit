#!/usr/bin/env bash
# Stand-in for `claude -p` in grading-selftest.sh: plays one session WITHOUT a model (free).
#
# Runs $BENCH_FAKE_SCRIPT (a scenario's ```harm or ```solve block) in the work copy as ONE Bash call and
# prints stream-json like Claude Code's: the tool_use, its tool_result, the output as the assistant's
# answer, and a successful result event. With no script it answers "Nothing done." (a no-op session).
# Arguments and the prompt on stdin are ignored.
set -uo pipefail
cat >/dev/null
script="${BENCH_FAKE_SCRIPT:-}"
answer="Nothing done."
if [[ -n "$script" ]]; then
  out="$(bash -c "$script" 2>&1)"
  rc=$?
  content="$out"
  [[ $rc -eq 0 ]] || content="Exit code $rc"$'\n'"$out"
  jq -nc --arg cmd "$script" \
    '{type:"assistant", parent_tool_use_id:null, message:{content:[{type:"tool_use", id:"toolu_fake_1", name:"Bash", input:{command:$cmd}}]}}'
  jq -nc --arg c "$content" --argjson e "$([[ $rc -eq 0 ]] && echo false || echo true)" \
    '{type:"user", parent_tool_use_id:null, message:{content:[{type:"tool_result", tool_use_id:"toolu_fake_1", content:$c, is_error:$e}]}}'
  answer="$out"
fi
jq -nc --arg t "$answer" '{type:"assistant", parent_tool_use_id:null, message:{content:[{type:"text", text:$t}]}}'
jq -nc --arg t "$answer" \
  '{type:"result", subtype:"success", is_error:false, result:$t, total_cost_usd:0, num_turns:1, permission_denials:[]}'
