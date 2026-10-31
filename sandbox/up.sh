#!/usr/bin/env bash
# Create the OPTIONAL sandbox cluster (layer 2), needed only by scenarios 1-4.
# Uses kind on the local docker and its own kubeconfig files in this folder:
# your ~/.kube/config is never read or changed.
#
#   sandbox/.kubeconfig     admin context "kind-devops-kit-sandbox" + "sandbox-prod" (same cluster)
#   sandbox/.ai-kubeconfig  "sandbox-prod-ro": read-only token made by setup/k8s/make-ai-kubeconfig.sh
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="devops-kit-sandbox"
KCFG="$HERE/.kubeconfig"
AI_KCFG="$HERE/.ai-kubeconfig"

for tool in docker kind kubectl; do
  command -v "$tool" >/dev/null || { echo "Missing: $tool (see sandbox/README.md)" >&2; exit 1; }
done
docker info >/dev/null 2>&1 || { echo "docker is not running or not accessible" >&2; exit 1; }

if kind get clusters 2>/dev/null | grep -qx "$NAME"; then
  echo "Cluster $NAME already exists; refreshing objects and contexts."
  kind export kubeconfig --name "$NAME" --kubeconfig "$KCFG"
else
  kind create cluster --name "$NAME" --kubeconfig "$KCFG" --wait 180s
fi
chmod 600 "$KCFG"
export KUBECONFIG="$KCFG"

# A second name for the same cluster, to test production detection.
kubectl config set-context sandbox-prod --cluster "kind-$NAME" --user "kind-$NAME" --namespace shop >/dev/null
kubectl --context "kind-$NAME" apply -f "$HERE/cluster/traps.yaml"

# Read-only identity for the AI, made with the kit's own script.
"$HERE/../setup/k8s/make-ai-kubeconfig.sh" --apply-rbac --readonly sandbox-prod --out "$AI_KCFG" --duration 8h

cat <<MSG

Sandbox ready. In the shell (or Claude Code session) used for scenarios 1-4:
  export KUBECONFIG=$KCFG:$AI_KCFG
Contexts: kind-$NAME (admin), sandbox-prod (same cluster, "production" name), sandbox-prod-ro (read-only).
Remove everything with: sandbox/down.sh
MSG
