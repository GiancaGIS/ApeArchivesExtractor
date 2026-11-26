# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import io
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "build_tools/common"))
from build import copy_sources
from release_privacy import PrivacyCheck


def test_staging_copies_current_release_sources_and_omits_local_data(tmp_path):
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    for relative in ("scratch.txt", ".git/config", "build/pip.log", ".venv/pyvenv.cfg",
                     "src/.cache.pyc", "src/.secrets/token.txt", "native/signing.pfx",
                     "src/app.py", "build_tools/common/build.py"):
        path = checkout / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    stage = tmp_path / "stage"
    copy_sources(checkout, stage)
    assert sorted(p.relative_to(stage).as_posix() for p in stage.rglob("*") if p.is_file()) == [
        "build_tools/common/build.py", "src/app.py",
    ]


def test_privacy_finds_utf16_paths_in_compressed_zip(tmp_path):
    private = tmp_path / "private-checkout"
    artifact = tmp_path / "bundle.zip"
    with zipfile.ZipFile(artifact, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("payload.txt", str(private / "code.py").upper().encode("utf-16-le"))
    with pytest.raises(RuntimeError, match="bundle.zip:payload.txt"):
        PrivacyCheck(private).check(artifact)


def test_privacy_detects_profile_paths_and_editable_install_metadata(tmp_path):
    profile = tmp_path / "profiles.txt"
    profile.write_text("/".join(("", "home", "build-user", "project")))
    metadata = tmp_path / "direct_url.json"
    metadata.write_text("{}")
    with pytest.raises(RuntimeError, match="direct_url.json, profiles.txt"):
        PrivacyCheck().check(tmp_path)


def test_privacy_rejects_personal_archive_ownership(tmp_path):
    artifact = tmp_path / "portable.tar.gz"
    with tarfile.open(artifact, "w:gz") as archive:
        entry = tarfile.TarInfo("file.txt")
        entry.uid = 1000
        entry.uname = "build-user"
        entry.size = 3
        archive.addfile(entry, io.BytesIO(b"app"))
    with pytest.raises(RuntimeError, match="portable.tar.gz:file.txt"):
        PrivacyCheck().check(artifact)
