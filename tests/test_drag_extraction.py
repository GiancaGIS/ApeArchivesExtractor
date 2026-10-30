# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import OperationCancelledError, UnsafeArchivePathError
from apearchivesextractor.gui.drag_extraction import prepare_drag_paths


@pytest.fixture(params=["zip", "tar.gz", "7z"])
def archive(tmp_path: Path, request) -> Path:
    path = tmp_path / ("selection." + request.param)
    files = {"left/report.txt": b"left", "right/report.txt": b"right",
             "folder/nested/child.txt": b"child", "unselected.txt": b"not selected"}
    if request.param == "zip":
        with zipfile.ZipFile(path, "w") as output:
            for name, contents in files.items():
                output.writestr(name, contents)
            output.writestr("empty/", b"")
    elif request.param == "tar.gz":
        with tarfile.open(path, "w:gz") as output:
            for name, contents in files.items():
                entry = tarfile.TarInfo(name)
                entry.size = len(contents)
                output.addfile(entry, io.BytesIO(contents))
            empty = tarfile.TarInfo("empty/")
            empty.type = tarfile.DIRTYPE
            output.addfile(empty)
    else:
        import py7zr

        empty = tmp_path / "empty"
        empty.mkdir()
        with py7zr.SevenZipFile(path, "w") as output:
            for name, contents in files.items():
                output.writestr(contents, name)
            output.write(empty, arcname="empty")
    return path


def test_drag_exports_files_with_distinct_names_without_changing_archive(archive, tmp_path) -> None:
    original = archive.read_bytes()
    paths = prepare_drag_paths(ArchiveService(), archive, tmp_path / "drag", ["left/report.txt", "right/report.txt"])
    assert [p.name for p in paths] == ["report.txt", "report (2).txt"]
    assert [p.read_bytes() for p in paths] == [b"left", b"right"]
    assert not (tmp_path / "drag/contents/unselected.txt").exists()
    assert archive.read_bytes() == original


def test_drag_exports_folders_and_collapses_selected_descendants(archive, tmp_path) -> None:
    paths = prepare_drag_paths(ArchiveService(), archive, tmp_path / "drag",
                              ["folder", "folder/nested/child.txt", "folder/", "empty/"])
    assert {p.name for p in paths} == {"folder", "empty"}
    folder = next(p for p in paths if p.name == "folder")
    assert (folder / "nested/child.txt").read_bytes() == b"child"
    assert list(next(p for p in paths if p.name == "empty").iterdir()) == []


def test_cancelled_drag_does_not_publish_partial_files(archive, tmp_path) -> None:
    calls = 0

    def cancel_before_export():
        nonlocal calls
        calls += 1
        return calls > 1

    with pytest.raises(OperationCancelledError):
        prepare_drag_paths(ArchiveService(), archive, tmp_path / "drag", ["left/report.txt"],
                           should_cancel=cancel_before_export)
    assert not list((tmp_path / "drag/files").glob("*"))


def test_drag_rejects_unsafe_member_before_extraction(tmp_path) -> None:
    class NoExtraction:
        def extract_members(self, *args, **kwargs):
            pytest.fail("Unsafe selection must not reach extraction")

    with pytest.raises(UnsafeArchivePathError):
        prepare_drag_paths(NoExtraction(), tmp_path / "any.zip", tmp_path / "drag", ["../outside.txt"])


def test_drag_qt_integration_exports_selected_urls_and_keeps_gui_responsive(tmp_path) -> None:
    # The full suite creates QCoreApplication, so run QWidget coverage separately.
    code = r'''
import shutil, sys, tempfile, zipfile
from pathlib import Path
from PySide6.QtCore import QEvent, QPointF, QSettings, QTimer, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox, QTreeWidget
from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.gui.main_window import MainWindow
from apearchivesextractor.gui import archive_tree
from apearchivesextractor.gui import settings as settings_module

root = Path(sys.argv[1])
settings_module.QSettings = lambda *_: QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
app = QApplication([])
window = MainWindow()
window.show()
path = root / 'selection.zip'
with zipfile.ZipFile(path, 'w') as output:
    output.writestr('a/report.txt', b'left')
    output.writestr('b/report.txt', b'right')
    output.writestr('not-selected.txt', b'other')
window.current_archive = path
window._current_entries = ArchiveService().list_entries(path)
window.archive_tree.populate(window._current_entries)
tree = window.archive_tree
tree.topLevelItem(0).child(0).setSelected(True)
tree.topLevelItem(1).child(0).setSelected(True)
assert len(tree.selected_members()) == 2
assert tree.dragDropMode() == QTreeWidget.DragDropMode.DragDrop

delivered = []
destination = root / 'drop-target'
destination.mkdir()
class DesktopDrag:
    def __init__(self, source):
        assert source is tree
    def setMimeData(self, mime):
        self.mime = mime
    def exec(self, actions, default):
        assert actions == default == Qt.DropAction.CopyAction
        assert self.mime.formats() == ['text/uri-list']
        for url in self.mime.urls():
            source = Path(url.toLocalFile())
            assert source.is_file()
            delivered.append(source)
            shutil.copy2(source, destination / source.name)
        return Qt.DropAction.CopyAction
    def deleteLater(self): pass
archive_tree.QDrag = DesktopDrag

ticks = []
timer = QTimer()
timer.timeout.connect(lambda: ticks.append(True))
timer.start(1)
app.processEvents()
position = tree.visualItemRect(tree.topLevelItem(0).child(0)).center()
QTest.mousePress(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
for distance in (30, 50):
    point = position + type(position)(distance, 0)
    event = QMouseEvent(QEvent.Type.MouseMove, QPointF(point), QPointF(tree.viewport().mapToGlobal(point)),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(tree.viewport(), event)
QTest.mouseRelease(tree.viewport(), Qt.MouseButton.LeftButton, pos=position)
timer.stop()
assert ticks, 'Preparation must process GUI events'
assert len(delivered) == 2
assert (destination / 'report.txt').read_bytes() == b'left'
assert (destination / 'report (2).txt').read_bytes() == b'right'
assert not window._busy and window._thread is None and not window._preparing_drag
assert tree.isEnabled()
assert all(p.exists() for p in delivered), 'Keep source files alive after the drop'

# Dragging back onto the source view must not modify the open archive/tree.
class OwnDrop:
    def source(self): return tree
    def ignore(self): self.ignored = True
event = OwnDrop()
tree.dragEnterEvent(event)
tree.dragMoveEvent(event)
tree.dropEvent(event)
assert event.ignored and window._drop_paths(event) == []

# Corrupt archives report an error without publishing partial paths or getting
# stuck in the nested event loop, and the failed temporary directory is removed.
errors = []
QMessageBox.critical = lambda *args: errors.append(args)
broken = root / 'broken.zip'
broken.write_bytes(b'not a ZIP')
window.current_archive = broken
retained = list(window._drag_extract_dirs)
assert window._prepare_selected_file_drag() == []
assert errors and window._drag_extract_dirs == retained
assert not window._busy and window._thread is None

# Empty selection does not allocate a staging area or start a drag.
tree.clearSelection()
assert window._prepare_selected_file_drag() == []
tree.startDrag(Qt.DropAction.CopyAction)
assert len(delivered) == 2
window.close()
app.processEvents()
assert all(not p.exists() for p in delivered)
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
