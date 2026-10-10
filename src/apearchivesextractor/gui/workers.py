# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import traceback
import time
from pathlib import Path
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal, pyqtSlot

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import OperationCancelledError
from apearchivesextractor.gui.originals_cleanup import delete_original_inputs
from apearchivesextractor.models import ProgressEvent


_PROGRESS_EMIT_INTERVAL_SECONDS = 0.08


class ArchiveWorker(QObject):
    """Run archive operations outside the GUI thread."""

    progress = pyqtSignal(str, str, object, object)
    result = pyqtSignal(object)
    cancelled = pyqtSignal()
    error = pyqtSignal(str, str)
    finished = pyqtSignal()

    def __init__(self, operation: str, *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.operation = operation
        self.args = args
        self.kwargs = kwargs
        self.service = ArchiveService()
        self._cancel_requested = False
        self._last_progress_emit = 0.0
        self._last_progress_message = ""
        self._progress_emit_interval_seconds = _PROGRESS_EMIT_INTERVAL_SECONDS

    def cancel(self) -> None:
        self._cancel_requested = True

    def should_cancel(self) -> bool:
        return self._cancel_requested

    def _emit_progress(self, event: ProgressEvent) -> None:
        processed = -1 if event.processed_bytes is None else int(event.processed_bytes)
        total = -1 if event.total_bytes is None else int(event.total_bytes)
        current_item = event.current_item or ""
        if not self._should_emit_progress(event.message, processed, total):
            return
        self.progress.emit(event.message, current_item, processed, total)

    def _should_emit_progress(self, message: str, processed: int, total: int) -> bool:
        now = time.monotonic()
        is_first = self._last_progress_emit == 0.0
        message_changed = message != self._last_progress_message
        is_complete = total > 0 and processed >= total
        interval_elapsed = now - self._last_progress_emit >= self._progress_emit_interval_seconds

        if not (is_first or message_changed or is_complete or interval_elapsed):
            return False

        self._last_progress_emit = now
        self._last_progress_message = message
        return True

    @pyqtSlot()
    def run(self) -> None:
        try:
            if self.operation == "list":
                archive_path: Path = self.args[0]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.result.emit(
                    self.service.list_entries(
                        archive_path,
                        password=password,
                        archive_format=archive_format,
                    )
                )
                return

            if self.operation == "extract_all":
                archive_path: Path = self.args[0]
                output_dir: Path = self.args[1]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.service.extract_all(
                    archive_path,
                    output_dir,
                    password=password,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "extract_members":
                archive_path: Path = self.args[0]
                output_dir: Path = self.args[1]
                members: list[str] = self.args[2]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.service.extract_members(
                    archive_path,
                    output_dir,
                    members,
                    password=password,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "extract_single_file":
                archive_path: Path = self.args[0]
                output_dir: Path = self.args[1]
                member: str = self.args[2]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.service.extract_member_flat(
                    archive_path,
                    output_dir,
                    member,
                    password=password,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "extract_flat_files":
                archive_path: Path = self.args[0]
                output_dir: Path = self.args[1]
                members: list[str] = self.args[2]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.service.extract_members_flat(
                    archive_path,
                    output_dir,
                    members,
                    password=password,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "create":
                output_path: Path = self.args[0]
                input_paths: list[Path] = self.args[1]
                archive_format: str | None = self.kwargs.get("archive_format")
                password: str | None = self.kwargs.get("password")
                compression_level: int | None = self.kwargs.get("compression_level")
                volume_size: int | None = self.kwargs.get("volume_size")
                delete_originals: bool = self.kwargs.get("delete_originals", False)
                created_path = self.service.create(
                    output_path,
                    input_paths,
                    archive_format=archive_format,
                    password=password,
                    compression_level=compression_level,
                    volume_size=volume_size,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                )
                result: dict[str, object] = {"created": True, "archive_path": created_path}
                if delete_originals:
                    try:
                        self._emit_progress(ProgressEvent("Deleting originals"))
                        result["deleted_originals"] = delete_original_inputs(input_paths)
                    except OSError as exc:
                        result["delete_originals_error"] = exc
                self.result.emit(result)
                return

            if self.operation == "delete_members":
                archive_path: Path = self.args[0]
                members: list[str] = self.args[1]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.service.delete_members(
                    archive_path,
                    members,
                    password=password,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "add_files":
                archive_path: Path = self.args[0]
                input_paths: list[Path] = self.args[1]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                compression_level: int | None = self.kwargs.get("compression_level")
                self.service.add_files(
                    archive_path,
                    input_paths,
                    password=password,
                    compression_level=compression_level,
                    progress=self._emit_progress,
                    should_cancel=self.should_cancel,
                    archive_format=archive_format,
                )
                self.result.emit(True)
                return

            if self.operation == "calculate_hashes":
                archive_path: Path = self.args[0]
                member: str = self.args[1]
                password: str | None = self.kwargs.get("password")
                archive_format: str | None = self.kwargs.get("archive_format")
                self.result.emit(
                    {
                        "member": member,
                        "hashes": self.service.calculate_member_hashes(
                            archive_path,
                            member,
                            password=password,
                            progress=self._emit_progress,
                            should_cancel=self.should_cancel,
                            archive_format=archive_format,
                        ),
                    }
                )
                return

            raise ValueError(f"Unknown worker operation: {self.operation}")

        except OperationCancelledError:
            self.cancelled.emit()
        except Exception as exc:
            self.error.emit(str(exc), traceback.format_exc())
        finally:
            self.finished.emit()
