# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Callable, Optional


class ArchiveFormat(StrEnum):
    ZIP = "zip"
    SEVEN_Z = "7z"
    RAR = "rar"
    TAR_GZ = "tar.gz"


@dataclass(frozen=True, slots=True)
class ArchiveEntry:
    """A normalized representation of one item inside an archive."""

    path: str
    size: int | None
    compressed_size: int | None
    is_dir: bool
    modified_at: Optional[datetime] = None


@dataclass(frozen=True, slots=True)
class ProgressEvent:
    """Simple progress event emitted by adapters.

    processed_bytes can be None when the archive format/library does not expose
    reliable byte-level progress.
    """

    message: str
    current_item: str | None = None
    processed_bytes: int | None = None
    total_bytes: int | None = None


ProgressCallback = Callable[[ProgressEvent], None] | None
CancelCallback = Callable[[], bool] | None


@dataclass(frozen=True, slots=True)
class CreateOptions:
    output_path: Path
    input_paths: list[Path]
    archive_format: ArchiveFormat
    password: str | None = None
    compression_level: int | None = None
    volume_size: int | None = None
