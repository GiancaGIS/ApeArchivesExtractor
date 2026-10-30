# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows shell registration")
@pytest.mark.parametrize("scenario", ["roundtrip", "other-install", "replaced-handler"])
def test_property_sheet_registration_owns_only_its_keys(tmp_path: Path, scenario: str) -> None:
    script = tmp_path / "registration-test.ps1"
    script.write_text(r'''
param([string]$Helper, [string]$Scenario)
. $Helper
class MemoryKey {
    [hashtable]$Values = @{}
    [object] GetValue([string]$Name) { return $this.Values[$Name] }
    [void] SetValue([string]$Name, [object]$Value, [Microsoft.Win32.RegistryValueKind]$Kind) { $this.Values[$Name] = $Value }
    [void] DeleteValue([string]$Name, [bool]$Throw) { $this.Values.Remove($Name) }
    [void] Dispose() {}
}
class MemoryRoot {
    [hashtable]$Keys = @{}
    [MemoryKey] OpenSubKey([string]$Name, [bool]$Write) { return $this.Keys[$Name] }
    [MemoryKey] CreateSubKey([string]$Name) {
        if (-not $this.Keys.ContainsKey($Name)) { $this.Keys[$Name] = [MemoryKey]::new() }
        return $this.Keys[$Name]
    }
    [void] DeleteSubKeyTree([string]$Name, [bool]$Throw) {
        foreach ($key in @($this.Keys.Keys)) {
            if ($key -eq $Name -or $key.StartsWith($Name + '\')) { $this.Keys.Remove($key) }
        }
    }
}
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$root = [MemoryRoot]::new()
$directory = 'C:\Program Files\APE Archives'
$clsid = '{D91D509B-3AAB-4938-B976-48910A455D61}'
$class = 'Software\Classes\CLSID\' + $clsid
$handler = 'Software\Classes\*\shellex\PropertySheetHandlers\ApeArchivesExtractor'
$approved = 'Software\Microsoft\Windows\CurrentVersion\Shell Extensions\Approved'
$other = $root.CreateSubKey('Software\Classes\*\shellex\PropertySheetHandlers\OtherApplication')
$other.SetValue('', '{OTHER}', [Microsoft.Win32.RegistryValueKind]::String)
Update-ArchivePropertiesRegistration $root $directory
Assert ($root.Keys[$handler].Values[''] -eq $clsid) 'Handler CLSID mismatch'
Assert ($root.Keys[$class + '\InprocServer32'].Values['ThreadingModel'] -eq 'Apartment') 'COM threading model mismatch'
Assert ($root.Keys[$class + '\InprocServer32'].Values[''] -eq ($directory + '\ApeArchivesExtractorShellExtension.dll')) 'DLL path mismatch'
$count = $root.Keys.Count
Update-ArchivePropertiesRegistration $root $directory
Assert ($root.Keys.Count -eq $count) 'Registration must be idempotent'
if ($Scenario -eq 'other-install') {
    Update-ArchivePropertiesRegistration $root 'C:\Newer Install'
    Update-ArchivePropertiesRegistration $root $directory -Remove
    Assert ($root.Keys.ContainsKey($class)) 'Old uninstall must preserve newer registration'
    Assert ($root.Keys.ContainsKey($handler)) 'Old uninstall removed newer handler'
    $directory = 'C:\Newer Install'
}
if ($Scenario -eq 'replaced-handler') { $root.Keys[$handler].Values[''] = '{SOMEONE-ELSE}' }
Update-ArchivePropertiesRegistration $root $directory -Remove
Assert (-not $root.Keys.ContainsKey($class)) 'Owned COM class was not removed'
Assert (-not $root.Keys[$approved].Values.ContainsKey($clsid)) 'Owned approval was not removed'
Assert ($root.Keys.ContainsKey('Software\Classes\*\shellex\PropertySheetHandlers\OtherApplication')) 'An unrelated handler was removed'
if ($Scenario -eq 'replaced-handler') {
    Assert ($root.Keys[$handler].Values[''] -eq '{SOMEONE-ELSE}') 'A replacement handler was removed'
} else { Assert (-not $root.Keys.ContainsKey($handler)) 'Owned handler was not removed' }
Update-ArchivePropertiesRegistration $root $directory -Remove
''', encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Helper", str(Path("scripts/register_archive_properties.ps1").resolve()), "-Scenario", scenario],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
