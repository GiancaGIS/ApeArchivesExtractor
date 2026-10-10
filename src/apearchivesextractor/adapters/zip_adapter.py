# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import io
import zipfile
from copy import copy
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Iterable

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
    is_zip_symlink,
    normalize_archive_name,
    resolve_safe_input,
    safe_output_path,
    validate_extraction_plan,
)
from apearchivesextractor.spanned import canonical_volume_path, numeric_volume_base, open_numeric_volumes

_CHUNK_SIZE = 1024 ** 2


@contextmanager
def _open_zip(archive_path: Path):
    """Open regular, numbered, or PKZIP-style split archives as one stream."""
    if numeric_volume_base(archive_path) is not None:
        with open_numeric_volumes(archive_path) as stream:
            with zipfile.ZipFile(stream, mode="r") as archive:
                yield archive
        return

    canonical = canonical_volume_path(archive_path)
    z_volumes = _zip_part_paths(canonical)
    if not z_volumes:
        with zipfile.ZipFile(canonical, mode="r") as archive:
            yield archive
        return

    try:
        import multivolumefile
    except ImportError as exc:
        from apearchivesextractor.errors import ArchiveDependencyError

        raise ArchiveDependencyError("multivolumefile is required for split ZIP archives.") from exc

    segment_paths = [*z_volumes, canonical]
    segment_starts: list[int] = []
    position = 0
    for segment in segment_paths:
        segment_starts.append(position)
        position += segment.stat().st_size

    with multivolumefile.open(canonical.with_suffix(""), mode="rb") as raw_stream:
        with io.BufferedReader(raw_stream) as stream, zipfile.ZipFile(stream, mode="r") as archive:
            # zipfile applies the last-volume offset to every local header.
            # Translate each entry using its central-directory disk number.
            final_volume_start = segment_starts[-1]
            for info in archive.infolist():
                if info.volume >= len(segment_starts):
                    raise zipfile.BadZipFile("ZIP entry refers to a missing volume")
                info.header_offset += segment_starts[info.volume] - final_volume_start
            end_offset = archive.start_dir
            for info in reversed(sorted(archive.infolist(), key=lambda item: item.header_offset)):
                info._end_offset = end_offset
                end_offset = info.header_offset
            yield archive


def _zip_part_paths(canonical: Path) -> list[Path]:
    base = canonical.with_suffix("")
    parts = []
    for candidate in canonical.parent.glob(base.name + ".z*"):
        suffix = candidate.suffix.lower()
        if len(suffix) >= 4 and suffix[2:].isdigit():
            parts.append(candidate)
    return sorted(parts, key=lambda item: int(item.suffix[2:]))


class ZipAdapter(ArchiveAdapter):
    """ZIP adapter based on Python's standard zipfile module."""

    def list_entries(self, archive_path: Path, password: str | None = None) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        pwd = password.encode("utf-8") if password else None

        with _open_zip(archive_path) as archive:
            if pwd:
                archive.setpassword(pwd)

            for info in archive.infolist():
                entries.append(
                    ArchiveEntry(
                        path=info.filename,
                        size=None if info.is_dir() else info.file_size,
                        compressed_size=None if info.is_dir() else info.compress_size,
                        is_dir=info.is_dir(),
                        modified_at=datetime(*info.date_time),
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
        output_dir.mkdir(parents=True, exist_ok=True)
        pwd = password.encode("utf-8") if password else None

        with _open_zip(archive_path) as archive:
            infos = archive.infolist()
            if selected_members is not None:
                infos = [info for info in infos if is_member_selected(info.filename, selected_members)]
                if not infos:
                    raise ArchiveMemberNotFoundError(
                        "No archive members matched the current selection."
                    )

            for info in infos:
                if is_zip_symlink(info.external_attr):
                    raise UnsafeArchivePathError(
                        f"ZIP symlinks are not extracted: {info.filename!r}"
                    )
                safe_output_path(output_dir, info.filename)

            validate_extraction_plan(self._entries_from_infos(infos))

            total = sum(info.file_size for info in infos if not info.is_dir())
            processed = 0

            for info in infos:
                self._raise_if_cancelled(should_cancel)
                destination = safe_output_path(output_dir, info.filename)
                if info.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue

                destination.parent.mkdir(parents=True, exist_ok=True)

                if progress:
                    progress(ProgressEvent("Extracting", info.filename, processed, total))

                with archive.open(info, mode="r", pwd=pwd) as src, atomic_output_file(destination) as dst:
                    while True:
                        self._raise_if_cancelled(should_cancel)
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        processed += len(chunk)
                        if progress:
                            progress(ProgressEvent("Extracting", info.filename, processed, total))

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
            raise UnsupportedFeatureError(
                "ZIP encryption is intentionally not implemented. Use 7Z for password-protected archives."
            )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs = [Path(p) for p in input_paths]
        compression = zipfile.ZIP_DEFLATED
        compresslevel = compression_level if compression_level is not None else 9
        work_items = self._collect_create_items(inputs)
        total = sum(size for file_path, _arcname, is_dir, size in work_items if not is_dir and file_path.is_file())
        processed = 0

        if progress:
            progress(ProgressEvent("Creating ZIP archive", output_path.name, processed, total))

        with zipfile.ZipFile(
            output_path,
            mode="w",
            compression=compression,
            compresslevel=compresslevel,
            allowZip64=True,
        ) as archive:
            for file_path, arcname, is_dir, size in work_items:
                self._raise_if_cancelled(should_cancel)

                if is_dir:
                    archive.write(file_path, arcname=arcname)
                    continue

                info = zipfile.ZipInfo.from_file(file_path, arcname=arcname)
                info.compress_type = compression
                info._compresslevel = compresslevel

                if progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

                with file_path.open("rb") as src, archive.open(info, mode="w", force_zip64=True) as dst:
                    while True:
                        self._raise_if_cancelled(should_cancel)
                        chunk = src.read(_CHUNK_SIZE)
                        if not chunk:
                            break
                        dst.write(chunk)
                        processed += len(chunk)
                        if progress:
                            progress(ProgressEvent("Adding", arcname, processed, total))

                if size == 0 and progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

            if progress:
                progress(ProgressEvent("Finalizing ZIP archive", output_path.name, total, total))

        if progress:
            progress(ProgressEvent("Archive created", output_path.name, total, total))

    def delete_members(
        self,
        archive_path: Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        selected = list(members)
        if not selected:
            return

        temp_file = NamedTemporaryFile(
            prefix=f".{archive_path.name}.",
            suffix=".tmp",
            dir=archive_path.parent,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()
        pwd = password.encode("utf-8") if password else None

        try:
            with zipfile.ZipFile(archive_path, mode="r") as source:
                infos = source.infolist()
                kept_infos = [info for info in infos if not is_member_selected(info.filename, selected)]
                removed_count = len(infos) - len(kept_infos)
                if removed_count == 0:
                    raise ArchiveMemberNotFoundError("No archive members matched the current selection.")

                encrypted_kept = [info.filename for info in kept_infos if info.flag_bits & 0x1]
                if encrypted_kept:
                    raise UnsupportedFeatureError(
                        "Deleting from encrypted ZIP archives is not supported because remaining encrypted entries "
                        "cannot be preserved safely."
                    )

                total = sum(info.file_size for info in kept_infos if not info.is_dir())
                processed = 0
                if progress:
                    progress(ProgressEvent("Deleting from ZIP archive", archive_path.name, processed, total))

                with zipfile.ZipFile(temp_path, mode="w", allowZip64=True) as target:
                    target.comment = source.comment
                    for info in kept_infos:
                        self._raise_if_cancelled(should_cancel)
                        copied_info = copy(info)

                        if info.is_dir():
                            target.writestr(copied_info, b"")
                            continue

                        if progress:
                            progress(ProgressEvent("Keeping", info.filename, processed, total))

                        with source.open(info, mode="r", pwd=pwd) as src, target.open(
                            copied_info,
                            mode="w",
                            force_zip64=True,
                        ) as dst:
                            while True:
                                self._raise_if_cancelled(should_cancel)
                                chunk = src.read(_CHUNK_SIZE)
                                if not chunk:
                                    break
                                dst.write(chunk)
                                processed += len(chunk)
                                if progress:
                                    progress(ProgressEvent("Keeping", info.filename, processed, total))

            self._raise_if_cancelled(should_cancel)
            self._replace_archive_with_backup(archive_path, temp_path)
            if progress:
                progress(ProgressEvent("Members deleted", archive_path.name, total, total))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    def add_files(
        self,
        archive_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        if password:
            raise UnsupportedFeatureError("Adding files to encrypted ZIP archives is not supported.")

        inputs = [resolve_safe_input(Path(path)) for path in input_paths]
        if not inputs:
            return
        if any(not path.is_file() for path in inputs):
            raise UnsupportedFeatureError("Only files can be added to an existing ZIP archive.")

        temp_file = NamedTemporaryFile(
            prefix=f".{archive_path.name}.",
            suffix=".tmp",
            dir=archive_path.parent,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()

        compression = zipfile.ZIP_DEFLATED
        compresslevel = compression_level if compression_level is not None else 9
        replacement_names = {normalize_archive_name(path.name) for path in inputs}

        try:
            with zipfile.ZipFile(archive_path, mode="r") as source:
                infos = source.infolist()
                encrypted_kept = [
                    info.filename
                    for info in infos
                    if normalize_archive_name(info.filename) not in replacement_names and info.flag_bits & 0x1
                ]
                if encrypted_kept:
                    raise UnsupportedFeatureError(
                        "Adding to encrypted ZIP archives is not supported because encrypted entries "
                        "cannot be preserved safely."
                    )

                total = sum(info.file_size for info in infos if not info.is_dir()) + sum(
                    path.stat().st_size for path in inputs
                )
                processed = 0
                if progress:
                    progress(ProgressEvent("Adding to ZIP archive", archive_path.name, processed, total))

                with zipfile.ZipFile(temp_path, mode="w", allowZip64=True) as target:
                    target.comment = source.comment
                    for info in infos:
                        self._raise_if_cancelled(should_cancel)
                        if normalize_archive_name(info.filename) in replacement_names:
                            continue

                        copied_info = copy(info)
                        if info.is_dir():
                            target.writestr(copied_info, b"")
                            continue

                        if progress:
                            progress(ProgressEvent("Keeping", info.filename, processed, total))

                        with source.open(info, mode="r") as src, target.open(
                            copied_info,
                            mode="w",
                            force_zip64=True,
                        ) as dst:
                            while True:
                                self._raise_if_cancelled(should_cancel)
                                chunk = src.read(_CHUNK_SIZE)
                                if not chunk:
                                    break
                                dst.write(chunk)
                                processed += len(chunk)
                                if progress:
                                    progress(ProgressEvent("Keeping", info.filename, processed, total))

                    for input_path in inputs:
                        self._raise_if_cancelled(should_cancel)
                        arcname = normalize_archive_name(input_path.name)
                        info = zipfile.ZipInfo.from_file(input_path, arcname=arcname)
                        info.compress_type = compression
                        info._compresslevel = compresslevel

                        if progress:
                            progress(ProgressEvent("Adding", arcname, processed, total))

                        with input_path.open("rb") as src, target.open(info, mode="w", force_zip64=True) as dst:
                            while True:
                                self._raise_if_cancelled(should_cancel)
                                chunk = src.read(_CHUNK_SIZE)
                                if not chunk:
                                    break
                                dst.write(chunk)
                                processed += len(chunk)
                                if progress:
                                    progress(ProgressEvent("Adding", arcname, processed, total))

                        if input_path.stat().st_size == 0 and progress:
                            progress(ProgressEvent("Adding", arcname, processed, total))

            self._raise_if_cancelled(should_cancel)
            self._replace_archive_with_backup(archive_path, temp_path)
            if progress:
                progress(ProgressEvent("Files added", archive_path.name, total, total))
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _entries_from_infos(infos: Iterable[zipfile.ZipInfo]) -> list[ArchiveEntry]:
        return [
            ArchiveEntry(
                path=info.filename,
                size=None if info.is_dir() else info.file_size,
                compressed_size=None if info.is_dir() else info.compress_size,
                is_dir=info.is_dir(),
                modified_at=datetime(*info.date_time),
            )
            for info in infos
        ]

    @staticmethod
    def _replace_archive_with_backup(archive_path: Path, temp_path: Path) -> None:
        backup_file = NamedTemporaryFile(
            prefix=f".{archive_path.name}.",
            suffix=".bak",
            dir=archive_path.parent,
            delete=False,
        )
        backup_path = Path(backup_file.name)
        backup_file.close()

        archive_path.replace(backup_path)
        try:
            temp_path.replace(archive_path)
            with zipfile.ZipFile(archive_path, mode="r") as verify:
                bad_member = verify.testzip()
                if bad_member is not None:
                    raise zipfile.BadZipFile(f"Corrupt ZIP member after rewrite: {bad_member}")
        except Exception:
            if archive_path.exists():
                archive_path.unlink()
            backup_path.replace(archive_path)
            raise
        else:
            backup_path.unlink(missing_ok=True)

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
                self_path = resolve_safe_input(file_path)
                arcname = archive_name_for(self_path, root_parent)
                is_dir = self_path.is_dir()
                size = 0 if is_dir else self_path.stat().st_size
                items.append((self_path, arcname, is_dir, size))

        return items

    @staticmethod
    def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
        if should_cancel is not None and should_cancel():
            raise OperationCancelledError("Operazione annullata dall'utente.")
