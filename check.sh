#!/usr/bin/env bash
# Show install status, hook registration, AI kubeconfig and which gate tools are available.
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run-kit.sh" check "$@"
