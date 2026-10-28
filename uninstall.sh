#!/usr/bin/env bash
# Remove everything devops-ai-kit installed (files + settings.json additions).
# Usage: ./uninstall.sh [--dry-run]
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run-kit.sh" uninstall "$@"
