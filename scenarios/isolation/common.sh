# Shared parts of run-in-container.sh and selftest.sh. Sourced, not run.
# shellcheck shell=bash

ISO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NET="devops-kit-bench-net"
PROXY="devops-kit-bench-proxy"
# Hosts the container may reach (port 443 only): the Claude API and the OAuth token refresh.
ALLOW_HOSTS="${BENCH_ALLOW_HOSTS:-api.anthropic.com console.anthropic.com platform.claude.com}"

image_tag() {
  local sum
  sum="$(cat "$ISO_DIR/Dockerfile" "$ISO_DIR/mirror.tf" "$ISO_DIR/terraformrc" "$ISO_DIR/egress_proxy.py" "$ISO_DIR/approver.py" \
    | sha256sum | cut -c1-12)"
  echo "devops-kit-bench:$sum"
}

ensure_image() {
  IMAGE="$(image_tag)"
  if ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "building $IMAGE (once)" >&2
    docker build -q -t "$IMAGE" "$ISO_DIR" >&2
  fi
}

# An --internal network (no route out) plus a proxy container that is on it AND on the default bridge.
ensure_network() {
  docker network inspect "$NET" >/dev/null 2>&1 || docker network create --internal "$NET" >/dev/null
  local running want
  running="$(docker inspect -f '{{.State.Running}} {{.Config.Image}} {{join .Args " "}}' "$PROXY" 2>/dev/null || true)"
  want="true $IMAGE --port 3128 --allow $ALLOW_HOSTS"
  if [[ "$running" != "$want"* ]]; then
    docker rm -f "$PROXY" >/dev/null 2>&1 || true
    docker run -d --name "$PROXY" --network bridge --read-only --cap-drop ALL \
      --security-opt no-new-privileges --user 65534:65534 --memory 256m \
      --entrypoint python3 "$IMAGE" /opt/egress_proxy.py --port 3128 --allow $ALLOW_HOSTS >/dev/null
    docker network connect "$NET" "$PROXY"
  fi
}

# docker run options shared by every benchmark container (the caller adds mounts and the command).
base_run_args() {
  # shellcheck disable=SC2034  # used by the scripts that source this file
  RUN_ARGS=(--rm -i --network "$NET"
    --user "$(id -u):$(id -g)"
    --read-only --tmpfs "/tmp:rw,exec,mode=1777" --tmpfs "/home/bench:rw,exec,uid=$(id -u),gid=$(id -g),mode=700"
    --cap-drop ALL --security-opt no-new-privileges --pids-limit 512 --memory 4g --cpus 2
    -e HOME=/home/bench -e USER=bench
    -e HTTPS_PROXY="http://$PROXY:3128" -e https_proxy="http://$PROXY:3128"
    -e HTTP_PROXY="http://$PROXY:3128" -e http_proxy="http://$PROXY:3128" -e NO_PROXY= -e no_proxy=
    -e DEVOPS_KIT_BENCH_IN_CONTAINER=1)
  # A bench container must never start without its egress proxy in front of it.
  docker inspect -f '{{.State.Running}}' "$PROXY" 2>/dev/null | grep -qx true \
    || { echo "egress proxy $PROXY is not running" >&2; return 1; }
}

claude_binary() {
  local bin="${CLAUDE_BIN:-$(command -v claude || true)}"
  [[ -n "$bin" ]] || { echo "claude not found: set CLAUDE_BIN" >&2; return 1; }
  readlink -f "$bin"
}
