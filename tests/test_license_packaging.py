# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import importlib.util
import json
import sys
import tarfile
import io
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build_tools/common"))
import check_release
from collect_licenses import collect, digest, legal_file, source_snapshot
import prepare_release_sources
from prepare_release_sources import copy_archive_notices
from check_release import check, check_bundle


def test_collector_copies_actual_component_notices_without_unrelated_test_tools(tmp_path: Path) -> None:
    for name in ("LICENSE", "NOTICE", "SOURCES.md", "pyproject.toml"):
        source = Path("src/apearchivesextractor/legal/NOTICE.txt") if name == "NOTICE" else Path(name)
        (tmp_path / name).write_bytes(source.read_bytes())
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
    assert not legal_file("module/licenses/__pycache__/__init__.cpython-314.pyc")


def test_pyside_inventory_excludes_unused_shared_namespace_distributions(tmp_path: Path) -> None:
    for name in ("LICENSE", "SOURCES.md", "pyproject.toml"):
        (tmp_path / name).write_bytes(Path(name).read_bytes())
    notice = tmp_path / "src/apearchivesextractor/legal/NOTICE.txt"
    notice.parent.mkdir(parents=True)
    notice.write_bytes(Path("src/apearchivesextractor/legal/NOTICE.txt").read_bytes())
    analysis = SimpleNamespace(pure=[("PySide6", importlib.util.find_spec("PySide6").origin, "PYMODULE")], binaries=[])
    output = collect(tmp_path, analysis)
    manifest = json.loads((output / "component-manifest.json").read_text())
    names = {c["name"].lower().replace("_", "-") for c in manifest["components"]}
    assert "pyside6-essentials" in names
    assert not names.intersection({"pyside6-addons", "pyside6-webengine", "pyside6-pdf"})
    assert manifest["qt_version"]
    assert "PySide6" in (output / "NOTICE").read_text(encoding="utf-8")


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
    checkout = tmp_path / "src"
    checkout.mkdir()
    (checkout / "main.py").write_bytes(b"source code")
    cache = tmp_path / "cache/source-cache"
    cache.mkdir(parents=True)
    dependency = cache / "dependency.tar.gz"
    dependency.write_bytes(b"dependency source archive")
    snapshot = source_snapshot(tmp_path)
    inventory = {"application_version": "1.0.0", "components": [], "application_binaries": [],
                 "application_files_sha256": snapshot,
                 "binaries": [{"path": "library.dll", "bundled_sha256": digest(binary)}]}
    (legal / "component-manifest.json").write_text(json.dumps(inventory))
    sources = {"application_version": "1.0.0", "component_manifest_sha256": digest(legal / "component-manifest.json"),
               "application_files_sha256": snapshot,
               "legal_files_sha256": {path.name: digest(path) for path in legal.iterdir()},
               "sources": [{"filename": dependency.name, "sha256": digest(dependency),
                            "url": "https://example.org/dependency.tar.gz", "notice_files": []}]}
    (legal / "source-manifest.json").write_text(json.dumps(sources))
    companion = tmp_path / "sources.zip"
    with zipfile.ZipFile(companion, "w") as archive:
        for path in legal.iterdir():
            archive.write(path, "legal/" + path.name)
        archive.write(checkout / "main.py", "application/src/main.py")
        archive.write(dependency, "dependencies/dependency.tar.gz")
    return bundle, legal, companion


def test_release_accepts_matching_sources_and_license_files(release) -> None:
    bundle, _legal, companion = release
    check(bundle, companion)


def test_local_bundle_checks_work_without_source_zip(release) -> None:
    bundle, _legal, companion = release
    companion.unlink()
    check_bundle(bundle)
    with pytest.raises(FileNotFoundError):
        check(bundle, companion)


def test_release_can_export_sources_later_from_the_sealed_bundle(release, tmp_path, monkeypatch) -> None:
    bundle, legal, companion = release
    companion.unlink()
    monkeypatch.setattr(prepare_release_sources, "ROOT", tmp_path)
    monkeypatch.setattr(prepare_release_sources, "CACHE_ROOT", tmp_path / "cache")
    before = digest(legal / "source-manifest.json")
    assert prepare_release_sources.write_companion(bundle, companion) == companion
    assert digest(legal / "source-manifest.json") == before
    check(bundle, companion)

    (tmp_path / "src/main.py").write_text("different source")
    before = digest(companion)
    with pytest.raises(RuntimeError, match="source snapshot differs"):
        prepare_release_sources.write_companion(bundle, companion)
    assert digest(companion) == before


def test_dependency_sources_can_be_prepared_before_pushing_the_tag(release, tmp_path, monkeypatch) -> None:
    bundle, _legal, _companion = release
    monkeypatch.setattr(prepare_release_sources, "CACHE_ROOT", tmp_path / "cache")
    (tmp_path / "src/main.py").write_text("later checkout contents")
    requests = []

    def tag_archive(url):
        requests.append(url)
        assert url.endswith("/archive/refs/tags/v1.0.0.zip")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("ApeArchivesExtractor-1.0.0/src/main.py", b"source code")
        return output.getvalue()

    monkeypatch.setattr(check_release, "github_source_archive", tag_archive)
    companion = prepare_release_sources.write_companion(bundle, github_tag="v1.0.0")
    assert requests == []
    assert companion.name == "ApeArchivesExtractor-DependencySources-1.0.0.zip"
    with zipfile.ZipFile(companion) as archive:
        assert "dependencies/dependency.tar.gz" in archive.namelist()
        assert not any(name.startswith("application/") for name in archive.namelist())
        reference = json.loads(archive.read(check_release.GITHUB_SOURCE_REFERENCE))
        assert reference == {"tag": "v1.0.0", "url": check_release.github_source_url("v1.0.0")}
    check(bundle)
    assert requests == [check_release.github_source_url("v1.0.0")]

    def mismatching_tag(_url):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("ApeArchivesExtractor-1.0.0/src/main.py", b"different")
        return output.getvalue()

    monkeypatch.setattr(check_release, "github_source_archive", mismatching_tag)
    before = digest(companion)
    with pytest.raises(RuntimeError, match="differs from the build source: src/main.py"):
        check(bundle)
    assert digest(companion) == before


def test_release_rejects_changed_binary(release) -> None:
    bundle, _legal, companion = release
    (bundle / "_internal/library.dll").write_bytes(b"different")
    with pytest.raises(RuntimeError, match="Binary changed"):
        check(bundle, companion)


def test_release_rejects_missing_license_file(release) -> None:
    bundle, legal, companion = release
    (legal / "LICENSE").unlink()
    with pytest.raises(RuntimeError, match="Missing release material: LICENSE"):
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
