# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Callable

from PyQt6.QtCore import QUrl, Qt
from PyQt6.QtGui import QDrag, QDragEnterEvent, QDragMoveEvent, QDropEvent, QIcon
from PyQt6.QtWidgets import QApplication, QHeaderView, QStyle, QTreeWidget, QTreeWidgetItem

from apearchivesextractor.gui.i18n import DEFAULT_LANGUAGE, normalize_language, translate
from apearchivesextractor.models import ArchiveEntry


class ArchiveTreeItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        column = self.treeWidget().sortColumn() if self.treeWidget() is not None else 0
        left = self.data(column, ArchiveTreeWidget.SORT_ROLE)
        right = other.data(column, ArchiveTreeWidget.SORT_ROLE)
        if left is not None and right is not None:
            return left < right
        return super().__lt__(other)


class ArchiveTreeWidget(QTreeWidget):
    """Tree representation of archive entries.

    Archive formats usually expose entries as flat POSIX-like paths. This widget
    turns those paths into a navigable folder tree while preserving the original
    archive member path in ``Qt.UserRole`` for selective extraction.
    """

    PATH_ROLE = Qt.ItemDataRole.UserRole
    IS_DIR_ROLE = Qt.ItemDataRole.UserRole + 1
    IS_IMPLICIT_ROLE = Qt.ItemDataRole.UserRole + 2
    SORT_ROLE = Qt.ItemDataRole.UserRole + 3

    def __init__(self) -> None:
        super().__init__()
        self._language = DEFAULT_LANGUAGE
        self._prepare_drag_paths: Callable[[], list[Path]] | None = None
        self._handle_external_drop: Callable[[list[Path]], bool] | None = None
        self.setColumnCount(6)
        self._update_headers()
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setSortingEnabled(True)
        self.sortByColumn(0, Qt.SortOrder.AscendingOrder)

        header = self.header()
        header.setStretchLastSection(False)
        header.setMinimumSectionSize(70)
        for col, width in enumerate((320, 100, 95, 105, 145, 260)):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
            header.resizeSection(col, width)

    def set_language(self, language: str) -> None:
        self._language = normalize_language(language)
        self._update_headers()

    def set_drag_handlers(
        self,
        prepare_drag_paths: Callable[[], list[Path]],
        handle_external_drop: Callable[[list[Path]], bool],
    ) -> None:
        self._prepare_drag_paths = prepare_drag_paths
        self._handle_external_drop = handle_external_drop

    def _tr(self, key: str, **kwargs: object) -> str:
        return translate(self._language, key, **kwargs)

    def startDrag(self, supported_actions: Qt.DropAction) -> None:  # noqa: N802 - Qt naming
        if self._prepare_drag_paths is None:
            return
        paths = self._prepare_drag_paths()
        if not paths:
            return

        mime_data = self.model().mimeData(self.selectedIndexes())
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        drag = QDrag(self)
        drag.setMimeData(mime_data)
        drag.exec(Qt.DropAction.CopyAction)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802 - Qt naming
        if self._drop_paths(event):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:  # noqa: N802 - Qt naming
        if self._drop_paths(event):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802 - Qt naming
        paths = self._drop_paths(event)
        if paths and self._handle_external_drop is not None and self._handle_external_drop(paths):
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    @staticmethod
    def _drop_paths(event: QDragEnterEvent | QDragMoveEvent | QDropEvent) -> list[Path]:
        mime_data = event.mimeData()
        if not mime_data.hasUrls():
            return []
        return [Path(url.toLocalFile()) for url in mime_data.urls() if url.toLocalFile()]

    def _update_headers(self) -> None:
        self.setHeaderLabels(
            [
                self._tr("tree.name"),
                self._tr("tree.type"),
                self._tr("tree.size"),
                self._tr("tree.compressed"),
                self._tr("tree.modified"),
                self._tr("tree.path"),
            ]
        )

    def populate(self, entries: list[ArchiveEntry]) -> None:
        self.setSortingEnabled(False)
        self.clear()

        folder_icon = self._standard_icon(QStyle.StandardPixmap.SP_DirIcon)
        file_icon = self._standard_icon(QStyle.StandardPixmap.SP_FileIcon)
        nodes: dict[str, QTreeWidgetItem] = {}

        for entry in sorted(entries, key=lambda e: (not e.is_dir, self._clean_path(e.path).lower())):
            cleaned = self._clean_path(entry.path)
            parts = self._parts(cleaned)
            if not parts:
                continue

            parent_item: QTreeWidgetItem | None = None
            current_parts: list[str] = []

            for index, part in enumerate(parts):
                current_parts.append(part)
                key = "/".join(current_parts)
                is_last = index == len(parts) - 1
                node_is_dir = entry.is_dir or not is_last

                item = nodes.get(key)
                if item is None:
                    item = self._make_item(
                        name=part,
                        archive_path=key,
                        is_dir=node_is_dir,
                        size=None,
                        compressed_size=None,
                        modified_at=None,
                        implicit=not is_last,
                        icon=folder_icon if node_is_dir else file_icon,
                    )
                    if parent_item is None:
                        self.addTopLevelItem(item)
                    else:
                        parent_item.addChild(item)
                    nodes[key] = item

                if is_last:
                    self._update_item_from_entry(item, entry, icon=folder_icon if entry.is_dir else file_icon)

                parent_item = item

        self.setSortingEnabled(True)
        self.expandToDepth(0)

    def apply_filter(self, text: str) -> None:
        """Hide rows that do not match the given text.

        A folder remains visible when at least one child matches. Matching is
        intentionally simple and case-insensitive: it checks the visible name and
        the full archive path.
        """

        needle = text.strip().lower()
        root = self.invisibleRootItem()
        for index in range(root.childCount()):
            self._apply_filter_to_item(root.child(index), needle)
        if needle:
            self.expandAll()
        else:
            self.expandToDepth(0)

    def selected_members(self) -> list[str]:
        members: list[str] = []
        seen: set[str] = set()
        for item in self.selectedItems():
            value = item.data(0, self.PATH_ROLE)
            if value and value not in seen:
                seen.add(value)
                members.append(str(value))
        return self._collapse_descendant_members(members)

    def selected_display_path(self) -> str | None:
        items = self.selectedItems()
        if not items:
            return None
        value = items[0].data(0, self.PATH_ROLE)
        return str(value) if value else None

    def entry_count(self) -> int:
        return self._count_items(self.invisibleRootItem())

    def _make_item(
        self,
        *,
        name: str,
        archive_path: str,
        is_dir: bool,
        size: int | None,
        compressed_size: int | None,
        modified_at: datetime | None,
        implicit: bool,
        icon: QIcon,
    ) -> QTreeWidgetItem:
        item = ArchiveTreeItem(
            [
                name,
                self._tr("tree.folder") if is_dir else self._tr("tree.file"),
                self._format_size(size),
                self._format_size(compressed_size),
                self._format_datetime(modified_at),
                archive_path,
            ]
        )
        item.setIcon(0, icon)
        item.setData(0, self.PATH_ROLE, archive_path)
        item.setData(0, self.IS_DIR_ROLE, is_dir)
        item.setData(0, self.IS_IMPLICIT_ROLE, implicit)
        self._set_sort_data(item, name, is_dir, size, compressed_size, modified_at)
        for col in range(self.columnCount()):
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        return item

    def _update_item_from_entry(self, item: QTreeWidgetItem, entry: ArchiveEntry, icon: QIcon) -> None:
        cleaned = self._clean_path(entry.path)
        item.setText(1, self._tr("tree.folder") if entry.is_dir else self._tr("tree.file"))
        item.setText(2, self._format_size(entry.size))
        item.setText(3, self._format_size(entry.compressed_size))
        item.setText(4, self._format_datetime(entry.modified_at))
        item.setText(5, cleaned)
        item.setIcon(0, icon)
        item.setData(0, self.PATH_ROLE, cleaned)
        item.setData(0, self.IS_DIR_ROLE, entry.is_dir)
        item.setData(0, self.IS_IMPLICIT_ROLE, False)
        self._set_sort_data(item, item.text(0), entry.is_dir, entry.size, entry.compressed_size, entry.modified_at)

    def _apply_filter_to_item(self, item: QTreeWidgetItem, needle: str) -> bool:
        if not needle:
            item.setHidden(False)
            for index in range(item.childCount()):
                self._apply_filter_to_item(item.child(index), needle)
            return True

        row_text = " ".join(item.text(col) for col in range(self.columnCount())).lower()
        self_matches = needle in row_text
        child_matches = False
        for index in range(item.childCount()):
            child_matches = self._apply_filter_to_item(item.child(index), needle) or child_matches
        visible = self_matches or child_matches
        item.setHidden(not visible)
        return visible

    @staticmethod
    def _parts(path: str) -> list[str]:
        return [part for part in PurePosixPath(path).parts if part not in ("", ".")]

    @staticmethod
    def _clean_path(path: str) -> str:
        return path.replace("\\", "/").strip("/")

    @staticmethod
    def _format_size(value: int | None) -> str:
        if value is None:
            return "-"
        size = float(value)
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if size < 1024 or unit == "TB":
                return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
            size /= 1024
        return f"{value} B"

    @staticmethod
    def _format_datetime(value: datetime | None) -> str:
        if value is None:
            return "-"
        return value.strftime("%Y-%m-%d %H:%M")

    @staticmethod
    def _set_sort_data(
        item: QTreeWidgetItem,
        name: str,
        is_dir: bool,
        size: int | None,
        compressed_size: int | None,
        modified_at: datetime | None,
    ) -> None:
        item.setData(0, ArchiveTreeWidget.SORT_ROLE, f"{0 if is_dir else 1}:{name.lower()}")
        item.setData(1, ArchiveTreeWidget.SORT_ROLE, 0 if is_dir else 1)
        item.setData(2, ArchiveTreeWidget.SORT_ROLE, -1 if size is None else int(size))
        item.setData(3, ArchiveTreeWidget.SORT_ROLE, -1 if compressed_size is None else int(compressed_size))
        item.setData(4, ArchiveTreeWidget.SORT_ROLE, 0 if modified_at is None else int(modified_at.timestamp()))
        item.setData(5, ArchiveTreeWidget.SORT_ROLE, item.text(5).lower())

    @staticmethod
    def _collapse_descendant_members(members: list[str]) -> list[str]:
        collapsed: list[str] = []
        for member in sorted(members, key=lambda value: (value.count("/"), value.lower())):
            if any(member == parent or member.startswith(parent + "/") for parent in collapsed):
                continue
            collapsed.append(member)
        return collapsed

    @staticmethod
    def _standard_icon(pixmap: QStyle.StandardPixmap) -> QIcon:
        app = QApplication.instance()
        if app is None:
            return QIcon()
        return app.style().standardIcon(pixmap)

    def _count_items(self, item: QTreeWidgetItem) -> int:
        total = 0
        for index in range(item.childCount()):
            total += 1 + self._count_items(item.child(index))
        return total
