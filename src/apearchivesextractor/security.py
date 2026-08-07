from __future__ import annotations

import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import BinaryIO, Iterable, Iterator

from .errors import ArchiveLimitExceededError, UnsafeArchivePathError
from .models import ArchiveEntry

_WINDOWS_DRIVE_RE = re.compile(r"^[a-zA-Z]:")
_WINDOWS_INVALID_CHARS = frozenset('<>:"|?*')
_WINDOWS_RESERVED_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{index}" for index in range(1, 10)}
    | {f"LPT{index}" for index in range(1, 10)}
)


@dataclass(frozen=True, slots=True)
class ArchiveSafetyLimits:
    """Guardrails that keep extraction from consuming unreasonable resources."""

    max_entries: int = 100_000
    max_total_uncompressed_bytes: int = 16 * 1024 ** 3
    max_single_file_uncompressed_bytes: int = 8 * 1024 ** 3
    max_compression_ratio: float = 1000.0


DEFAULT_EXTRACTION_LIMITS = ArchiveSafetyLimits()


def normalize_archive_name(name: str) -> str:
    """Validate and normalize a path coming from an archive.

    The function rejects traversal and names that cannot be represented safely
    on Windows. Archive paths are normalized to POSIX-style separators because
    ZIP, TAR and 7Z usually store member names that way.
    """

    if not name or name.strip() == "":
        raise UnsafeArchivePathError("Archive member has an empty path.")

    if "\x00" in name:
        raise UnsafeArchivePathError(f"Archive member contains a null byte: {name!r}")

    normalized = name.replace("\\", "/")

    if normalized.startswith("/") or normalized.startswith("//"):
        raise UnsafeArchivePathError(f"Absolute archive path is not allowed: {name!r}")

    if _WINDOWS_DRIVE_RE.match(normalized):
        raise UnsafeArchivePathError(f"Windows drive path is not allowed: {name!r}")

    path = PurePosixPath(normalized)
    parts = [part for part in path.parts if part not in ("", ".")]

    if any(part == ".." for part in parts):
        raise UnsafeArchivePathError(f"Parent traversal is not allowed: {name!r}")

    if not parts:
        raise UnsafeArchivePathError(f"Archive member has no usable path: {name!r}")

    for part in parts:
        if any(char in _WINDOWS_INVALID_CHARS or ord(char) < 32 for char in part):
            raise UnsafeArchivePathError(
                f"Archive member contains characters unsafe on Windows: {name!r}"
            )
        if part.endswith((" ", ".")):
            raise UnsafeArchivePathError(
                f"Archive member ends with a Windows-unsafe character: {name!r}"
            )
        device_name = part.split(".", 1)[0].upper()
        if device_name in _WINDOWS_RESERVED_NAMES:
            raise UnsafeArchivePathError(
                f"Archive member uses a reserved Windows device name: {name!r}"
            )

    return "/".join(parts)


def safe_output_path(output_dir: Path, archive_name: str) -> Path:
    """Return a destination path guaranteed to stay under output_dir."""

    safe_name = normalize_archive_name(archive_name)
    root = output_dir.resolve(strict=False)
    destination = (root / safe_name).resolve(strict=False)

    try:
        destination.relative_to(root)
    except ValueError as exc:
        raise UnsafeArchivePathError(
            f"Archive member would escape output directory: {archive_name!r}"
        ) from exc

    return destination


@contextmanager
def atomic_output_file(destination: Path) -> Iterator[BinaryIO]:
    """Write a destination without following an existing link at the final path."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NamedTemporaryFile(
        prefix=".apearchivesextractor-write-",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    committed = False

    try:
        with temp_file as file:
            yield file
        temp_path.replace(destination)
        committed = True
    finally:
        if not committed:
            temp_file.close()
            temp_path.unlink(missing_ok=True)


def atomic_copy2(source: Path, destination: Path) -> None:
    """Copy a file and atomically replace the destination directory entry."""

    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_file = NamedTemporaryFile(
        prefix=".apearchivesextractor-copy-",
        suffix=".tmp",
        dir=destination.parent,
        delete=False,
    )
    temp_path = Path(temp_file.name)
    temp_file.close()
    committed = False

    try:
        shutil.copy2(source, temp_path, follow_symlinks=False)
        temp_path.replace(destination)
        committed = True
    finally:
        if not committed:
            temp_path.unlink(missing_ok=True)


def resolve_safe_input(path: Path) -> Path:
    """Resolve an archive input while refusing symlinks and Windows junctions."""

    is_junction = getattr(path, "is_junction", lambda: False)
    if path.is_symlink() or is_junction():
        raise UnsafeArchivePathError(f"Filesystem links are not archived: {path!s}")
    return path.resolve(strict=True)


def validate_extraction_plan(
    entries: Iterable[ArchiveEntry],
    limits: ArchiveSafetyLimits | None = None,
) -> None:
    """Reject extraction plans that look too large or suspiciously compressed."""

    active_limits = limits or DEFAULT_EXTRACTION_LIMITS
    entry_count = 0
    total_uncompressed = 0

    for entry in entries:
        entry_count += 1
        if entry_count > active_limits.max_entries:
            raise ArchiveLimitExceededError(
                f"Archive contains too many entries ({entry_count:,}). "
                f"Limit is {active_limits.max_entries:,}."
            )

        if entry.is_dir or entry.size is None:
            continue

        if entry.size > active_limits.max_single_file_uncompressed_bytes:
            raise ArchiveLimitExceededError(
                f"Archive member is too large after extraction: {entry.path!r} "
                f"({entry.size:,} bytes)."
            )

        total_uncompressed += entry.size
        if total_uncompressed > active_limits.max_total_uncompressed_bytes:
            raise ArchiveLimitExceededError(
                f"Archive would extract too much data ({total_uncompressed:,} bytes). "
                f"Limit is {active_limits.max_total_uncompressed_bytes:,} bytes."
            )

        if entry.compressed_size and entry.compressed_size > 0:
            ratio = entry.size / entry.compressed_size
            if ratio > active_limits.max_compression_ratio:
                raise ArchiveLimitExceededError(
                    f"Archive member has a suspicious compression ratio: {entry.path!r} "
                    f"({ratio:.1f}:1)."
                )


def is_member_selected(member_name: str, selected_members: Iterable[str]) -> bool:
    """Return True if member_name matches one selected file or a selected folder."""

    normalized = normalize_archive_name(member_name)
    for selected in selected_members:
        selected_normalized = normalize_archive_name(selected).rstrip("/")
        if normalized == selected_normalized:
            return True
        if normalized.startswith(selected_normalized + "/"):
            return True
    return False


def iter_input_files(input_path: Path) -> list[Path]:
    """Return all files below a path, or the path itself if it is a file."""

    resolved_input = resolve_safe_input(input_path)
    if resolved_input.is_file():
        return [resolved_input]

    if resolved_input.is_dir():
        files: list[Path] = []
        for path in resolved_input.rglob("*"):
            resolved_path = resolve_safe_input(path)
            if resolved_path.is_file():
                files.append(resolved_path)
        return files

    raise FileNotFoundError(f"Input path does not exist: {input_path}")


def archive_name_for(path: Path, root_parent: Path) -> str:
    """Build a stable archive name for a file or directory entry."""

    rel = path.resolve(strict=False).relative_to(root_parent.resolve(strict=False))
    return normalize_archive_name(rel.as_posix())


def is_zip_symlink(external_attr: int) -> bool:
    """Best-effort detection of POSIX symlinks stored in ZIP metadata."""

    # Upper 16 bits contain Unix mode when created on Unix-like systems.
    mode = (external_attr >> 16) & 0o777777
    return (mode & 0o170000) == 0o120000
