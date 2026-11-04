#!/usr/bin/env bash
# Check the benchmark container's isolation WITHOUT any model call (free).
#
#   scenarios/isolation/selftest.sh
#
# Starts the same container as run-in-container.sh (with an empty work copy and an empty config dir)
# and tries, from inside, what a model in approve-all mode could try. Every line must say "ok".
set -euo pipefail
# shellcheck source=scenarios/isolation/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

command -v docker >/dev/null || { echo "docker is needed" >&2; exit 1; }
ensure_image
ensure_network
base_run_args
WORK="$(mktemp -d /tmp/devops-kit-bench-selftest.XXXXXX)"
trap 'rm -rf "$WORK"' EXIT

# shellcheck disable=SC2016  # expanded inside the container
probe='
fail=0
check() { if eval "$2" >/dev/null 2>&1; then echo "ok   $1"; else echo "FAIL $1"; fail=1; fi; }
check "not root"                         "[ \"\$(id -u)\" != 0 ]"
check "no capabilities"                  "grep -q \"^CapEff:[[:space:]]*0*\$\" /proc/self/status"
check "host kubeconfig not visible"      "! cat \"$HOST_HOME/.kube/config\""
check "host ssh keys not visible"        "! ls \"$HOST_HOME/.ssh\""
check "host claude config not visible"   "! ls \"$HOST_HOME/.claude/settings.json\""
check "no docker socket"                 "[ ! -e /var/run/docker.sock ]"
check "root fs is read-only"             "! touch /usr/local/bin/x"
check "work copy is writable"            "touch \"$WORK/x\""
check "no DNS for outside names"         "! getent hosts example.com"
check "no direct internet"               "! curl -sS --noproxy \"*\" -m 5 https://example.com"
check "proxy blocks other hosts"         "! curl -sS -m 10 https://example.com"
check "proxy allows the Claude API"      "curl -sS -m 15 -o /dev/null -w %{http_code} https://api.anthropic.com/ | grep -qE \"^[1-5][0-9][0-9]\$\""
check "terraform providers offline"      "cd /tmp && cp /dev/null m.tf && printf \"resource \\\"null_resource\\\" \\\"x\\\" {}\\n\" > m.tf && terraform init -input=false"
exit $fail
'
docker run "${RUN_ARGS[@]}" -v "$WORK:$WORK" -e HOST_HOME="$HOME" -e WORK="$WORK" "$IMAGE" bash -c "$probe"
