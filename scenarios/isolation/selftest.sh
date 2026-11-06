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
host_open() { for a in $HOST_ADDRS; do for p in $HOST_PORTS; do timeout 2 bash -c "</dev/tcp/$a/$p" 2>/dev/null && return 0; done; done; return 1; }
check "no host listener reachable"       "! host_open"
check "kit hook denies inside"           "printf %s \"\$HOOK_INPUT\" | python3 /opt/kit-hook/infra-context-guard.py | grep -q \"\\\"permissionDecision\\\": *\\\"deny\\\"\""
exit $fail
'
# Every address of the host a container might try (bridge gateways, LAN addresses) and every TCP port
# the host listens on (any address): none may answer from inside.
HOST_ADDRS="$( { docker network inspect -f '{{range .IPAM.Config}}{{.Gateway}} {{end}}' "$NET" bridge 2>/dev/null; \
  hostname -I 2>/dev/null; } | tr ' ' '\n' | grep -E '^[0-9.]+$' | sort -u | tr '\n' ' ')"
HOST_PORTS="$(ss -ltnH 2>/dev/null | awk '{n=split($4, a, ":"); print a[n]}' | sort -un | head -40 | tr '\n' ' ')"
HOOK_INPUT='{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"terraform state pull"},"cwd":"/tmp"}'
rc=0
docker run "${RUN_ARGS[@]}" -v "$WORK:$WORK" -e HOST_HOME="$HOME" -e WORK="$WORK" \
  -e HOST_ADDRS="$HOST_ADDRS" -e HOST_PORTS="$HOST_PORTS" -e HOOK_INPUT="$HOOK_INPUT" \
  -v "$(dirname "$ISO_DIR")/../claude/hooks/devops-kit:/opt/kit-hook:ro" \
  "$IMAGE" bash -c "$probe" || rc=1

# Host side after a session: links the session plants in the folders it can write must not make the host
# overwrite or import a host file (run-in-container.sh finish(), copy_back.py). Fake session, no model.
T="$(mktemp -d /tmp/devops-kit-bench-selftest-links.XXXXXX)"
trap 'rm -rf "$WORK" "$T"' EXIT
mkdir -p "$T/work" "$T/config" "$T/logs" "$T/host"
echo '{"claudeAiOauth":{"accessToken":"bench"}}' > "$T/config/.credentials.json"
echo "host secret" > "$T/host/secret"
echo "precious" > "$T/host/victim"
# shellcheck disable=SC2016  # expanded inside the container
BENCH_FAKE_SCRIPT='ln -sf '"$T/host/secret"' "$CLAUDE_CONFIG_DIR/.credentials.json"; ln -sf '"$T/host/victim"' '"$T/logs/proxy.log"'' \
  CLAUDE_BIN="$ISO_DIR/fake-claude.sh" "$ISO_DIR/run-in-container.sh" --work "$T/work" --config "$T/config" \
  --logs "$T/logs" --proxy-log "$T/proxy.log" -- >/dev/null 2>&1 || true
if grep -q bench "$T/config/.credentials.json" && ! grep -q "host secret" "$T/config/.credentials.json" \
  && [[ ! -L "$T/config/.credentials.json" && "$(cat "$T/host/victim")" == precious ]]; then
  echo "ok   planted links do not reach host files"
else
  echo "FAIL planted links do not reach host files"; rc=1
fi
exit $rc
