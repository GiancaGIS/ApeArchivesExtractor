# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Package the checked Linux bundle as a portable tarball and a Debian package."""
from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APP = "ApeArchivesExtractor"
PACKAGE = "apearchivesextractor"
DESKTOP_ID = "com.giancagis.apearchivesextractor"


def root_owner(entry: tarfile.TarInfo) -> tarfile.TarInfo:
    entry.uid = entry.gid = 0
    entry.uname = entry.gname = "root"
    return entry


def dependencies(bundle: Path, work: Path, control: str) -> str:
    # Resolve deployed SONAMEs against the build distribution's package and
    # symbol tables. Libraries already inside the application have no package.
    debian = work / "debian"
    debian.mkdir()
    (debian / "control").write_text(f"Source: {PACKAGE}\n\n{control}", encoding="utf-8")
    elf_files = []
    for path in sorted(bundle.rglob("*")):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as stream:
                if stream.read(4) == b"\x7fELF":
                    elf_files.append(path)
    directories = sorted({path.parent for path in elf_files})
    output = subprocess.check_output([
        "dpkg-shlibdeps", "-O", "--ignore-missing-info",
        *(f"-l{path}" for path in directories), *(f"-e{path}" for path in elf_files),
    ], cwd=work, text=True)
    return output.strip().removeprefix("shlibs:Depends=")


def main() -> None:
    dist = ROOT / "dist"
    bundle = dist / APP
    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    arch = subprocess.check_output(["dpkg", "--print-architecture"], text=True).strip()
    with tarfile.open(dist / f"{APP}-{version}-linux-{arch}.tar.gz", "w:gz") as archive:
        archive.add(bundle, arcname=APP, filter=root_owner)

    work = ROOT / "build/linux"
    package = work / "package"
    prefix = package / "opt" / PACKAGE
    prefix.parent.mkdir(parents=True)
    shutil.copytree(bundle, prefix, symlinks=True)
    control = (
        f"Package: {PACKAGE}\nVersion: {version}\nArchitecture: {arch}\n"
        "Maintainer: GiancaGIS\nSection: utils\nPriority: optional\n"
        "Homepage: https://github.com/GiancaGIS/ApeArchivesExtractor\n"
        "Description: Desktop and command-line archive manager\n"
        " Browse, pack and extract ZIP, 7z, RAR and TAR.GZ archives.\n"
    )
    debian = package / "DEBIAN"
    debian.mkdir()
    depends = dependencies(bundle, work, control)
    (debian / "control").write_text(control + f"Depends: {depends}\n", encoding="utf-8")

    bin_dir = package / "usr/bin"
    bin_dir.mkdir(parents=True)
    for name, executable in (("ape-arch", "ape-arch"), ("apearchivesextractor-gui", APP)):
        (bin_dir / name).symlink_to(os.path.relpath(prefix / executable, bin_dir))
    applications = package / "usr/share/applications"
    applications.mkdir(parents=True)
    shutil.copyfile(Path(__file__).with_name(f"{DESKTOP_ID}.desktop"), applications / f"{DESKTOP_ID}.desktop")
    icons = package / "usr/share/icons/hicolor/512x512/apps"
    icons.mkdir(parents=True)
    shutil.copyfile(ROOT / "docs/assets/app-icon.png", icons / f"{DESKTOP_ID}.png")
    doc = package / "usr/share/doc" / PACKAGE
    doc.mkdir(parents=True)
    shutil.copyfile(ROOT / "LICENSE", doc / "copyright")
    shutil.copyfile(ROOT / "SOURCES.md", doc / "SOURCES.md")
    subprocess.run([
        "dpkg-deb", "--root-owner-group", "-Zxz", "--build", str(package), str(dist / f"{PACKAGE}_{version}_{arch}.deb"),
    ], check=True)


if __name__ == "__main__":
    main()
