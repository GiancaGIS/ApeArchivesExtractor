#!/usr/bin/env bash
set -euo pipefail
# Run from the project root on macOS.
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[package]"
python scripts/build_icons.py
python -m PyInstaller --noconfirm --clean packaging/ApeArchivesExtractor.spec
echo "Build completata. Output: dist/ApeArchivesExtractor.app"
