# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("archive_format", ["zip", "7z"])
def test_explorer_drop_adds_files_and_reloads_on_gui_thread(tmp_path: Path, archive_format: str) -> None:
    # Exercise real Qt delivery and workers in a process with its own QApplication.
    # A contextless result lambda used to run UI updates on the archive thread.
    code = r'''
import faulthandler, sys, time
from pathlib import Path
from PySide6.QtCore import QMimeData, QPoint, QPointF, QSettings, QThread, QUrl, Qt
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.gui import settings as settings_module
from apearchivesextractor.gui.main_window import MainWindow

faulthandler.enable()
if sys.platform == 'win32':
    import ctypes
    # Native failures should terminate the subprocess rather than show WER UI.
    ctypes.windll.kernel32.SetErrorMode(0x8003)
    ctypes.CDLL('ucrtbase')._set_abort_behavior(0, 3)
root, archive_format = Path(sys.argv[1]), sys.argv[2]
settings_module.QSettings = lambda *_: QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
app = QApplication([])
wrong_threads, results, callbacks, errors = [], [], [], []
QMessageBox.critical = lambda *args: errors.append((QThread.currentThread() == app.thread(), args))

class ObservedWindow(MainWindow):
    def _start_worker(self, operation, *args, on_result=None, **kwargs):
        def observe(result):
            if QThread.currentThread() != app.thread():
                wrong_threads.append(operation)
                return  # Fail safely before the callback touches widgets.
            results.append(result)
            if on_result is not None:
                on_result(result)
        super()._start_worker(operation, *args, on_result=observe, **kwargs)

    def _populate_entries(self, result):
        callbacks.append(QThread.currentThread() == app.thread())
        super()._populate_entries(result)

def idle(expect_error=False):
    deadline = time.monotonic() + 10
    while window._busy and time.monotonic() < deadline:
        QTest.qWait(10)
    assert not window._busy and window._thread is None, 'Worker did not finish'
    assert not wrong_threads, wrong_threads
    assert bool(errors) == expect_error, errors
    assert all(on_gui for on_gui, _ in errors), errors
    errors.clear()

def drop(target, path, expect_error=False):
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile(str(path))])
    enter = QDragEnterEvent(QPoint(20, 20), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, enter)
    assert enter.isAccepted(), 'Local Explorer drag should be accepted'
    event = QDropEvent(QPointF(20, 20), Qt.DropAction.CopyAction, mime,
                       Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(target, event)
    assert event.isAccepted(), 'Local Explorer drop should be accepted'
    idle(expect_error)

window = ObservedWindow()
window.show()
original = root / 'original.txt'
original.write_bytes(b'original contents')
archive = root / ('archive.' + archive_format)
service = ArchiveService()
service.create(archive, [original], archive_format=archive_format)

# Drop an archive onto the window to open it asynchronously.
drop(window, archive)
assert window.current_archive == archive
assert [entry.path for entry in window._current_entries] == ['original.txt'], (window._current_entries, results, callbacks)

# Drop plain files from Explorer onto both the tree and the surrounding window.
for index, target in enumerate((window.archive_tree.viewport(), window, window.archive_tree.viewport())):
    added = root / ('incoming-' + str(index) + '.txt')
    added.write_bytes(('file ' + str(index)).encode())
    drop(target, added)
    assert added.read_bytes() == ('file ' + str(index)).encode(), 'Source file must be preserved'
    assert {entry.path for entry in window._current_entries} == {'original.txt'} | {
        'incoming-' + str(i) + '.txt' for i in range(index + 1)
    }
    assert window.archive_tree.isEnabled() and not window._preparing_drag

output = root / 'extracted'
service.extract_all(archive, output)
assert (output / original.name).read_bytes() == original.read_bytes()
for index in range(3):
    assert (output / ('incoming-' + str(index) + '.txt')).read_bytes() == ('file ' + str(index)).encode()
assert len(results) == 7, 'Opening + three additions and their automatic reloads'
assert len(callbacks) == 4 and all(callbacks), callbacks
window.close()

# Failed worker delivery must also stay on the GUI thread and allow recovery.
window = ObservedWindow()
window.show()
broken = root / 'broken.zip'
broken.write_bytes(b'not an archive')
drop(window, broken, expect_error=True)
window.load_archive(archive)
idle()
assert len(window._current_entries) == 4
window.close()
app.processEvents()
'''
    result = subprocess.run(
        [sys.executable, "-X", "faulthandler", "-c", code, str(tmp_path), archive_format],
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
        capture_output=True, text=True, timeout=50,
    )
    assert result.returncode == 0, result.stdout + result.stderr
