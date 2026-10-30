# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer PATH registration")
@pytest.mark.parametrize("scenario", ["roundtrip", "existing", "relocate", "duplicates", "long"])
def test_installer_path_preserves_environment_and_ownership(tmp_path: Path, scenario: str) -> None:
    script = tmp_path / "path_test.ps1"
    script.write_text(r'''
param([string]$Helper, [string]$Scenario)
$ErrorActionPreference = 'Stop'
. $Helper

# No registry or process/user PATH writes: use the production update logic with
# in-memory keys implementing the RegistryKey methods it needs.
class MemoryKey {
    [hashtable]$Values = @{}
    [hashtable]$Kinds = @{}
    [object] GetValue([string]$Name, [object]$Fallback, [Microsoft.Win32.RegistryValueOptions]$Options) {
        if ($this.Values.ContainsKey($Name)) { return $this.Values[$Name] }
        return $Fallback
    }
    [Microsoft.Win32.RegistryValueKind] GetValueKind([string]$Name) { return $this.Kinds[$Name] }
    [void] SetValue([string]$Name, [object]$Value, [Microsoft.Win32.RegistryValueKind]$Kind) {
        $this.Values[$Name] = $Value
        $this.Kinds[$Name] = $Kind
    }
    [void] DeleteValue([string]$Name, [bool]$ThrowOnMissing) { $this.Values.Remove($Name) }
}
function Assert([bool]$Condition, [string]$Message) { if (-not $Condition) { throw $Message } }
$environmentKey = [MemoryKey]::new()
$state = [MemoryKey]::new()
$directory = 'C:\Program Files\APE Archives'
$original = '%SystemRoot%\system32;C:\Other Tools;'
$kind = [Microsoft.Win32.RegistryValueKind]::ExpandString

switch ($Scenario) {
    'existing' { $original = 'C:\Tools;"c:\PROGRAM FILES\ape archives\";%SystemRoot%' }
    'long' {
        $original = (1..250 | ForEach-Object { 'C:\Other Tools\Tool-' + $_ }) -join ';'
        $kind = [Microsoft.Win32.RegistryValueKind]::String
    }
}
$environmentKey.SetValue('Path', $original, $kind)
Update-CliPath $environmentKey $state $directory
$installed = $environmentKey.Values['Path']
Assert ($environmentKey.Kinds['Path'] -eq $kind) 'Registry value type must be preserved'
Update-CliPath $environmentKey $state $directory
Assert ($environmentKey.Values['Path'] -ceq $installed) 'Reinstall must not add duplicates'

if ($Scenario -eq 'existing') {
    Assert (-not $state.Values.ContainsKey('CliPathEntry')) 'Preexisting entries must not be owned'
    Update-CliPath $environmentKey $state $directory -Remove
    Assert ($environmentKey.Values['Path'] -ceq $original) 'Uninstall must preserve preexisting entries'
    exit 0
}
Assert ($installed -ceq ($original + ';' + $directory)) 'Keep original tokens and separators verbatim'
if ($Scenario -eq 'relocate') {
    $newDirectory = 'C:\Apps\APE'
    Update-CliPath $environmentKey $state $newDirectory
    Assert ($environmentKey.Values['Path'] -ceq ($original + ';' + $newDirectory)) 'Remove the owned old directory'
    Update-CliPath $environmentKey $state $directory -Remove
    Assert ($environmentKey.Values['Path'] -ceq ($original + ';' + $newDirectory)) 'An older uninstall must not remove the new path'
    $directory = $newDirectory
}
if ($Scenario -eq 'duplicates') {
    $environmentKey.Values['Path'] += ';' + $directory
    $original += ';' + $directory
}
Update-CliPath $environmentKey $state $directory -Remove
Assert ($environmentKey.Values['Path'] -ceq $original) 'Remove only one owned entry, preserving other PATH entries'
Assert (-not $state.Values.ContainsKey('CliPathEntry')) 'Remove ownership after uninstall'
Update-CliPath $environmentKey $state $directory -Remove
Assert ($environmentKey.Values['Path'] -ceq $original) 'Repeated unregister must be harmless'
''', encoding="utf-8")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
         "-Helper", str(Path("scripts/register_cli_path.ps1").resolve()), "-Scenario", scenario],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
