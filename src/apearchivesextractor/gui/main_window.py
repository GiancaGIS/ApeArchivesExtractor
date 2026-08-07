from __future__ import annotations

import shutil
import tempfile
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable

from PyQt6.QtCore import QPoint, Qt, QThread
from PyQt6.QtGui import QAction, QActionGroup, QCloseEvent, QDragEnterEvent, QDropEvent, QFont, QIcon, QKeySequence
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QDialog,
    QFileDialog,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import UnsafeArchivePathError
from apearchivesextractor.gui.archive_tree import ArchiveTreeWidget
from apearchivesextractor.gui.create_dialog import CreateArchiveDialog
from apearchivesextractor.gui.extraction_planner import existing_output_paths
from apearchivesextractor.gui.i18n import LANGUAGE_NAMES, SUPPORTED_LANGUAGES, translate
from apearchivesextractor.gui.settings import AppSettings
from apearchivesextractor.gui.workers import ArchiveWorker
from apearchivesextractor.models import ArchiveEntry, ArchiveFormat
from apearchivesextractor.security import normalize_archive_name
from apearchivesextractor.spanned import detect_archive_format, is_spanned_archive


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = AppSettings()
        self._language = self.settings.language()
        self.setWindowTitle("ApeArchivesExtractor")
        self.resize(1180, 760)
        self.setAcceptDrops(True)
        self._set_window_icon()

        self.current_archive: Path | None = None
        self._forced_archive_format: ArchiveFormat | None = None
        self._current_entries: list[ArchiveEntry] = []
        self._thread: QThread | None = None
        self._worker: ArchiveWorker | None = None
        self._busy = False
        self._reload_after_finish: Path | None = None
        self._recent_menu: QMenu | None = None
        self._confirm_overwrite_action: QAction | None = None
        self._drag_extract_dirs: list[Path] = []

        self.archive_edit = QLineEdit()
        self.archive_edit.setClearButtonEnabled(True)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setMaximumWidth(260)
        self.password_edit.setClearButtonEnabled(True)

        self.show_password_check = QCheckBox()
        self.show_password_check.toggled.connect(self._toggle_password_visibility)

        self.filter_edit = QLineEdit()
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._apply_filter)

        self.open_btn = QPushButton()
        self.open_btn.clicked.connect(self.open_archive_dialog)

        self.reload_btn = QPushButton()
        self.reload_btn.clicked.connect(self.reload_archive)

        self.extract_all_btn = QToolButton()
        self.extract_all_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.extract_all_btn.clicked.connect(self.extract_all)
        self.extract_all_btn.setEnabled(False)
        self.extract_all_menu = QMenu(self.extract_all_btn)
        self.extract_all_choose_action = QAction(self)
        self.extract_all_choose_action.triggered.connect(self.extract_all)
        self.extract_all_here_action = QAction(self)
        self.extract_all_here_action.triggered.connect(self.extract_all_here)
        self.extract_all_menu.addAction(self.extract_all_choose_action)
        self.extract_all_menu.addAction(self.extract_all_here_action)
        self.extract_all_btn.setMenu(self.extract_all_menu)

        self.extract_selected_btn = QToolButton()
        self.extract_selected_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.extract_selected_btn.clicked.connect(self.extract_selected)
        self.extract_selected_btn.setEnabled(False)
        self.extract_selected_menu = QMenu(self.extract_selected_btn)
        self.extract_selected_choose_action = QAction(self)
        self.extract_selected_choose_action.triggered.connect(self.extract_selected)
        self.extract_selected_here_action = QAction(self)
        self.extract_selected_here_action.triggered.connect(self.extract_selected_here)
        self.extract_selected_menu.addAction(self.extract_selected_choose_action)
        self.extract_selected_menu.addAction(self.extract_selected_here_action)
        self.extract_selected_btn.setMenu(self.extract_selected_menu)

        self.delete_selected_btn = QPushButton()
        self.delete_selected_btn.clicked.connect(self.delete_selected)
        self.delete_selected_btn.setEnabled(False)

        self.cancel_btn = QPushButton()
        self.cancel_btn.clicked.connect(self.cancel_operation)
        self.cancel_btn.setEnabled(False)

        self.create_btn = QPushButton()
        self.create_btn.clicked.connect(self.open_create_dialog)

        self.archive_label = QLabel()
        top_row = QHBoxLayout()
        top_row.addWidget(self.archive_label)
        top_row.addWidget(self.archive_edit, 1)
        top_row.addWidget(self.open_btn)
        top_row.addWidget(self.reload_btn)

        self.password_label = QLabel()
        self.filter_label = QLabel()
        second_row = QHBoxLayout()
        second_row.addWidget(self.password_label)
        second_row.addWidget(self.password_edit)
        second_row.addWidget(self.show_password_check)
        second_row.addWidget(self.filter_label)
        second_row.addWidget(self.filter_edit, 1)

        actions_row = QHBoxLayout()
        actions_row.addWidget(self.create_btn)
        actions_row.addStretch(1)
        actions_row.addWidget(self.extract_all_btn)
        actions_row.addWidget(self.extract_selected_btn)
        actions_row.addWidget(self.delete_selected_btn)
        actions_row.addWidget(self.cancel_btn)

        self.archive_tree = ArchiveTreeWidget()
        self.archive_tree.set_language(self._language)
        self.archive_tree.set_drag_handlers(self._prepare_selected_file_drag, self._handle_external_file_drop)
        self.archive_tree.itemSelectionChanged.connect(self._selection_changed)
        self.archive_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.archive_tree.customContextMenuRequested.connect(self._show_archive_context_menu)

        self.summary_label = QLabel()
        self.selection_label = QLabel()
        self.selection_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.selection_label.setMaximumWidth(460)
        info_row = QHBoxLayout()
        info_row.addWidget(self.summary_label, 1)
        info_row.addWidget(self.selection_label)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(140)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.archive_tree)
        splitter.addWidget(self.log)
        splitter.setStretchFactor(0, 5)
        splitter.setStretchFactor(1, 1)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(top_row)
        layout.addLayout(second_row)
        layout.addLayout(actions_row)
        layout.addLayout(info_row)
        layout.addWidget(splitter, 1)
        layout.addWidget(self.progress)
        self.setCentralWidget(central)
        self._apply_style()

        self._retranslate_ui()
        self._create_menu()
        self._restore_window_state()
        self.statusBar().showMessage(self._tr("app.ready"))

    def _tr(self, key: str, **kwargs: object) -> str:
        return translate(self._language, key, **kwargs)

    def _create_menu(self) -> None:
        self.menuBar().clear()
        file_menu = self.menuBar().addMenu(self._tr("menu.file"))

        open_action = QAction(self._tr("menu.open"), self)
        open_action.setShortcut(QKeySequence.StandardKey.Open)
        open_action.triggered.connect(self.open_archive_dialog)
        file_menu.addAction(open_action)

        self._recent_menu = file_menu.addMenu(self._tr("menu.recent"))
        self._refresh_recent_archives_menu()

        create_action = QAction(self._tr("menu.create"), self)
        create_action.setShortcut(QKeySequence.StandardKey.New)
        create_action.triggered.connect(self.open_create_dialog)
        file_menu.addAction(create_action)

        file_menu.addSeparator()
        exit_action = QAction(self._tr("menu.exit"), self)
        exit_action.setShortcut(QKeySequence.StandardKey.Quit)
        exit_action.triggered.connect(QApplication.instance().quit)  # type: ignore[union-attr]
        file_menu.addAction(exit_action)

        archive_menu = self.menuBar().addMenu(self._tr("menu.archive"))

        extract_all_action = QAction(self._tr("menu.extract_all"), self)
        extract_all_action.setShortcut("Ctrl+E")
        extract_all_action.triggered.connect(self.extract_all)
        archive_menu.addAction(extract_all_action)

        extract_here_action = QAction(self._tr("menu.extract_here"), self)
        extract_here_action.setShortcut("Ctrl+Shift+E")
        extract_here_action.triggered.connect(self.extract_all_here)
        archive_menu.addAction(extract_here_action)

        extract_selected_action = QAction(self._tr("menu.extract_selected"), self)
        extract_selected_action.setShortcut("Ctrl+Alt+E")
        extract_selected_action.triggered.connect(self.extract_selected)
        archive_menu.addAction(extract_selected_action)

        extract_selected_here_action = QAction(self._tr("menu.extract_selected_here"), self)
        extract_selected_here_action.setShortcut("Ctrl+Alt+Shift+E")
        extract_selected_here_action.triggered.connect(self.extract_selected_here)
        archive_menu.addAction(extract_selected_here_action)

        delete_selected_action = QAction(self._tr("menu.delete_selected"), self)
        delete_selected_action.setShortcut(QKeySequence.StandardKey.Delete)
        delete_selected_action.triggered.connect(self.delete_selected)
        archive_menu.addAction(delete_selected_action)

        archive_menu.addSeparator()
        cancel_action = QAction(self._tr("menu.cancel_operation"), self)
        cancel_action.setShortcut(QKeySequence.StandardKey.Cancel)
        cancel_action.triggered.connect(self.cancel_operation)
        archive_menu.addAction(cancel_action)

        options_menu = self.menuBar().addMenu(self._tr("menu.options"))
        clear_log_action = QAction(self._tr("menu.clear_log"), self)
        clear_log_action.triggered.connect(self.log.clear)
        options_menu.addAction(clear_log_action)

        self._confirm_overwrite_action = QAction(self._tr("menu.confirm_overwrite"), self)
        self._confirm_overwrite_action.setCheckable(True)
        self._confirm_overwrite_action.setChecked(self.settings.confirm_overwrite())
        self._confirm_overwrite_action.toggled.connect(self.settings.set_confirm_overwrite)
        options_menu.addAction(self._confirm_overwrite_action)

        language_menu = options_menu.addMenu(self._tr("menu.language"))
        language_group = QActionGroup(self)
        language_group.setExclusive(True)
        for language in SUPPORTED_LANGUAGES:
            action = QAction(LANGUAGE_NAMES[language], self)
            action.setCheckable(True)
            action.setChecked(language == self._language)
            action.triggered.connect(lambda checked=False, value=language: self._set_language(value))
            language_group.addAction(action)
            language_menu.addAction(action)

    def _set_language(self, language: str) -> None:
        if language == self._language:
            return
        self._language = language
        self.settings.set_language(language)
        self._retranslate_ui()
        self._create_menu()
        self.statusBar().showMessage(self._tr("app.ready"))

    def _retranslate_ui(self) -> None:
        self.archive_label.setText(self._tr("archive.label"))
        self.archive_edit.setPlaceholderText(self._tr("archive.placeholder"))
        self.password_label.setText(self._tr("password.label"))
        self.password_edit.setPlaceholderText(self._tr("password.placeholder"))
        self.show_password_check.setText(self._tr("show_password"))
        self.filter_label.setText(self._tr("filter.label"))
        self.filter_edit.setPlaceholderText(self._tr("filter.placeholder"))
        self.open_btn.setText(self._tr("button.open"))
        self.reload_btn.setText(self._tr("button.reload"))
        self.extract_all_btn.setText(self._tr("button.extract_all"))
        self.extract_all_choose_action.setText(self._tr("action.extract_choose_folder"))
        self.extract_all_here_action.setText(self._tr("action.extract_here"))
        self.extract_selected_btn.setText(self._tr("button.extract_selected"))
        self.extract_selected_choose_action.setText(self._tr("action.extract_selected_choose_folder"))
        self.extract_selected_here_action.setText(self._tr("action.extract_selected_here"))
        self.delete_selected_btn.setText(self._tr("button.delete"))
        self.cancel_btn.setText(self._tr("button.cancel"))
        self.create_btn.setText(self._tr("button.create"))
        self.log.setPlaceholderText(self._tr("log.placeholder"))
        self.archive_tree.set_language(self._language)
        if self._current_entries:
            self.archive_tree.populate(self._current_entries)
        self._configure_buttons()
        self._update_summary_label()
        self._selection_changed()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt naming
        paths = self._drop_paths(event)
        if not self._busy and (self._can_add_external_file(paths) or self._drop_contains_supported_archive(paths)):
            event.acceptProposedAction()
            return
        event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt naming
        paths = self._drop_paths(event)
        if not paths or self._busy:
            event.ignore()
            return

        if self._handle_external_file_drop(paths):
            event.acceptProposedAction()
            return

        for path in paths:
            if self._is_supported_archive(path):
                self.load_archive(path)
                event.acceptProposedAction()
                return
        event.ignore()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 - Qt naming
        self.settings.save_geometry(self.saveGeometry())
        self._cleanup_drag_extract_dirs()
        super().closeEvent(event)

    def open_archive_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            self._tr("dialog.open.title"),
            str(self.settings.last_open_dir()),
            self._tr("dialog.open.filter"),
        )
        if path:
            archive_path = Path(path)
            self.settings.set_last_open_dir(archive_path.parent)
            self.load_archive(archive_path)

    def reload_archive(self) -> None:
        text = self.archive_edit.text().strip()
        if not text:
            return
        self.load_archive(Path(text))

    def load_archive(self, path: Path, forced_format: ArchiveFormat | None = None) -> None:
        if self._busy:
            return
        if forced_format is None and not self._is_supported_archive(path):
            QMessageBox.warning(self, self._tr("warning.unsupported.title"), self._tr("warning.unsupported.body"))
            return
        if not path.exists():
            QMessageBox.warning(self, self._tr("warning.not_found.title"), self._tr("warning.not_found.body", path=path))
            return

        self.current_archive = path
        self._forced_archive_format = forced_format
        self._current_entries = []
        self.archive_edit.setText(str(path))
        self.filter_edit.clear()
        self.archive_tree.clear()
        self.extract_all_btn.setEnabled(False)
        self.extract_selected_btn.setEnabled(False)
        self.delete_selected_btn.setEnabled(False)
        self.summary_label.setText(self._tr("load.summary"))
        self.selection_label.setText(self._tr("selection.none"))
        forced_label = self._tr("load.as_format", format=forced_format.value.upper()) if forced_format else ""
        self._log(self._tr("load.log", forced=forced_label, path=path))
        self._start_worker(
            "list",
            path,
            password=self._password(),
            archive_format=forced_format.value if forced_format else None,
            on_result=self._populate_entries,
            success_message=self._tr("load.success"),
        )

    def load_archive_as_zip(self, path: Path) -> None:
        self.load_archive(path, forced_format=ArchiveFormat.ZIP)

    def extract_all(self) -> None:
        if self.current_archive is None or self._busy:
            return
        output_dir = self._ask_output_dir()
        if output_dir is None:
            return
        if not self._confirm_overwrite_conflicts(output_dir, members=None):
            return
        self._start_extract_all(output_dir, self._tr("extract.success"))

    def extract_all_here(self) -> None:
        if self.current_archive is None or self._busy:
            return
        output_dir = self.current_archive.parent
        if not self._confirm_overwrite_conflicts(output_dir, members=None):
            return
        self._start_extract_all(output_dir, self._tr("extract_here.success"))

    def extract_selected(self) -> None:
        if self.current_archive is None or self._busy:
            return
        members = self._selected_members()
        if not members:
            QMessageBox.information(
                self,
                self._tr("warning.no_selection.title"),
                self._tr("warning.no_selection.extract"),
            )
            return
        output_dir = self._ask_output_dir()
        if output_dir is None:
            return
        flat_files = self._selected_file_members(members)
        if not self._confirm_overwrite_conflicts(
            output_dir,
            members=members,
            flatten_files=flat_files is not None,
        ):
            return
        if flat_files is not None:
            success = self._tr("extract_file.success") if len(flat_files) == 1 else self._tr("extract_files.success")
            self._start_extract_flat_files(output_dir, flat_files, success)
        else:
            self._start_extract_members(output_dir, members, self._tr("extract_selected.success"))

    def extract_selected_here(self) -> None:
        if self.current_archive is None or self._busy:
            return
        members = self._selected_members()
        if not members:
            return
        output_dir = self.current_archive.parent
        flat_files = self._selected_file_members(members)
        if not self._confirm_overwrite_conflicts(
            output_dir,
            members=members,
            flatten_files=flat_files is not None,
        ):
            return
        if flat_files is not None:
            success = (
                self._tr("extract_file_here.success")
                if len(flat_files) == 1
                else self._tr("extract_files_here.success")
            )
            self._start_extract_flat_files(output_dir, flat_files, success)
        else:
            self._start_extract_members(output_dir, members, self._tr("extract_selected_here.success"))

    def delete_selected(self) -> None:
        if self.current_archive is None or self._busy:
            return
        if self._effective_archive_format() != ArchiveFormat.ZIP or is_spanned_archive(self.current_archive):
            QMessageBox.information(
                self,
                self._tr("delete.unavailable.title"),
                self._tr("delete.unavailable.body"),
            )
            return

        members = self._selected_members()
        if not members:
            QMessageBox.information(
                self,
                self._tr("warning.no_selection.title"),
                self._tr("warning.no_selection.delete"),
            )
            return

        max_preview = 10
        preview = "\n".join(members[:max_preview])
        if len(members) > max_preview:
            preview += "\n" + self._tr("delete.preview.more", count=len(members) - max_preview)

        answer = QMessageBox.question(
            self,
            self._tr("delete.confirm.title"),
            self._tr("delete.confirm.body", count=len(members), preview=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        self._log(self._tr("delete.log", count=len(members), path=self.current_archive))
        self._start_worker(
            "delete_members",
            self.current_archive,
            members,
            password=self._password(),
            archive_format=ArchiveFormat.ZIP.value,
            success_message=self._tr("delete.success"),
            on_result=lambda _: self._schedule_reload(self.current_archive),  # type: ignore[arg-type]
        )

    def open_create_dialog(self, initial_inputs: Iterable[Path] | None = None) -> None:
        if self._busy:
            return
        dialog = CreateArchiveDialog(
            self,
            initial_output_dir=self.settings.last_create_dir(),
            initial_input_dir=self.settings.last_input_dir(),
            initial_inputs=list(initial_inputs) if initial_inputs is not None else None,
            language=self._language,
        )
        if dialog.exec() != CreateArchiveDialog.DialogCode.Accepted:
            return
        self.settings.set_last_create_dir(dialog.last_used_output_dir)
        self.settings.set_last_input_dir(dialog.last_used_input_dir)
        output_path = dialog.output_path
        input_paths = dialog.input_paths
        delete_originals = dialog.delete_originals
        self._log(self._tr("create.log", path=output_path))
        if delete_originals:
            self._log(self._tr("create.delete_originals.log", count=len(input_paths)))
        self._start_worker(
            "create",
            output_path,
            input_paths,
            archive_format=dialog.archive_format,
            password=dialog.password,
            compression_level=dialog.compression_level,
            volume_size=dialog.volume_size,
            delete_originals=delete_originals,
            success_message=self._tr("create.success"),
            on_result=lambda result: self._handle_create_success(result, output_path, delete_originals),
        )

    def _handle_create_success(self, result: object, output_path: Path, delete_originals: bool) -> None:
        created_path = result.get("archive_path") if isinstance(result, dict) else None
        self._schedule_reload(created_path if isinstance(created_path, Path) else output_path)
        if not delete_originals:
            return

        deleted_count = 0
        if isinstance(result, dict):
            error = result.get("delete_originals_error")
            if error is not None:
                self._log(str(error))
                QMessageBox.warning(
                    self,
                    self._tr("create.delete_originals.error_title"),
                    self._tr("create.delete_originals.error_body", error=error),
                )
                return

            deleted = result.get("deleted_originals")
            if isinstance(deleted, list):
                deleted_count = len(deleted)
        else:
            QMessageBox.warning(
                self,
                self._tr("create.delete_originals.error_title"),
                self._tr("create.delete_originals.error_body", error="Unexpected worker result."),
            )
            return

        self._log(self._tr("create.delete_originals.success", count=deleted_count))

    def _handle_external_file_drop(self, paths: list[Path]) -> bool:
        if not self._can_add_external_file(paths):
            return False
        self._add_file_to_current_archive(paths[0])
        return True

    def _can_add_external_file(self, paths: list[Path]) -> bool:
        if self._busy or self.current_archive is None:
            return False
        if is_spanned_archive(self.current_archive):
            return False
        if self._effective_archive_format() not in (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_Z):
            return False
        if len(paths) != 1:
            return False
        path = paths[0]
        if not path.is_file():
            return False
        return path.resolve(strict=False) != self.current_archive.resolve(strict=False)

    def _add_file_to_current_archive(self, input_path: Path) -> None:
        if self.current_archive is None or self._busy:
            return
        archive_format = self._effective_archive_format()
        if (
            archive_format not in (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_Z)
            or is_spanned_archive(self.current_archive)
        ):
            QMessageBox.information(self, self._tr("add.unavailable.title"), self._tr("add.unavailable.body"))
            return
        if not input_path.is_file():
            QMessageBox.information(self, self._tr("add.invalid.title"), self._tr("add.invalid.body"))
            return

        self._log(self._tr("add.log", file=input_path, archive=self.current_archive))
        self._start_worker(
            "add_files",
            self.current_archive,
            [input_path],
            password=self._password(),
            archive_format=archive_format.value,
            success_message=self._tr("add.success"),
            on_result=lambda _: self._schedule_reload(self.current_archive),  # type: ignore[arg-type]
        )

    def _prepare_selected_file_drag(self) -> list[Path]:
        if self.current_archive is None or self._busy:
            return []
        members = self._selected_members()
        file_members = self._selected_file_members(members)
        if file_members is None:
            self.statusBar().showMessage(self._tr("drag.files_only"))
            return []

        temp_dir = Path(tempfile.mkdtemp(prefix="apearchivesextractor_drag_"))
        try:
            ArchiveService().extract_members_flat(
                self.current_archive,
                temp_dir,
                file_members,
                password=self._password(),
                archive_format=self._forced_archive_format.value if self._forced_archive_format else None,
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            QMessageBox.critical(self, self._tr("worker.error_title"), str(exc))
            return []

        self._drag_extract_dirs.append(temp_dir)
        extracted_paths = [temp_dir / PurePosixPath(member).name for member in file_members]
        self._log(self._tr("drag.extract.log", count=len(extracted_paths)))
        return [path for path in extracted_paths if path.exists()]

    def cancel_operation(self) -> None:
        if self._worker is None or not self._busy:
            return
        self._worker.cancel()
        self.cancel_btn.setEnabled(False)
        self.statusBar().showMessage(self._tr("cancel.requested"))
        self._log(self._tr("cancel.log"))

    def extract_archive_here_from_shell(self, archive_path: Path) -> None:
        if self._busy:
            return
        if not self._is_supported_archive(archive_path):
            QMessageBox.warning(self, self._tr("warning.unsupported.title"), self._tr("warning.unsupported.body"))
            return
        if not archive_path.exists():
            QMessageBox.warning(
                self,
                self._tr("warning.not_found.title"),
                self._tr("warning.not_found.body", path=archive_path),
            )
            return

        self.current_archive = archive_path
        self._forced_archive_format = None
        self._current_entries = []
        self.archive_edit.setText(str(archive_path))
        self.filter_edit.clear()
        self.archive_tree.clear()
        self.summary_label.setText(self._tr("extract.shell.summary", name=archive_path.name))
        self.selection_label.setText(self._tr("extract.shell.selection"))
        self._start_extract_all(archive_path.parent, self._tr("extract_here.success"))

    def _start_extract_all(self, output_dir: Path, success_message: str) -> None:
        if self.current_archive is None:
            return
        self._log(self._tr("extract.log.all", output_dir=output_dir))
        self._start_worker(
            "extract_all",
            self.current_archive,
            output_dir,
            password=self._password(),
            archive_format=self._forced_archive_format.value if self._forced_archive_format else None,
            success_message=success_message,
        )

    def _start_extract_members(self, output_dir: Path, members: list[str], success_message: str) -> None:
        if self.current_archive is None:
            return
        self._log(self._tr("extract.log.selected", count=len(members), output_dir=output_dir))
        self._start_worker(
            "extract_members",
            self.current_archive,
            output_dir,
            members,
            password=self._password(),
            archive_format=self._forced_archive_format.value if self._forced_archive_format else None,
            success_message=success_message,
        )

    def _start_extract_single_file(self, output_dir: Path, member: str, success_message: str) -> None:
        if self.current_archive is None:
            return
        self._log(self._tr("extract.log.file", member=member, output_dir=output_dir))
        self._start_worker(
            "extract_single_file",
            self.current_archive,
            output_dir,
            member,
            password=self._password(),
            archive_format=self._forced_archive_format.value if self._forced_archive_format else None,
            success_message=success_message,
        )

    def _start_extract_flat_files(self, output_dir: Path, members: list[str], success_message: str) -> None:
        if self.current_archive is None:
            return
        if len(members) == 1:
            self._log(self._tr("extract.log.file", member=members[0], output_dir=output_dir))
        else:
            self._log(self._tr("extract.log.files_flat", count=len(members), output_dir=output_dir))
        self._start_worker(
            "extract_flat_files",
            self.current_archive,
            output_dir,
            members,
            password=self._password(),
            archive_format=self._forced_archive_format.value if self._forced_archive_format else None,
            success_message=success_message,
        )

    def calculate_selected_hashes(self) -> None:
        if self.current_archive is None or self._busy:
            return
        archive_format = self._effective_archive_format()
        if archive_format not in (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_Z, ArchiveFormat.RAR):
            QMessageBox.information(self, self._tr("hash.unavailable.title"), self._tr("hash.unavailable.body"))
            return

        member = self._single_selected_file_member(self._selected_members())
        if member is None:
            QMessageBox.information(self, self._tr("hash.invalid.title"), self._tr("hash.invalid.body"))
            return

        self._log(self._tr("hash.log", member=member))
        self._start_worker(
            "calculate_hashes",
            self.current_archive,
            member,
            password=self._password(),
            archive_format=archive_format.value,
            success_message=self._tr("hash.success"),
            on_result=self._show_hash_result,
        )

    def _show_archive_context_menu(self, position: QPoint) -> None:
        if self.current_archive is None or self._busy:
            return
        item = self.archive_tree.itemAt(position)
        if item is None:
            return
        if not item.isSelected():
            self.archive_tree.clearSelection()
            item.setSelected(True)
            self.archive_tree.setCurrentItem(item)

        menu = QMenu(self)

        extract_action = menu.addAction(self._tr("menu.extract_selected"))
        extract_action.triggered.connect(self.extract_selected)

        extract_here_action = menu.addAction(self._tr("menu.extract_selected_here"))
        extract_here_action.triggered.connect(self.extract_selected_here)

        delete_action = menu.addAction(self._tr("menu.delete_selected"))
        delete_action.setEnabled(
            self._effective_archive_format() == ArchiveFormat.ZIP
            and not is_spanned_archive(self.current_archive)
        )
        delete_action.triggered.connect(self.delete_selected)

        menu.addSeparator()
        hash_action = menu.addAction(self._tr("context.hashes"))
        hash_action.setEnabled(
            self._effective_archive_format() in (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_Z, ArchiveFormat.RAR)
            and self._single_selected_file_member(self._selected_members()) is not None
        )
        hash_action.triggered.connect(self.calculate_selected_hashes)

        menu.addSeparator()
        copy_path_action = menu.addAction(self._tr("context.copy_path"))
        copy_path_action.triggered.connect(self._copy_selected_path)

        expand_action = menu.addAction(self._tr("context.expand"))
        expand_action.triggered.connect(lambda: item.setExpanded(True))

        collapse_action = menu.addAction(self._tr("context.collapse"))
        collapse_action.triggered.connect(lambda: item.setExpanded(False))

        menu.exec(self.archive_tree.viewport().mapToGlobal(position))

    def _ask_output_dir(self) -> Path | None:
        start = self.settings.last_extract_dir()
        if self.current_archive and not start.exists():
            start = self.current_archive.parent
        folder = QFileDialog.getExistingDirectory(self, self._tr("dialog.output.title"), str(start))
        if not folder:
            return None
        output_dir = Path(folder)
        self.settings.set_last_extract_dir(output_dir)
        return output_dir

    def _populate_entries(self, result: object) -> None:
        entries = result if isinstance(result, list) else []
        self._current_entries = entries  # type: ignore[assignment]
        self.archive_tree.populate(entries)  # type: ignore[arg-type]
        self.extract_all_btn.setEnabled(bool(entries))
        self._update_summary_label()
        self._selection_changed()

        if self.current_archive is not None:
            self.settings.add_recent_archive(self.current_archive)
            self.settings.set_last_open_dir(self.current_archive.parent)
            self._refresh_recent_archives_menu()

        self.statusBar().showMessage(self._tr("loaded.count", count=len(entries)))

    def _selected_members(self) -> list[str]:
        return self.archive_tree.selected_members()

    def _selection_changed(self) -> None:
        members = self._selected_members()
        has_selection = bool(members)
        self.extract_selected_btn.setEnabled(has_selection and self.current_archive is not None and not self._busy)
        self.delete_selected_btn.setEnabled(
            has_selection
            and self.current_archive is not None
            and not self._busy
            and self._effective_archive_format() == ArchiveFormat.ZIP
            and not is_spanned_archive(self.current_archive)
        )
        if not has_selection:
            self.selection_label.setText(self._tr("selection.none"))
            self.selection_label.setToolTip("")
        elif len(members) == 1:
            self.selection_label.setText(
                self._elide_label_text(self._tr("selection.one", member=members[0]), self.selection_label)
            )
            self.selection_label.setToolTip(members[0])
        else:
            self.selection_label.setText(self._tr("selection.many", count=len(members)))
            self.selection_label.setToolTip("\n".join(members[:20]))

    def _apply_filter(self, text: str) -> None:
        self.archive_tree.apply_filter(text)

    def _toggle_password_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)

    def _copy_selected_path(self) -> None:
        path = self.archive_tree.selected_display_path()
        if not path:
            return
        clipboard = QApplication.clipboard()
        clipboard.setText(path)
        self.statusBar().showMessage(self._tr("copy_path.status", path=path))

    def _show_hash_result(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        member = result.get("member")
        hashes = result.get("hashes")
        if not isinstance(member, str) or not isinstance(hashes, dict):
            return

        order = {"MD5": 0, "SHA1": 1, "SHA256": 2}
        hash_items = sorted(
            ((str(name), str(value)) for name, value in hashes.items()),
            key=lambda item: order.get(item[0], len(order)),
        )
        lines = [f"{name}: {value}" for name, value in hash_items]
        details = "\n".join(lines)
        self._log(self._tr("hash.result.log", member=member, hashes=details))

        dialog = QDialog(self)
        dialog.setWindowTitle(self._tr("hash.result.title"))
        dialog.resize(760, 310)

        layout = QVBoxLayout(dialog)
        member_label = QLabel(self._tr("hash.result.body", member=member))
        member_label.setWordWrap(True)
        member_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(member_label)

        table = QTableWidget(len(hash_items), 2, dialog)
        table.setHorizontalHeaderLabels([self._tr("hash.column.algorithm"), self._tr("hash.column.value")])
        table.verticalHeader().setVisible(False)
        table.setAlternatingRowColors(True)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)

        hash_font = QFont("Consolas")
        hash_font.setStyleHint(QFont.StyleHint.Monospace)
        for row, (algorithm, value) in enumerate(hash_items):
            algorithm_item = QTableWidgetItem(algorithm)
            value_item = QTableWidgetItem(value)
            value_item.setFont(hash_font)
            table.setItem(row, 0, algorithm_item)
            table.setItem(row, 1, value_item)

        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.resizeRowsToContents()
        layout.addWidget(table, 1)

        hint = QLabel(self._tr("hash.result.copy_hint"))
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        copy_sha256_btn = QPushButton(self._tr("hash.copy_sha256"))
        copy_all_btn = QPushButton(self._tr("hash.copy_all"))
        close_btn = QPushButton(self._tr("button.close"))
        close_btn.setDefault(True)

        sha256_value = dict(hash_items).get("SHA256", "")
        copy_sha256_btn.setEnabled(bool(sha256_value))
        copy_sha256_btn.clicked.connect(lambda: self._copy_text_to_clipboard(sha256_value, self._tr("hash.sha256_copied")))
        copy_all_btn.clicked.connect(lambda: self._copy_text_to_clipboard(details, self._tr("hash.all_copied")))
        close_btn.clicked.connect(dialog.accept)

        buttons.addWidget(copy_sha256_btn)
        buttons.addWidget(copy_all_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        dialog.exec()

    def _copy_text_to_clipboard(self, text: str, status_message: str) -> None:
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage(status_message)

    def _password(self) -> str | None:
        value = self.password_edit.text()
        return value if value else None

    def _schedule_reload(self, archive_path: Path) -> None:
        self._reload_after_finish = archive_path

    def _confirm_overwrite_conflicts(
        self,
        output_dir: Path,
        members: list[str] | None,
        flatten_single_file: bool = False,
        flatten_files: bool = False,
    ) -> bool:
        if not self.settings.confirm_overwrite():
            return True
        if not self._current_entries:
            return True

        try:
            conflicts = existing_output_paths(
                self._current_entries,
                output_dir,
                members,
                flatten_single_file=flatten_single_file,
                flatten_files=flatten_files,
            )
        except UnsafeArchivePathError as exc:
            QMessageBox.critical(self, self._tr("unsafe_archive.title"), str(exc))
            return False

        if not conflicts:
            return True

        max_preview = 8
        preview = "\n".join(str(path) for path in conflicts[:max_preview])
        if len(conflicts) > max_preview:
            preview += "\n" + self._tr("overwrite.more", count=len(conflicts) - max_preview)

        answer = QMessageBox.question(
            self,
            self._tr("overwrite.title"),
            self._tr("overwrite.body", count=len(conflicts), preview=preview),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _single_selected_file_member(self, members: list[str]) -> str | None:
        if len(members) != 1:
            return None
        selected = normalize_archive_name(members[0])
        for entry in self._current_entries:
            if entry.is_dir:
                continue
            if normalize_archive_name(entry.path).rstrip("/") == selected:
                return selected
        return None

    def _selected_file_members(self, members: list[str]) -> list[str] | None:
        if not members:
            return None

        file_members = {
            normalize_archive_name(entry.path).rstrip("/")
            for entry in self._current_entries
            if not entry.is_dir
        }
        selected = [normalize_archive_name(member) for member in members]
        if any(member not in file_members for member in selected):
            return None
        return selected

    def _refresh_recent_archives_menu(self) -> None:
        if self._recent_menu is None:
            return
        self._recent_menu.clear()

        recent_archives = self.settings.recent_archives()
        existing_archives = [path for path in recent_archives if path.exists()]

        if not existing_archives:
            empty_action = QAction(self._tr("menu.recent_empty"), self)
            empty_action.setEnabled(False)
            self._recent_menu.addAction(empty_action)
            return

        for archive_path in existing_archives:
            action = QAction(str(archive_path), self)
            action.triggered.connect(lambda checked=False, p=archive_path: self.load_archive(p))
            self._recent_menu.addAction(action)

        self._recent_menu.addSeparator()
        clear_action = QAction(self._tr("menu.recent_clear"), self)
        clear_action.triggered.connect(self._clear_recent_archives)
        self._recent_menu.addAction(clear_action)

    def _clear_recent_archives(self) -> None:
        self.settings.clear_recent_archives()
        self._refresh_recent_archives_menu()
        self.statusBar().showMessage(self._tr("recent.cleared"))

    def _restore_window_state(self) -> None:
        geometry = self.settings.restore_geometry()
        if geometry is not None:
            self.restoreGeometry(geometry)

    def _start_worker(
        self,
        operation: str,
        *args,
        on_result: Callable[[object], None] | None = None,
        success_message: str | None = None,
        **kwargs,
    ) -> None:
        if self._busy:
            return

        self._busy = True
        self.progress.setRange(0, 0)
        self.progress.setValue(0)
        self._set_controls_enabled(False)

        self._thread = QThread(self)
        self._worker = ArchiveWorker(operation, *args, **kwargs)
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self._on_progress)
        final_success_message = success_message or self._tr("worker.default_success")
        self._worker.result.connect(lambda result: self._on_worker_result(result, on_result, final_success_message))
        self._worker.cancelled.connect(self._on_worker_cancelled)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def _on_progress(self, message: str, current_item: str, processed: int, total: int) -> None:
        if total > 0 and processed >= 0:
            percent = min(100, int((processed / total) * 100))
            self.progress.setRange(0, 100)
            self.progress.setValue(percent)
            progress_text = f"{percent}% - {self._format_size(processed)} / {self._format_size(total)}"
        else:
            self.progress.setRange(0, 0)
            progress_text = ""
        if current_item:
            details = f"{message}: {current_item}"
        else:
            details = message
        self.statusBar().showMessage(f"{progress_text} - {details}" if progress_text else details)

    def _on_worker_result(
        self,
        result: object,
        on_result: Callable[[object], None] | None,
        success_message: str,
    ) -> None:
        if on_result is not None:
            on_result(result)
        self._log(success_message)
        self.statusBar().showMessage(success_message)
        self.progress.setRange(0, 100)
        self.progress.setValue(100)

    def _on_worker_cancelled(self) -> None:
        self._log(self._tr("worker.cancelled"))
        self.statusBar().showMessage(self._tr("worker.cancelled"))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)

    def _on_worker_error(self, message: str, detail: str) -> None:
        self._log(self._tr("worker.error_log", message=message))
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        QMessageBox.critical(
            self,
            self._tr("worker.error_title"),
            self._tr("worker.error_body", message=message, detail=detail),
        )

    def _on_thread_finished(self) -> None:
        if self._thread is not None:
            self._thread.deleteLater()
        self._thread = None
        self._worker = None
        self._busy = False
        self._set_controls_enabled(True)
        self._selection_changed()

        reload_path = self._reload_after_finish
        self._reload_after_finish = None
        if reload_path is not None:
            self.load_archive(reload_path)

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.open_btn.setEnabled(enabled)
        self.reload_btn.setEnabled(enabled)
        self.create_btn.setEnabled(enabled)
        self.archive_edit.setEnabled(enabled)
        self.password_edit.setEnabled(enabled)
        self.show_password_check.setEnabled(enabled)
        self.filter_edit.setEnabled(enabled)
        self.archive_tree.setEnabled(enabled)
        self.cancel_btn.setEnabled(not enabled and self._busy)
        has_entries = self.archive_tree.topLevelItemCount() > 0
        self.extract_all_btn.setEnabled(enabled and self.current_archive is not None and has_entries)
        self.extract_selected_btn.setEnabled(enabled and bool(self._selected_members()))
        self.delete_selected_btn.setEnabled(
            enabled
            and bool(self._selected_members())
            and self.current_archive is not None
            and self._effective_archive_format() == ArchiveFormat.ZIP
            and not is_spanned_archive(self.current_archive)
        )

    def _log(self, message: str) -> None:
        self.log.append(message)

    def _configure_buttons(self) -> None:
        style = self.style()
        button_specs = [
            (self.open_btn, QStyle.StandardPixmap.SP_DialogOpenButton, self._tr("tooltip.open")),
            (self.reload_btn, QStyle.StandardPixmap.SP_BrowserReload, self._tr("tooltip.reload")),
            (self.create_btn, QStyle.StandardPixmap.SP_FileDialogNewFolder, self._tr("tooltip.create")),
            (self.extract_all_btn, QStyle.StandardPixmap.SP_DialogSaveButton, self._tr("tooltip.extract_all")),
            (
                self.extract_selected_btn,
                QStyle.StandardPixmap.SP_DialogApplyButton,
                self._tr("tooltip.extract_selected"),
            ),
            (
                self.delete_selected_btn,
                QStyle.StandardPixmap.SP_TrashIcon,
                self._tr("tooltip.delete"),
            ),
            (self.cancel_btn, QStyle.StandardPixmap.SP_DialogCancelButton, self._tr("tooltip.cancel")),
        ]
        for button, pixmap, tooltip in button_specs:
            button.setIcon(style.standardIcon(pixmap))
            button.setToolTip(tooltip)
            button.setMinimumHeight(32)
            if isinstance(button, QToolButton):
                button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

    def _update_summary_label(self) -> None:
        if self.current_archive is None:
            self.summary_label.setText(self._tr("summary.none"))
            return

        files = sum(1 for entry in self._current_entries if not entry.is_dir)
        folders = sum(1 for entry in self._current_entries if entry.is_dir)
        total_size = sum(entry.size or 0 for entry in self._current_entries if not entry.is_dir)
        self.summary_label.setText(
            self._tr(
                "summary.loaded",
                name=self.current_archive.name,
                files=files,
                folders=folders,
                size=self._format_size(total_size),
            )
        )

    def _apply_style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow {
                background: #f6f7f9;
            }
            QLineEdit, QTextEdit, QTreeWidget {
                background: #ffffff;
                border: 1px solid #cfd5dd;
                border-radius: 4px;
                padding: 5px;
            }
            QPushButton, QToolButton {
                padding: 6px 10px;
                border: 1px solid #b9c1cc;
                border-radius: 4px;
                background: #ffffff;
            }
            QPushButton:hover, QToolButton:hover {
                background: #eef3f8;
            }
            QPushButton:disabled, QToolButton:disabled {
                color: #8a93a0;
                background: #eef0f3;
            }
            QLabel {
                color: #26313f;
            }
            QProgressBar {
                border: 1px solid #c7ced8;
                border-radius: 4px;
                text-align: center;
                background: #ffffff;
            }
            QProgressBar::chunk {
                background: #2f6fed;
                border-radius: 3px;
            }
            """
        )

    def _set_window_icon(self) -> None:
        assets_dir = Path(__file__).resolve().parents[1] / "assets"
        for icon_name in ("apearchivesextractor_app.ico", "apearchivesextractor_icon.svg"):
            icon_path = assets_dir / icon_name
            if icon_path.exists():
                self.setWindowIcon(QIcon(str(icon_path)))
                break

    @staticmethod
    def _format_size(value: int) -> str:
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{value} B"

    @staticmethod
    def _elide_label_text(text: str, label: QLabel) -> str:
        width = label.maximumWidth() if label.maximumWidth() > 0 else 420
        return label.fontMetrics().elidedText(text, Qt.TextElideMode.ElideMiddle, width)

    @staticmethod
    def _is_supported_archive(path: Path) -> bool:
        try:
            detect_archive_format(path)
        except Exception:
            return False
        return True

    @staticmethod
    def _drop_paths(event: QDragEnterEvent | QDropEvent) -> list[Path]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []

        paths: list[Path] = []
        for url in mime_data.urls():
            local_file = url.toLocalFile()
            if local_file:
                paths.append(Path(local_file))
        return paths

    def _drop_contains_supported_archive(self, paths: list[Path]) -> bool:
        return any(self._is_supported_archive(path) for path in paths)

    def _cleanup_drag_extract_dirs(self) -> None:
        for path in self._drag_extract_dirs:
            shutil.rmtree(path, ignore_errors=True)
        self._drag_extract_dirs.clear()

    def _effective_archive_format(self) -> ArchiveFormat | None:
        if self.current_archive is None:
            return None
        if self._forced_archive_format is not None:
            return self._forced_archive_format
        try:
            return detect_archive_format(self.current_archive)
        except Exception:
            return None
