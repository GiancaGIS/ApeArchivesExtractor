# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def installer_project(tmp_path: Path) -> Path:
    if not shutil.which("powershell.exe"):
        pytest.skip("Windows PowerShell is required")
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copyfile("scripts/build_windows_installer.ps1", scripts / "build_windows_installer.ps1")
    (scripts / "build_windows.ps1").write_text("throw 'Unexpected portable rebuild'", encoding="utf-8")
    (scripts / "check_release.py").write_text("raise SystemExit('Release review is pending')", encoding="utf-8")
    (scripts / "prepare_release_sources.py").write_text("raise SystemExit('Unexpected source download')", encoding="utf-8")
    venv = tmp_path / ".venv/Scripts"
    venv.mkdir(parents=True)
    shutil.copyfile(sys.executable, venv / "python.exe")
    (tmp_path / ".venv/pyvenv.cfg").write_text(f"home = {sys.base_prefix}\n", encoding="utf-8")
    portable = tmp_path / "dist/ApeArchivesExtractor"
    portable.mkdir(parents=True)
    (portable / "ApeArchivesExtractor.exe").write_bytes(b"fixture")
    packaging = tmp_path / "packaging"
    packaging.mkdir()
    (packaging / "ApeArchivesExtractor.iss").write_text('#define MyAppVersion "1.0.1"\n', encoding="utf-8")
    (scripts / "compiler.ps1").write_text("""
$args | Set-Content compiler-args.txt
New-Item -Path dist/ApeArchivesExtractorSetup-1.0.1-development.exe -ItemType File | Out-Null
$global:LASTEXITCODE = 0
""", encoding="utf-8")
    (scripts / "run.ps1").write_text("""
function Get-Command {
    param($Name, $ErrorAction)
    [pscustomobject]@{ Source = (Join-Path $PSScriptRoot 'compiler.ps1') }
}
& (Join-Path $PSScriptRoot 'build_windows_installer.ps1') @args
""", encoding="utf-8")
    return tmp_path


def run_build(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(project / "scripts/run.ps1"), *args], cwd=project, capture_output=True,
                          text=True, timeout=20)


def test_development_installer_skips_release_downloads_and_review(installer_project: Path) -> None:
    result = run_build(installer_project, "-SkipBuild", "-DevelopmentBuild")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "/DDevelopmentBuild" in (installer_project / "compiler-args.txt").read_text()
    assert "-development.exe" in result.stdout


def test_distributable_installer_stops_when_review_is_pending(installer_project: Path) -> None:
    result = run_build(installer_project, "-SkipBuild")
    assert result.returncode != 0
    assert "Release review is pending" in result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_reports_compiler_failure(installer_project: Path) -> None:
    (installer_project / "scripts/compiler.ps1").write_text("$global:LASTEXITCODE = 42\n", encoding="utf-8")
    result = run_build(installer_project, "-SkipBuild", "-DevelopmentBuild")
    assert result.returncode != 0
    assert "Inno Setup fallita" in result.stderr


def test_installer_reports_missing_portable(installer_project: Path) -> None:
    (installer_project / "dist/ApeArchivesExtractor/ApeArchivesExtractor.exe").unlink()
    result = run_build(installer_project, "-SkipBuild", "-DevelopmentBuild")
    assert result.returncode != 0
    assert "Eseguibile portabile non trovato" in result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_retries_transient_windows_resource_update_failure(installer_project: Path) -> None:
    (installer_project / "scripts/compiler.ps1").write_text("""
if (-not (Test-Path compiler-first-attempt.txt)) {
    New-Item compiler-first-attempt.txt -ItemType File | Out-Null
    Write-Output 'Resource update error: EndUpdateResource failed (110)'
    $global:LASTEXITCODE = 1
} else {
    New-Item -Path dist/ApeArchivesExtractorSetup-1.0.1-development.exe -ItemType File | Out-Null
    $global:LASTEXITCODE = 0
}
""", encoding="utf-8")
    result = run_build(installer_project, "-SkipBuild", "-DevelopmentBuild")
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Riprovo" in result.stdout
