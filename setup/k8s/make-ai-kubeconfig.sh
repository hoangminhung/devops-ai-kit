#!/usr/bin/env bash
# Build a dedicated kubeconfig for Claude Code sessions (devops-ai-kit).
#
#   --readonly CTX     add "<CTX>-ro": short-lived token of SA ai-access/claude-readonly
#                      (view + ai-cluster-reader, no Secrets). Repeatable.
#   --passthrough CTX  copy CTX unchanged from your normal kubeconfig, e.g. a dev
#                      cluster where the AI may apply after your confirmation. Repeatable.
#   --out FILE         output kubeconfig (default: ~/.kube/ai-config)
#   --duration DUR     token lifetime for read-only contexts (default: 24h; the API
#                      server may cap it, see --service-account-max-token-expiration)
#   --apply-rbac       apply ai-readonly-rbac.yaml to every --readonly context first
#
# Run it from a NORMAL shell with your admin credentials, not from a Claude session.
# Tokens expire: re-run the generated "<out>.refresh.sh" to renew them.
#
# Example:
#   ./make-ai-kubeconfig.sh --apply-rbac --readonly aks-prod-weu --readonly onprem-prod \
#                           --passthrough kind-dev --duration 12h
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RBAC_FILE="$SCRIPT_DIR/ai-readonly-rbac.yaml"
OUT="$HOME/.kube/ai-config"
DURATION="24h"
APPLY_RBAC=0
READONLY=()
PASSTHROUGH=()
ORIG_ARGS=("$@")

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [[ $# -gt 0 ]]; do
  case "$1" in
    --readonly)    READONLY+=("${2:?--readonly needs a context}"); shift 2 ;;
    --passthrough) PASSTHROUGH+=("${2:?--passthrough needs a context}"); shift 2 ;;
    --out)         OUT="${2:?--out needs a path}"; shift 2 ;;
    --duration)    DURATION="${2:?--duration needs a value}"; shift 2 ;;
    --apply-rbac)  APPLY_RBAC=1; shift ;;
    -h|--help)     usage 0 ;;
    *) echo "Unknown argument: $1" >&2; usage 1 ;;
  esac
done

[[ ${#READONLY[@]} -gt 0 || ${#PASSTHROUGH[@]} -gt 0 ]] || { echo "Nothing to do: give --readonly and/or --passthrough" >&2; exit 1; }
command -v kubectl >/dev/null || { echo "kubectl not found" >&2; exit 1; }

SRC_KUBECONFIG="${KUBECONFIG:-$HOME/.kube/config}"
OUT_ABS="$OUT"
if [[ -d "$(dirname "$OUT")" ]]; then OUT_ABS="$(cd "$(dirname "$OUT")" && pwd)/$(basename "$OUT")"; fi
case ":$SRC_KUBECONFIG:" in
  *":$OUT:"*|*":$OUT_ABS:"*)
    echo "Your KUBECONFIG points at the AI kubeconfig ($OUT). Run this from a normal shell with admin credentials." >&2
    exit 1 ;;
esac

src()  { KUBECONFIG="$SRC_KUBECONFIG" kubectl "$@"; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
NEW="$TMP/ai-config"
cat > "$NEW" << 'EOF'
apiVersion: v1
kind: Config
clusters: []
contexts: []
users: []
preferences: {}
EOF
new()  { KUBECONFIG="$NEW" kubectl "$@"; }

FIRST_CTX=""
i=0
for ctx in "${READONLY[@]}"; do
  i=$((i + 1))
  name="${ctx}-ro"
  echo "==> $ctx  →  $name (read-only)"
  src config get-contexts "$ctx" >/dev/null 2>&1 || { echo "   context '$ctx' not found in $SRC_KUBECONFIG" >&2; exit 1; }
  if [[ $APPLY_RBAC -eq 1 ]]; then
    echo "   applying RBAC (with your credentials)…"
    src --context "$ctx" apply -f "$RBAC_FILE" >/dev/null
  fi
  server="$(src config view --raw --minify --flatten --context "$ctx" -o jsonpath='{.clusters[0].cluster.server}')"
  ca="$(src config view --raw --minify --flatten --context "$ctx" -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
  token="$(src --context "$ctx" -n ai-access create token claude-readonly --duration "$DURATION")" || {
    echo "   could not create token — did you apply the RBAC (--apply-rbac)?" >&2; exit 1; }
  if [[ -n "$ca" ]]; then
    printf '%s' "$ca" | base64 -d > "$TMP/ca-$i.crt"
    new config set-cluster "$name" --server="$server" --certificate-authority="$TMP/ca-$i.crt" --embed-certs=true >/dev/null
  else
    echo "   WARN: no embedded CA data for $ctx; cluster entry uses the system trust store" >&2
    new config set-cluster "$name" --server="$server" >/dev/null
  fi
  new config set-credentials "$name" --token="$token" >/dev/null
  new config set-context "$name" --cluster="$name" --user="$name" >/dev/null
  FIRST_CTX="${FIRST_CTX:-$name}"
done

for ctx in "${PASSTHROUGH[@]}"; do
  i=$((i + 1))
  echo "==> $ctx  →  $ctx (passthrough, same permissions as your own kubeconfig)"
  src config view --raw --minify --flatten --context "$ctx" > "$TMP/pt-$i.yaml"
  KUBECONFIG="$NEW:$TMP/pt-$i.yaml" kubectl config view --raw --flatten > "$TMP/merged.yaml"
  mv "$TMP/merged.yaml" "$NEW"
  FIRST_CTX="${FIRST_CTX:-$ctx}"
done

new config use-context "$FIRST_CTX" >/dev/null

mkdir -p "$(dirname "$OUT")"
if [[ -f "$OUT" ]]; then
  cp -p "$OUT" "$OUT.bak.$(date +%Y%m%d-%H%M%S)"
fi
install -m 600 "$NEW" "$OUT"

# Refresh helper (same arguments, without --apply-rbac)
REFRESH="$OUT.refresh.sh"
{
  echo "#!/usr/bin/env bash"
  echo "# Re-generate $OUT with fresh tokens (created by make-ai-kubeconfig.sh)"
  printf 'exec %q' "$SCRIPT_DIR/make-ai-kubeconfig.sh"
  for a in "${ORIG_ARGS[@]}"; do [[ "$a" == "--apply-rbac" ]] || printf ' %q' "$a"; done
  echo
} > "$REFRESH"
chmod 700 "$REFRESH"

echo
echo "Written: $OUT  (current-context: $FIRST_CTX)"
echo "Refresh: $REFRESH   (tokens expire after $DURATION)"
echo
echo "Self-test of read-only contexts:"
for ctx in "${READONLY[@]}"; do
  name="${ctx}-ro"
  pods="$(KUBECONFIG="$OUT" kubectl --context "$name" auth can-i list pods -A 2>/dev/null || true)"
  secrets="$(KUBECONFIG="$OUT" kubectl --context "$name" auth can-i get secrets -A 2>/dev/null || true)"
  write="$(KUBECONFIG="$OUT" kubectl --context "$name" auth can-i create deployments -A 2>/dev/null || true)"
  printf '  %-30s list pods: %-4s get secrets: %-4s create deployments: %s\n' "$name" "${pods:-?}" "${secrets:-?}" "${write:-?}"
done
echo "  expected:                      list pods: yes  get secrets: no   create deployments: no"
echo
echo "Point Claude Code at it:  ./install.sh --env KUBECONFIG=$OUT   (from the devops-ai-kit folder)"
