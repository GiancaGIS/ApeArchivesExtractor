from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import Iterable

from apearchivesextractor.adapters.base import ArchiveAdapter
from apearchivesextractor.errors import (
    ArchiveDependencyError,
    ArchiveMemberNotFoundError,
    OperationCancelledError,
    UnsupportedFeatureError,
    UnsafeArchivePathError,
)
from apearchivesextractor.models import ArchiveEntry, CancelCallback, ProgressCallback, ProgressEvent
from apearchivesextractor.security import (
    archive_name_for,
    atomic_copy2,
    is_member_selected,
    normalize_archive_name,
    resolve_safe_input,
    safe_output_path,
    validate_extraction_plan,
)
from apearchivesextractor.spanned import numeric_volume_base, open_numeric_volumes


def _import_py7zr():
    try:
        import py7zr  # type: ignore
    except ImportError as exc:
        raise ArchiveDependencyError(
            "py7zr is required for .7z support. Install it with: pip install py7zr"
        ) from exc
    return py7zr


@contextmanager
def _open_seven_zip(archive_path: Path, password: str | None):
    py7zr = _import_py7zr()
    if numeric_volume_base(archive_path) is None:
        with py7zr.SevenZipFile(archive_path, mode="r", password=password) as archive:
            yield archive
        return

    with open_numeric_volumes(archive_path) as stream:
        with py7zr.SevenZipFile(stream, mode="r", password=password) as archive:
            yield archive


def _as_datetime(value) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return None


def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
    if should_cancel is not None and should_cancel():
        raise OperationCancelledError("Operazione annullata dall'utente.")


class SevenZAdapter(ArchiveAdapter):
    """7Z adapter based on py7zr.

    Note: py7zr does not expose the same byte-level streaming extraction hooks
    used by the ZIP/TAR.GZ adapters here. Cancellation is therefore cooperative
    before and after the py7zr operation, not during each internal chunk.
    """

    def list_entries(self, archive_path: Path, password: str | None = None) -> list[ArchiveEntry]:
        py7zr = _import_py7zr()
        entries: list[ArchiveEntry] = []

        with _open_seven_zip(archive_path, password) as archive:
            entries = self._entries_from_items(archive.list())

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
        py7zr = _import_py7zr()
        output_dir.mkdir(parents=True, exist_ok=True)

        with _open_seven_zip(archive_path, password) as archive:
            entries = self._entries_from_items(archive.list())
            names = [entry.path for entry in entries]
            for entry in entries:
                normalize_archive_name(entry.path)

            targets = None
            planned_entries = entries
            if selected_members is not None:
                targets = [name for name in names if is_member_selected(name, selected_members)]
                if not targets:
                    raise ArchiveMemberNotFoundError(
                        "No archive members matched the current selection."
                    )
                planned_entries = [
                    entry for entry in entries if is_member_selected(entry.path, selected_members)
                ]

            validate_extraction_plan(planned_entries)

            _raise_if_cancelled(should_cancel)
            if progress:
                progress(ProgressEvent("Extracting 7Z archive", archive_path.name))

            with TemporaryDirectory(prefix="apearchivesextractor_7z_", dir=output_dir.parent) as tmp:
                staging_dir = Path(tmp)
                if targets is None:
                    archive.extractall(path=staging_dir)
                else:
                    archive.extract(path=staging_dir, targets=targets)

                _raise_if_cancelled(should_cancel)
                self._validate_staged_tree(staging_dir)
                self._copy_staged_tree(staging_dir, output_dir, progress, should_cancel)

            _raise_if_cancelled(should_cancel)
            if progress:
                progress(ProgressEvent("Extraction completed", archive_path.name))

    def create(
        self,
        output_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        py7zr = _import_py7zr()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        inputs = [Path(input_path) for input_path in input_paths]
        work_items = self._collect_create_items(inputs)
        total = sum(size for file_path, _arcname, is_dir, size in work_items if not is_dir and file_path.is_file())
        processed = 0

        if progress:
            progress(ProgressEvent("Creating 7Z archive", output_path.name, processed, total))

        with py7zr.SevenZipFile(output_path, mode="w", password=password) as archive:
            for file_path, arcname, is_dir, size in work_items:
                _raise_if_cancelled(should_cancel)

                if progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

                archive.write(file_path, arcname=arcname)
                if not is_dir:
                    processed += size

                if progress:
                    progress(ProgressEvent("Adding", arcname, processed, total))

            _raise_if_cancelled(should_cancel)
            if progress:
                progress(ProgressEvent("Archive created", output_path.name, total, total))

    def add_files(
        self,
        archive_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        inputs = [resolve_safe_input(Path(path)) for path in input_paths]
        if not inputs:
            return
        if any(not path.is_file() for path in inputs):
            raise UnsupportedFeatureError("Only files can be added to an existing 7Z archive.")

        temp_file = archive_path.parent / f".{archive_path.name}.tmp"
        with TemporaryDirectory(prefix=f".{archive_path.name}.", dir=archive_path.parent) as staging:
            staging_dir = Path(staging)
            extracted_dir = staging_dir / "contents"
            temp_file = staging_dir / f"{archive_path.name}.tmp"

            _raise_if_cancelled(should_cancel)
            if progress:
                progress(ProgressEvent("Preparing 7Z archive", archive_path.name))
            self.extract_all(
                archive_path,
                extracted_dir,
                password=password,
                progress=progress,
                should_cancel=should_cancel,
            )

            for input_path in inputs:
                _raise_if_cancelled(should_cancel)
                safe_input_name = normalize_archive_name(input_path.name)
                destination = extracted_dir / safe_input_name
                if destination.exists() and destination.is_dir():
                    raise UnsupportedFeatureError(
                        f"Cannot replace a 7Z folder with a file: {input_path.name}"
                    )
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(input_path, destination)

            _raise_if_cancelled(should_cancel)
            top_level_inputs = sorted(extracted_dir.iterdir(), key=lambda path: path.name.lower())
            if progress:
                progress(ProgressEvent("Rebuilding 7Z archive", archive_path.name))
            self.create(
                temp_file,
                top_level_inputs,
                password=password,
                compression_level=compression_level,
                progress=progress,
                should_cancel=should_cancel,
            )

            _raise_if_cancelled(should_cancel)
            self._replace_archive_with_backup(archive_path, temp_file)
            if progress:
                progress(ProgressEvent("Files added", archive_path.name))

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
    def _entries_from_items(items: Iterable[object]) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        for item in items:
            filename = getattr(item, "filename", None) or str(item)
            is_dir = bool(getattr(item, "is_directory", False))
            uncompressed = getattr(item, "uncompressed", None)
            compressed = getattr(item, "compressed", None)
            modified_at = _as_datetime(getattr(item, "lastwritetime", None))

            entries.append(
                ArchiveEntry(
                    path=filename,
                    size=None if is_dir else uncompressed,
                    compressed_size=None if is_dir else compressed,
                    is_dir=is_dir,
                    modified_at=modified_at,
                )
            )
        return entries

    @staticmethod
    def _validate_staged_tree(staging_dir: Path) -> None:
        root = staging_dir.resolve(strict=True)
        for path in staging_dir.rglob("*"):
            if path.is_symlink():
                raise UnsafeArchivePathError(f"7Z symlinks are not extracted: {path.name!r}")
            try:
                path.resolve(strict=False).relative_to(root)
            except ValueError as exc:
                raise UnsafeArchivePathError(
                    f"Extracted 7Z member would escape staging directory: {path!s}"
                ) from exc

    @staticmethod
    def _copy_staged_tree(
        staging_dir: Path,
        output_dir: Path,
        progress: ProgressCallback,
        should_cancel: CancelCallback,
    ) -> None:
        files = [path for path in staging_dir.rglob("*") if path.is_file()]
        total = sum(path.stat().st_size for path in files)
        processed = 0

        for path in sorted(staging_dir.rglob("*")):
            _raise_if_cancelled(should_cancel)
            relative_name = path.relative_to(staging_dir).as_posix()
            destination = safe_output_path(output_dir, relative_name)

            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            if progress:
                progress(ProgressEvent("Copying extracted 7Z data", relative_name, processed, total))
            atomic_copy2(path, destination)
            processed += path.stat().st_size
            if progress:
                progress(ProgressEvent("Copying extracted 7Z data", relative_name, processed, total))

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
        except Exception:
            if archive_path.exists():
                archive_path.unlink()
            backup_path.replace(archive_path)
            raise
        else:
            backup_path.unlink(missing_ok=True)
