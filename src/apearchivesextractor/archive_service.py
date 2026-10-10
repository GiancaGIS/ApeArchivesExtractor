# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Iterable

from apearchivesextractor.adapters.base import ArchiveAdapter
from apearchivesextractor.adapters.sevenz_adapter import SevenZAdapter
from apearchivesextractor.adapters.rar_adapter import RarAdapter
from apearchivesextractor.adapters.tar_gz_adapter import TarGzAdapter
from apearchivesextractor.adapters.zip_adapter import ZipAdapter
from apearchivesextractor.errors import (
    ArchiveMemberNotFoundError,
    OperationCancelledError,
    UnsupportedArchiveError,
    UnsupportedFeatureError,
)
from apearchivesextractor.models import ArchiveEntry, ArchiveFormat, CancelCallback, ProgressCallback, ProgressEvent
from apearchivesextractor.security import atomic_copy2, normalize_archive_name
from apearchivesextractor.spanned import detect_archive_format, numbered_volume_paths, numeric_volume_base

_COPY_CHUNK_SIZE = 1024 ** 2


class ArchiveService:
    """Facade used by CLI and GUI."""

    def __init__(self) -> None:
        self._adapters: dict[ArchiveFormat, ArchiveAdapter] = {
            ArchiveFormat.ZIP: ZipAdapter(),
            ArchiveFormat.SEVEN_Z: SevenZAdapter(),
            ArchiveFormat.RAR: RarAdapter(),
            ArchiveFormat.TAR_GZ: TarGzAdapter(),
        }

    def detect_format(self, path: str | Path) -> ArchiveFormat:
        return detect_archive_format(path)

    def get_adapter(self, archive_format: ArchiveFormat) -> ArchiveAdapter:
        try:
            return self._adapters[archive_format]
        except KeyError as exc:
            raise UnsupportedArchiveError(f"Unsupported archive format: {archive_format}") from exc

    def _adapter_for_path(
        self,
        path: Path,
        archive_format: ArchiveFormat | str | None = None,
    ) -> ArchiveAdapter:
        fmt = ArchiveFormat(archive_format) if archive_format else self.detect_format(path)
        return self.get_adapter(fmt)

    def list_entries(
        self,
        archive_path: str | Path,
        password: str | None = None,
        *,
        archive_format: ArchiveFormat | str | None = None,
    ) -> list[ArchiveEntry]:
        path = Path(archive_path)
        adapter = self._adapter_for_path(path, archive_format)
        return adapter.list_entries(path, password=password)

    def extract_all(
        self,
        archive_path: str | Path,
        output_dir: str | Path,
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        adapter = self._adapter_for_path(path, archive_format)
        adapter.extract_all(path, Path(output_dir), password=password, progress=progress, should_cancel=should_cancel)

    def extract_members(
        self,
        archive_path: str | Path,
        output_dir: str | Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        adapter = self._adapter_for_path(path, archive_format)
        adapter.extract_members(
            path,
            Path(output_dir),
            members,
            password=password,
            progress=progress,
            should_cancel=should_cancel,
        )

    def extract_member_flat(
        self,
        archive_path: str | Path,
        output_dir: str | Path,
        member: str,
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        normalized_member = normalize_archive_name(member)
        entries = self.list_entries(path, password=password, archive_format=archive_format)
        matching_entry = next(
            (
                entry
                for entry in entries
                if normalize_archive_name(entry.path).rstrip("/") == normalized_member
            ),
            None,
        )

        if matching_entry is None:
            raise ArchiveMemberNotFoundError("No archive members matched the current selection.")
        if matching_entry.is_dir:
            raise UnsupportedFeatureError("Single-file flat extraction requires a file, not a folder.")

        destination_dir = Path(output_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)
        destination = destination_dir / PurePosixPath(normalized_member).name

        with TemporaryDirectory(prefix="apearchivesextractor_extract_") as tmp:
            temp_dir = Path(tmp)
            self.extract_members(
                path,
                temp_dir,
                [normalized_member],
                password=password,
                progress=progress,
                should_cancel=should_cancel,
                archive_format=archive_format,
            )

            extracted = temp_dir / normalized_member
            if not extracted.is_file():
                raise ArchiveMemberNotFoundError("Selected file was not extracted.")

            if should_cancel is not None and should_cancel():
                raise OperationCancelledError("Operazione annullata dall'utente.")
            atomic_copy2(extracted, destination)

    def extract_members_flat(
        self,
        archive_path: str | Path,
        output_dir: str | Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        normalized_members = [normalize_archive_name(member) for member in members]
        if not normalized_members:
            return

        entries = self.list_entries(path, password=password, archive_format=archive_format)
        entry_by_member = {
            normalize_archive_name(entry.path).rstrip("/"): entry
            for entry in entries
            if not entry.is_dir
        }
        missing = [member for member in normalized_members if member not in entry_by_member]
        if missing:
            raise ArchiveMemberNotFoundError("No archive members matched the current selection.")

        output_names = [PurePosixPath(member).name for member in normalized_members]
        duplicate_names = sorted({name for name in output_names if output_names.count(name) > 1})
        if duplicate_names:
            raise UnsupportedFeatureError(
                "Flat extraction cannot write multiple selected files with the same name: "
                + ", ".join(duplicate_names)
            )

        destination_dir = Path(output_dir)
        destination_dir.mkdir(parents=True, exist_ok=True)

        with TemporaryDirectory(prefix="apearchivesextractor_extract_") as tmp:
            temp_dir = Path(tmp)
            self.extract_members(
                path,
                temp_dir,
                normalized_members,
                password=password,
                progress=progress,
                should_cancel=should_cancel,
                archive_format=archive_format,
            )

            for member in normalized_members:
                extracted = temp_dir / member
                if not extracted.is_file():
                    raise ArchiveMemberNotFoundError("Selected file was not extracted.")

                if should_cancel is not None and should_cancel():
                    raise OperationCancelledError("Operazione annullata dall'utente.")
                atomic_copy2(extracted, destination_dir / PurePosixPath(member).name)

    def create(
        self,
        output_path: str | Path,
        input_paths: Iterable[str | Path],
        archive_format: ArchiveFormat | str | None = None,
        password: str | None = None,
        compression_level: int | None = None,
        volume_size: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> Path:
        output = Path(output_path)
        fmt = ArchiveFormat(archive_format) if archive_format else self.detect_format(output)
        multi_volume_formats = (ArchiveFormat.ZIP, ArchiveFormat.SEVEN_Z, ArchiveFormat.RAR)
        if volume_size is not None:
            if volume_size <= 0:
                raise ValueError("Volume size must be greater than zero.")
            if fmt not in multi_volume_formats:
                raise UnsupportedFeatureError("Multi-volume creation is supported only for ZIP, 7Z, and RAR archives.")
            if numeric_volume_base(output) is not None:
                raise ValueError("Use the base archive path, not a numbered volume path.")
        adapter = self.get_adapter(fmt)
        output.parent.mkdir(parents=True, exist_ok=True)
        temp_file = NamedTemporaryFile(
            prefix=f".{output.name}.",
            suffix=".tmp",
            dir=output.parent,
            delete=False,
        )
        temp_path = Path(temp_file.name)
        temp_file.close()
        temp_path.unlink()
        try:
            adapter.create(
                temp_path,
                [Path(p) for p in input_paths],
                password=password,
                compression_level=compression_level,
                progress=progress,
                should_cancel=should_cancel,
            )
            if volume_size is not None:
                created_path = self._split_and_commit_archive(
                    temp_path,
                    output,
                    volume_size,
                    fmt,
                    progress,
                    should_cancel,
                )
            else:
                if fmt in multi_volume_formats and numbered_volume_paths(output):
                    self._commit_single_archive(temp_path, output)
                else:
                    temp_path.replace(output)
                created_path = output
            return created_path
        finally:
            temp_path.unlink(missing_ok=True)

    @staticmethod
    def _split_and_commit_archive(
        archive_path: Path,
        output: Path,
        volume_size: int,
        archive_format: ArchiveFormat,
        progress: ProgressCallback,
        should_cancel: CancelCallback,
    ) -> Path:
        total = archive_path.stat().st_size
        volume_count = max(1, (total + volume_size - 1) // volume_size)
        if volume_count > 999:
            raise UnsupportedFeatureError(
                "The selected volume size would create more than 999 parts. Choose a larger size."
            )
        processed = 0

        with TemporaryDirectory(prefix=f".{output.name}.volumes.", dir=output.parent) as tmp:
            staging_dir = Path(tmp)
            staged: list[Path] = []
            with archive_path.open("rb") as source:
                index = 1
                while processed < total:
                    if should_cancel is not None and should_cancel():
                        raise OperationCancelledError("Operazione annullata dall'utente.")
                    staged_path = staging_dir / f"{output.name}.{index:03d}"
                    remaining = volume_size
                    with staged_path.open("wb") as target:
                        while remaining > 0:
                            if should_cancel is not None and should_cancel():
                                raise OperationCancelledError("Operazione annullata dall'utente.")
                            chunk = source.read(min(_COPY_CHUNK_SIZE, remaining))
                            if not chunk:
                                break
                            target.write(chunk)
                            processed += len(chunk)
                            remaining -= len(chunk)
                            if progress:
                                progress(
                                    ProgressEvent(
                                        f"Splitting {archive_format.value.upper()} archive",
                                        staged_path.name,
                                        processed,
                                        total,
                                    )
                                )
                    staged.append(staged_path)
                    index += 1

            backup_dir = staging_dir / "backup"
            backup_dir.mkdir()
            previous = numbered_volume_paths(output)
            if output.exists():
                previous.append(output)
            committed_paths: list[Path] = []
            try:
                for path in previous:
                    path.replace(backup_dir / path.name)
                for path in staged:
                    destination = output.parent / path.name
                    path.replace(destination)
                    committed_paths.append(destination)
            except Exception:
                for path in committed_paths:
                    path.unlink(missing_ok=True)
                for backup in backup_dir.iterdir():
                    backup.replace(output.parent / backup.name)
                raise

        first_volume = output.parent / f"{output.name}.001"
        if progress:
            progress(ProgressEvent("Archive volumes created", first_volume.name, total, total))
        return first_volume

    @staticmethod
    def _commit_single_archive(archive_path: Path, output: Path) -> None:
        with TemporaryDirectory(prefix=f".{output.name}.backup.", dir=output.parent) as tmp:
            backup_dir = Path(tmp)
            previous = numbered_volume_paths(output)
            if output.exists():
                previous.append(output)
            try:
                for path in previous:
                    path.replace(backup_dir / path.name)
                archive_path.replace(output)
            except Exception:
                output.unlink(missing_ok=True)
                for backup in backup_dir.iterdir():
                    backup.replace(output.parent / backup.name)
                raise

    def delete_members(
        self,
        archive_path: str | Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        adapter = self._adapter_for_path(path, archive_format)
        adapter.delete_members(
            path,
            members,
            password=password,
            progress=progress,
            should_cancel=should_cancel,
        )

    def add_files(
        self,
        archive_path: str | Path,
        input_paths: Iterable[str | Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> None:
        path = Path(archive_path)
        adapter = self._adapter_for_path(path, archive_format)
        adapter.add_files(
            path,
            [Path(p) for p in input_paths],
            password=password,
            compression_level=compression_level,
            progress=progress,
            should_cancel=should_cancel,
        )

    def calculate_member_hashes(
        self,
        archive_path: str | Path,
        member: str,
        password: str | None = None,
        algorithms: Iterable[str] = ("md5", "sha1", "sha256"),
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
        archive_format: ArchiveFormat | str | None = None,
    ) -> dict[str, str]:
        normalized_member = normalize_archive_name(member)
        hashers = {algorithm: hashlib.new(algorithm) for algorithm in algorithms}

        with TemporaryDirectory(prefix="apearchivesextractor_hash_") as tmp:
            temp_dir = Path(tmp)
            self.extract_member_flat(
                archive_path,
                temp_dir,
                normalized_member,
                password=password,
                progress=progress,
                should_cancel=should_cancel,
                archive_format=archive_format,
            )

            extracted = temp_dir / PurePosixPath(normalized_member).name
            total = extracted.stat().st_size
            processed = 0
            if progress:
                progress(ProgressEvent("Hashing", normalized_member, processed, total))

            with extracted.open("rb") as file:
                while True:
                    if should_cancel is not None and should_cancel():
                        raise OperationCancelledError("Operazione annullata dall'utente.")
                    chunk = file.read(1024 ** 2)
                    if not chunk:
                        break
                    for hasher in hashers.values():
                        hasher.update(chunk)
                    processed += len(chunk)
                    if progress:
                        progress(ProgressEvent("Hashing", normalized_member, processed, total))

        return {algorithm.upper(): hasher.hexdigest() for algorithm, hasher in hashers.items()}
