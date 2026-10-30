# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Mirror exact upstream sources and legal files without executing downloaded code."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import tarfile
import urllib.parse
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath

from collect_licenses import digest, legal_file, slug, source_snapshot

ROOT = Path(__file__).resolve().parents[1]


def legal_directory(bundle: Path) -> Path:
    candidates = [bundle / "_internal/apearchivesextractor/legal/generated",
                  bundle / "Contents/Resources/apearchivesextractor/legal/generated"]
    for candidate in candidates:
        if (candidate / "component-manifest.json").is_file():
            return candidate
    raise RuntimeError(f"No generated license inventory in {bundle}; rebuild the application first")


def bundle_file(bundle: Path, name: str) -> Path:
    for base in (bundle / "_internal", bundle / "Contents/Frameworks", bundle / "Contents/Resources", bundle):
        candidate = base / name
        if candidate.is_file():
            return candidate
    raise RuntimeError(f"Bundled file not found: {name}")


def read_url(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "ApeArchivesExtractor-license-preparation/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def download(url: str, cache: Path, expected: str | None) -> Path:
    filename = Path(urllib.parse.urlparse(url).path).name
    if not filename or filename in (".", ".."):
        raise ValueError(f"Invalid archive URL: {url}")
    target = cache / filename
    if not target.exists() or (expected and digest(target) != expected):
        temporary = target.with_suffix(target.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "ApeArchivesExtractor-license-preparation/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response, temporary.open("wb") as output:
            shutil.copyfileobj(response, output)
        if expected and digest(temporary) != expected:
            temporary.unlink()
            raise RuntimeError(f"Upstream SHA-256 mismatch: {filename}")
        temporary.replace(target)
    return target


def copy_archive_notices(archive: Path, destination: Path) -> list[str]:
    """Read only regular legal files; never extract links or traversal paths."""
    copied = []
    original_paths = {}

    def save(name: str, content: bytes) -> None:
        path = PurePosixPath(name.replace("\\", "/"))
        if path.is_absolute() or ".." in path.parts or any(":" in p for p in path.parts):
            raise ValueError(f"Unsafe archive member: {name}")
        # Native source trees contain paths beyond Inno Setup's Windows path
        # limit. Preserve exact content under short, collision-resistant names;
        # the index and full source archive retain the original member paths.
        basename = hashlib.sha256(path.as_posix().encode("utf-8")).hexdigest()[:12] + "-" + path.name[:60]
        target = destination / basename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        copied.append(target.relative_to(destination).as_posix())
        original_paths[basename] = path.as_posix()

    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as source:
            for entry in source.infolist():
                if not entry.is_dir() and legal_file(entry.filename):
                    if entry.file_size > 8 * 1024 * 1024:
                        raise ValueError(f"Oversized legal file: {entry.filename}")
                    save(entry.filename, source.read(entry))
    else:
        with tarfile.open(archive) as source:
            for entry in source:
                if entry.isfile() and legal_file(entry.name):
                    if entry.size > 8 * 1024 * 1024:
                        raise ValueError(f"Oversized legal file: {entry.name}")
                    stream = source.extractfile(entry)
                    if stream:
                        with stream:
                            save(entry.name, stream.read())
    if original_paths:
        (destination / "source-path-index.json").write_text(json.dumps(original_paths, indent=2) + "\n", encoding="utf-8")
        copied.append("source-path-index.json")
    return copied


def prepare(bundle: Path) -> Path:
    legal = legal_directory(bundle)
    inventory_path = legal / "component-manifest.json"
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    snapshot = source_snapshot(ROOT)
    if snapshot != inventory.get("application_files_sha256"):
        raise RuntimeError("Application source snapshot differs from this binary's build. Rebuild before preparing release sources.")
    cache = ROOT / "build" / "source-cache"
    cache.mkdir(parents=True, exist_ok=True)
    records = []
    archives = []

    def add(name: str, version: str, url: str, expected: str | None) -> None:
        print(f"Preparing source: {name} {version}", flush=True)
        archive = download(url, cache, expected)
        notices = copy_archive_notices(archive, legal / "native" / slug(name))
        records.append({"name": name, "version": version, "url": url, "filename": archive.name,
                        "sha256": digest(archive), "upstream_sha256_verified": expected is not None,
                        "notice_files": [f"native/{slug(name)}/{p}" for p in notices]})
        archives.append(archive)

    binding_versions = set()
    for component in inventory["components"]:
        if slug(component["name"]).startswith(("pyside6", "shiboken6")):
            binding_versions.add(component["version"])
            continue  # PySide6 and Shiboken6 sources are published by Qt, not as PyPI sdists.
        data = json.loads(read_url(component["source_metadata"]))
        sdists = [f for f in data["urls"] if f["packagetype"] == "sdist"]
        if not sdists:
            raise RuntimeError(f"No source distribution: {component['name']} {component['version']}")
        source = sdists[0]
        add(component["name"], component["version"], source["url"], source["digests"]["sha256"])

    for version in sorted(binding_versions):
        url = ("https://download.qt.io/official_releases/QtForPython/pyside6/"
               f"PySide6-{version}-src/pyside-setup-everywhere-src-{version}.tar.xz")
        checksum = read_url(url + ".sha256").decode("ascii").split()[0]
        add("QtForPython", version, url.replace("https://download.qt.io/", "https://master.qt.io/"), checksum)

    qt = inventory["qt_version"]
    minor = ".".join(qt.split(".")[:2])
    modules = {"qtbase", "qtsvg", "qtimageformats", "qttranslations"}
    if any("Qt6Pdf" in b["path"] for b in inventory["binaries"]):
        modules.add("qtwebengine")
    for module in sorted(modules):
        url = f"https://download.qt.io/official_releases/qt/{minor}/{qt}/submodules/{module}-everywhere-src-{qt}.tar.xz"
        checksum = read_url(url + ".sha256").decode("ascii").split()[0]
        # The master endpoint avoids mirror redirects while retaining Qt's
        # independently fetched published checksum and normal TLS verification.
        add(module, qt, url.replace("https://download.qt.io/", "https://master.qt.io/"), checksum)
    python = inventory["python_version"]
    add("Python", python, f"https://www.python.org/ftp/python/{python}/Python-{python}.tar.xz", None)
    # Windows CPython sources name the external dependency versions used by its
    # official build. Their archives preserve additional native copyright notices.
    # A release reviewer must still verify these against the actual interpreter.
    if inventory["platform"] == "win32":
        python_archive = archives[-1]
        with tarfile.open(python_archive) as archive:
            entry = next(e for e in archive if e.name.endswith("/PCbuild/python.props"))
            with archive.extractfile(entry) as stream:
                props = stream.read().decode("utf-8")
        for library in ("bzip2", "xz", "libffi", "openssl", "zlib", "zlib-ng", "zstd"):
            match = re.search(r"(" + re.escape(library) + r"-\d[\w.-]*)\\", props)
            if match:
                tag = match.group(1)
                add("cpython-" + library, tag.removeprefix(library + "-"),
                    f"https://github.com/python/cpython-source-deps/archive/refs/tags/{tag}.tar.gz", None)
        mesa_binary = next((b for b in inventory["binaries"] if b["path"].endswith("opengl32sw.dll")), None)
        if mesa_binary:
            data = bundle_file(bundle, mesa_binary["path"]).read_bytes()
            mesa = re.search(rb"Mesa (\d+\.\d+\.\d+)", data)
            llvm = re.search(rb"based on LLVM (\d+\.\d+\.\d+)", data)
            if not mesa or not llvm:
                raise RuntimeError("Cannot identify Mesa/LLVM versions in Qt's software OpenGL library; review sources manually")
            mesa_version = mesa.group(1).decode("ascii")
            llvm_version = llvm.group(1).decode("ascii")
            major = mesa_version.split(".")[0]
            add("Mesa", mesa_version, f"https://archive.mesa3d.org/older-versions/{major}.x/{mesa_version}/mesa-{mesa_version}.tar.xz", None)
            add("LLVM", llvm_version, f"https://releases.llvm.org/{llvm_version}/llvm-{llvm_version}.src.tar.xz", None)
        # Preserve Microsoft's original license document as well as readable text.
        # This does not establish the distributor's entitlement under those terms.
        runtime_info = legal / "windows-runtime.json"
        series = json.loads(runtime_info.read_text(encoding="utf-8-sig"))["license_series"] if runtime_info.exists() else "2022"
        urls = [
            ("Microsoft Visual C++ runtime license", "2015-2022", "microsoft-runtime",
             "https://visualstudio.microsoft.com/wp-content/uploads/2021/09/Visual-C-Runtime-2015-2022-License-1.docx"),
        ]
        if series == "2026":
            urls.extend([
                ("Microsoft Visual C++ runtime license", "2026", "microsoft-runtime-2026",
                 "https://visualstudio.microsoft.com/wp-content/uploads/2025/10/Visual-C-V14-License-Redistributable_and_Runtime_ENU.docx"),
                ("Microsoft Visual Studio Community license", "2026", "microsoft-community-2026",
                 "https://visualstudio.microsoft.com/wp-content/uploads/2025/10/Visual_Studio_2026-License-Community_ENU.docx"),
            ])
        for name, version, folder, url in urls:
            document = download(url, cache, None)
            directory = legal / "native" / folder
            directory.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(document, directory / document.name)
            with zipfile.ZipFile(document) as archive:
                body = ET.fromstring(archive.read("word/document.xml"))
            namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = ["".join(t.text or "" for t in p.findall(".//w:t", namespace))
                          for p in body.findall(".//w:p", namespace)]
            (directory / "LICENSE.txt").write_text("Source: " + url + "\n\n" + "\n".join(paragraphs) + "\n", encoding="utf-8")
            records.append({"name": name, "version": version, "artifact_kind": "license-document", "url": url,
                            "filename": document.name, "sha256": digest(document), "upstream_sha256_verified": False,
                            "notice_files": [f"native/{folder}/LICENSE.txt", f"native/{folder}/" + document.name]})
            archives.append(document)
        runtime_folder = "microsoft-runtime-2026" if series == "2026" else "microsoft-runtime"
        installer_license = (legal / "LICENSE").read_text(encoding="utf-8")
        installer_license += (
            "\n\nMICROSOFT VISUAL C++ RUNTIME\n\n"
            "The application includes unmodified Microsoft Visual C++ runtime DLLs.\n"
            "The following Microsoft terms apply to those runtime files only.\n"
            "ApeArchivesExtractor and its open-source components retain their respective licenses.\n\n"
            + (legal / "native" / runtime_folder / "LICENSE.txt").read_text(encoding="utf-8")
        )
        (legal / "INSTALLER_LICENSE.txt").write_text(installer_license, encoding="utf-8")

    # Copy final binary hashes (macOS install names or UPX can change the wheel's bytes).
    for binary in inventory["binaries"]:
        binary["bundled_sha256"] = digest(bundle_file(bundle, binary["path"]))
    inventory["application_binaries"] = [
        {"path": p.relative_to(bundle).as_posix(), "sha256": digest(p)}
        for p in sorted(bundle.rglob("*")) if p.is_file() and p.suffix.lower() in {".exe", ".dll", ".msix"}
        and "_internal" not in p.parts and "legal" not in p.parts
    ]
    inventory_path.write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    if source_snapshot(ROOT) != snapshot:
        raise RuntimeError("Application sources changed during source preparation; rebuild before distributing")
    manifest = {"application_version": inventory["application_version"], "sources": records,
                "application_files_sha256": snapshot, "component_manifest_sha256": digest(inventory_path)}
    (legal / "THIRD_PARTY_NOTICES.md").write_text(
        (legal / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8").split("\n## Source archive notices")[0]
        + "\n## Source archive notices\n\n" + "\n".join(f"- [{p}]({p})" for r in records for p in r["notice_files"]) + "\n", encoding="utf-8")
    manifest["legal_files_sha256"] = {p.relative_to(legal).as_posix(): digest(p) for p in sorted(legal.rglob("*"))
                                    if p.is_file() and p.name != "source-manifest.json"}
    (legal / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    companion = ROOT / "dist" / f"ApeArchivesExtractor-sources-{inventory['application_version']}.zip"
    # Replace atomically, so failed preparation cannot leave a new partial release artifact.
    temporary = companion.with_suffix(".zip.part")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as source_zip:
        for relative in snapshot:
            source_zip.write(ROOT / relative, "application/" + relative)
        for archive in archives:
            source_zip.write(archive, "dependencies/" + archive.name)
        for p in sorted(legal.rglob("*")):
            if p.is_file():
                source_zip.write(p, "legal/" + p.relative_to(legal).as_posix())
    temporary.replace(companion)
    print(f"Source companion: {companion}", flush=True)
    print("Run scripts/check_release.py to verify license files, sources and checksums.", flush=True)
    return companion


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=ROOT / "dist/ApeArchivesExtractor")
    args = parser.parse_args()
    prepare(args.bundle.resolve())
