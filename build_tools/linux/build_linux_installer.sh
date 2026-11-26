#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python="${PYTHON:-python3}"
if [[ "${1:-}" == "--python" ]]; then
    python="${2:?Pass a Python executable after --python}"
    shift 2
fi
exec "$python" "$root/build_tools/common/build.py" "$@"
