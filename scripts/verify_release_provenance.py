# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Verify bundled native bytes against published wheels, CPython and the release CRT.

This produces evidence; it does not assert asset ownership or approve a release.
Run after the portable build and before prepare_release_sources.py.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as metadata
import json
import zipfile
from pathlib import Path

from packaging.utils import parse_wheel_filename
from packaging.tags import parse_tag

from collect_licenses import digest, slug
from prepare_release_sources import ROOT, bundle_file, download, legal_directory, read_url


def verify(bundle: Path) -> Path:
    legal = legal_directory(bundle)
    inventory = json.loads((legal / "component-manifest.json").read_text(encoding="utf-8"))
    cache = ROOT / "build" / "provenance-cache"
    cache.mkdir(parents=True, exist_ok=True)
    artifacts = []
    verified = []
    runtime_path = legal / "windows-runtime.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8-sig")) if runtime_path.exists() else {"files": []}
    runtime_files = {r["path"].casefold(): r for r in runtime["files"]}
    for relative, record in runtime_files.items():
        original = Path(record["source"])
        if "debug_nonredist" in str(original).lower() or not any(p.lower() == "redist" for p in original.parts):
            raise RuntimeError(f"Not a release redistributable: {original}")
        if digest(original) != record["sha256"] or digest(bundle / relative) != record["sha256"]:
            raise RuntimeError(f"Runtime differs from the recorded Visual Studio redistributable: {relative}")
        verified.append({"path": relative, "origin": "Visual Studio release CRT", "sha256": record["sha256"]})

    for component in inventory["components"]:
        owner = slug(component["name"])
        binaries = [b for b in inventory["binaries"] if b.get("owner") == owner
                    and ("_internal/" + b["path"]).casefold() not in runtime_files]
        if not binaries:
            continue
        distribution = metadata.distribution(component["name"])
        tags = set()
        for line in distribution.read_text("WHEEL").splitlines():
            if line.startswith("Tag: "):
                tags.update(parse_tag(line[5:]))
        data = json.loads(read_url(component["source_metadata"]))
        wheels = [f for f in data["urls"] if f["packagetype"] == "bdist_wheel"
                  and parse_wheel_filename(f["filename"])[3] & tags]
        if len(wheels) != 1:
            raise RuntimeError(f"Cannot identify a unique installed wheel for {component['name']}")
        wheel = wheels[0]
        print(f"Verifying published wheel: {wheel['filename']}", flush=True)
        artifact = download(wheel["url"], cache, wheel["digests"]["sha256"])
        artifacts.append({"filename": artifact.name, "url": wheel["url"], "sha256": digest(artifact),
                          "upstream_sha256_verified": True})
        with zipfile.ZipFile(artifact) as archive:
            for binary in binaries:
                original_hash = hashlib.sha256(archive.read(binary.get("distribution_path", binary["path"]))).hexdigest()
                if original_hash != binary["sha256"] or digest(bundle_file(bundle, binary["path"])) != original_hash:
                    raise RuntimeError(f"Binary differs from the published wheel: {binary['path']}")
                verified.append({"path": "_internal/" + binary["path"], "origin": artifact.name, "sha256": original_hash})

    python_version = inventory["python_version"]
    url = f"https://www.python.org/ftp/python/{python_version}/python-{python_version}-embed-amd64.zip"
    python_archive = download(url, cache, None)
    artifacts.append({"filename": python_archive.name, "url": url, "sha256": digest(python_archive),
                      "upstream_sha256_verified": False})
    with zipfile.ZipFile(python_archive) as archive:
        for binary in inventory["binaries"]:
            if binary.get("owner") or ("_internal/" + binary["path"]).casefold() in runtime_files:
                continue
            original_hash = hashlib.sha256(archive.read(binary["path"])).hexdigest()
            if original_hash != binary["sha256"] or digest(bundle_file(bundle, binary["path"])) != original_hash:
                raise RuntimeError(f"Binary differs from the official CPython payload: {binary['path']}")
            verified.append({"path": "_internal/" + binary["path"], "origin": python_archive.name, "sha256": original_hash})

    application = {"ApeArchivesExtractor.exe", "ape-arch.exe", "ApeArchivesExtractorShellExtension.dll", "ApeArchivesExtractorIdentity.msix"}
    known = {r["path"].casefold() for r in verified} | {name.casefold() for name in application}
    for path in bundle.rglob("*"):
        if path.is_file() and path.suffix.lower() in {".dll", ".pyd", ".exe", ".msix"}:
            relative = path.relative_to(bundle).as_posix()
            if relative.casefold() not in known:
                raise RuntimeError(f"Unexplained binary in the bundle: {relative}")
    result = legal / "binary-provenance.json"
    result.write_text(json.dumps({"artifacts": artifacts, "verified_binaries": verified,
                                 "application_artifacts": sorted(application),
                                 "scope": "Byte provenance only; follow docs/BUILDING.md for release checks."}, indent=2) + "\n", encoding="utf-8")
    print(f"Native byte provenance verified: {len(verified)} files", flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/ApeArchivesExtractor")
    args = parser.parse_args()
    verify(args.bundle.resolve())
