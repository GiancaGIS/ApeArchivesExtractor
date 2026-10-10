# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QPushButton, QSplitter, QTextEdit, QVBoxLayout, QWidget

from apearchivesextractor.gui.i18n import translate
from apearchivesextractor.legal_info import legal_sections


class LicensesDialog(QDialog):
    def __init__(self, language: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(translate(language, "menu.licenses"))
        self.resize(850, 620)
        self.documents = legal_sections()
        self.selector = QListWidget(self)
        self.selector.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.selector.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.selector.setAccessibleName(translate(language, "menu.licenses"))
        self.selector.addItems([translate(language, title) for title, _ in self.documents])
        self.viewer = QTextEdit(self)
        self.viewer.setReadOnly(True)

        splitter = QSplitter(Qt.Orientation.Vertical, self)
        splitter.addWidget(self.selector)
        splitter.addWidget(self.viewer)
        splitter.setSizes([220, 340])
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)

        close_button = QPushButton(translate(language, "button.close"), self)
        close_button.clicked.connect(self.accept)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addLayout(buttons)

        self.selector.currentRowChanged.connect(self._select_document)
        if self.documents:
            self.selector.setCurrentRow(0)

    def _select_document(self, index: int) -> None:
        self.viewer.setPlainText(self.documents[index][1] if 0 <= index < len(self.documents) else "")
