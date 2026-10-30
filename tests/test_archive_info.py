# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import io
import json
from pathlib import Path
import tarfile
import zipfile

import pytest

from apearchivesextractor import archive_info
from apearchivesextractor.archive_info import inspect_archive, format_archive_info
from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.cli import main


def test_zip_metadata_counts_implicit_directories_without_extracting(tmp_path: Path) -> None:
    path = tmp_path / "dati unicode è.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("one/two/readme.txt", b"hello" * 1000)
        archive.writestr("empty/", b"")
    before = path.read_bytes()
    info = inspect_archive(path)
    assert info.files == 1 and info.folders == 3
    assert info.uncompressed_bytes == 5000 and info.archive_bytes == len(before)
    assert info.encrypted is False and "Deflate" in info.methods
    assert info.compression_ratio == pytest.approx(5000 / len(before))
    assert info.space_saving_percent == pytest.approx(100 * (1 - len(before) / 5000))
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]
    assert "File contenuti: 1" in format_archive_info(info, "it")
    assert "integrity was not tested" in format_archive_info(info)


@pytest.mark.parametrize("fmt", ["7z", "tar.gz"])
def test_metadata_works_for_other_formats(tmp_path: Path, fmt: str) -> None:
    source = tmp_path / "input.txt"
    source.write_bytes(b"content" * 1000)
    path = tmp_path / ("archive." + fmt)
    ArchiveService().create(path, [source])
    info = inspect_archive(path)
    assert info.status == "ok" and info.files == 1
    assert info.uncompressed_bytes == source.stat().st_size
    assert info.methods and info.encrypted is False


def test_encrypted_7z_reports_password_and_header_lock(tmp_path: Path) -> None:
    import py7zr
    source = tmp_path / "secret.txt"
    source.write_text("private contents")
    for locked in (False, True):
        path = tmp_path / f"protected-{locked}.7z"
        with py7zr.SevenZipFile(path, "w", password="test-password", header_encryption=locked) as archive:
            archive.write(source, arcname="secret.txt")
        info = inspect_archive(path)
        assert info.encrypted is True
        assert info.status == ("locked" if locked else "ok")
        assert info.files == (None if locked else 1)


def test_split_zip_reports_total_volume_size_from_any_part(tmp_path: Path) -> None:
    source = tmp_path / "source.txt"
    source.write_bytes(bytes(range(256)) * 100)
    ArchiveService().create(tmp_path / "archive.zip", [source], volume_size=100)
    parts = sorted(tmp_path.glob("archive.zip.*"))
    assert len(parts) > 1
    info = inspect_archive(parts[-1])
    assert info.status == "ok" and info.files == 1
    assert info.volumes == len(parts)
    assert info.archive_bytes == sum(part.stat().st_size for part in parts)


def test_unsafe_names_and_links_are_reported_without_extracting(tmp_path: Path) -> None:
    path = tmp_path / "hostile.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("../outside.txt", b"never extracted")
        link = zipfile.ZipInfo("shortcut")
        link.external_attr = 0o120777 << 16
        archive.writestr(link, "../target")
    info = inspect_archive(path)
    assert info.unsafe_names == 1 and info.links == 1
    assert info.notes
    assert list(tmp_path.iterdir()) == [path]


def test_tar_scan_budget_returns_partial_metadata(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "big.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        item = tarfile.TarInfo("large.txt")
        item.size = 1024 * 1024
        archive.addfile(item, io.BytesIO(b"x" * item.size))
        archive.addfile(tarfile.TarInfo("after-limit.txt"), io.BytesIO())
    monkeypatch.setattr(archive_info, "MAX_TAR_SCAN_BYTES", 16 * 1024)
    info = inspect_archive(path)
    assert info.status == "limited" and info.files == 1
    assert info.compression_ratio is None and info.notes
    assert "partial" in format_archive_info(info)


def test_entry_limit_does_not_claim_complete_counts(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "many.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for index in range(5):
            archive.writestr(str(index), b"data")
    monkeypatch.setattr(archive_info, "MAX_INFO_ENTRIES", 2)
    info = inspect_archive(path)
    assert info.status == "limited" and info.files == 2
    assert info.compression_ratio is None


def test_corrupt_archive_and_empty_archive(tmp_path: Path) -> None:
    path = tmp_path / "broken.zip"
    path.write_bytes(b"broken")
    info = inspect_archive(path)
    assert info.status == "error" and info.files is None
    assert "BadZipFile" in info.notes[0]
    with zipfile.ZipFile(path, "w"):
        pass
    info = inspect_archive(path)
    assert info.status == "ok" and info.files == 0 and info.uncompressed_bytes == 0
    assert info.compression_ratio is None


def test_info_cli_json_and_error_exit(tmp_path: Path, capsys) -> None:
    path = tmp_path / "sample.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("item.txt", b"contents")
    assert main(["info", str(path), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["files"] == 1 and data["status"] == "ok"
    path.write_bytes(b"broken")
    assert main(["info", str(path), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "error"


@pytest.mark.parametrize("locked", [False, True])
def test_rar_metadata_uses_filename_and_handles_locked_headers(tmp_path, monkeypatch, locked) -> None:
    import rarfile
    from types import SimpleNamespace
    path = tmp_path / "sample.rar"
    path.write_bytes(b"fixture")

    class HeaderReader:
        def __init__(self, filename, *, errors):
            assert filename == path and errors == "strict"
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def needs_password(self): return locked
        def is_solid(self): return True
        def volumelist(self): return [str(path)]
        def infolist(self):
            return [] if locked else [SimpleNamespace(filename="docs/file.txt", file_size=100,
                compress_size=50, compress_type=0x33, isdir=lambda: False, is_symlink=lambda: False)]

    monkeypatch.setattr(rarfile, "RarFile", HeaderReader)
    info = inspect_archive(path)
    assert info.status == ("locked" if locked else "ok")
    assert info.files == (None if locked else 1)
    assert info.encrypted == locked and info.solid is True
