# Compatibility entry point for the portable Windows build.
param(
    [string]$Python,
    [string]$BuildRoot
)
& (Join-Path $PSScriptRoot "..\build_tools\windows\build_windows_installer.ps1") -BundleOnly @PSBoundParameters
exit $LASTEXITCODE
