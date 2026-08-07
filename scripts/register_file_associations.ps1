param(
    [string]$InstallPath = (Join-Path $PSScriptRoot "ApeArchivesExtractor.exe"),
    [switch]$SetDefault,
    [switch]$Unregister
)

$ErrorActionPreference = "Stop"

$appName = "ApeArchivesExtractor"
$appExeName = "ApeArchivesExtractor.exe"
$appDescription = "Archive manager for ZIP, 7Z, RAR and multi-volume files"
$extensions = @{
    ".zip" = "ApeArchivesExtractor.zip"
    ".7z" = "ApeArchivesExtractor.7z"
    ".rar" = "ApeArchivesExtractor.rar"
    ".001" = "ApeArchivesExtractor.numbered-volume"
    ".r00" = "ApeArchivesExtractor.rar-volume"
    ".r01" = "ApeArchivesExtractor.rar-volume"
    ".z01" = "ApeArchivesExtractor.zip-volume"
}
$createContextTargets = @(
    "*",
    "Directory"
)

function Ensure-Key {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        New-Item -Path $Path -Force | Out-Null
    }
}

function Set-Value {
    param(
        [string]$Path,
        [string]$Name,
        [string]$Value
    )
    Ensure-Key $Path
    if ($Name -eq "(default)") {
        Set-Item -LiteralPath $Path -Value $Value
    } else {
        New-ItemProperty -LiteralPath $Path -Name $Name -Value $Value -PropertyType String -Force | Out-Null
    }
}

function Remove-ValueIfExists {
    param(
        [string]$Path,
    [string]$Name
    )
    if (Test-Path -LiteralPath $Path) {
        if ($Name -eq "(default)") {
            Set-Item -LiteralPath $Path -Value ""
        } else {
            Remove-ItemProperty -LiteralPath $Path -Name $Name -ErrorAction SilentlyContinue
        }
    }
}

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

    # SHCNE_ASSOCCHANGED | SHCNF_IDLIST
    [ApeArchivesExtractor.ShellNativeMethods]::SHChangeNotify(
        0x08000000,
        0x0000,
        [IntPtr]::Zero,
        [IntPtr]::Zero
    )
}

$classesRoot = "HKCU:\Software\Classes"
$applicationsKey = Join-Path $classesRoot "Applications\$appExeName"
$capabilitiesKey = "HKCU:\Software\$appName\Capabilities"
$registeredApplicationsKey = "HKCU:\Software\RegisteredApplications"

if ($Unregister) {
    foreach ($entry in $extensions.GetEnumerator()) {
        $extension = $entry.Key
        $progId = $entry.Value

        Remove-Item -LiteralPath (Join-Path $classesRoot $progId) -Recurse -Force -ErrorAction SilentlyContinue
        Remove-ValueIfExists -Path (Join-Path $classesRoot "$extension\OpenWithProgids") -Name $progId
        Remove-ValueIfExists -Path (Join-Path $applicationsKey "SupportedTypes") -Name $extension
        Remove-Item -LiteralPath (Join-Path $classesRoot "SystemFileAssociations\$extension\shell\ApeArchivesExtractorOpen") -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path $classesRoot "SystemFileAssociations\$extension\shell\ApeArchivesExtractorExtractHere") -Recurse -Force -ErrorAction SilentlyContinue

        $extensionKey = Join-Path $classesRoot $extension
        if (Test-Path -LiteralPath $extensionKey) {
            $currentDefault = (Get-Item -LiteralPath $extensionKey -ErrorAction SilentlyContinue).GetValue("")
            if ($currentDefault -eq $progId) {
                Remove-ValueIfExists -Path $extensionKey -Name "(default)"
            }
        }
    }

    foreach ($target in $createContextTargets) {
        Remove-Item -LiteralPath (Join-Path $classesRoot "$target\shell\ApeArchivesExtractorCreateArchive") -Recurse -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath (Join-Path $classesRoot "*\shell\ApeArchivesExtractorOpenAsZip") -Recurse -Force -ErrorAction SilentlyContinue

    Remove-Item -LiteralPath $applicationsKey -Recurse -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath "HKCU:\Software\$appName" -Recurse -Force -ErrorAction SilentlyContinue
    Remove-ValueIfExists -Path $registeredApplicationsKey -Name $appName
    Notify-Shell
    Write-Host "Associazioni ApeArchivesExtractor rimosse."
    exit 0
}

if (-not (Test-Path $InstallPath)) {
    throw "ApeArchivesExtractor.exe non trovato: $InstallPath"
}

$resolvedInstallPath = (Resolve-Path $InstallPath).Path
$openCommand = '"' + $resolvedInstallPath + '" "%1"'
$openAsZipCommand = '"' + $resolvedInstallPath + '" --open-as-zip "%1"'
$extractHereCommand = '"' + $resolvedInstallPath + '" --extract-here "%1"'
$createArchiveCommand = '"' + $resolvedInstallPath + '" --create-archive "%1"'
$installDir = Split-Path -Parent $resolvedInstallPath
$assetsDir = Join-Path $installDir "_internal\apearchivesextractor\assets"
$appIconPath = Join-Path $assetsDir "apearchivesextractor_app.ico"
$archiveIconPath = Join-Path $assetsDir "apearchivesextractor_archive.ico"
$appIconValue = if (Test-Path -LiteralPath $appIconPath) { $appIconPath + ",0" } else { $resolvedInstallPath + ",0" }
$archiveIconValue = if (Test-Path -LiteralPath $archiveIconPath) { $archiveIconPath + ",0" } else { $appIconValue }

Set-Value -Path $applicationsKey -Name "FriendlyAppName" -Value $appName
Set-Value -Path $applicationsKey -Name "ApplicationDescription" -Value $appDescription
Set-Value -Path $registeredApplicationsKey -Name $appName -Value "Software\$appName\Capabilities"
Set-Value -Path $capabilitiesKey -Name "ApplicationName" -Value $appName
Set-Value -Path $capabilitiesKey -Name "ApplicationDescription" -Value $appDescription

foreach ($entry in $extensions.GetEnumerator()) {
    $extension = $entry.Key
    $progId = $entry.Value
    $progIdKey = Join-Path $classesRoot $progId
    $extensionKey = Join-Path $classesRoot $extension
    $openContextMenuKey = Join-Path $classesRoot "SystemFileAssociations\$extension\shell\ApeArchivesExtractorOpen"
    $extractContextMenuKey = Join-Path $classesRoot "SystemFileAssociations\$extension\shell\ApeArchivesExtractorExtractHere"

    Set-Value -Path $progIdKey -Name "(default)" -Value "$appName Archive"
    Set-Value -Path (Join-Path $progIdKey "DefaultIcon") -Name "(default)" -Value $archiveIconValue
    Set-Value -Path (Join-Path $progIdKey "shell\open\command") -Name "(default)" -Value $openCommand
    Set-Value -Path (Join-Path $progIdKey "shell\ApeArchivesExtractorExtractHere") -Name "(default)" -Value "Estrai qui con $appName"
    Set-Value -Path (Join-Path $progIdKey "shell\ApeArchivesExtractorExtractHere") -Name "Icon" -Value $appIconValue
    Set-Value -Path (Join-Path $progIdKey "shell\ApeArchivesExtractorExtractHere\command") -Name "(default)" -Value $extractHereCommand

    Set-Value -Path (Join-Path $extensionKey "OpenWithProgids") -Name $progId -Value ""
    Set-Value -Path (Join-Path $applicationsKey "SupportedTypes") -Name $extension -Value ""
    Set-Value -Path (Join-Path $capabilitiesKey "FileAssociations") -Name $extension -Value $progId

    Set-Value -Path $openContextMenuKey -Name "(default)" -Value "Apri con $appName"
    Set-Value -Path $openContextMenuKey -Name "MUIVerb" -Value "Apri con $appName"
    Set-Value -Path $openContextMenuKey -Name "Icon" -Value $appIconValue
    Set-Value -Path (Join-Path $openContextMenuKey "command") -Name "(default)" -Value $openCommand

    Set-Value -Path $extractContextMenuKey -Name "(default)" -Value "Estrai qui con $appName"
    Set-Value -Path $extractContextMenuKey -Name "MUIVerb" -Value "Estrai qui con $appName"
    Set-Value -Path $extractContextMenuKey -Name "Icon" -Value $appIconValue
    Set-Value -Path (Join-Path $extractContextMenuKey "command") -Name "(default)" -Value $extractHereCommand

    if ($SetDefault) {
        Set-Value -Path $extensionKey -Name "(default)" -Value $progId
    }
}

foreach ($target in $createContextTargets) {
    $createContextMenuKey = Join-Path $classesRoot "$target\shell\ApeArchivesExtractorCreateArchive"
    Set-Value -Path $createContextMenuKey -Name "(default)" -Value "Crea archivio con $appName"
    Set-Value -Path $createContextMenuKey -Name "MUIVerb" -Value "Crea archivio con $appName"
    Set-Value -Path $createContextMenuKey -Name "Icon" -Value $appIconValue
    Set-Value -Path $createContextMenuKey -Name "MultiSelectModel" -Value "Player"
    Set-Value -Path (Join-Path $createContextMenuKey "command") -Name "(default)" -Value $createArchiveCommand
}

$openAsZipContextMenuKey = Join-Path $classesRoot "*\shell\ApeArchivesExtractorOpenAsZip"
Set-Value -Path $openAsZipContextMenuKey -Name "(default)" -Value "Apri come archivio ZIP con $appName"
Set-Value -Path $openAsZipContextMenuKey -Name "MUIVerb" -Value "Apri come archivio ZIP con $appName"
Set-Value -Path $openAsZipContextMenuKey -Name "Icon" -Value $appIconValue
Set-Value -Path (Join-Path $openAsZipContextMenuKey "command") -Name "(default)" -Value $openAsZipCommand

Notify-Shell

Write-Host "ApeArchivesExtractor registrato per ZIP, 7Z, RAR e archivi multi-volume."
if ($SetDefault) {
    Write-Host "Tentativo di impostazione come app predefinita completato. Su Windows 10/11 potrebbe servire confermare da Impostazioni > App > App predefinite."
} else {
    Write-Host "Menu contestuale aggiunto: 'Apri con ApeArchivesExtractor', 'Apri come archivio ZIP con ApeArchivesExtractor', 'Estrai qui con ApeArchivesExtractor' e 'Crea archivio con ApeArchivesExtractor'."
    Write-Host "Per il doppio click, scegli ApeArchivesExtractor da Impostazioni > App > App predefinite."
}
