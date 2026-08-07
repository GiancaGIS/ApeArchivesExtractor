# Run from the project root on Windows PowerShell.
param(
    [string]$CertificatePfx = $env:APEARCHIVESEXTRACTOR_SIGNING_CERT,
    [string]$CertificatePassword = $env:APEARCHIVESEXTRACTOR_SIGNING_PASSWORD
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$manifestSource = Join-Path $root "packaging\windows11\AppxManifest.xml"
$layoutDir = Join-Path $root "build\windows11\ApeArchivesExtractorIdentity"
$outputDir = Join-Path $root "dist\ApeArchivesExtractor"
$packagePath = Join-Path $outputDir "ApeArchivesExtractorIdentity.msix"

if (-not (Test-Path -LiteralPath $manifestSource -PathType Leaf)) {
    throw "Manifest identity package non trovato: $manifestSource"
}
if (-not (Test-Path -LiteralPath $outputDir -PathType Container)) {
    throw "Output PyInstaller non trovato: $outputDir"
}

function Find-WindowsSdkTool {
    param([string]$Name)

    $command = Get-Command $Name -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $sdkBin = "${env:ProgramFiles(x86)}\Windows Kits\10\bin"
    if (-not (Test-Path -LiteralPath $sdkBin -PathType Container)) {
        return $null
    }

    $candidate = Get-ChildItem -LiteralPath $sdkBin -Recurse -Filter $Name -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\$([regex]::Escape($Name))$" } |
        Sort-Object FullName -Descending |
        Select-Object -First 1

    if ($candidate) {
        return $candidate.FullName
    }
    return $null
}

$makeAppx = Find-WindowsSdkTool -Name "MakeAppx.exe"
if (-not $makeAppx) {
    Write-Warning "MakeAppx.exe non trovato. Il pacchetto identity Windows 11 non verra' creato."
    Write-Warning "Installa Windows SDK e rilancia lo script."
    exit 0
}

New-Item -ItemType Directory -Path $layoutDir -Force | Out-Null
Copy-Item -LiteralPath $manifestSource -Destination (Join-Path $layoutDir "AppxManifest.xml") -Force

& $makeAppx pack /o /d $layoutDir /nv /p $packagePath
if ($LASTEXITCODE -ne 0) {
    throw "Creazione pacchetto identity MSIX fallita."
}

if ($CertificatePfx) {
    if (-not (Test-Path -LiteralPath $CertificatePfx -PathType Leaf)) {
        throw "Certificato PFX non trovato: $CertificatePfx"
    }

    $signTool = Find-WindowsSdkTool -Name "SignTool.exe"
    if (-not $signTool) {
        throw "SignTool.exe non trovato. Installa Windows SDK o mettilo nel PATH."
    }

    $signArgs = @("sign", "/fd", "SHA256", "/f", $CertificatePfx)
    if ($CertificatePassword) {
        $signArgs += @("/p", $CertificatePassword)
    }
    $signArgs += $packagePath

    & $signTool @signArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Firma del pacchetto identity MSIX fallita."
    }

    Write-Host "Pacchetto identity Windows 11 creato e firmato: $packagePath"
} else {
    Write-Warning "Pacchetto identity creato ma non firmato: $packagePath"
    Write-Warning "Windows lo registrera' solo dopo la firma con un certificato attendibile."
}
