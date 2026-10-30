# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from apearchivesextractor.gui.i18n import DEFAULT_LANGUAGE, normalize_language, translate
from apearchivesextractor.gui.originals_cleanup import output_is_inside_inputs
from apearchivesextractor.spanned import numbered_volume_paths


class CreateArchiveDialog(QDialog):
    """Small dialog used to collect create-archive options."""

    def __init__(
        self,
        parent: QWidget | None = None,
        initial_output_dir: Path | None = None,
        initial_input_dir: Path | None = None,
        initial_inputs: Iterable[Path] | None = None,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        super().__init__(parent)
        self._language = normalize_language(language)
        self._last_output_dir = initial_output_dir or Path.home()
        self._last_input_dir = initial_input_dir or Path.home()
        self.setWindowTitle(self._tr("create.title"))
        self.resize(680, 460)

        self.output_edit = QLineEdit()
        self.output_edit.setPlaceholderText(self._tr("create.output.placeholder"))
        self.output_edit.setClearButtonEnabled(True)

        self.format_combo = QComboBox()
        self.format_combo.addItems(["zip", "7z", "rar", "tar.gz"])
        self.format_combo.currentTextChanged.connect(self._on_format_changed)

        self.password_edit = QLineEdit()
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText(self._tr("create.password.placeholder"))
        self.password_edit.setClearButtonEnabled(True)

        self.show_password_check = QCheckBox(self._tr("show_password"))
        self.show_password_check.toggled.connect(self._toggle_password_visibility)

        self.compression_spin = QSpinBox()
        self.compression_spin.setRange(0, 9)
        self.compression_spin.setValue(9)

        self.volume_size_spin = QSpinBox()
        self.volume_size_spin.setRange(0, 2_097_151)
        self.volume_size_spin.setSingleStep(10)
        self.volume_size_spin.setSuffix(" MB")
        self.volume_size_spin.setSpecialValueText(self._tr("create.volume_size.none"))
        self.volume_size_spin.setToolTip(self._tr("create.volume_size.tooltip"))

        self.delete_originals_check = QCheckBox(self._tr("create.delete_originals"))
        self.delete_originals_check.setToolTip(self._tr("create.delete_originals.tooltip"))

        self.inputs_list = QListWidget()
        self.inputs_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.inputs_list.itemSelectionChanged.connect(self._update_inputs_state)
        self.inputs_count_label = QLabel(self._tr("create.inputs.none"))

        browse_output = QPushButton(self._tr("create.browse"))
        browse_output.clicked.connect(self._browse_output)

        add_files = QPushButton(self._tr("create.add_files"))
        add_files.clicked.connect(self._add_files)

        add_folder = QPushButton(self._tr("create.add_folder"))
        add_folder.clicked.connect(self._add_folder)

        self.remove_selected_btn = QPushButton(self._tr("create.remove_selected"))
        self.remove_selected_btn.clicked.connect(self._remove_selected)
        self.remove_selected_btn.setEnabled(False)

        create_btn = QPushButton(self._tr("create.create"))
        create_btn.clicked.connect(self._accept_if_valid)
        create_btn.setDefault(True)

        cancel_btn = QPushButton(self._tr("create.cancel"))
        cancel_btn.clicked.connect(self.reject)

        output_row = QHBoxLayout()
        output_row.addWidget(self.output_edit)
        output_row.addWidget(browse_output)

        form = QFormLayout()
        form.addRow(self._tr("create.output"), output_row)
        form.addRow(self._tr("create.format"), self.format_combo)
        form.addRow(self._tr("create.compression"), self.compression_spin)
        form.addRow(self._tr("create.volume_size"), self.volume_size_spin)
        form.addRow("", self.delete_originals_check)
        password_row = QHBoxLayout()
        password_row.addWidget(self.password_edit)
        password_row.addWidget(self.show_password_check)
        form.addRow(self._tr("create.password"), password_row)

        input_buttons = QHBoxLayout()
        input_buttons.addWidget(add_files)
        input_buttons.addWidget(add_folder)
        input_buttons.addStretch(1)
        input_buttons.addWidget(self.remove_selected_btn)

        actions = QHBoxLayout()
        actions.addStretch(1)
        actions.addWidget(cancel_btn)
        actions.addWidget(create_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(QLabel(self._tr("create.inputs")))
        layout.addWidget(self.inputs_list, 1)
        layout.addWidget(self.inputs_count_label)
        layout.addLayout(input_buttons)
        layout.addLayout(actions)

        self._on_format_changed(self.format_combo.currentText())
        if initial_inputs:
            self._prefill_inputs(list(initial_inputs))

    @property
    def last_used_output_dir(self) -> Path:
        return self._last_output_dir

    @property
    def last_used_input_dir(self) -> Path:
        return self._last_input_dir

    @property
    def output_path(self) -> Path:
        return Path(self.output_edit.text().strip())

    @property
    def archive_format(self) -> str:
        return self.format_combo.currentText()

    @property
    def input_paths(self) -> list[Path]:
        return [Path(self.inputs_list.item(i).text()) for i in range(self.inputs_list.count())]

    @property
    def password(self) -> str | None:
        value = self.password_edit.text()
        return value if value else None

    @property
    def compression_level(self) -> int:
        return self.compression_spin.value()

    @property
    def volume_size(self) -> int | None:
        if self.archive_format not in ("zip", "7z", "rar") or self.volume_size_spin.value() == 0:
            return None
        return self.volume_size_spin.value() * 1024 ** 2

    @property
    def delete_originals(self) -> bool:
        return self.delete_originals_check.isChecked()

    def _tr(self, key: str, **kwargs: object) -> str:
        return translate(self._language, key, **kwargs)

    def _extension_for_format(self) -> str:
        fmt = self.archive_format
        if fmt == "zip":
            return ".zip"
        if fmt == "7z":
            return ".7z"
        if fmt == "rar":
            return ".rar"
        return ".tar.gz"

    def _browse_output(self) -> None:
        fmt = self.archive_format
        extension = self._extension_for_format()
        filters = {
            "zip": "ZIP archive (*.zip)",
            "7z": "7Z archive (*.7z)",
            "rar": "RAR archive (*.rar)",
            "tar.gz": "TAR.GZ archive (*.tar.gz)",
        }
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            self._tr("create.output_dialog.title"),
            str(self._last_output_dir / f"{self._tr('create.default_name')}{extension}"),
            filters[fmt],
        )
        if not file_name:
            return
        path = Path(file_name)
        if not str(path).lower().endswith(extension):
            path = Path(str(path) + extension)
        self.output_edit.setText(str(path))
        self._last_output_dir = path.parent

    def _add_files(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            self._tr("create.add_files_dialog.title"),
            str(self._last_input_dir),
        )
        for file_name in files:
            path = Path(file_name)
            self._add_input(path)
            self._last_input_dir = path.parent

    def _add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            self._tr("create.add_folder_dialog.title"),
            str(self._last_input_dir),
        )
        if folder:
            path = Path(folder)
            self._add_input(path)
            self._last_input_dir = path.parent

    def _add_input(self, path: Path) -> None:
        path = path.resolve(strict=False)
        existing = {self.inputs_list.item(i).text() for i in range(self.inputs_list.count())}
        if str(path) not in existing:
            self.inputs_list.addItem(str(path))
            self._update_inputs_state()

    def _prefill_inputs(self, paths: list[Path]) -> None:
        existing_paths = [path for path in paths if path.exists()]
        for path in existing_paths:
            self._add_input(path)

        if not existing_paths:
            return

        first = existing_paths[0].resolve(strict=False)
        self._last_input_dir = first.parent if first.is_file() else first
        if not self.output_edit.text().strip():
            base_name = first.stem if first.is_file() else first.name
            output_dir = first.parent if first.is_file() else first.parent
            self.output_edit.setText(str(output_dir / f"{base_name}.zip"))
            self._last_output_dir = output_dir

    def _remove_selected(self) -> None:
        for item in self.inputs_list.selectedItems():
            self.inputs_list.takeItem(self.inputs_list.row(item))
        self._update_inputs_state()

    def _on_format_changed(self, value: str) -> None:
        supports_password = value in ("7z", "rar")
        self.volume_size_spin.setEnabled(value in ("zip", "7z", "rar"))
        self.password_edit.setEnabled(supports_password)
        self.show_password_check.setEnabled(supports_password)
        self.password_edit.setPlaceholderText(
            self._tr("create.password.archive") if supports_password else self._tr("create.password.disabled")
        )
        if not supports_password:
            self.password_edit.clear()
            self.show_password_check.setChecked(False)

        current_output = self.output_edit.text().strip()
        if current_output:
            self.output_edit.setText(self._with_format_extension(Path(current_output)))

    def _toggle_password_visibility(self, visible: bool) -> None:
        mode = QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password
        self.password_edit.setEchoMode(mode)

    def _update_inputs_state(self) -> None:
        count = self.inputs_list.count()
        selected = len(self.inputs_list.selectedItems())
        self.remove_selected_btn.setEnabled(selected > 0)
        if count == 0:
            self.inputs_count_label.setText(self._tr("create.inputs.none"))
        elif count == 1:
            self.inputs_count_label.setText(self._tr("create.inputs.one"))
        else:
            self.inputs_count_label.setText(self._tr("create.inputs.many", count=count))

    def _with_format_extension(self, path: Path) -> str:
        text = str(path)
        lower = text.lower()
        for suffix in (".tar.gz", ".zip", ".7z", ".rar"):
            if lower.endswith(suffix):
                text = text[: -len(suffix)]
                break
        return text + self._extension_for_format()

    def _accept_if_valid(self) -> None:
        if not self.output_edit.text().strip():
            QMessageBox.warning(
                self,
                self._tr("create.missing_output.title"),
                self._tr("create.missing_output.body"),
            )
            return

        if self.inputs_list.count() == 0:
            QMessageBox.warning(
                self,
                self._tr("create.missing_inputs.title"),
                self._tr("create.missing_inputs.body"),
            )
            return

        missing_inputs = [path for path in self.input_paths if not path.exists()]
        if missing_inputs:
            preview = "\n".join(str(path) for path in missing_inputs[:8])
            if len(missing_inputs) > 8:
                preview += "\n" + self._tr("delete.preview.more", count=len(missing_inputs) - 8)
            QMessageBox.warning(
                self,
                self._tr("create.missing_files.title"),
                self._tr("create.missing_files.body", preview=preview),
            )
            return

        extension = self._extension_for_format()
        if not str(self.output_path).lower().endswith(extension):
            self.output_edit.setText(str(self.output_path) + extension)

        output_parent = self.output_path.parent
        if output_parent and not output_parent.exists():
            answer = QMessageBox.question(
                self,
                self._tr("create.missing_folder.title"),
                self._tr("create.missing_folder.body", path=output_parent),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return
            output_parent.mkdir(parents=True, exist_ok=True)

        existing_outputs = [self.output_path] if self.output_path.exists() else []
        if self.archive_format in ("zip", "7z", "rar"):
            existing_outputs.extend(numbered_volume_paths(self.output_path))
        if existing_outputs:
            answer = QMessageBox.question(
                self,
                self._tr("create.overwrite.title"),
                self._tr("create.overwrite.body", path=existing_outputs[0]),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        if self.delete_originals:
            unsafe_input = output_is_inside_inputs(self.output_path, self.input_paths)
            if unsafe_input is not None:
                QMessageBox.warning(
                    self,
                    self._tr("create.delete_originals.unsafe_title"),
                    self._tr(
                        "create.delete_originals.unsafe_body",
                        output=self.output_path,
                        input=unsafe_input,
                    ),
                )
                return

            answer = QMessageBox.question(
                self,
                self._tr("create.delete_originals.confirm_title"),
                self._tr("create.delete_originals.confirm_body", count=len(self.input_paths)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return

        self.accept()
