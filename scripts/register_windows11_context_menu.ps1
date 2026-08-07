param(
    [string]$InstallDir = $PSScriptRoot,
    [string]$PackagePath = (Join-Path $PSScriptRoot "ApeArchivesExtractorIdentity.msix"),
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$packageName = "GiancaGIS.ApeArchivesExtractor"
$dllPath = Join-Path $InstallDir "ApeArchivesExtractorShellExtension.dll"

function Notify-Shell {
    if (-not ("ApeArchivesExtractor.ShellNativeMethods" -as [type])) {
        Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

namespace ApeArchivesExtractor {
    public static class ShellNativeMethods {
        [DllImport("shell32.dll")]
        public static extern void SHChangeNotify(
            uint eventId,
            uint flags,
            IntPtr item1,
            IntPtr item2
        );
    }
}
"@
    }

    [ApeArchivesExtractor.ShellNativeMethods]::SHChangeNotify(
        0x08000000,
        0x0000,
        [IntPtr]::Zero,
        [IntPtr]::Zero
    )
}

if ([Environment]::OSVersion.Version.Build -lt 19041) {
    Write-Host "Identity package non supportato su questa build di Windows. Registrazione Windows 11 saltata."
    exit 0
}

if ($Unregister) {
    if (Test-Path -LiteralPath $dllPath -PathType Leaf) {
        & regsvr32.exe /s /u $dllPath
        if ($LASTEXITCODE -ne 0) {
            Write-Warning "Deregistrazione COM non riuscita per: $dllPath"
        }
    }

    $package = Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue
    if ($package) {
        $package | Remove-AppxPackage
    }

    Notify-Shell
    Write-Host "Integrazione Windows 11 rimossa."
    exit 0
}

if (-not (Test-Path -LiteralPath $dllPath -PathType Leaf)) {
    Write-Warning "ApeArchivesExtractorShellExtension.dll non trovata. Menu contestuale moderno non registrato."
    exit 0
}
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) {
    Write-Warning "ApeArchivesExtractorIdentity.msix non trovato. Menu contestuale moderno non registrato."
    exit 0
}

$signature = Get-AuthenticodeSignature -FilePath $PackagePath
if ($signature.Status -ne "Valid") {
    Write-Warning "ApeArchivesExtractorIdentity.msix non ha una firma valida. Menu contestuale moderno non registrato."
    Write-Warning "Firma il pacchetto con un certificato attendibile e riesegui questo script."
    exit 0
}

& regsvr32.exe /s $dllPath
if ($LASTEXITCODE -ne 0) {
    throw "Registrazione COM fallita per: $dllPath"
}

$existing = Get-AppxPackage -Name $packageName -ErrorAction SilentlyContinue
if ($existing) {
    $existing | Remove-AppxPackage
}

$resolvedPackagePath = (Resolve-Path -LiteralPath $PackagePath).Path
$resolvedInstallDir = (Resolve-Path -LiteralPath $InstallDir).Path
Add-AppxPackage -Path $resolvedPackagePath -ExternalLocation $resolvedInstallDir

Notify-Shell
Write-Host "Menu contestuale moderno di Windows 11 registrato per ApeArchivesExtractor."
