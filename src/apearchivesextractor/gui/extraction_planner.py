from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Iterable

from apearchivesextractor.models import ArchiveEntry
from apearchivesextractor.security import is_member_selected, normalize_archive_name, safe_output_path


def planned_output_paths(
    entries: Iterable[ArchiveEntry],
    output_dir: Path,
    members: Iterable[str] | None = None,
    flatten_single_file: bool = False,
    flatten_files: bool = False,
) -> list[Path]:
    """Return the files that an extraction operation would write.

    Directory entries are ignored because overwrite confirmation is useful only
    for concrete file paths. The same security validation used by extraction is
    applied here through ``safe_output_path``.
    """

    selected_members = list(members) if members is not None else None

    if flatten_single_file and selected_members is not None and len(selected_members) == 1:
        selected = normalize_archive_name(selected_members[0])
        for entry in entries:
            if entry.is_dir:
                continue
            if normalize_archive_name(entry.path).rstrip("/") == selected:
                return [output_dir.resolve(strict=False) / PurePosixPath(selected).name]
        return []

    if flatten_files and selected_members is not None:
        selected = {normalize_archive_name(member) for member in selected_members}
        planned_flat: list[Path] = []
        for entry in entries:
            if entry.is_dir:
                continue
            normalized_entry = normalize_archive_name(entry.path).rstrip("/")
            if normalized_entry in selected:
                planned_flat.append(output_dir.resolve(strict=False) / PurePosixPath(normalized_entry).name)
        return planned_flat

    planned: list[Path] = []

    for entry in entries:
        if entry.is_dir:
            continue
        if selected_members is not None and not is_member_selected(entry.path, selected_members):
            continue
        planned.append(safe_output_path(output_dir, entry.path))

    return planned


def existing_output_paths(
    entries: Iterable[ArchiveEntry],
    output_dir: Path,
    members: Iterable[str] | None = None,
    flatten_single_file: bool = False,
    flatten_files: bool = False,
) -> list[Path]:
    """Return destination files that already exist on disk."""

    return [
        path
        for path in planned_output_paths(
            entries,
            output_dir,
            members,
            flatten_single_file=flatten_single_file,
            flatten_files=flatten_files,
        )
        if path.exists()
    ]
