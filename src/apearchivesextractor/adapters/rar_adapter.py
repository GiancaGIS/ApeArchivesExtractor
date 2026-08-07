from __future__ import annotations

import os
import shutil
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from typing import Iterable

from apearchivesextractor.adapters.base import ArchiveAdapter
from apearchivesextractor.errors import (
    ApeArchivesExtractorError,
    ArchiveDependencyError,
    ArchiveMemberNotFoundError,
    OperationCancelledError,
)
from apearchivesextractor.models import ArchiveEntry, CancelCallback, ProgressCallback, ProgressEvent
from apearchivesextractor.security import (
    atomic_output_file,
    is_member_selected,
    normalize_archive_name,
    resolve_safe_input,
    safe_output_path,
    validate_extraction_plan,
)
from apearchivesextractor.spanned import canonical_volume_path, numeric_volume_base, open_numeric_volumes

_CHUNK_SIZE = 1024 ** 2


def _import_rarfile():
    try:
        import rarfile
    except ImportError as exc:
        raise ArchiveDependencyError("rarfile is required for RAR archive support.") from exc
    return rarfile


def _find_rar_command() -> str:
    configured = os.environ.get("APEARCH_RAR")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return str(candidate)
        raise ArchiveDependencyError(f"APEARCH_RAR does not point to a file: {candidate}")

    for name in ("rar", "rar.exe", "WinRAR.exe"):
        command = shutil.which(name)
        if command:
            return command

    if os.name == "nt":
        for candidate in (
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WinRAR" / "Rar.exe",
            Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "WinRAR" / "WinRAR.exe",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "WinRAR" / "Rar.exe",
        ):
            if candidate.is_file():
                return str(candidate)

    raise ArchiveDependencyError(
        "Creating RAR archives requires the official rar command or WinRAR. "
        "Install it or set APEARCH_RAR to the executable path."
    )


@contextmanager
def _open_rar(archive_path: Path):
    rarfile = _import_rarfile()
    if numeric_volume_base(archive_path) is None:
        with rarfile.RarFile(canonical_volume_path(archive_path)) as archive:
            yield archive
        return

    with TemporaryDirectory(prefix="apearchivesextractor_rar_") as tmp:
        combined = Path(tmp) / numeric_volume_base(archive_path).name
        with open_numeric_volumes(archive_path) as source, combined.open("wb") as target:
            shutil.copyfileobj(source, target, length=_CHUNK_SIZE)
        with rarfile.RarFile(combined) as archive:
            yield archive


class RarAdapter(ArchiveAdapter):
    """RAR adapter using rarfile for reading and the official rar tool for creation."""

    def list_entries(self, archive_path: Path, password: str | None = None) -> list[ArchiveEntry]:
        entries: list[ArchiveEntry] = []
        with _open_rar(archive_path) as archive:
            for info in archive.infolist():
                entries.append(_entry_from_info(info))
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
        if selected:
            self._extract(archive_path, output_dir, selected, password, progress, should_cancel)

    def _extract(
        self,
        archive_path: Path,
        output_dir: Path,
        selected_members: list[str] | None,
        password: str | None,
        progress: ProgressCallback,
        should_cancel: CancelCallback,
    ) -> None:
        output_dir.mkdir(parents=True, exist_ok=True)

        with _open_rar(archive_path) as archive:
            selected = [
                (info, _entry_from_info(info))
                for info in archive.infolist()
                if selected_members is None or is_member_selected(info.filename, selected_members)
            ]
            if selected_members is not None and not selected:
                raise ArchiveMemberNotFoundError("No archive members matched the current selection.")
            validate_extraction_plan([entry for _, entry in selected])
            total = sum(entry.size or 0 for _, entry in selected if not entry.is_dir)
            processed = 0
            for info, entry in selected:
                _raise_if_cancelled(should_cancel)
                destination = safe_output_path(output_dir, entry.path)
                if entry.is_dir:
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                if progress:
                    progress(ProgressEvent("Extracting", entry.path, processed, total))
                with archive.open(info, pwd=password) as source, atomic_output_file(destination) as target:
                    while chunk := source.read(_CHUNK_SIZE):
                        _raise_if_cancelled(should_cancel)
                        target.write(chunk)
                        processed += len(chunk)
                        if progress:
                            progress(ProgressEvent("Extracting", entry.path, processed, total))

    def create(
        self,
        output_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        command = _find_rar_command()
        inputs = [resolve_safe_input(Path(path)) for path in input_paths]
        if not inputs:
            raise ValueError("At least one input path is required.")
        _raise_if_cancelled(should_cancel)

        level = 5 if compression_level is None else max(0, min(5, round(compression_level * 5 / 9)))
        args = [command, "a", "-idq", "-r", "-ep1", f"-m{level}"]
        args.append(f"-p{password}" if password else "-p-")
        args.extend(["--", str(output_path), *(str(path) for path in inputs)])

        if progress:
            progress(ProgressEvent("Creating RAR archive", output_path.name))
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        with TemporaryFile(mode="w+t", encoding="utf-8", errors="replace") as log:
            process = subprocess.Popen(
                args,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=creation_flags,
            )
            while process.poll() is None:
                if should_cancel is not None and should_cancel():
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise OperationCancelledError("Operazione annullata dall'utente.")
                time.sleep(0.05)
            log.seek(0)
            detail = log.read().strip()

        if process.returncode != 0:
            suffix = f": {detail}" if detail else ""
            raise ApeArchivesExtractorError(f"RAR creation failed with exit code {process.returncode}{suffix}")
        if not output_path.is_file():
            raise ApeArchivesExtractorError("The RAR backend completed without creating the archive.")
        if progress:
            progress(ProgressEvent("Archive created", output_path.name))


def _rar_datetime(info) -> datetime | None:
    value = getattr(info, "mtime", None)
    if isinstance(value, datetime):
        return value
    date_time = getattr(info, "date_time", None)
    try:
        return datetime(*date_time) if date_time else None
    except (TypeError, ValueError):
        return None


def _entry_from_info(info) -> ArchiveEntry:
    return ArchiveEntry(
        path=info.filename,
        size=None if info.isdir() else info.file_size,
        compressed_size=None if info.isdir() else info.compress_size,
        is_dir=info.isdir(),
        modified_at=_rar_datetime(info),
    )


def _raise_if_cancelled(should_cancel: CancelCallback) -> None:
    if should_cancel is not None and should_cancel():
        raise OperationCancelledError("Operazione annullata dall'utente.")
