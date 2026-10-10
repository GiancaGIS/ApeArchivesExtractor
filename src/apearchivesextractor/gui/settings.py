# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from PyQt6.QtCore import QByteArray, QSettings

from apearchivesextractor.gui.i18n import DEFAULT_LANGUAGE, normalize_language


class AppSettings:
    """Thin QSettings wrapper used by the GUI.

    Keeping QSettings calls here avoids scattering magic key names throughout
    the widgets and makes the behavior easy to evolve later.
    """

    ORGANIZATION = "GiancaGIS"
    APPLICATION = "ApeArchivesExtractor"
    MAX_RECENT_ARCHIVES = 8

    def __init__(self) -> None:
        self._settings = QSettings(self.ORGANIZATION, self.APPLICATION)

    def save_geometry(self, geometry: QByteArray) -> None:
        self._settings.setValue("window/geometry", geometry)

    def restore_geometry(self) -> QByteArray | None:
        value = self._settings.value("window/geometry")
        if isinstance(value, QByteArray):
            return value
        return None

    def last_open_dir(self) -> Path:
        return self._path_value("paths/last_open_dir", Path.home())

    def set_last_open_dir(self, path: Path) -> None:
        self._settings.setValue("paths/last_open_dir", str(path))

    def last_extract_dir(self) -> Path:
        return self._path_value("paths/last_extract_dir", Path.home())

    def set_last_extract_dir(self, path: Path) -> None:
        self._settings.setValue("paths/last_extract_dir", str(path))

    def last_create_dir(self) -> Path:
        return self._path_value("paths/last_create_dir", Path.home())

    def set_last_create_dir(self, path: Path) -> None:
        self._settings.setValue("paths/last_create_dir", str(path))

    def last_input_dir(self) -> Path:
        return self._path_value("paths/last_input_dir", Path.home())

    def set_last_input_dir(self, path: Path) -> None:
        self._settings.setValue("paths/last_input_dir", str(path))

    def confirm_overwrite(self) -> bool:
        value = self._settings.value("safety/confirm_overwrite", True, type=bool)
        return bool(value)

    def set_confirm_overwrite(self, enabled: bool) -> None:
        self._settings.setValue("safety/confirm_overwrite", enabled)

    def language(self) -> str:
        return normalize_language(str(self._settings.value("ui/language", DEFAULT_LANGUAGE)))

    def set_language(self, language: str) -> None:
        self._settings.setValue("ui/language", normalize_language(language))

    def recent_archives(self) -> list[Path]:
        raw = self._settings.value("recent/archives", "[]")
        try:
            data = json.loads(str(raw))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        return [Path(item) for item in data if isinstance(item, str)]

    def add_recent_archive(self, archive_path: Path) -> None:
        archive_path = archive_path.resolve(strict=False)
        archives = [p for p in self.recent_archives() if p != archive_path]
        archives.insert(0, archive_path)
        self._set_recent_archives(archives[: self.MAX_RECENT_ARCHIVES])

    def clear_recent_archives(self) -> None:
        self._set_recent_archives([])

    def _set_recent_archives(self, paths: Iterable[Path]) -> None:
        self._settings.setValue("recent/archives", json.dumps([str(path) for path in paths]))

    def _path_value(self, key: str, default: Path) -> Path:
        raw = self._settings.value(key, str(default))
        path = Path(str(raw))
        if path.exists():
            return path
        return default
