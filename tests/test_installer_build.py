# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def installer_project(tmp_path: Path) -> Path:
    if not shutil.which("powershell.exe"):
        pytest.skip("Windows PowerShell is required")
    windows = tmp_path / "build_tools/windows"
    common = tmp_path / "build_tools/common"
    windows.mkdir(parents=True)
    common.mkdir()
    shutil.copyfile("build_tools/windows/compile_installer.ps1", windows / "compile_installer.ps1")
    (common / "check_release.py").write_text("from pathlib import Path; Path('release-checked.txt').write_text('checked')", encoding="utf-8")
    venv = tmp_path / ".venv/Scripts"
    venv.mkdir(parents=True)
    shutil.copyfile(sys.executable, venv / "python.exe")
    (tmp_path / ".venv/pyvenv.cfg").write_text(f"home = {sys.base_prefix}\n", encoding="utf-8")
    portable = tmp_path / "dist/ApeArchivesExtractor"
    portable.mkdir(parents=True)
    (portable / "ApeArchivesExtractor.exe").write_bytes(b"fixture")
    (portable / "ape-arch.exe").write_bytes(b"console fixture")
    (windows / "ApeArchivesExtractor.iss").write_text('#define MyAppVersion "1.1.0"\n', encoding="utf-8")
    (windows / "compiler.ps1").write_text("""
if ($args[0] -eq '/?') {
    Write-Output "Inno Setup $env:FIXTURE_INNO_MAJOR Command-Line Compiler"
    $global:LASTEXITCODE = 0
    return
}
& (Join-Path $PSScriptRoot 'compiler_action.ps1') @args
""", encoding="utf-8")
    (windows / "compiler_action.ps1").write_text("""
$args | Set-Content compiler-args.txt
New-Item -Path dist/ApeArchivesExtractorSetup-1.1.0.exe -ItemType File | Out-Null
$global:LASTEXITCODE = 0
""", encoding="utf-8")
    (windows / "run.ps1").write_text("""
$emptyToolDir = Join-Path $PSScriptRoot 'empty-tool-directory'
$env:ProgramFiles = $emptyToolDir
${env:ProgramFiles(x86)} = $emptyToolDir
$env:LOCALAPPDATA = $emptyToolDir
function Get-Command {
    param($Name, $CommandType, $ErrorAction)
    [pscustomobject]@{ Source = (Join-Path $PSScriptRoot 'compiler.ps1') }
}
& (Join-Path $PSScriptRoot 'compile_installer.ps1')
""", encoding="utf-8")
    return tmp_path


def run_build(project: Path, *, compiler_major: int = 7) -> subprocess.CompletedProcess:
    env = {**os.environ, "FIXTURE_INNO_MAJOR": str(compiler_major)}
    return subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                           str(project / "build_tools/windows/run.ps1")], cwd=project, capture_output=True,
                          env=env, text=True, timeout=20)


def test_installer_verifies_prepared_release_and_uses_standard_filename(installer_project: Path) -> None:
    result = run_build(installer_project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert (installer_project / "compiler-args.txt").read_text().strip() == "build_tools\\windows\\ApeArchivesExtractor.iss"
    assert "ApeArchivesExtractorSetup-1.1.0.exe" in result.stdout
    assert (installer_project / "release-checked.txt").is_file()


def test_installer_rejects_a_bundle_without_the_console_command(installer_project: Path) -> None:
    (installer_project / "dist/ApeArchivesExtractor/ape-arch.exe").unlink()
    result = run_build(installer_project)
    assert result.returncode != 0
    assert "ape-arch.exe" in result.stdout + result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_stops_when_release_material_checks_fail(installer_project: Path) -> None:
    (installer_project / "build_tools/common/check_release.py").write_text("raise SystemExit('Source archive digest mismatch')", encoding="utf-8")
    result = run_build(installer_project)
    assert result.returncode != 0
    assert "Source archive digest mismatch" in result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_reports_compiler_failure(installer_project: Path) -> None:
    (installer_project / "build_tools/windows/compiler_action.ps1").write_text("$global:LASTEXITCODE = 42\n", encoding="utf-8")
    result = run_build(installer_project)
    assert result.returncode != 0
    assert "Inno Setup fallita" in result.stderr


def test_installer_rejects_inno_setup_6_on_path(installer_project: Path) -> None:
    result = run_build(installer_project, compiler_major=6)
    assert result.returncode != 0
    assert "Inno Setup 7 non trovato" in result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_reports_missing_portable(installer_project: Path) -> None:
    (installer_project / "dist/ApeArchivesExtractor/ApeArchivesExtractor.exe").unlink()
    result = run_build(installer_project)
    assert result.returncode != 0
    assert "Eseguibile portabile non trovato" in result.stderr
    assert not (installer_project / "compiler-args.txt").exists()


def test_installer_retries_transient_windows_resource_update_failure(installer_project: Path) -> None:
    (installer_project / "build_tools/windows/compiler_action.ps1").write_text("""
if (-not (Test-Path compiler-first-attempt.txt)) {
    New-Item compiler-first-attempt.txt -ItemType File | Out-Null
    Write-Output 'Resource update error: EndUpdateResource failed (110)'
    $global:LASTEXITCODE = 1
} else {
    New-Item -Path dist/ApeArchivesExtractorSetup-1.1.0.exe -ItemType File | Out-Null
    $global:LASTEXITCODE = 0
}
""", encoding="utf-8")
    result = run_build(installer_project)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Riprovo" in result.stdout
