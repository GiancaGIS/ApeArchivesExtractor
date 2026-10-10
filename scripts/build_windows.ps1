# Run from the project root on Windows PowerShell.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m venv .venv

$python = Join-Path $root ".venv\Scripts\python.exe"

& $python -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "Aggiornamento pip fallito." }

& $python -m pip install -e ".[package]"
if ($LASTEXITCODE -ne 0) { throw "Installazione dipendenze package fallita." }

& $python scripts\build_icons.py
if ($LASTEXITCODE -ne 0) { throw "Generazione icone fallita." }

& $python -m PyInstaller --noconfirm --clean packaging\ApeArchivesExtractor.spec
if ($LASTEXITCODE -ne 0) { throw "Build PyInstaller fallita." }

$shellExtensionScript = Join-Path $PSScriptRoot "build_shell_extension.ps1"
if (Test-Path -LiteralPath $shellExtensionScript -PathType Leaf) {
    & $shellExtensionScript
    if ($LASTEXITCODE -ne 0) { throw "Build shell extension Windows 11 fallita." }
}

$sparsePackageScript = Join-Path $PSScriptRoot "build_sparse_package.ps1"
if (Test-Path -LiteralPath $sparsePackageScript -PathType Leaf) {
    & $sparsePackageScript
    if ($LASTEXITCODE -ne 0) { throw "Build identity package Windows 11 fallita." }
}

Write-Host "Build locale completata. Output: dist\ApeArchivesExtractor"
Write-Host "Prima di distribuire: esegui scripts\prepare_release_sources.py e segui RELEASE_CHECKLIST.md."
