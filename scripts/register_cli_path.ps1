# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
[CmdletBinding()]
param(
    [string]$InstallPath,
    [ValidateSet('User', 'Machine')][string]$Scope = 'User',
    [switch]$Unregister
)

$ErrorActionPreference = 'Stop'

function ConvertTo-CliPathKey {
    param([string]$Value)
    [Environment]::ExpandEnvironmentVariables($Value.Trim().Trim('"')).TrimEnd('\', '/')
}

function Remove-OwnedCliPathEntry {
    param([string]$PathValue, [string]$Entry)
    $parts = [System.Collections.Generic.List[string]]::new()
    $parts.AddRange([string[]]$PathValue.Split(';'))
    # The installer appends one entry. Preserve other entries, even duplicates.
    for ($index = $parts.Count - 1; $index -ge 0; $index--) {
        if ((ConvertTo-CliPathKey $parts[$index]) -ieq (ConvertTo-CliPathKey $Entry)) {
            $parts.RemoveAt($index)
            break
        }
    }
    $parts -join ';'
}

function Update-CliPath {
    param($EnvironmentKey, $StateKey, [string]$Directory, [switch]$Remove)
    $raw = $EnvironmentKey.GetValue('Path', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
    if ($null -ne $raw) { $kind = $EnvironmentKey.GetValueKind('Path') }
    $pathValue = [string]$raw
    $owned = [string]$StateKey.GetValue('CliPathEntry', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    if ($Remove) {
        if (-not $owned -or (ConvertTo-CliPathKey $owned) -ine (ConvertTo-CliPathKey $Directory)) { return }
        $updated = Remove-OwnedCliPathEntry $pathValue $owned
        if ($updated -cne $pathValue) { $EnvironmentKey.SetValue('Path', $updated, $kind) }
        $StateKey.DeleteValue('CliPathEntry', $false)
        return
    }

    # A change of installation directory must not leave an owned stale entry.
    if ($owned -and (ConvertTo-CliPathKey $owned) -ine (ConvertTo-CliPathKey $Directory)) {
        $pathValue = Remove-OwnedCliPathEntry $pathValue $owned
        $StateKey.DeleteValue('CliPathEntry', $false)
        $owned = ''
    }
    $present = @($pathValue.Split(';') | Where-Object {
        (ConvertTo-CliPathKey $_) -ieq (ConvertTo-CliPathKey $Directory)
    }).Count -gt 0
    if (-not $present) {
        if ($pathValue.Length -eq 0) { $pathValue = $Directory }
        else { $pathValue += ';' + $Directory }
    }
    if ($pathValue -cne [string]$raw) { $EnvironmentKey.SetValue('Path', $pathValue, $kind) }
    # Existing entries belong to the user. Only record an entry added by us.
    if (-not $present -or $owned) {
        $StateKey.SetValue('CliPathEntry', $Directory, [Microsoft.Win32.RegistryValueKind]::String)
    }
}

# Dot-sourcing exposes the pure update logic for tests using in-memory keys.
if ($MyInvocation.InvocationName -eq '.') { return }
if (-not $InstallPath -or $InstallPath.Contains(';')) { throw 'Invalid CLI installation directory.' }
$InstallPath = [IO.Path]::GetFullPath($InstallPath).TrimEnd('\', '/')
if (-not $Unregister -and -not (Test-Path -LiteralPath (Join-Path $InstallPath 'ape-arch.exe') -PathType Leaf)) {
    throw "Console executable not found: $InstallPath\ape-arch.exe"
}
$hive = [Microsoft.Win32.Registry]::CurrentUser
$environmentSubkey = 'Environment'
if ($Scope -eq 'Machine') {
    $hive = [Microsoft.Win32.Registry]::LocalMachine
    $environmentSubkey = 'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
}
$stateSubkey = 'Software\GiancaGIS\ApeArchivesExtractor\Installer'
$environmentKey = $null
$stateKey = $null
try {
    if ($Unregister) {
        $stateKey = $hive.OpenSubKey($stateSubkey, $true)
        if ($null -eq $stateKey) { return }
        $environmentKey = $hive.OpenSubKey($environmentSubkey, $true)
        if ($null -eq $environmentKey) { return }
    } else {
        $stateKey = $hive.CreateSubKey($stateSubkey)
        $environmentKey = $hive.CreateSubKey($environmentSubkey)
    }
    Update-CliPath $environmentKey $stateKey $InstallPath -Remove:$Unregister
} finally {
    if ($null -ne $environmentKey) { $environmentKey.Dispose() }
    if ($null -ne $stateKey) { $stateKey.Dispose() }
}
