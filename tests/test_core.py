# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import hashlib
import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import (
    ArchiveLimitExceededError,
    ArchiveMemberNotFoundError,
    OperationCancelledError,
    UnsafeArchivePathError,
    UnsupportedFeatureError,
)
from apearchivesextractor.models import ArchiveFormat, ProgressEvent
from apearchivesextractor.security import normalize_archive_name


def _make_sample_tree(root: Path) -> Path:
    source = root / "sample"
    (source / "nested").mkdir(parents=True)
    (source / "alpha.txt").write_text("alpha", encoding="utf-8")
    (source / "nested" / "beta.txt").write_text("beta", encoding="utf-8")
    return source


def test_detect_supported_formats() -> None:
    service = ArchiveService()
    assert service.detect_format("demo.zip") == ArchiveFormat.ZIP
    assert service.detect_format("demo.7z") == ArchiveFormat.SEVEN_Z
    assert service.detect_format("demo.tar.gz") == ArchiveFormat.TAR_GZ
    assert service.detect_format("demo.rar") == ArchiveFormat.RAR
    assert service.detect_format("demo.7z.001") == ArchiveFormat.SEVEN_Z
    assert service.detect_format("demo.zip.003") == ArchiveFormat.ZIP
    assert service.detect_format("demo.r01") == ArchiveFormat.RAR
    assert service.detect_format("demo.z01") == ArchiveFormat.ZIP


def test_cli_uses_short_program_name() -> None:
    from apearchivesextractor.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["create", "output.zip", "input", "--volume-size", "100M"])

    assert parser.prog == "ape-arch"
    assert args.volume_size == 100 * 1024 ** 2
    assert parser.parse_args(["create", "output.rar", "input", "--format", "rar"]).format == "rar"


def test_generic_later_numbered_volume_uses_first_volume_signature(tmp_path: Path) -> None:
    (tmp_path / "generic.001").write_bytes(b"7z\xbc\xaf'\x1c\x00\x04")
    later = tmp_path / "generic.002"
    later.write_bytes(b"continuation")
    assert ArchiveService().detect_format(later) == ArchiveFormat.SEVEN_Z


def test_numbered_zip_volumes_can_be_listed_and_extracted(tmp_path: Path) -> None:
    service = ArchiveService()
    complete = tmp_path / "numbered.zip"
    with zipfile.ZipFile(complete, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("folder/payload.txt", "numbered payload")

    payload = complete.read_bytes()
    complete.unlink()
    split = len(payload) // 2
    first = tmp_path / "numbered.zip.001"
    first.write_bytes(payload[:split])
    (tmp_path / "numbered.zip.002").write_bytes(payload[split:])

    assert [entry.path for entry in service.list_entries(first)] == ["folder/payload.txt"]
    output = tmp_path / "numbered-out"
    service.extract_all(first, output)
    assert (output / "folder" / "payload.txt").read_text() == "numbered payload"


def test_create_numbered_zip_volumes_roundtrip(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "payload.bin"
    source.write_bytes(os.urandom(220_000))
    archive_path = tmp_path / "created.zip"

    created_path = service.create(
        archive_path,
        [source],
        archive_format="zip",
        volume_size=64 * 1024,
    )

    volumes = sorted(tmp_path.glob("created.zip.[0-9][0-9][0-9]"))
    assert created_path == tmp_path / "created.zip.001"
    assert len(volumes) >= 2
    assert all(volume.stat().st_size <= 64 * 1024 for volume in volumes)
    assert not archive_path.exists()

    output = tmp_path / "created-out"
    service.extract_all(created_path, output)
    assert (output / source.name).read_bytes() == source.read_bytes()


def test_recreating_numbered_zip_removes_stale_volumes(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "payload.bin"
    source.write_bytes(os.urandom(180_000))
    archive_path = tmp_path / "replace.zip"
    service.create(archive_path, [source], archive_format="zip", volume_size=32 * 1024)
    assert len(list(tmp_path.glob("replace.zip.[0-9][0-9][0-9]"))) >= 3

    source.write_bytes(b"replacement")
    service.create(archive_path, [source], archive_format="zip", volume_size=32 * 1024)

    assert [path.name for path in tmp_path.glob("replace.zip.[0-9][0-9][0-9]")] == [
        "replace.zip.001"
    ]


def test_regular_zip_replaces_existing_numbered_volume_set(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "payload.bin"
    source.write_bytes(os.urandom(100_000))
    archive_path = tmp_path / "switch.zip"
    service.create(archive_path, [source], archive_format="zip", volume_size=24 * 1024)
    assert list(tmp_path.glob("switch.zip.[0-9][0-9][0-9]"))

    service.create(archive_path, [source], archive_format="zip")

    assert archive_path.is_file()
    assert not list(tmp_path.glob("switch.zip.[0-9][0-9][0-9]"))
    assert [entry.path for entry in service.list_entries(archive_path)] == [source.name]


def test_multi_volume_creation_rejects_tar_gz(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "payload.txt"
    source.write_text("payload")

    with pytest.raises(UnsupportedFeatureError, match="ZIP, 7Z, and RAR"):
        service.create(tmp_path / "archive.tar.gz", [source], volume_size=1024)


def test_multi_volume_creation_rejects_more_than_999_parts(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "payload.bin"
    source.write_bytes(os.urandom(2_000))

    with pytest.raises(UnsupportedFeatureError, match="999 parts"):
        service.create(tmp_path / "archive.zip", [source], volume_size=1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1024", 1024),
        ("100M", 100 * 1024 ** 2),
        ("700 MB", 700 * 1024 ** 2),
        ("1.5GiB", int(1.5 * 1024 ** 3)),
    ],
)
def test_parse_volume_size(value: str, expected: int) -> None:
    from apearchivesextractor.volume_size import parse_volume_size

    assert parse_volume_size(value) == expected


def test_pkzip_z_volumes_can_be_listed_and_extracted(tmp_path: Path) -> None:
    service = ArchiveService()
    final_volume = tmp_path / "classic.zip"
    with zipfile.ZipFile(final_volume, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.txt", "classic split payload")

    payload = bytearray(final_volume.read_bytes())
    eocd = payload.rfind(b"PK\x05\x06")
    central = int.from_bytes(payload[eocd + 16:eocd + 20], "little")
    payload[eocd + 4:eocd + 6] = (1).to_bytes(2, "little")
    payload[eocd + 6:eocd + 8] = (1).to_bytes(2, "little")
    payload[eocd + 16:eocd + 20] = (0).to_bytes(4, "little")
    (tmp_path / "classic.z01").write_bytes(payload[:central])
    final_volume.write_bytes(payload[central:])

    selected_volume = tmp_path / "classic.z01"
    assert [entry.path for entry in service.list_entries(selected_volume)] == ["payload.txt"]
    output = tmp_path / "classic-out"
    service.extract_all(selected_volume, output)
    assert (output / "payload.txt").read_text() == "classic split payload"


def test_numbered_7z_volumes_can_be_listed_and_extracted(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    complete = tmp_path / "numbered.7z"
    source = tmp_path / "seven.txt"
    source.write_text("seven volume payload")
    with py7zr.SevenZipFile(complete, "w") as archive:
        archive.write(source, "seven.txt")

    payload = complete.read_bytes()
    complete.unlink()
    split = len(payload) // 2
    first = tmp_path / "numbered.7z.001"
    first.write_bytes(payload[:split])
    (tmp_path / "numbered.7z.002").write_bytes(payload[split:])

    service = ArchiveService()
    assert [entry.path for entry in service.list_entries(first)] == ["seven.txt"]
    output = tmp_path / "seven-out"
    service.extract_all(first, output)
    assert (output / "seven.txt").read_text() == "seven volume payload"


def test_create_numbered_7z_volumes_roundtrip(tmp_path: Path) -> None:
    pytest.importorskip("py7zr")
    source = tmp_path / "payload.bin"
    source.write_bytes(os.urandom(220_000))
    archive_path = tmp_path / "created.7z"
    service = ArchiveService()

    created_path = service.create(archive_path, [source], volume_size=64 * 1024)

    volumes = sorted(tmp_path.glob("created.7z.[0-9][0-9][0-9]"))
    assert created_path == tmp_path / "created.7z.001"
    assert len(volumes) >= 2
    assert all(volume.stat().st_size <= 64 * 1024 for volume in volumes)
    output = tmp_path / "created-7z-out"
    service.extract_all(created_path, output)
    assert (output / source.name).read_bytes() == source.read_bytes()


def test_rar_creation_uses_external_backend(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apearchivesextractor.adapters import rar_adapter

    source = tmp_path / "payload.txt"
    source.write_text("payload", encoding="utf-8")
    output = tmp_path / "created.rar"
    captured: list[str] = []

    class FakeProcess:
        returncode = 0

        def poll(self) -> int:
            return self.returncode

    def fake_popen(args: list[str], **_kwargs: object) -> FakeProcess:
        captured.extend(args)
        Path(args[args.index("--") + 1]).write_bytes(b"Rar!\x1a\x07\x01\x00")
        return FakeProcess()

    monkeypatch.setattr(rar_adapter, "_find_rar_command", lambda: "rar")
    monkeypatch.setattr(rar_adapter.subprocess, "Popen", fake_popen)

    rar_adapter.RarAdapter().create(output, [source], password="secret", compression_level=9)

    assert output.is_file()
    assert "-m5" in captured
    assert "-psecret" in captured
    assert captured[-1] == str(source.resolve())


def test_gui_translations_have_matching_keys() -> None:
    from apearchivesextractor.gui.i18n import TRANSLATIONS, normalize_language, translate

    assert set(TRANSLATIONS["it"]) == set(TRANSLATIONS["en"])
    assert normalize_language("missing") == "it"
    assert translate("en", "button.open") == "Open..."


def test_gui_worker_progress_accepts_large_byte_counts() -> None:
    from apearchivesextractor.gui.workers import ArchiveWorker

    worker = ArchiveWorker("noop")
    events: list[tuple[str, str, int, int]] = []
    worker.progress.connect(
        lambda message, item, processed, total: events.append((message, item, processed, total))
    )

    worker._emit_progress(
        ProgressEvent(
            "Adding",
            "huge.bin",
            processed_bytes=5 * 1024**3,
            total_bytes=6 * 1024**3,
        )
    )

    assert events == [("Adding", "huge.bin", 5 * 1024**3, 6 * 1024**3)]


def test_gui_worker_progress_throttles_repeated_updates() -> None:
    from apearchivesextractor.gui.workers import ArchiveWorker

    worker = ArchiveWorker("noop")
    worker._progress_emit_interval_seconds = 3600
    events: list[tuple[str, str, int, int]] = []
    worker.progress.connect(
        lambda message, item, processed, total: events.append((message, item, processed, total))
    )

    worker._emit_progress(ProgressEvent("Adding", "huge.bin", 0, 100))
    for processed in range(1, 10):
        worker._emit_progress(ProgressEvent("Adding", "huge.bin", processed, 100))
    worker._emit_progress(ProgressEvent("Adding", "huge.bin", 100, 100))

    assert [event[2] for event in events] == [0, 100]


def test_original_cleanup_detects_output_inside_deleted_folder(tmp_path: Path) -> None:
    from apearchivesextractor.gui.originals_cleanup import output_is_inside_inputs

    source = tmp_path / "source"
    source.mkdir()
    output = source / "archive.zip"

    assert output_is_inside_inputs(output, [source]) == source
    assert output_is_inside_inputs(tmp_path / "archive.zip", [source]) is None


def test_original_cleanup_deletes_top_level_inputs_only(tmp_path: Path) -> None:
    from apearchivesextractor.gui.originals_cleanup import delete_original_inputs

    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    child = nested / "child.txt"
    child.write_text("child", encoding="utf-8")
    sibling = tmp_path / "sibling.txt"
    sibling.write_text("sibling", encoding="utf-8")

    deleted = delete_original_inputs([source, child, sibling])

    assert set(deleted) == {source.resolve(), sibling.resolve()}
    assert not source.exists()
    assert not sibling.exists()


@pytest.mark.parametrize(
    "archive_name, archive_format",
    [
        ("sample.zip", "zip"),
        ("sample.tar.gz", "tar.gz"),
    ],
)
def test_create_list_and_extract_selected_for_standard_formats(
    tmp_path: Path,
    archive_name: str,
    archive_format: str,
) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / archive_name
    output_dir = tmp_path / "out"

    service.create(archive_path, [source], archive_format=archive_format)
    entries = service.list_entries(archive_path)
    paths = {entry.path.rstrip("/") for entry in entries}

    assert "sample/alpha.txt" in paths
    assert "sample/nested/beta.txt" in paths

    service.extract_members(archive_path, output_dir, ["sample/nested"])

    assert not (output_dir / "sample" / "alpha.txt").exists()
    assert (output_dir / "sample" / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta"


@pytest.mark.parametrize(
    "archive_name, archive_format",
    [
        ("sample.zip", "zip"),
        ("sample.tar.gz", "tar.gz"),
    ],
)
def test_extract_single_selected_file_for_standard_formats(
    tmp_path: Path,
    archive_name: str,
    archive_format: str,
) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / archive_name
    output_dir = tmp_path / "single_out"

    service.create(archive_path, [source], archive_format=archive_format)
    service.extract_members(archive_path, output_dir, ["sample/nested/beta.txt"])

    assert not (output_dir / "sample" / "alpha.txt").exists()
    assert (output_dir / "sample" / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta"


@pytest.mark.parametrize(
    "archive_name, archive_format",
    [
        ("sample.zip", "zip"),
        ("sample.tar.gz", "tar.gz"),
    ],
)
def test_extract_single_file_flat_for_standard_formats(
    tmp_path: Path,
    archive_name: str,
    archive_format: str,
) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / archive_name
    output_dir = tmp_path / "flat_out"

    service.create(archive_path, [source], archive_format=archive_format)
    service.extract_member_flat(archive_path, output_dir, "sample/nested/beta.txt")

    assert (output_dir / "beta.txt").read_text(encoding="utf-8") == "beta"
    assert not (output_dir / "sample").exists()


@pytest.mark.parametrize(
    "archive_name, archive_format",
    [
        ("sample.zip", "zip"),
        ("sample.tar.gz", "tar.gz"),
    ],
)
def test_extract_multiple_files_flat_for_standard_formats(
    tmp_path: Path,
    archive_name: str,
    archive_format: str,
) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / archive_name
    output_dir = tmp_path / "flat_multi_out"

    service.create(archive_path, [source], archive_format=archive_format)
    service.extract_members_flat(
        archive_path,
        output_dir,
        ["sample/alpha.txt", "sample/nested/beta.txt"],
        archive_format=archive_format,
    )

    assert (output_dir / "alpha.txt").read_text(encoding="utf-8") == "alpha"
    assert (output_dir / "beta.txt").read_text(encoding="utf-8") == "beta"
    assert not (output_dir / "sample").exists()


def test_extract_multiple_files_flat_rejects_duplicate_output_names(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "sample"
    (source / "one").mkdir(parents=True)
    (source / "two").mkdir(parents=True)
    (source / "one" / "same.txt").write_text("one", encoding="utf-8")
    (source / "two" / "same.txt").write_text("two", encoding="utf-8")
    archive_path = tmp_path / "sample.zip"

    service.create(archive_path, [source], archive_format="zip")

    with pytest.raises(UnsupportedFeatureError):
        service.extract_members_flat(
            archive_path,
            tmp_path / "flat_duplicate_out",
            ["sample/one/same.txt", "sample/two/same.txt"],
            archive_format="zip",
        )


def test_calculate_member_hashes_for_zip(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.zip"
    payload = b"beta"

    service.create(archive_path, [source], archive_format="zip")

    hashes = service.calculate_member_hashes(archive_path, "sample/nested/beta.txt", archive_format="zip")

    assert hashes == {
        "MD5": hashlib.md5(payload).hexdigest(),
        "SHA1": hashlib.sha1(payload).hexdigest(),
        "SHA256": hashlib.sha256(payload).hexdigest(),
    }


def test_zip_password_creation_is_rejected(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)

    with pytest.raises(UnsupportedFeatureError):
        service.create(tmp_path / "encrypted.zip", [source], archive_format="zip", password="secret")


def test_zip_like_file_can_be_opened_with_forced_zip_format(tmp_path: Path) -> None:
    service = ArchiveService()
    wheel_path = tmp_path / "demo.whl"

    with zipfile.ZipFile(wheel_path, "w") as archive:
        archive.writestr("demo/__init__.py", "")
        archive.writestr("demo-1.0.dist-info/METADATA", "Name: demo\n")

    entries = service.list_entries(wheel_path, archive_format="zip")

    assert {entry.path for entry in entries} == {
        "demo/__init__.py",
        "demo-1.0.dist-info/METADATA",
    }


def test_zip_delete_members_removes_selected_folder_only(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.zip"

    service.create(archive_path, [source], archive_format="zip")
    service.delete_members(archive_path, ["sample/nested"], archive_format="zip")

    paths = {entry.path.rstrip("/") for entry in service.list_entries(archive_path)}
    assert "sample/alpha.txt" in paths
    assert "sample/nested/beta.txt" not in paths
    assert "sample/nested" not in paths


def test_zip_add_file_replaces_existing_root_member(tmp_path: Path) -> None:
    service = ArchiveService()
    original = tmp_path / "alpha.txt"
    original.write_text("old", encoding="utf-8")
    archive_path = tmp_path / "sample.zip"
    service.create(archive_path, [original], archive_format="zip")

    replacement = tmp_path / "replacement" / "alpha.txt"
    replacement.parent.mkdir()
    replacement.write_text("new", encoding="utf-8")

    service.add_files(archive_path, [replacement], archive_format="zip")

    entries = service.list_entries(archive_path)
    assert [entry.path for entry in entries].count("alpha.txt") == 1
    extract_dir = tmp_path / "out"
    service.extract_all(archive_path, extract_dir)
    assert (extract_dir / "alpha.txt").read_text(encoding="utf-8") == "new"


def test_delete_members_is_rejected_for_tar_gz(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.tar.gz"

    service.create(archive_path, [source], archive_format="tar.gz")

    with pytest.raises(UnsupportedFeatureError):
        service.delete_members(archive_path, ["sample/nested"], archive_format="tar.gz")


@pytest.mark.parametrize(
    "archive_name, archive_format",
    [
        ("sample.zip", "zip"),
        ("sample.tar.gz", "tar.gz"),
    ],
)
def test_create_reports_determinate_progress_for_standard_formats(
    tmp_path: Path,
    archive_name: str,
    archive_format: str,
) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    events: list[ProgressEvent] = []

    service.create(
        tmp_path / archive_name,
        [source],
        archive_format=archive_format,
        progress=events.append,
    )

    determinate_events = [
        event
        for event in events
        if event.total_bytes is not None and event.total_bytes > 0 and event.processed_bytes is not None
    ]
    assert determinate_events
    assert determinate_events[-1].processed_bytes == determinate_events[-1].total_bytes


def test_extract_selected_missing_member_reports_error(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.zip"

    service.create(archive_path, [source], archive_format="zip")

    with pytest.raises(ArchiveMemberNotFoundError):
        service.extract_members(archive_path, tmp_path / "out", ["sample/missing.txt"])


def test_zip_path_traversal_is_blocked(tmp_path: Path) -> None:
    service = ArchiveService()
    archive_path = tmp_path / "evil.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../evil.txt", "nope")

    with pytest.raises(UnsafeArchivePathError):
        service.extract_all(archive_path, tmp_path / "out")

    assert not (tmp_path / "evil.txt").exists()


@pytest.mark.parametrize(
    "member_name",
    [
        "victim.txt::$DATA",
        "folder/CON.txt",
        "folder/trailing.",
        "folder/trailing ",
        "folder/name?.txt",
        "folder/control\x01.txt",
    ],
)
def test_windows_unsafe_archive_names_are_blocked(member_name: str) -> None:
    with pytest.raises(UnsafeArchivePathError):
        normalize_archive_name(member_name)


def test_zip_ntfs_data_stream_alias_cannot_overwrite_existing_file(tmp_path: Path) -> None:
    service = ArchiveService()
    archive_path = tmp_path / "ads.zip"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    victim = output_dir / "victim.txt"
    victim.write_text("original", encoding="utf-8")

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("victim.txt::$DATA", "replaced")

    with pytest.raises(UnsafeArchivePathError):
        service.extract_all(archive_path, output_dir)

    assert victim.read_text(encoding="utf-8") == "original"


def test_extraction_replaces_hard_link_without_changing_its_target(tmp_path: Path) -> None:
    service = ArchiveService()
    archive_path = tmp_path / "hardlink.zip"
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("original", encoding="utf-8")
    destination = output_dir / "victim.txt"
    os.link(outside, destination)

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("victim.txt", "replacement")

    service.extract_all(archive_path, output_dir)

    assert outside.read_text(encoding="utf-8") == "original"
    assert destination.read_text(encoding="utf-8") == "replacement"


def test_create_replaces_hard_link_without_changing_its_target(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "source.txt"
    source.write_text("source", encoding="utf-8")
    outside = tmp_path / "outside.bin"
    outside.write_text("original", encoding="utf-8")
    archive_path = tmp_path / "archive.zip"
    os.link(outside, archive_path)

    service.create(archive_path, [source], archive_format="zip")

    assert outside.read_text(encoding="utf-8") == "original"
    assert zipfile.is_zipfile(archive_path)


def test_create_archive_inside_input_does_not_include_temporary_output(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "source"
    source.mkdir()
    (source / "input.txt").write_text("input", encoding="utf-8")
    archive_path = source / "archive.zip"

    service.create(archive_path, [source], archive_format="zip")

    with zipfile.ZipFile(archive_path, "r") as archive:
        assert archive.testzip() is None
        assert archive.namelist() == ["source/", "source/input.txt"]


def test_create_rejects_symlinked_inputs(tmp_path: Path) -> None:
    service = ArchiveService()
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    linked_input = source / "linked.txt"
    try:
        linked_input.symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"Symlinks are not available in this test environment: {exc}")

    with pytest.raises(UnsafeArchivePathError):
        service.create(tmp_path / "archive.zip", [source], archive_format="zip")

    assert not (tmp_path / "archive.zip").exists()


def test_tar_gz_path_traversal_is_blocked(tmp_path: Path) -> None:
    service = ArchiveService()
    archive_path = tmp_path / "evil.tar.gz"
    payload = b"nope"

    with tarfile.open(archive_path, "w:gz") as archive:
        info = tarfile.TarInfo("../evil.txt")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))

    with pytest.raises(UnsafeArchivePathError):
        service.extract_all(archive_path, tmp_path / "out")

    assert not (tmp_path / "evil.txt").exists()


def test_zip_extraction_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apearchivesextractor.security import ArchiveSafetyLimits

    service = ArchiveService()
    archive_path = tmp_path / "too_many.zip"

    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")

    monkeypatch.setattr(
        "apearchivesextractor.security.DEFAULT_EXTRACTION_LIMITS",
        ArchiveSafetyLimits(max_entries=1),
    )

    with pytest.raises(ArchiveLimitExceededError):
        service.extract_all(archive_path, tmp_path / "out")


def test_zip_listing_limit_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apearchivesextractor.security import ArchiveSafetyLimits

    service = ArchiveService()
    archive_path = tmp_path / "too_many.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("one.txt", "one")
        archive.writestr("two.txt", "two")

    monkeypatch.setattr(
        "apearchivesextractor.security.DEFAULT_EXTRACTION_LIMITS",
        ArchiveSafetyLimits(max_entries=1),
    )

    with pytest.raises(ArchiveLimitExceededError):
        service.list_entries(archive_path)


def test_7z_roundtrip_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.7z"
    output_dir = tmp_path / "out7z"

    service.create(archive_path, [source], archive_format="7z", password="secret")
    entries = service.list_entries(archive_path, password="secret")
    assert any(entry.path.rstrip("/") == "sample/nested/beta.txt" for entry in entries)

    service.extract_members(archive_path, output_dir, ["sample/nested"], password="secret")
    assert (output_dir / "sample" / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta"


def test_7z_extract_single_selected_file_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.7z"
    output_dir = tmp_path / "single_out7z"

    service.create(archive_path, [source], archive_format="7z", password="secret")
    service.extract_members(archive_path, output_dir, ["sample/nested/beta.txt"], password="secret")

    assert not (output_dir / "sample" / "alpha.txt").exists()
    assert (output_dir / "sample" / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta"


def test_7z_extract_single_file_flat_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.7z"
    output_dir = tmp_path / "flat_out7z"

    service.create(archive_path, [source], archive_format="7z", password="secret")
    service.extract_member_flat(archive_path, output_dir, "sample/nested/beta.txt", password="secret")

    assert (output_dir / "beta.txt").read_text(encoding="utf-8") == "beta"
    assert not (output_dir / "sample").exists()


def test_7z_calculate_member_hashes_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.7z"
    payload = b"beta"

    service.create(archive_path, [source], archive_format="7z", password="secret")

    hashes = service.calculate_member_hashes(
        archive_path,
        "sample/nested/beta.txt",
        archive_format="7z",
        password="secret",
    )

    assert hashes == {
        "MD5": hashlib.md5(payload).hexdigest(),
        "SHA1": hashlib.sha1(payload).hexdigest(),
        "SHA256": hashlib.sha256(payload).hexdigest(),
    }


def test_7z_add_file_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.7z"
    service.create(archive_path, [source], archive_format="7z", password="secret")

    extra = tmp_path / "extra.txt"
    extra.write_text("extra", encoding="utf-8")

    service.add_files(archive_path, [extra], archive_format="7z", password="secret")

    output_dir = tmp_path / "out_added7z"
    service.extract_all(archive_path, output_dir, password="secret")
    assert (output_dir / "sample" / "nested" / "beta.txt").read_text(encoding="utf-8") == "beta"
    assert (output_dir / "extra.txt").read_text(encoding="utf-8") == "extra"


def test_7z_create_reports_determinate_progress_when_py7zr_is_available(tmp_path: Path) -> None:
    py7zr = pytest.importorskip("py7zr")
    assert py7zr is not None

    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    events: list[ProgressEvent] = []

    service.create(
        tmp_path / "sample.7z",
        [source],
        archive_format="7z",
        progress=events.append,
    )

    determinate_events = [
        event
        for event in events
        if event.total_bytes is not None and event.total_bytes > 0 and event.processed_bytes is not None
    ]
    assert determinate_events
    assert determinate_events[-1].processed_bytes == determinate_events[-1].total_bytes


def test_zip_create_can_be_cancelled_cooperatively(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)

    with pytest.raises(OperationCancelledError):
        service.create(
            tmp_path / "cancelled.zip",
            [source],
            archive_format="zip",
            should_cancel=lambda: True,
        )


def test_tar_gz_extract_can_be_cancelled_cooperatively(tmp_path: Path) -> None:
    service = ArchiveService()
    source = _make_sample_tree(tmp_path)
    archive_path = tmp_path / "sample.tar.gz"
    service.create(archive_path, [source], archive_format="tar.gz")

    with pytest.raises(OperationCancelledError):
        service.extract_all(
            archive_path,
            tmp_path / "cancelled_out",
            should_cancel=lambda: True,
        )


def test_existing_output_paths_detects_selected_conflicts_only(tmp_path: Path) -> None:
    from apearchivesextractor.gui.extraction_planner import existing_output_paths
    from apearchivesextractor.models import ArchiveEntry

    entries = [
        ArchiveEntry("sample/alpha.txt", size=5, compressed_size=5, is_dir=False),
        ArchiveEntry("sample/nested/beta.txt", size=4, compressed_size=4, is_dir=False),
        ArchiveEntry("sample/nested", size=None, compressed_size=None, is_dir=True),
    ]
    output_dir = tmp_path / "out"
    (output_dir / "sample").mkdir(parents=True)
    (output_dir / "sample" / "alpha.txt").write_text("old", encoding="utf-8")

    conflicts = existing_output_paths(entries, output_dir, members=["sample/nested"])
    assert conflicts == []

    conflicts = existing_output_paths(entries, output_dir, members=None)
    assert conflicts == [output_dir / "sample" / "alpha.txt"]


def test_existing_output_paths_can_detect_flat_single_file_conflict(tmp_path: Path) -> None:
    from apearchivesextractor.gui.extraction_planner import existing_output_paths
    from apearchivesextractor.models import ArchiveEntry

    entries = [
        ArchiveEntry("sample/nested/beta.txt", size=4, compressed_size=4, is_dir=False),
    ]
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "beta.txt").write_text("old", encoding="utf-8")

    conflicts = existing_output_paths(
        entries,
        output_dir,
        members=["sample/nested/beta.txt"],
        flatten_single_file=True,
    )

    assert conflicts == [output_dir / "beta.txt"]


def test_existing_output_paths_can_detect_flat_multi_file_conflict(tmp_path: Path) -> None:
    from apearchivesextractor.gui.extraction_planner import existing_output_paths
    from apearchivesextractor.models import ArchiveEntry

    entries = [
        ArchiveEntry("sample/alpha.txt", size=5, compressed_size=5, is_dir=False),
        ArchiveEntry("sample/nested/beta.txt", size=4, compressed_size=4, is_dir=False),
    ]
    output_dir = tmp_path / "out"
    output_dir.mkdir()
    (output_dir / "beta.txt").write_text("old", encoding="utf-8")

    conflicts = existing_output_paths(
        entries,
        output_dir,
        members=["sample/alpha.txt", "sample/nested/beta.txt"],
        flatten_files=True,
    )

    assert conflicts == [output_dir / "beta.txt"]
