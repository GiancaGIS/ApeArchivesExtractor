# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Verify release license files, matching sources and binary checksums."""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

from collect_licenses import digest
from prepare_release_sources import ROOT, bundle_file, legal_directory


def check(bundle: Path, companion: Path | None = None) -> None:
    legal = legal_directory(bundle)
    for name in ("LICENSE", "NOTICE", "SOURCES.md", "THIRD_PARTY_NOTICES.md", "component-manifest.json", "source-manifest.json"):
        if not (legal / name).is_file():
            raise RuntimeError(f"Missing release material: {name}")
    inventory = json.loads((legal / "component-manifest.json").read_text(encoding="utf-8"))
    sources = json.loads((legal / "source-manifest.json").read_text(encoding="utf-8"))
    for name, expected in sources.get("legal_files_sha256", {}).items():
        if digest(legal / name) != expected:
            raise RuntimeError(f"Legal material changed since source preparation: {name}")
    if sources["component_manifest_sha256"] != digest(legal / "component-manifest.json"):
        raise RuntimeError("Source companion and component inventory do not match")
    for component in inventory["components"]:
        for name in component["license_files"]:
            if not (legal / name).is_file():
                raise RuntimeError(f"Missing component license: {name}")
    for record in sources["sources"]:
        for name in record["notice_files"]:
            if not (legal / name).is_file():
                raise RuntimeError(f"Missing source notice: {name}")
    for binary in inventory["binaries"]:
        if digest(bundle_file(bundle, binary["path"])) != binary.get("bundled_sha256"):
            raise RuntimeError(f"Binary changed since source preparation: {binary['path']}")
    for binary in inventory["application_binaries"]:
        if digest(bundle / binary["path"]) != binary["sha256"]:
            raise RuntimeError(f"Application binary changed: {binary['path']}")
    companion = companion or ROOT / "dist" / f"ApeArchivesExtractor-sources-{inventory['application_version']}.zip"
    with zipfile.ZipFile(companion) as archive:
        if archive.read("legal/source-manifest.json") != (legal / "source-manifest.json").read_bytes():
            raise RuntimeError("Published source manifest differs from the application's manifest")
        for name, expected in sources.get("legal_files_sha256", {}).items():
            if hashlib.sha256(archive.read("legal/" + name)).hexdigest() != expected:
                raise RuntimeError(f"Source companion legal material mismatch: {name}")
        for record in sources["sources"]:
            with archive.open("dependencies/" + record["filename"]) as stream:
                if hashlib.file_digest(stream, "sha256").hexdigest() != record["sha256"]:
                    raise RuntimeError(f"Source archive digest mismatch: {record['filename']}")
        for relative, expected in sources["application_files_sha256"].items():
            if hashlib.sha256(archive.read("application/" + relative)).hexdigest() != expected:
                raise RuntimeError(f"Application source digest mismatch: {relative}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/ApeArchivesExtractor")
    parser.add_argument("--companion", type=Path)
    args = parser.parse_args()
    try:
        check(args.bundle.resolve(), args.companion)
    except (RuntimeError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    print("Release license files, sources and binary checksums verified. Publish sources alongside the binary.")
