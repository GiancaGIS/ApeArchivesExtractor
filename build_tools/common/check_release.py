# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Verify release license files, matching sources and binary checksums."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import urllib.parse
import urllib.request
import zipfile
from functools import cache
from pathlib import Path

from collect_licenses import ROOT, bundle_file, digest, legal_directory

GITHUB_SOURCE_REFERENCE = "legal/application-source.json"
REPOSITORY = "https://github.com/GiancaGIS/ApeArchivesExtractor"


def companion_path(bundle: Path, inventory: dict, *, dependency_sources: bool = False) -> Path:
    suffix = ""
    if inventory.get("platform") == "linux":
        suffix = "-linux-" + (inventory.get("architecture") or platform.machine())
    kind = "DependencySources" if dependency_sources else "sources"
    return bundle.parent / f"ApeArchivesExtractor-{kind}-{inventory['application_version']}{suffix}.zip"


def github_source_url(tag: str) -> str:
    if not tag or any(part in {"", ".", ".."} for part in tag.split("/")):
        raise ValueError("A GitHub release tag is required.")
    return f"{REPOSITORY}/archive/refs/tags/{urllib.parse.quote(tag, safe='/')}.zip"


@cache
def github_source_archive(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ApeArchivesExtractor-source-verification"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.read()
    except OSError as exc:
        raise RuntimeError(f"Could not download the GitHub tag archive: {url} ({exc})") from exc


def check_github_source(tag: str, snapshot: dict[str, str]) -> str:
    url = github_source_url(tag)
    with zipfile.ZipFile(io.BytesIO(github_source_archive(url))) as archive:
        names = [entry.filename for entry in archive.infolist() if not entry.is_dir()]
        roots = {name.partition("/")[0] for name in names}
        if len(roots) != 1 or any("/" not in name for name in names):
            raise RuntimeError(f"Unexpected GitHub source archive layout for tag {tag}")
        root = roots.pop()
        for relative, expected in snapshot.items():
            name = f"{root}/{relative}"
            try:
                data = archive.read(name)
            except KeyError as exc:
                raise RuntimeError(f"GitHub tag {tag} is missing a build source: {relative}") from exc
            if hashlib.sha256(data).hexdigest() == expected:
                continue
            # Git can convert CRLF line endings when checking out text on Windows.
            if Path(relative).suffix.lower() not in {".png", ".ico", ".icns"} and b"\x00" not in data:
                lf = data.replace(b"\r\n", b"\n")
                if expected in {hashlib.sha256(lf).hexdigest(), hashlib.sha256(lf.replace(b"\n", b"\r\n")).hexdigest()}:
                    continue
            raise RuntimeError(f"GitHub tag {tag} differs from the build source: {relative}")
    return url


def check_bundle(bundle: Path) -> tuple[Path, dict, dict]:
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
        raise RuntimeError("Source manifest and component inventory do not match")
    if (sources["application_version"] != inventory["application_version"]
            or sources["application_files_sha256"] != inventory["application_files_sha256"]):
        raise RuntimeError("Source manifest describes a different application snapshot")
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
    return legal, inventory, sources


def check_companion(companion: Path, legal: Path, sources: dict) -> str | None:
    """Check the local ZIP and return its application source tag, if separate."""
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
        snapshot = sources["application_files_sha256"]
        if GITHUB_SOURCE_REFERENCE in archive.namelist():
            reference = json.loads(archive.read(GITHUB_SOURCE_REFERENCE))
            if reference["url"] != github_source_url(reference["tag"]):
                raise RuntimeError("Unexpected application source URL in dependency archive")
            return reference["tag"]
        for relative, expected in snapshot.items():
            if hashlib.sha256(archive.read("application/" + relative)).hexdigest() != expected:
                raise RuntimeError(f"Application source digest mismatch: {relative}")
    return None


def check(bundle: Path, companion: Path | None = None) -> None:
    legal, inventory, sources = check_bundle(bundle)
    if companion is None:
        dependencies = companion_path(bundle, inventory, dependency_sources=True)
        companion = dependencies if dependencies.is_file() else companion_path(bundle, inventory)
    tag = check_companion(companion, legal, sources)
    if tag is not None:
        check_github_source(tag, sources["application_files_sha256"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/ApeArchivesExtractor")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--companion", type=Path)
    mode.add_argument("--bundle-only", action="store_true", help="check packaged notices, inventory and binary hashes")
    args = parser.parse_args()
    try:
        if args.bundle_only:
            check_bundle(args.bundle.resolve())
        else:
            check(args.bundle.resolve(), args.companion)
    except (RuntimeError, OSError, ValueError, KeyError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"Release check failed: {exc}\n")
    if args.bundle_only:
        print("Bundle license files, source inventory and binary checksums verified.")
    else:
        print("Release license files, matching sources and binary checksums verified.")
