#!/usr/bin/env bash
# Install or update devops-ai-kit into the Claude Code user config dir (~/.claude).
# Usage: ./install.sh [--dry-run] [--no-settings] [--lang en|vi] [--env KUBECONFIG=~/.kube/ai-config]
set -euo pipefail
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/run-kit.sh" install "$@"
