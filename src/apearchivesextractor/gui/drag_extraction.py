# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from pathlib import Path
from typing import Iterable

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import ArchiveMemberNotFoundError, OperationCancelledError
from apearchivesextractor.models import CancelCallback, ProgressCallback
from apearchivesextractor.security import normalize_archive_name, safe_output_path


def prepare_drag_paths(
    service: ArchiveService,
    archive_path: Path,
    temporary_dir: Path,
    members: Iterable[str],
    *,
    password: str | None = None,
    archive_format: str | None = None,
    progress: ProgressCallback = None,
    should_cancel: CancelCallback = None,
) -> list[Path]:
    """Extract a selection once and expose real files/folders for desktop drops.

    Keep each selected folder's contents together. Selected files are exposed at
    the drop destination's top level, with distinct names even when they came
    from different archive directories. The caller owns the temporary directory
    and must retain it while the receiving application copies its contents.
    """
    selected: list[str] = []
    for member in sorted({normalize_archive_name(m) for m in members}, key=lambda m: (m.count("/"), m)):
        if not any(member.startswith(parent + "/") for parent in selected):
            selected.append(member)
    if not selected:
        return []

    def check_cancelled() -> None:
        if should_cancel is not None and should_cancel():
            raise OperationCancelledError("Operazione annullata dall'utente.")

    check_cancelled()
    contents = temporary_dir / "contents"
    service.extract_members(
        archive_path, contents, selected, password=password, archive_format=archive_format,
        progress=progress, should_cancel=should_cancel,
    )
    export_dir = temporary_dir / "files"
    export_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    names: set[str] = set()
    for member in selected:
        check_cancelled()
        source = safe_output_path(contents, member)
        if not source.exists():
            raise ArchiveMemberNotFoundError(f"Selected archive member was not extracted: {member}")
        name = source.name
        number = 2
        suffix = "" if source.is_dir() else source.suffix
        stem = name[:-len(suffix)] if suffix else name
        while name.casefold() in names:
            name = f"{stem} ({number}){suffix}"
            number += 1
        names.add(name.casefold())
        destination = export_dir / name
        # Same filesystem: avoid copying large files a second time for staging.
        source.rename(destination)
        paths.append(destination)
    return paths
