#!/usr/bin/env bash
# Run scripts/kit.py with the first working Python >= 3.8 (python3, python, or the Windows `py -3` launcher).
set -euo pipefail
KIT_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/kit.py"
for candidate in "python3" "python" "py -3"; do
  # shellcheck disable=SC2086  # word splitting of "py -3" is intended
  if command -v ${candidate%% *} >/dev/null 2>&1 \
     && $candidate -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $candidate "$KIT_PY" "$@"
  fi
done
echo "Python 3.8+ not found. Linux: sudo apt install python3 · Windows: winget install Python.Python.3.12" >&2
exit 1
