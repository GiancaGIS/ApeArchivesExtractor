# Run from the project root on Windows PowerShell.
param(
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$buildScript = Join-Path $PSScriptRoot "build_windows.ps1"
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Script di build non trovato: $buildScript"
}

if (-not $SkipBuild) {
    & $buildScript
}

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python del progetto non trovato: $python. Esegui prima scripts\build_windows.ps1."
}
$portable = Join-Path $root "dist\ApeArchivesExtractor\ApeArchivesExtractor.exe"
if (-not (Test-Path -LiteralPath $portable -PathType Leaf)) {
    throw "Eseguibile portabile non trovato: $portable. Esegui prima scripts\build_windows.ps1."
}
$console = Join-Path $root "dist\ApeArchivesExtractor\ape-arch.exe"
if (-not (Test-Path -LiteralPath $console -PathType Leaf)) {
    throw "Eseguibile console ape-arch.exe non trovato: $console. Ricompila con scripts\build_windows.ps1."
}
if (-not $SkipBuild) {
    & $python scripts\prepare_release_sources.py
    if ($LASTEXITCODE -ne 0) { throw "Preparazione sorgenti e licenze fallita." }
}
& $python scripts\check_release.py
if ($LASTEXITCODE -ne 0) {
    throw "Verifica dei materiali di release fallita. Correggi gli errori indicati prima di compilare l'installer."
}

$isccCommand = Get-Command "ISCC.exe" -ErrorAction SilentlyContinue
$isccPath = if ($isccCommand) { $isccCommand.Source } else { $null }

if (-not $isccPath) {
    $candidates = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles}\Inno Setup 6\ISCC.exe"
    )

    foreach ($candidate in $candidates) {
        if ($candidate -and (Test-Path $candidate)) {
            $isccPath = $candidate
            break
        }
    }
}

if (-not $isccPath) {
    throw "Inno Setup 6 non trovato. Installalo e rilancia lo script con -SkipBuild. Exe portabile disponibile in: $portable"
}

$compilerArgs = @("packaging\ApeArchivesExtractor.iss")
& $isccPath @compilerArgs | Tee-Object -Variable compilerOutput
if ($LASTEXITCODE -ne 0 -and ($compilerOutput -match 'EndUpdateResource failed')) {
    Write-Warning "Aggiornamento risorse Windows fallito. Riprovo la compilazione una volta."
    Start-Sleep -Seconds 1
    & $isccPath @compilerArgs
}
if ($LASTEXITCODE -ne 0) { throw "Compilazione installer Inno Setup fallita." }

$definition = Get-Content -LiteralPath (Join-Path $root "packaging\ApeArchivesExtractor.iss") -Raw
$version = [regex]::Match($definition, '(?m)^#define MyAppVersion "([^"]+)"').Groups[1].Value
if (-not $version) { throw "Versione installer non trovata in packaging\ApeArchivesExtractor.iss." }
$installerPath = Join-Path $root "dist\ApeArchivesExtractorSetup-$version.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer compilato ma non trovato: $installerPath"
}

Write-Host "Installer creato in: $installerPath"
