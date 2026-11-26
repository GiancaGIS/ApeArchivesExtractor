#!/usr/bin/env bash
set -euo pipefail
exec bash "$(dirname "$0")/../build_tools/macos/build_macos_app.sh" "$@"
