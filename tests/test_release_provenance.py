# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_release_provenance as provenance
from collect_licenses import digest


@pytest.fixture
def native_bundle(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    legal = bundle / "_internal/apearchivesextractor/legal/generated"
    legal.mkdir(parents=True)
    runtime = bundle / "_internal/PySide6/MSVCP140.dll"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"release runtime")
    original = tmp_path / "VisualStudio/VC/Redist/MSVC/14.51/x64/Microsoft.VC145.CRT/msvcp140.dll"
    original.parent.mkdir(parents=True)
    original.write_bytes(runtime.read_bytes())
    python = bundle / "_internal/python314.dll"
    python.write_bytes(b"official python")
    (legal / "component-manifest.json").write_text(json.dumps({
        "python_version": "3.14.5", "components": [{"name": "PySide6_Essentials"}],
        "binaries": [{"path": "PySide6/MSVCP140.dll", "owner": "pyside6-essentials", "sha256": "pre-staging hash"},
                     {"path": "python314.dll", "owner": None, "sha256": digest(python)}],
    }))
    (legal / "windows-runtime.json").write_text(json.dumps({"files": [{
        "path": "_internal/PySide6/msvcp140.dll", "source": str(original), "sha256": digest(original),
    }]}))
    payload = tmp_path / "python.zip"
    with zipfile.ZipFile(payload, "w") as archive:
        archive.writestr("python314.dll", python.read_bytes())
    monkeypatch.setattr(provenance, "ROOT", tmp_path)
    monkeypatch.setattr(provenance, "download", lambda *_args: payload)
    return bundle, legal


def test_native_provenance_accepts_windows_runtime_case_variations(native_bundle):
    bundle, _ = native_bundle
    result = json.loads(provenance.verify(bundle).read_text())
    assert len(result["verified_binaries"]) == 2


def test_native_provenance_rejects_changed_python_payload(native_bundle):
    bundle, _ = native_bundle
    (bundle / "_internal/python314.dll").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="official CPython payload"):
        provenance.verify(bundle)


def test_native_provenance_rejects_unexplained_dll(native_bundle):
    bundle, _ = native_bundle
    (bundle / "unknown.dll").write_bytes(b"unexplained")
    with pytest.raises(RuntimeError, match="Unexplained binary"):
        provenance.verify(bundle)


def test_native_provenance_rejects_debug_runtime(native_bundle):
    bundle, legal = native_bundle
    path = legal / "windows-runtime.json"
    data = json.loads(path.read_text())
    data["files"][0]["source"] = str(bundle / "Redist/debug_nonredist/msvcp140.dll")
    path.write_text(json.dumps(data))
    with pytest.raises(RuntimeError, match="Not a release redistributable"):
        provenance.verify(bundle)


def test_native_provenance_verifies_relocated_pyside_library(native_bundle, tmp_path, monkeypatch):
    from types import SimpleNamespace

    bundle, legal = native_bundle
    library = bundle / "_internal/pyside6.abi3.dll"
    library.write_bytes(b"published pyside library")
    manifest = legal / "component-manifest.json"
    inventory = json.loads(manifest.read_text())
    inventory["components"][0]["source_metadata"] = "https://pypi.org/pypi/pyside6-essentials/6.12.0/json"
    inventory["binaries"].append({"path": "pyside6.abi3.dll", "distribution_path": "PySide6/pyside6.abi3.dll",
                                  "owner": "pyside6-essentials", "sha256": digest(library)})
    manifest.write_text(json.dumps(inventory))
    wheel = tmp_path / "pyside6_essentials-6.12.0-cp310-abi3-win_amd64.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("PySide6/pyside6.abi3.dll", library.read_bytes())
    original_download = provenance.download
    monkeypatch.setattr(provenance, "download", lambda url, *args: wheel if url.endswith(".whl") else original_download(url, *args))
    monkeypatch.setattr(provenance.metadata, "distribution", lambda _name: SimpleNamespace(read_text=lambda _name: "Tag: cp310-abi3-win_amd64\n"))
    monkeypatch.setattr(provenance, "read_url", lambda _url: json.dumps({"urls": [{
        "filename": wheel.name, "packagetype": "bdist_wheel", "url": "https://example.org/" + wheel.name,
        "digests": {"sha256": digest(wheel)},
    }]}).encode())
    result = json.loads(provenance.verify(bundle).read_text())
    assert any(b["path"] == "_internal/pyside6.abi3.dll" for b in result["verified_binaries"])
