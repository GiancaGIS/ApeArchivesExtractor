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
echo "Build locale completata. Output: dist/ApeArchivesExtractor.app"
echo "Prima di distribuire: python scripts/prepare_release_sources.py --bundle dist/ApeArchivesExtractor.app"
echo "Segui RELEASE_CHECKLIST.md e verifica con scripts/check_release.py --bundle dist/ApeArchivesExtractor.app"
