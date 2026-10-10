# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import tarfile
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Iterable

from apearchivesextractor.adapters.base import ArchiveAdapter
from apearchivesextractor.errors import (
    ArchiveMemberNotFoundError,
    OperationCancelledError,
    UnsupportedFeatureError,
    UnsafeArchivePathError,
)
from apearchivesextractor.models import ArchiveEntry, CancelCallback, ProgressCallback, ProgressEvent
from apearchivesextractor.security import (
    archive_name_for,
    atomic_output_file,
    is_member_selected,
    normalize_archive_name,
    resolve_safe_input,
    safe_output_path,
    validate_extraction_plan,
)

_CHUNK_SIZE = 1024 ** 2


class _ProgressReader:
    def __init__(
        self,
        fileobj: BinaryIO,
        arcname: str,
        base_processed: int,
        total: int,
        progress: ProgressCallback,
        should_cancel: CancelCallback,
    ) -> None:
        self._fileobj = fileobj
        self._arcname = arcname
        self._base_processed = base_processed
        self._total = total
        self._progress = progress
        self._should_cancel = should_cancel
        self.processed = 0

    def read(self, size: int = -1) -> bytes:
        TarGzAdapter._raise_if_cancelled(self._should_cancel)
        chunk = self._fileobj.read(size)
        if chunk:
            self.processed += len(chunk)
            if self._progress:
                self._progress(
                    ProgressEvent(
                        "Adding",
                        self._arcname,
                        self._base_processed + self.processed,
                        self._total,
                    )
                )
        return chunk


class TarGzAdapter(ArchiveAdapter):
    """TAR.GZ adapter based on Python's standard tarfile module."""

    def list_entries(self, archive_path: Path, password: str | None = None) -> list[ArchiveEntry]:
        if password:
            raise UnsupportedFeatureError("TAR.GZ does not support password protection.")

        entries: list[ArchiveEntry] = []
        with tarfile.open(archive_path, mode="r:gz") as archive:
            for member in archive.getmembers():
                entries.append(
                    ArchiveEntry(
                        path=member.name,
                        size=None if member.isdir() else member.size,
                        compressed_size=None,
                        is_dir=member.isdir(),
                        modified_at=datetime.fromtimestamp(member.mtime) if member.mtime else None,
                    )
                )

        validate_extraction_plan(entries)
        return entries

    def extract_all(
        self,
        archive_path: Path,
        output_dir: Path,
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        self._extract(archive_path, output_dir, None, password, progress, should_cancel)

    def extract_members(
        self,
        archive_path: Path,
        output_dir: Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        selected = list(members)
        if not selected:
            return
        self._extract(archive_path, output_dir, selected, password, progress, should_cancel)

    def _extract(
        self,
        archive_path: Path,
        output_dir: Path,
        selected_members: list[str] | None,
        password: str | None,
        progress: ProgressCallback,
        should_cancel: CancelCallback = None,
    ) -> None:
        if password:
            raise UnsupportedFeatureError("TAR.GZ does not support password protection.")

        output_dir.mkdir(parents=True, exist_ok=True)

        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if selected_members is not None:
                members = [m for m in members if is_member_selected(m.name, selected_members)]
                if not members:
                    raise ArchiveMemberNotFoundError(
                        "No archive members matched the current selection."
                    )

            for member in members:
                safe_output_path(output_dir, member.name)
                if member.issym() or member.islnk() or member.isdev():
                    raise UnsafeArchivePathError(
                        f"Links and device files are not extracted: {member.name!r}"
                    )
                if not (member.isfile() or member.isdir()):
                    raise UnsafeArchivePathError(
                        f"Unsupported TAR member type: {member.name!r}"
                    )

            validate_extraction_plan(self._entries_from_members(members))

            total = sum(member.size for member in members if member.isfile())
            processed = 0

            for member in members:
                self._raise_if_cancelled(should_cancel)
                destination = safe_output_path(output_dir, member.name)

                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)
                src = archive.extractfile(member)
                if src is None:
                    continue

                if progress:
                    progress(ProgressEvent("Extracting", member.name, processed, total))

                with src, atomic_output_file(destination) as dst:
                    while True:
                        self._raise_if_cancelled(should_cancel)
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        processed += len(chunk)
                        if progress:
                            progress(ProgressEvent("Extracting", member.name, processed, total))

    def create(
        self,
        output_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        if password:
            raise UnsupportedFeatureError("TAR.GZ does not support password protection.")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs = [Path(p) for p in input_paths]
        compresslevel = compression_level if compression_level is not None else 9
        work_items = self._collect_create_items(inputs)
        total = sum(size for file_path, _arcname, is_dir, size in work_items if not is_dir and file_path.is_file())
        processed = 0

        if progress:
            progress(ProgressEvent("Creating TAR.GZ archive", output_path.name, processed, total))

        with tarfile.open(output_path, mode="w:gz", compresslevel=compresslevel) as archive:
            for file_path, arcname, is_dir, size in work_items:
                self._raise_if_cancelled(should_cancel)

                info = archive.gettarinfo(str(file_path), arcname=arcname)
                if is_dir:
                    archive.addfile(info)
                    continue

                if progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

                with file_path.open("rb") as src:
                    reader = _ProgressReader(src, arcname, processed, total, progress, should_cancel)
                    archive.addfile(info, reader)
                    processed += reader.processed

                if size == 0 and progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

            if progress:
                progress(ProgressEvent("Archive created", output_path.name, total, total))

    @staticmethod
    def _collect_create_items(inputs: list[Path]) -> list[tuple[Path, str, bool, int]]:
        items: list[tuple[Path, str, bool, int]] = []

        for input_path in inputs:
            input_path = resolve_safe_input(input_path)
            root_parent = input_path.parent

            if input_path.is_file():
                arcname = normalize_archive_name(input_path.name)
                items.append((input_path, arcname, False, input_path.stat().st_size))
                continue

            if not input_path.is_dir():
                raise FileNotFoundError(f"Input path does not exist: {input_path}")

            items.append((input_path, normalize_archive_name(input_path.name), True, 0))
            for file_path in sorted(input_path.rglob("*")):
                file_path = resolve_safe_input(file_path)
                arcname = archive_name_for(file_path, root_parent)
                is_dir = file_path.is_dir()
                size = 0 if is_dir else file_path.stat().st_size
                items.append((file_path, arcname, is_dir, size))

        return items

    @staticmethod
    def _entries_from_members(members: Iterable[tarfile.TarInfo]) -> list[ArchiveEntry]:
        return [
            ArchiveEntry(
                path=member.name,
                size=None if member.isdir() else member.size,
                compressed_size=None,
                is_dir=member.isdir(),
                modified_at=datetime.fromtimestamp(member.mtime) if member.mtime else None,
            )
            for member in members
        ]

    @staticmethod
    def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
        if should_cancel is not None and should_cancel():
            raise OperationCancelledError("Operazione annullata dall'utente.")
