# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from PySide6.QtCore import QEvent, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QToolButton, QVBoxLayout, QWidget

from apearchivesextractor.gui.i18n import translate


class UpdateToast(QFrame):
    """A dismissible in-window notification that never blocks or activates a window."""

    def __init__(self, parent: QWidget, language: str) -> None:
        super().__init__(parent)
        self.setObjectName("updateToast")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setStyleSheet("""
            QFrame#updateToast { background: palette(window); border: 1px solid palette(mid);
                                border-left: 4px solid palette(highlight); border-radius: 8px; }
            QFrame#updateToast QLabel { color: palette(window-text); background: transparent; border: none; }
            QToolButton#toastClose { border: none; background: transparent; color: palette(window-text); }
            QToolButton#toastClose:hover { background: palette(midlight); }
        """)
        self._url = ""
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(20000)
        self._timer.timeout.connect(self.hide)
        self.title = QLabel(self)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.title.setWordWrap(True)
        self.title.setTextFormat(Qt.TextFormat.PlainText)
        self.message = QLabel(self)
        self.message.setWordWrap(True)
        self.message.setTextFormat(Qt.TextFormat.PlainText)
        self.dismiss_button = QToolButton(self)
        self.dismiss_button.setObjectName("toastClose")
        self.dismiss_button.setText("×")
        self.dismiss_button.clicked.connect(self.hide)
        self.action_button = QPushButton(self)
        self.action_button.clicked.connect(self._open_release)
        heading = QHBoxLayout()
        heading.addWidget(self.title, 1)
        heading.addWidget(self.dismiss_button, 0, Qt.AlignmentFlag.AlignTop)
        actions = QHBoxLayout()
        actions.addStretch()
        actions.addWidget(self.action_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 12, 12)
        layout.addLayout(heading)
        layout.addWidget(self.message)
        layout.addLayout(actions)
        parent.installEventFilter(self)
        self.set_language(language)
        self.hide()

    def set_language(self, language: str) -> None:
        self.dismiss_button.setToolTip(translate(language, "button.close"))
        self.dismiss_button.setAccessibleName(translate(language, "button.close"))

    def show_message(self, title: str, message: str, *, url: str = "", action: str = "") -> None:
        self.title.setText(title)
        self.message.setText(message)
        self._url = url
        self.action_button.setText(action)
        self.action_button.setVisible(bool(url))
        self.setFixedWidth(min(410, max(120, self.parentWidget().width() - 32)))
        self.adjustSize()
        self._position()
        self.show()
        self.raise_()
        self._timer.start()

    def _position(self) -> None:
        parent = self.parentWidget()
        self.move(max(8, parent.width() - self.width() - 16),
                  max(8, parent.height() - self.height() - 16))

    def eventFilter(self, watched, event) -> bool:
        if watched is self.parentWidget() and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self.setFixedWidth(min(410, max(120, watched.width() - 32)))
            self.adjustSize()
            self._position()
        return super().eventFilter(watched, event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self.isVisible():
            self._timer.start()
        super().leaveEvent(event)

    def hideEvent(self, event) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(event)

    def _open_release(self) -> None:
        if self._url and QDesktopServices.openUrl(QUrl(self._url)):
            self.hide()
