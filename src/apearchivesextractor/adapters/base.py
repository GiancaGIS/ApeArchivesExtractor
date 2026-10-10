# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterable

from apearchivesextractor.errors import UnsupportedFeatureError
from apearchivesextractor.models import ArchiveEntry, CancelCallback, ProgressCallback


class ArchiveAdapter(ABC):
    """Common interface implemented by all archive backends."""

    @abstractmethod
    def list_entries(self, archive_path: Path, password: str | None = None) -> list[ArchiveEntry]:
        raise NotImplementedError

    @abstractmethod
    def extract_all(
        self,
        archive_path: Path,
        output_dir: Path,
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def extract_members(
        self,
        archive_path: Path,
        output_dir: Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        """Extract a subset of archive members.

        Directory entries are treated recursively: selecting ``folder`` extracts
        every member whose normalized path starts with ``folder/``.
        """
        raise NotImplementedError

    @abstractmethod
    def create(
        self,
        output_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        raise NotImplementedError

    def delete_members(
        self,
        archive_path: Path,
        members: Iterable[str],
        password: str | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        raise UnsupportedFeatureError("Deleting archive members is not supported for this format.")

    def add_files(
        self,
        archive_path: Path,
        input_paths: Iterable[Path],
        password: str | None = None,
        compression_level: int | None = None,
        progress: ProgressCallback = None,
        should_cancel: CancelCallback = None,
    ) -> None:
        raise UnsupportedFeatureError("Adding files to existing archives is not supported for this format.")
