#!/usr/bin/env bash
set -euo pipefail
# Run from the project root on macOS.
cd "$(dirname "$0")/../.."
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e ".[package]"
python build_tools/branding/build_icons.py
python -m PyInstaller --noconfirm --clean build_tools/common/ApeArchivesExtractor.spec
echo "Build locale completata. Output: dist/ApeArchivesExtractor.app"
echo "Prima di distribuire: python build_tools/common/prepare_release_sources.py --bundle dist/ApeArchivesExtractor.app"
echo "Segui docs/BUILDING.md e verifica con build_tools/common/check_release.py --bundle dist/ApeArchivesExtractor.app"
