#!/usr/bin/env bash
# Run ONE `claude -p` call (or one harness command) inside a locked-down container.
#
#   run-in-container.sh --work DIR --config DIR --logs DIR -- <claude args>   (prompt on stdin)
#   run-in-container.sh --work DIR --exec -- <command ...>                    (harness step, no Claude)
#
# Claude runs in the default permission mode (no --permission-mode flag; the kit sets no defaultMode), and every permission prompt goes to an approve-all
# prompt tool (approver.py): a person who says yes to everything. Deny rules and hook denials still
# stop a call; ask rules, hook asks and critical-path rm prompts are approved and logged in
# <logs>/approvals.jsonl. Both benchmark arms run the same way (RFC 0002 §10).
#
# What the container can reach (nothing else):
#   - the work copy DIR (read-write, same absolute path as on the host);
#   - a THROW-AWAY copy of the Claude config dir (same absolute path, so the kit hook path still works);
#   - the logs folder (approvals), which is NOT the run folder: canaries.json is never mounted;
#   - the claude binary (read-only);
#   - the network only through the allow-list proxy (common.sh ALLOW_HOSTS, port 443); no DNS.
# No ~/.kube, cloud credentials, SSH agent or Docker socket; non-root, no capabilities, read-only root fs.
# After the call (also on error or Ctrl-C), a refreshed OAuth credential in the copy is written back to
# the config dir so the bench login keeps working; nothing is printed. stdout = claude's stream-json.
set -euo pipefail
# shellcheck source=scenarios/isolation/common.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/common.sh"

WORK="" CONFIG="" LOGS="" EXEC=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --work) WORK="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --logs) LOGS="$2"; shift 2 ;;
    --exec) EXEC=1; shift ;;
    --) shift; break ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[[ -d "$WORK" ]] || { echo "--work must be a folder" >&2; exit 2; }
WORK="$(cd "$WORK" && pwd -P)"
case "$WORK" in /tmp/*|/var/tmp/*) ;; *) echo "the work copy must be under /tmp (got $WORK)" >&2; exit 2 ;; esac
if [[ $EXEC == 0 ]]; then
  [[ -d "$CONFIG" && -d "$LOGS" ]] || { echo "--config and --logs must be folders" >&2; exit 2; }
  CONFIG="$(cd "$CONFIG" && pwd -P)"
  LOGS="$(cd "$LOGS" && pwd -P)"
  [[ "$LOGS" != "$(dirname "$WORK")" && ! -e "$LOGS/canaries.json" ]] \
    || { echo "--logs must not be the run folder (it holds canaries.json)" >&2; exit 2; }
fi
for real in "$HOME/.claude" "$HOME/.kube" "$HOME/.ssh" "$HOME"; do
  [[ -e "$real" ]] || continue
  real="$(cd "$real" && pwd -P)"
  for mounted in "$WORK" "$CONFIG" "$LOGS"; do
    [[ -z "$mounted" || "$mounted" != "$real" ]] || { echo "refusing to mount $real" >&2; exit 2; }
  done
done

command -v docker >/dev/null || { echo "docker is needed for --isolation container" >&2; exit 1; }
ensure_image
ensure_network
base_run_args

if [[ $EXEC == 1 ]]; then
  exec docker run "${RUN_ARGS[@]}" -v "$WORK:$WORK" -w "$WORK" "$IMAGE" "$@"
fi

BIN="$(claude_binary)"
COPY="$(mktemp -d /tmp/devops-kit-bench-config.XXXXXX)"
since="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
finish() {
  if [[ -f "$COPY/.credentials.json" ]] && ! cmp -s "$COPY/.credentials.json" "$CONFIG/.credentials.json"; then
    install -m 600 "$COPY/.credentials.json" "$CONFIG/.credentials.json.tmp" \
      && mv "$CONFIG/.credentials.json.tmp" "$CONFIG/.credentials.json"
  fi
  docker logs --since "$since" "$PROXY" 2>&1 | grep -E '^(ALLOW|DENY|FAIL) ' > "$LOGS/proxy.log" || true
  rm -rf "$COPY"
}
trap finish EXIT
# The copy skips history and caches: only what a session needs to start (login, settings, kit files).
tar -C "$CONFIG" --exclude=./projects --exclude=./file-history --exclude=./shell-snapshots \
  --exclude=./history.jsonl --exclude=./backups --exclude=./.devops-kit-backup --exclude=./cache \
  --exclude=./session-env --exclude=./sessions -cf - . | tar -C "$COPY" -xf -
: > "$LOGS/approvals.jsonl"

MCP="{\"mcpServers\":{\"bench\":{\"command\":\"python3\",\"args\":[\"/opt/approver.py\"],\"env\":{\"APPROVER_LOG\":\"$LOGS/approvals.jsonl\"}}}}"
fake=()
[[ -z "${BENCH_FAKE_SCRIPT:-}" ]] || fake=(-e BENCH_FAKE_SCRIPT)  # selftest only (fake-claude.sh)
rc=0
docker run "${RUN_ARGS[@]}" "${fake[@]}" \
  -v "$BIN:/usr/local/bin/claude:ro" \
  -v "$WORK:$WORK" -w "$WORK" \
  -v "$COPY:$CONFIG" -e CLAUDE_CONFIG_DIR="$CONFIG" \
  -v "$LOGS:$LOGS" \
  "$IMAGE" claude -p --permission-prompts host \
  --mcp-config "$MCP" --permission-prompt-tool mcp__bench__approve "$@" || rc=$?
exit "$rc"
