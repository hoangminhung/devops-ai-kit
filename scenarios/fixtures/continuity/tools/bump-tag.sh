#!/usr/bin/env bash
# Change the image tag of one service in release/tags.yaml.
#   tools/bump-tag.sh <service> <tag> --inplace|--patch
set -euo pipefail
FILE="$(cd "$(dirname "$0")/.." && pwd)/release/tags.yaml"
svc="${1:-}" tag="${2:-}" mode="${3:-}"
[[ -n "$svc" && -n "$tag" ]] || { echo "usage: tools/bump-tag.sh <service> <tag> --inplace|--patch" >&2; exit 2; }
grep -q "^  $svc:\$" "$FILE" || { echo "error: unknown service '$svc'" >&2; exit 2; }
case "$mode" in
  --inplace)
    echo "error: --inplace rewrites the whole file and expands the YAML anchors (<<: *defaults)." >&2
    echo "The change was rolled back; nothing changed. Use --patch." >&2
    exit 3 ;;
  --patch)
    awk -v svc="  $svc:" -v tag="$tag" '
      /^  [a-z]+:$/ { inside = ($0 == svc) }
      inside && /^    tag:/ { $0 = "    tag: \"" tag "\"" }
      { print }' "$FILE" > "$FILE.tmp"
    mv "$FILE.tmp" "$FILE"
    echo "$svc: tag $tag" ;;
  *)
    echo "error: choose --inplace or --patch" >&2
    exit 2 ;;
esac
