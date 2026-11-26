# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Build and check distributable packages from a neutral staging directory."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import tomllib
from contextlib import contextmanager
from pathlib import Path

from check_release import companion_path
from collect_licenses import application_files, source_snapshot
from release_privacy import PROFILE

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path("dist/ApeArchivesExtractor")
LEGAL = BUNDLE / "_internal/apearchivesextractor/legal/generated"
COMMON = Path("build_tools/common")
WINDOWS = Path("build_tools/windows")


def staging_parent(source: Path, requested: Path | None) -> Path:
    default = (Path(os.environ["SystemDrive"] + "/Users/Public/Documents") if os.name == "nt" else Path("/tmp"))
    parent = (requested or default).resolve()
    if (parent.is_relative_to(Path.home()) or parent.is_relative_to(source)
            or PROFILE.search(parent.as_posix() + "/")):
        raise ValueError("The staging parent must be outside the checkout and user profiles.")
    if not parent.is_dir():
        raise FileNotFoundError("Create the neutral staging parent or pass --build-root.")
    return parent


def restrict_windows_stage(stage: Path) -> None:
    # Python < 3.13 cannot set a private Windows ACL through mkdir(mode=0o700).
    sid = subprocess.check_output([
        "powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
        "[Security.Principal.WindowsIdentity]::GetCurrent().User.Value",
    ], text=True).strip()
    subprocess.run([
        "icacls.exe", str(stage), "/inheritance:r", "/grant:r",
        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
    ], check=True, stdout=subprocess.DEVNULL)


def copy_sources(source: Path, stage: Path) -> None:
    for path in application_files(source):
        relative = path.relative_to(source)
        if path.is_symlink() or not path.resolve().is_relative_to(source):
            raise ValueError(f"Source file outside the checkout: {relative.as_posix()}")
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def build_environment(stage: Path, source: Path) -> dict[str, str]:
    blocked = {"PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV", "CL", "_CL_", "LINK", "_LINK_",
               "LD_LIBRARY_PATH", "LD_PRELOAD", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH"}
    env = {key: value for key, value in os.environ.items() if key.upper() not in blocked}
    scratch = stage / "build/tmp"
    scratch.mkdir(parents=True)
    return env | {
        "TMP": str(scratch), "TEMP": str(scratch), "TMPDIR": str(scratch),
        "PYINSTALLER_CONFIG_DIR": str(stage / "build/pyinstaller-cache"),
        "PYTHONNOUSERSITE": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1",
        "PIP_CONFIG_FILE": os.devnull, "PIP_NO_CACHE_DIR": "1",
        "APE_RELEASE_CACHE": str(source / "build"),
        "QT_QPA_PLATFORM": "offscreen",
    }


@contextmanager
def publish_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as lock:
        if os.name == "nt":
            import msvcrt

            lock.seek(0)
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            try:
                yield
            finally:
                msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield


def publish(outputs: list[Path], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ape-build-", dir=destination) as temporary:
        incoming = Path(temporary)
        if os.name == "nt":
            # A same-volume rename retains ACLs. Let exported files inherit
            # the distribution folder's ACL instead of the temporary ACL.
            subprocess.run(["icacls.exe", str(incoming), "/reset", "/Q"], check=True)
        for path in outputs:
            target = incoming / path.name
            if path.is_dir():
                shutil.copytree(path, target, symlinks=True)
            else:
                shutil.copyfile(path, target)
        backup = incoming / "previous"
        backup.mkdir()
        replaced = []
        try:
            for path in outputs:
                source = incoming / path.name
                target = destination / path.name
                previous = backup / path.name
                if target.exists() or target.is_symlink():
                    target.replace(previous)
                replaced.append(path.name)
                source.replace(target)
        except OSError:
            for name in reversed(replaced):
                target = destination / name
                if target.exists() or target.is_symlink():
                    target.replace(incoming / name)
                if (backup / name).exists() or (backup / name).is_symlink():
                    (backup / name).replace(target)
            raise


def build(stage: Path, source: Path, options: argparse.Namespace) -> None:
    windows = sys.platform == "win32"
    if windows:
        restrict_windows_stage(stage)
    copy_sources(source, stage)
    env = build_environment(stage, source)
    print(f"Staging directory: {stage}", flush=True)

    def run(*command: str | Path) -> None:
        subprocess.run(command, cwd=stage, env=env, check=True)

    def powershell(script: str) -> None:
        run("powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", WINDOWS / script)

    def privacy(*paths: Path) -> None:
        run(python, COMMON / "release_privacy.py", "--private-root", source, "--private-root", stage, *paths)

    run(sys.executable, "-m", "venv", ".venv")
    python = stage / (".venv/Scripts/python.exe" if windows else ".venv/bin/python")
    run(python, "-m", "pip", "install", "--only-binary=:all:", "-e", ".[package]")
    version = tomllib.loads((stage / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    destination = source / ("dist" if windows else "dist/linux")
    bundle = stage / BUNDLE

    if options.skip_build:
        bundle.parent.mkdir(exist_ok=True)
        shutil.copytree(destination / BUNDLE.name, bundle)
    else:
        run(python, "-m", "PyInstaller", "--noconfirm", "--clean", COMMON / "ApeArchivesExtractor.spec")
        if windows:
            powershell("build_shell_extension.ps1")
            powershell("build_sparse_package.ps1")
            run(python, COMMON / "verify_release_provenance.py")

    manifest = json.loads((stage / LEGAL / "component-manifest.json").read_text(encoding="utf-8"))
    if options.skip_build and manifest["application_files_sha256"] != source_snapshot(stage):
        raise RuntimeError("The prepared bundle belongs to different sources. Rebuild without -SkipBuild.")
    companion = companion_path(bundle, manifest, dependency_sources=True)
    run(python, COMMON / "prepare_release_sources.py", "--github-tag", f"v{version}", "--companion", companion)
    privacy(bundle, companion)
    outputs = [companion] if options.skip_build else [bundle, companion]
    if not options.bundle_only:
        if windows:
            privacy(stage / "scripts", stage / WINDOWS, stage / "SOURCES.md")
            powershell("compile_installer.ps1")
            packages = [stage / "dist" / f"ApeArchivesExtractorSetup-{version}.exe"]
        else:
            run(python, "build_tools/linux/package_linux.py")
            packages = sorted((stage / "dist").glob("*.deb")) + sorted((stage / "dist").glob("*.tar.gz"))
            if len(packages) != 2:
                raise RuntimeError("The Debian package or portable tarball was not created.")
            outputs.remove(bundle)
        privacy(*packages)
        outputs.extend(packages)
    with publish_lock(source / "build" / ("windows-release.lock" if windows else "linux-release.lock")):
        publish(outputs, destination)
    for path in outputs:
        print(f"Built: {destination / path.name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--bundle-only", action="store_true")
    modes.add_argument("--skip-build", action="store_true", help="reuse a prepared Windows bundle")
    parser.add_argument("--build-root", type=Path, help="existing neutral parent for temporary build directories")
    args = parser.parse_args()
    if sys.version_info < (3, 11):
        parser.error("Python 3.11 or newer is required.")
    if sys.platform not in {"win32", "linux"} or (args.skip_build and sys.platform != "win32"):
        parser.error("Use Windows or Linux for this entry point. --skip-build is Windows-only.")
    if sys.platform == "linux" and not args.bundle_only and not all(
        shutil.which(command) for command in ("dpkg-deb", "dpkg-shlibdeps")
    ):
        parser.error("Install dpkg and dpkg-dev for Debian packaging or use --bundle-only.")
    try:
        parent = staging_parent(ROOT, args.build_root)
        with tempfile.TemporaryDirectory(prefix="ape-archives-", dir=parent) as temp:
            build(Path(temp), ROOT, args)
    except subprocess.CalledProcessError as exc:
        parser.exit(exc.returncode if exc.returncode > 0 else 1, "Build step failed. See its output above.\n")
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"Build failed: {exc}\n")
