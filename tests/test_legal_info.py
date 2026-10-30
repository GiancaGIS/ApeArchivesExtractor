# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from apearchivesextractor import legal_info


def test_license_sections_use_bundled_inventory_and_preserve_nested_notices(tmp_path, monkeypatch) -> None:
    legal = tmp_path / "legal"
    generated = legal / "generated"
    generated.mkdir(parents=True)
    (legal / "LICENSE.txt").write_text("fallback license")
    (generated / "LICENSE").write_text("bundled GPLv3")
    (generated / "NOTICE").write_text("bundled copyright")
    (generated / "THIRD_PARTY_NOTICES.md").write_text("third-party notices")
    (generated / "SOURCES.md").write_text("build instructions")
    (generated / "component-manifest.json").write_text(json.dumps({
        "application_version": "1.0.2", "python_version": "3.14.5",
        "components": [{"name": "PyQt6", "version": "6.11", "license": "GPL-3.0-only"}],
    }))
    (generated / "source-manifest.json").write_text(json.dumps({"sources": [{
        "name": "Qt", "version": "6.11", "filename": "qt.tar.xz",
        "url": "https://example.org/qt.tar.xz", "sha256": "abc123",
    }]}))
    qt = generated / "licenses/pyqt6"
    qt.mkdir(parents=True)
    (qt / "LICENSE").write_text("PyQt copyright and GPL terms")
    native = generated / "native/qtbase"
    native.mkdir(parents=True)
    (native / "MIT.txt").write_text("native copyright and MIT terms")
    (native / "ignored.pyc").write_bytes(b"\xff\x00")
    (native / "ignored.docx").write_bytes(b"\xff\x00")
    monkeypatch.setattr(legal_info, "files", lambda _name: tmp_path)

    sections = dict(legal_info.legal_sections())

    assert sections["legal.program"] == "bundled GPLv3"
    assert sections["legal.source_code"] == "build instructions"
    assert "PyQt copyright and GPL terms" in sections["Qt / PyQt6"]
    assert "native copyright and MIT terms" in sections["Qt / PyQt6"]
    assert "PyQt6 6.11" in sections["legal.versions"]
    assert "SHA-256: abc123" in sections["legal.source_archives"]
    assert "ignored" not in "\n".join(sections.values())
    assert "fallback license" not in sections.values()


def test_source_installation_includes_build_instructions() -> None:
    assert Path("SOURCES.md").read_bytes() == Path("src/apearchivesextractor/legal/SOURCES.md").read_bytes()
    sections = dict(legal_info.legal_sections())
    assert "GNU GENERAL PUBLIC LICENSE" in sections["legal.program"]
    assert "prepare_release_sources.py" in sections["legal.source_code"]


def test_license_dialog_lists_topics_and_switches_text_without_invalid_index() -> None:
    # Existing tests create QCoreApplication; a fresh process is needed for QWidget.
    code = """
from PyQt6.QtWidgets import QApplication
from apearchivesextractor.gui.licenses_dialog import LicensesDialog
app = QApplication([])
for language, label in [('it', 'Licenza del programma (GPLv3)'), ('en', 'Program license (GPLv3)')]:
    dialog = LicensesDialog(language)
    assert dialog.selector.item(0).text() == label
    assert dialog.viewer.isReadOnly()
    assert 'GNU GENERAL PUBLIC LICENSE' in dialog.viewer.toPlainText()
    dialog.selector.setCurrentRow(1)
    assert 'GiancaGIS' in dialog.viewer.toPlainText()
    dialog.selector.setCurrentRow(-1)
    assert dialog.viewer.toPlainText() == ''
    dialog.close()
"""
    result = subprocess.run([sys.executable, "-c", code], env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
