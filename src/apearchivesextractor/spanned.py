# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import io
import re
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

from apearchivesextractor.errors import UnsupportedArchiveError
from apearchivesextractor.models import ArchiveFormat

_NUMERIC_VOLUME = re.compile(r"^(?P<base>.+)\.(?P<part>\d{3,})$", re.IGNORECASE)
_RAR_VOLUME = re.compile(r"^(?P<base>.+)\.r\d{2,}$", re.IGNORECASE)
_ZIP_VOLUME = re.compile(r"^(?P<base>.+)\.z\d{2,}$", re.IGNORECASE)


def is_spanned_archive(path: str | Path) -> bool:
    value = str(path)
    if any(pattern.match(value) for pattern in (_NUMERIC_VOLUME, _RAR_VOLUME, _ZIP_VOLUME)):
        return True
    candidate = Path(path)
    if candidate.suffix.lower() == ".zip":
        return candidate.with_suffix(".z01").exists()
    return False


def canonical_volume_path(path: str | Path) -> Path:
    """Return the path expected by the archive backend for a selected volume."""
    value = str(path)
    match = _RAR_VOLUME.match(value)
    if match:
        return Path(match.group("base") + ".rar")
    match = _ZIP_VOLUME.match(value)
    if match:
        return Path(match.group("base") + ".zip")
    return Path(path)


def detect_archive_format(path: str | Path) -> ArchiveFormat:
    value = str(path)
    lower = value.lower()
    if lower.endswith(".tar.gz"):
        return ArchiveFormat.TAR_GZ
    if lower.endswith(".zip") or _ZIP_VOLUME.match(value):
        return ArchiveFormat.ZIP
    if lower.endswith(".7z"):
        return ArchiveFormat.SEVEN_Z
    if lower.endswith(".rar") or _RAR_VOLUME.match(value):
        return ArchiveFormat.RAR

    match = _NUMERIC_VOLUME.match(value)
    if match:
        base = match.group("base").lower()
        if base.endswith(".7z"):
            return ArchiveFormat.SEVEN_Z
        if base.endswith(".zip"):
            return ArchiveFormat.ZIP
        if base.endswith(".rar"):
            return ArchiveFormat.RAR
        detected = _detect_magic(Path(path)) or _detect_magic(Path(match.group("base") + ".001"))
        if detected is not None:
            return detected

    raise UnsupportedArchiveError(f"Unsupported archive format: {path}")


def numeric_volume_base(path: Path) -> Path | None:
    match = _NUMERIC_VOLUME.match(str(path))
    return Path(match.group("base")) if match else None


def numbered_volume_paths(base: Path) -> list[Path]:
    pattern = re.compile(re.escape(base.name) + r"\.(\d{3,})$", re.IGNORECASE)
    volumes: list[tuple[int, Path]] = []
    for candidate in base.parent.glob(base.name + ".*"):
        match = pattern.match(candidate.name)
        if match:
            volumes.append((int(match.group(1)), candidate))
    return [path for _, path in sorted(volumes)]


@contextmanager
def open_numeric_volumes(path: Path) -> Iterator[BinaryIO]:
    base = numeric_volume_base(path)
    if base is None:
        with path.open("rb") as stream:
            yield stream
        return

    try:
        import multivolumefile
    except ImportError as exc:
        from apearchivesextractor.errors import ArchiveDependencyError

        raise ArchiveDependencyError(
            "multivolumefile is required for numbered archive volumes."
        ) from exc

    with multivolumefile.open(base, mode="rb") as raw_stream:
        # MultiVolume.read(size) may stop at a volume boundary. BufferedReader
        # completes sized reads, as archive parsers expect from a normal file.
        with io.BufferedReader(raw_stream) as stream:
            yield stream


def _detect_magic(path: Path) -> ArchiveFormat | None:
    try:
        with path.open("rb") as stream:
            signature = stream.read(8)
    except OSError:
        return None
    if signature.startswith(b"7z\xbc\xaf'\x1c"):
        return ArchiveFormat.SEVEN_Z
    if signature.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return ArchiveFormat.ZIP
    if signature.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00")):
        return ArchiveFormat.RAR
    return None
