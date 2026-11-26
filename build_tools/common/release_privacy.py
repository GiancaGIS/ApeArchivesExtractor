# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Check distribution payloads for local paths and private build metadata."""
from __future__ import annotations

import argparse
import io
import os
import re
import subprocess
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import quote

APPLICATIONS = {"apearchivesextractor", "apearchivesextractor.exe", "ape-arch", "ape-arch.exe"}
PROFILE = re.compile(
    r"(?i)(?<![\w.:/])(?:[a-z]:[/\\]+users[/\\]+|/mnt/[a-z]/users/|/(?:home|users)/)"
    r"(?!(?:public|default|default user|all users)[/\\])[^/\\\s\x00<>:\"|?*]{1,80}[/\\]"
)
# Official Qt binaries retain their CI account's workspace. Keep these bytes
# intact for provenance and still check them against all local path markers.
QT_WORKSPACE = re.compile(rb"(?:c:[/\\]+users[/\\]+qt[/\\]+|/home[/]qt/)work[/\\]", re.I)


def private_metadata(name: str) -> bool:
    path = PurePosixPath(name.replace("\\", "/"))
    return (path.name.lower() in {"direct_url.json", "windows-runtime-local.json"}
            or path.suffix.lower() in {".pdb", ".ilk", ".exp", ".lib"})


class PrivacyCheck:
    def __init__(self, *roots: Path) -> None:
        markers = set()
        for root in (Path.home(), *roots):
            value = root.as_posix().rstrip("/")
            if len(value) < 5:
                continue
            variants = {value, quote(value, safe="/:"), quote(value, safe="")}
            if value[1:2] == ":":
                backslashes = value.replace("/", "\\")
                variants.update((backslashes, backslashes.replace("\\", "\\\\"),
                                 "/mnt/" + value[0].lower() + value[2:]))
            for variant in variants:
                markers.update(variant.lower().encode(encoding) for encoding in ("utf-8", "utf-16-le", "utf-16-be"))
        self.markers = tuple(markers)
        self.overlap = max(512, max(map(len, self.markers), default=0))
        self.profile_pattern = re.compile(PROFILE.pattern.encode("ascii"), re.I)
        self.findings: set[str] = set()

    def has_path(self, content: bytes) -> bool:
        lowered = content.lower()
        return any(marker in lowered for marker in self.markers) or any(
            not QT_WORKSPACE.match(lowered, match.start()) for match in self.profile_pattern.finditer(lowered)
        )

    def data(self, name: str, content: bytes) -> None:
        if self.has_path(content):
            self.findings.add(name)

    def stream(self, name, stream) -> None:
        tail = b""
        while chunk := stream.read(2**20):
            block = tail + chunk
            if self.has_path(block):
                self.findings.add(name)
                return
            tail = block[-self.overlap:]

    def member(self, label: str, name: str) -> None:
        if private_metadata(name) or self.has_path(name.encode()):
            self.findings.add(label)

    def zip(self, label, stream) -> None:
        with zipfile.ZipFile(stream) as archive:
            self.data(label, archive.comment)
            for entry in archive.infolist():
                name = f"{label}:{entry.filename}"
                self.member(name, entry.filename)
                self.data(name, entry.comment)
                # Source mirrors contain untouched, separately hashed upstream
                # archives. Scan their entry names and all first-party members.
                if entry.is_dir() or entry.filename.startswith("dependencies/"):
                    continue
                with archive.open(entry) as member:
                    self.stream(name, member)

    def tar(self, label, stream) -> None:
        with tarfile.open(fileobj=stream, mode="r|*") as archive:
            for entry in archive:
                name = f"{label}:{entry.name}"
                self.member(name, entry.name)
                self.data(name, entry.linkname.encode())
                self.data(name, str(entry.pax_headers).encode())
                if entry.uid != 0 or entry.gid != 0 or entry.uname not in {"", "root"} or entry.gname not in {"", "root"}:
                    self.findings.add(name)
                if entry.isfile():
                    with archive.extractfile(entry) as member:
                        self.stream(name, member)

    def deb(self, path: Path) -> None:
        for option in ("--ctrl-tarfile", "--fsys-tarfile"):
            with tempfile.TemporaryFile() as errors, subprocess.Popen(
                ["dpkg-deb", option, str(path)], stdout=subprocess.PIPE, stderr=errors
            ) as process:
                try:
                    self.tar(path.name, process.stdout)
                finally:
                    process.stdout.close()
                if process.wait():
                    errors.seek(0)
                    raise RuntimeError(errors.read().decode(errors="replace"))

    def frozen(self, name: str, path: Path) -> None:
        from PyInstaller.archive.readers import CArchiveReader

        archive = CArchiveReader(str(path))
        for entry, (_, _, _, _, kind) in archive.toc.items():
            label = f"{name}:{entry}"
            self.member(label, entry)
            if kind == "z":
                pyz = archive.open_embedded_archive(entry)
                for module in pyz.toc:
                    payload = pyz.extract(module, raw=True)
                    if payload:
                        self.data(f"{label}:{module}", payload)
            elif kind != "o":
                payload = archive.extract(entry)
                if entry.lower().endswith(".zip"):
                    self.zip(label, io.BytesIO(payload))
                else:
                    self.data(label, payload)

    def check(self, *roots: Path) -> None:
        for root in roots:
            if not root.exists():
                raise FileNotFoundError(root.name)
            for path in root.rglob("*") if root.is_dir() else (root,):
                name = path.relative_to(root).as_posix() if root.is_dir() else path.name
                self.member(name, name)
                if path.is_symlink():
                    target = os.readlink(path)
                    self.data(name, target.encode())
                    if Path(target).is_absolute() or not path.resolve().is_relative_to(root.resolve()):
                        self.findings.add(name)
                elif path.is_file():
                    with path.open("rb") as stream:
                        if path.suffix.lower() in {".zip", ".msix"}:
                            self.zip(name, stream)
                        elif path.name.endswith(".tar.gz"):
                            self.tar(name, stream)
                        elif path.suffix.lower() != ".deb":
                            self.stream(name, stream)
                    if path.name.lower() in APPLICATIONS:
                        self.frozen(name, path)
                    elif path.suffix.lower() == ".deb":
                        self.deb(path)
        if self.findings:
            raise RuntimeError("Local build information in: " + ", ".join(sorted(self.findings)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--private-root", action="append", default=[], type=Path)
    options = parser.parse_args()
    try:
        PrivacyCheck(*options.private_root).check(*options.paths)
    except (OSError, RuntimeError, ValueError, zipfile.BadZipFile, tarfile.TarError) as exc:
        parser.exit(1, f"Privacy check failed: {exc}\n")
    print("Release privacy check passed.")
