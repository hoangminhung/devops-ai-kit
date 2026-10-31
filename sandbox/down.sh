#!/usr/bin/env bash
# Delete the sandbox cluster and its kubeconfig files. Touches nothing else.
#   sandbox/down.sh         asks for confirmation
#   sandbox/down.sh --yes   no question
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="devops-kit-sandbox"

if [[ "${1:-}" != "--yes" ]]; then
  read -r -p "Delete kind cluster '$NAME' and sandbox/.kubeconfig, sandbox/.ai-kubeconfig*? [y/N] " answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Nothing deleted."; exit 0; }
fi
if kind get clusters 2>/dev/null | grep -qx "$NAME"; then
  kind delete cluster --name "$NAME"
fi
rm -f "$HERE/.kubeconfig" "$HERE/.ai-kubeconfig" "$HERE/.ai-kubeconfig.refresh.sh"
echo "Sandbox removed."
