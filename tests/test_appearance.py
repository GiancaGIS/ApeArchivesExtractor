# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


def test_open_windows_follow_light_dark_palette_changes(tmp_path: Path) -> None:
    # Isolate QApplication and preferences from the main QCoreApplication suite.
    code = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication
from apearchivesextractor.gui import settings as settings_module
from apearchivesextractor.gui.main_window import MainWindow
from apearchivesextractor.gui.create_dialog import CreateArchiveDialog
from apearchivesextractor.gui.licenses_dialog import LicensesDialog
from apearchivesextractor.models import ArchiveEntry

root = Path(sys.argv[1])
settings_module.QSettings = lambda *_: QSettings(str(root/'settings.ini'), QSettings.Format.IniFormat)
app = QApplication([])
app.setStyle('Fusion')
if sys.platform == 'win32':
    for font in ('segoeui.ttf', 'segoeuib.ttf', 'seguisb.ttf', 'seguiemj.ttf'):
        QFontDatabase.addApplicationFont('C:/Windows/Fonts/' + font)
    app.setFont(QFont('Segoe UI', 10))
role = QPalette.ColorRole

def palette(dark):
    result = QPalette(app.style().standardPalette())
    colors = {
        role.Window: '#242424' if dark else '#f3f3f3',
        role.WindowText: '#eeeeee' if dark else '#171717',
        role.Base: '#191919' if dark else '#ffffff',
        role.AlternateBase: '#292929' if dark else '#f1f4f8',
        role.Text: '#eeeeee' if dark else '#171717',
        role.Button: '#333333' if dark else '#f8f8f8',
        role.ButtonText: '#eeeeee' if dark else '#171717',
        role.Mid: '#686868' if dark else '#b8b8b8',
        role.Midlight: '#484848' if dark else '#e1e1e1',
        role.Light: '#535353' if dark else '#ffffff',
        role.Dark: '#141414' if dark else '#888888',
        role.Shadow: '#080808' if dark else '#555555',
        role.Highlight: '#1f4e8c' if dark else '#2463b8',
        role.HighlightedText: '#ffffff',
        role.PlaceholderText: '#b5b5b5' if dark else '#5a5a5a',
        role.ToolTipBase: '#333333' if dark else '#ffffe1',
        role.ToolTipText: '#eeeeee' if dark else '#171717',
    }
    for key, value in colors.items():
        result.setColor(key, QColor(value))
    for key in (role.Text, role.WindowText, role.ButtonText):
        result.setColor(QPalette.ColorGroup.Disabled, key, QColor('#888888'))
    return result

def luminance(color):
    channels = (color.redF(), color.greenF(), color.blueF())
    linear = [c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4 for c in channels]
    return sum(c*w for c, w in zip(linear, (0.2126, 0.7152, 0.0722)))

def contrast(a, b):
    values = sorted((luminance(a), luminance(b)))
    return (values[1]+0.05)/(values[0]+0.05)

app.setPalette(palette(False))
window = MainWindow()
window._set_language('en')
window.resize(1180, 650)
window.current_archive = root/'example.zip'
window.archive_edit.setText('example.zip')
window._populate_entries([
    ArchiveEntry('documents/readme.txt', 1024, 512, False),
    ArchiveEntry('documents/notes.txt', 2048, 640, False),
])
window.archive_tree.expandAll()
item = window.archive_tree.findItems('readme.txt', Qt.MatchFlag.MatchExactly | Qt.MatchFlag.MatchRecursive, 0)[0]
item.setSelected(True)
window.password_edit.setText('kept-password')
window.progress.setValue(60)
create = CreateArchiveDialog(window, language='en')
create.output_edit.setText('backup.7z')
create.format_combo.setCurrentText('7z')
licenses = LicensesDialog('en', window)
licenses.selector.setCurrentRow(1)
window.show()
create.show()
licenses.show()

for name, dark in [('light', False), ('dark', True), ('light-again', False)]:
    app.setPalette(palette(dark))
    app.processEvents()
    toast = window._update_toast
    toast.show_message('Update available', 'Version 1.0.4 is ready to download.',
                       url='https://github.com/GiancaGIS/ApeArchivesExtractor/releases', action='View release')
    app.processEvents()
    pairs = [
        (window.archive_edit, role.Text, role.Base),
        (window.password_edit, role.Text, role.Base),
        (window.filter_edit, role.PlaceholderText, role.Base),
        (window.archive_label, role.WindowText, role.Window),
        (window.open_btn, role.ButtonText, role.Button),
        (window.archive_tree, role.Text, role.Base),
        (window.archive_tree, role.HighlightedText, role.Highlight),
        (create.output_edit, role.Text, role.Base),
        (create.format_combo, role.ButtonText, role.Button),
        (licenses.viewer, role.Text, role.Base),
        (licenses.selector, role.Text, role.Base),
        (toast.title, role.WindowText, role.Window),
        (toast.dismiss_button, role.WindowText, role.Window),
    ]
    for widget, foreground, background in pairs:
        p = widget.palette()
        backdrop = p.color(background)
        parent = widget.parentWidget()
        while backdrop.alpha() == 0 and parent is not None:
            backdrop = parent.palette().color(role.Window)
            parent = parent.parentWidget()
        ratio = contrast(p.color(foreground), backdrop)
        assert ratio >= 4.5, (name, widget.metaObject().className(), widget.objectName(),
                              p.color(foreground).name(), backdrop.name(), ratio)
    # Inspect actual rendered pixels; palette values alone miss white QSS fills.
    for widget in (window.archive_edit, licenses.viewer, create.output_edit):
        image = widget.grab().toImage()
        # Stay clear of the native clear-button/scrollbar hit area.
        color = image.pixelColor(image.width()-50, image.height()//2)
        assert (luminance(color) < 0.15) == dark, (name, widget, color.name())
    image = toast.grab().toImage()
    color = image.pixelColor(12, image.height()//2)
    assert (luminance(color) < 0.15) == dark, (name, 'toast background', color.name())
    assert window._selected_members() == ['documents/readme.txt']
    assert window.password_edit.text() == 'kept-password'
    assert create.output_edit.text() == 'backup.7z'
    assert licenses.selector.currentRow() == 1
    assert window.progress.value() == 60
    window.grab().save(str(root/(name+'-main.png')))
    create.grab().save(str(root/(name+'-create.png')))
    licenses.grab().save(str(root/(name+'-licenses.png')))
    toast.hide()

licenses.close()
create.close()
window.close()
app.processEvents()
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Native Windows Qt theme")
def test_windows_style_follows_the_application_color_scheme(tmp_path: Path) -> None:
    code = r'''
import sys
from pathlib import Path
from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory
from apearchivesextractor.gui import settings as settings_module
from apearchivesextractor.gui.main_window import MainWindow

root = Path(sys.argv[1])
settings_module.QSettings = lambda *_: QSettings(str(root/'settings.ini'), QSettings.Format.IniFormat)
app = QApplication([])
if not hasattr(app.styleHints(), 'setColorScheme'):
    sys.exit(77)  # Programmatic theme requests were introduced in Qt 6.8.
assert 'windows11' in [name.lower() for name in QStyleFactory.keys()]
app.setStyle('windows11')
window = MainWindow()
window.ensurePolished()
window.layout().activate()

# Override this application's theme only. Do not modify Windows preferences or
# show windows on the user's desktop. Capture the real Windows style offscreen.
for scheme in (Qt.ColorScheme.Dark, Qt.ColorScheme.Light, Qt.ColorScheme.Dark):
    app.styleHints().setColorScheme(scheme)
    app.processEvents()
    app.processEvents()
    assert app.styleHints().colorScheme() == scheme
    dark = scheme == Qt.ColorScheme.Dark
    assert (app.palette().color(QPalette.ColorRole.Window).lightness() < 128) == dark
    image = window.archive_edit.grab().toImage()
    color = image.pixelColor(image.width()-20, image.height()//2)
    assert (color.lightness() < 128) == dark, (scheme, color.name())
window.close()
app.processEvents()
'''
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        env={**os.environ, "QT_QPA_PLATFORM": "windows"},
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 77:
        pytest.skip("Programmatic color scheme requests need Qt 6.8+")
    assert result.returncode == 0, result.stdout + result.stderr
