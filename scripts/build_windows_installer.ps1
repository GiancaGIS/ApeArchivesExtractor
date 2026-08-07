# Run from the project root on Windows PowerShell.
$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$buildScript = Join-Path $PSScriptRoot "build_windows.ps1"
if (-not (Test-Path -LiteralPath $buildScript -PathType Leaf)) {
    throw "Script di build non trovato: $buildScript"
}

& $buildScript

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
    Write-Warning "Build PyInstaller completata, ma Inno Setup 6 non e' installato o non e' nel PATH."
    Write-Warning "Installa Inno Setup 6 e rilancia: .\scripts\build_windows_installer.ps1"
    Write-Host "Exe portabile disponibile in: dist\ApeArchivesExtractor\ApeArchivesExtractor.exe"
    exit 0
}

& $isccPath "packaging\ApeArchivesExtractor.iss"
if ($LASTEXITCODE -ne 0) { throw "Compilazione installer Inno Setup fallita." }

$installer = Get-ChildItem -Path (Join-Path $root "dist") -Filter "ApeArchivesExtractorSetup-*.exe" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1
if (-not $installer) { throw "Installer compilato ma non trovato nella cartella dist." }

Write-Host "Installer creato in: $($installer.FullName)"
