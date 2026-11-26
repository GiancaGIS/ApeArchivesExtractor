# Compatibility entry point.
param(
    [string]$Python,
    [string]$BuildRoot,
    [switch]$BundleOnly,
    [switch]$SkipBuild
)
& (Join-Path $PSScriptRoot "..\build_tools\windows\build_windows_installer.ps1") @PSBoundParameters
exit $LASTEXITCODE
