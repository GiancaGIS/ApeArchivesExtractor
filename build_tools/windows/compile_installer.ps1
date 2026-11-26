# Called inside the staging directory after preparing bundled notices.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Ambiente di compilazione non trovato: $python"
}
$portable = Join-Path $root "dist\ApeArchivesExtractor\ApeArchivesExtractor.exe"
if (-not (Test-Path -LiteralPath $portable -PathType Leaf)) {
    throw "Eseguibile portabile non trovato: $portable"
}
$console = Join-Path $root "dist\ApeArchivesExtractor\ape-arch.exe"
if (-not (Test-Path -LiteralPath $console -PathType Leaf)) {
    throw "Eseguibile console ape-arch.exe non trovato: $console"
}
& $python build_tools\common\check_release.py --bundle-only
if ($LASTEXITCODE -ne 0) {
    throw "Verifica dei materiali inclusi nel pacchetto fallita."
}

$isccCommand = Get-Command "ISCC.exe" -CommandType Application -ErrorAction SilentlyContinue
$candidates = @(
    $isccCommand.Source,
    "$env:ProgramFiles\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 7 (32-bit)\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 7 (32-bit)\ISCC.exe"
)
$isccPath = $null
foreach ($candidate in $candidates) {
    if (-not $candidate -or -not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    # The help banner also identifies 7.0, which predates the --version option.
    $banner = & $candidate '/?' | Out-String
    if ($banner -match '(?m)^Inno Setup 7 Command-Line Compiler\b') {
        $isccPath = $candidate
        break
    }
}

if (-not $isccPath) {
    throw "Inno Setup 7 non trovato. Installa Inno Setup 7 o aggiungi il suo ISCC.exe al PATH."
}

$compilerArgs = @("build_tools\windows\ApeArchivesExtractor.iss")
& $isccPath @compilerArgs | Tee-Object -Variable compilerOutput
if ($LASTEXITCODE -ne 0 -and ($compilerOutput -match 'EndUpdateResource failed')) {
    Write-Warning "Aggiornamento risorse Windows fallito. Riprovo la compilazione una volta."
    Start-Sleep -Seconds 1
    & $isccPath @compilerArgs
}
if ($LASTEXITCODE -ne 0) { throw "Compilazione installer Inno Setup fallita." }

$definition = Get-Content -LiteralPath $compilerArgs[0] -Raw
$version = [regex]::Match($definition, '(?m)^#define MyAppVersion "([^"]+)"').Groups[1].Value
if (-not $version) { throw "Versione installer non trovata in $($compilerArgs[0])." }
$installerPath = Join-Path $root "dist\ApeArchivesExtractorSetup-$version.exe"
if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
    throw "Installer compilato ma non trovato: $installerPath"
}

Write-Host "Installer creato in: $installerPath"
