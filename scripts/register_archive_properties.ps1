# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
[CmdletBinding()]
param(
    [string]$InstallDir = $PSScriptRoot,
    [ValidateSet('User', 'Machine')][string]$Scope = 'User',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'
$script:ArchivePropertiesClsid = '{D91D509B-3AAB-4938-B976-48910A455D61}'

function Update-ArchivePropertiesRegistration {
    param($RootKey, [string]$Directory, [switch]$Remove)
    $classKey = 'Software\Classes\CLSID\' + $script:ArchivePropertiesClsid
    $handlerKey = 'Software\Classes\*\shellex\PropertySheetHandlers\ApeArchivesExtractor'
    $approvedKey = 'Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved'
    $dll = [IO.Path]::GetFullPath((Join-Path $Directory 'ApeArchivesExtractorShellExtension.dll'))
    if ($Remove) {
        $inproc = $RootKey.OpenSubKey($classKey + '\InprocServer32', $false)
        if ($null -eq $inproc) { return }
        try { $registered = [string]$inproc.GetValue('') } finally { $inproc.Dispose() }
        # An older installation must not unregister a newer installation's DLL.
        if (-not $registered -or $registered -ine $dll) { return }
        $handler = $RootKey.OpenSubKey($handlerKey, $false)
        if ($null -ne $handler) {
            try { $owner = [string]$handler.GetValue('') } finally { $handler.Dispose() }
            if ($owner -ieq $script:ArchivePropertiesClsid) { $RootKey.DeleteSubKeyTree($handlerKey, $false) }
        }
        $RootKey.DeleteSubKeyTree($classKey, $false)
        $approved = $RootKey.OpenSubKey($approvedKey, $true)
        if ($null -ne $approved) {
            try { $approved.DeleteValue($script:ArchivePropertiesClsid, $false) } finally { $approved.Dispose() }
        }
        return
    }
    $values = @(
        @($classKey, '', 'ApeArchivesExtractor archive properties'),
        @(($classKey + '\InprocServer32'), '', $dll),
        @(($classKey + '\InprocServer32'), 'ThreadingModel', 'Apartment'),
        @($handlerKey, '', $script:ArchivePropertiesClsid),
        @($approvedKey, $script:ArchivePropertiesClsid, 'ApeArchivesExtractor archive properties')
    )
    foreach ($entry in $values) {
        $key = $RootKey.CreateSubKey($entry[0])
        try { $key.SetValue($entry[1], $entry[2], [Microsoft.Win32.RegistryValueKind]::String) }
        finally { $key.Dispose() }
    }
}

# Unit tests dot-source the updater and provide in-memory registry keys.
if ($MyInvocation.InvocationName -eq '.') { return }
$InstallDir = [IO.Path]::GetFullPath($InstallDir)
if (-not $Unregister) {
    foreach ($name in @('ApeArchivesExtractorShellExtension.dll', 'ape-arch.exe')) {
        if (-not (Test-Path -LiteralPath (Join-Path $InstallDir $name) -PathType Leaf)) {
            throw "Archive properties component missing: $name"
        }
    }
}
$rootKey = [Microsoft.Win32.Registry]::CurrentUser
if ($Scope -eq 'Machine') { $rootKey = [Microsoft.Win32.Registry]::LocalMachine }
Update-ArchivePropertiesRegistration $rootKey $InstallDir -Remove:$Unregister
if (-not ('ApeArchivesExtractor.ArchivePropertiesShellNotify' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
namespace ApeArchivesExtractor {
    public static class ArchivePropertiesShellNotify {
        [DllImport("shell32.dll")]
        public static extern void SHChangeNotify(uint eventId, uint flags, IntPtr first, IntPtr second);
    }
}
'@
}
[ApeArchivesExtractor.ArchivePropertiesShellNotify]::SHChangeNotify(0x08000000, 0, [IntPtr]::Zero, [IntPtr]::Zero)
Write-Output 'Archive properties registration updated.'
