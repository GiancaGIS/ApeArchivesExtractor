# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tarfile
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from collect_licenses import collect, digest, legal_file, source_snapshot
from prepare_release_sources import copy_archive_notices
from check_release import check


def test_collector_copies_actual_component_notices_without_unrelated_test_tools(tmp_path: Path) -> None:
    for name in ("LICENSE", "NOTICE", "SOURCES.md", "pyproject.toml"):
        (tmp_path / name).write_bytes(Path(name).read_bytes())
    analysis = SimpleNamespace(pure=[("py7zr", importlib.util.find_spec("py7zr").origin, "PYMODULE")], binaries=[])
    output = collect(tmp_path, analysis)
    manifest = json.loads((output / "component-manifest.json").read_text())
    names = {c["name"].lower() for c in manifest["components"]}
    assert "py7zr" in names
    assert "pytest" not in names
    assert manifest["application_license"] == "GPL-3.0-only"
    for component in manifest["components"]:
        assert component["license_files"]
        assert all((output / p).is_file() for p in component["license_files"])
    assert "LESSER GENERAL PUBLIC LICENSE" in next((output / p).read_text() for c in manifest["components"]
                                                    if c["name"] == "py7zr" for p in c["license_files"])


def test_canonical_spdx_license_directory_is_collected() -> None:
    assert legal_file("qtbase/LICENSES/BSD-3-Clause.txt")
    assert legal_file("module/qt_attributions.json")
    assert not legal_file("module/main.cpp")


def test_build_rejects_sources_changed_during_analysis(tmp_path: Path) -> None:
    source = tmp_path / "src"
    source.mkdir()
    module = source / "main.py"
    module.write_text("original source")
    initial = source_snapshot(tmp_path)
    module.write_text("modified source")
    with pytest.raises(RuntimeError, match="changed during the build"):
        collect(tmp_path, SimpleNamespace(pure=[], binaries=[]), initial)


def test_source_license_reader_preserves_nested_notices_and_rejects_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "source.tar.gz"
    with tarfile.open(archive, "w:gz") as output:
        content = b"copyright and terms"
        entry = tarfile.TarInfo("module/LICENSES/MIT.txt")
        entry.size = len(content)
        output.addfile(entry, io.BytesIO(content))
        link = tarfile.TarInfo("module/LICENSE-link")
        link.type = tarfile.SYMTYPE
        link.linkname = "../../../outside"
        output.addfile(link)
    destination = tmp_path / "notices"
    copied = copy_archive_notices(archive, destination)
    assert len(copied) == 2
    assert copied[0].endswith("-MIT.txt")
    assert (destination / copied[0]).read_bytes() == b"copyright and terms"
    index = json.loads((destination / "source-path-index.json").read_text())
    assert index[copied[0]] == "module/LICENSES/MIT.txt"
    with zipfile.ZipFile(tmp_path / "unsafe.zip", "w") as output:
        output.writestr("../../LICENSE", "escape")
    with pytest.raises(ValueError, match="Unsafe archive"):
        copy_archive_notices(tmp_path / "unsafe.zip", destination)


@pytest.fixture
def release(tmp_path: Path) -> tuple[Path, Path, Path]:
    bundle = tmp_path / "bundle"
    legal = bundle / "_internal/apearchivesextractor/legal/generated"
    legal.mkdir(parents=True)
    for name in ("LICENSE", "NOTICE", "SOURCES.md", "THIRD_PARTY_NOTICES.md"):
        (legal / name).write_text("legal text", encoding="utf-8")
    binary = bundle / "_internal/library.dll"
    binary.write_bytes(b"original binary")
    inventory = {"application_version": "1.0.0", "components": [], "application_binaries": [],
                 "binaries": [{"path": "library.dll", "bundled_sha256": digest(binary)}]}
    (legal / "component-manifest.json").write_text(json.dumps(inventory))
    code = b"source code"
    dependency = b"dependency source archive"
    sources = {"component_manifest_sha256": digest(legal / "component-manifest.json"),
               "application_files_sha256": {"main.py": hashlib.sha256(code).hexdigest()},
               "sources": [{"filename": "dependency.tar.gz", "sha256": hashlib.sha256(dependency).hexdigest(), "notice_files": []}]}
    (legal / "source-manifest.json").write_text(json.dumps(sources))
    companion = tmp_path / "sources.zip"
    with zipfile.ZipFile(companion, "w") as archive:
        archive.write(legal / "source-manifest.json", "legal/source-manifest.json")
        archive.writestr("application/main.py", code)
        archive.writestr("dependencies/dependency.tar.gz", dependency)
    review = {"component_manifest_sha256": digest(legal / "component-manifest.json"),
              "source_manifest_sha256": digest(legal / "source-manifest.json"), "reviewer": "Test reviewer",
              "evidence": "Fixture evidence", "native_components_reviewed": True,
              "asset_rights_confirmed": True, "corresponding_source_verified": True}
    (legal / "release-review.json").write_text(json.dumps(review))
    return bundle, legal, companion


def test_release_accepts_matching_sources_and_review(release) -> None:
    bundle, _legal, companion = release
    check(bundle, companion)


def test_release_rejects_changed_binary(release) -> None:
    bundle, _legal, companion = release
    (bundle / "_internal/library.dll").write_bytes(b"different")
    with pytest.raises(RuntimeError, match="Binary changed"):
        check(bundle, companion)


def test_release_rejects_missing_and_stale_review(release) -> None:
    bundle, legal, companion = release
    original = (legal / "release-review.json").read_text()
    (legal / "release-review.json").unlink()
    with pytest.raises(RuntimeError, match="pending"):
        check(bundle, companion)
    review = json.loads(original)
    review["component_manifest_sha256"] = "outdated"
    (legal / "release-review.json").write_text(json.dumps(review))
    with pytest.raises(RuntimeError, match="Stale"):
        check(bundle, companion)


def test_release_rejects_substituted_source_archive(release) -> None:
    bundle, _legal, companion = release
    with zipfile.ZipFile(companion) as archive:
        entries = {name: archive.read(name) for name in archive.namelist()}
    entries["dependencies/dependency.tar.gz"] = b"substituted source"
    with zipfile.ZipFile(companion, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    with pytest.raises(RuntimeError, match="digest mismatch"):
        check(bundle, companion)
