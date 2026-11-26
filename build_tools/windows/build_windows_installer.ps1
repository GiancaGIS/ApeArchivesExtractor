param(
    [string]$Python,
    [string]$BuildRoot,
    [switch]$BundleOnly,
    [switch]$SkipBuild
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Python) {
    $Python = Join-Path $root ".venv\Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) { $Python = "python.exe" }
}
$buildArguments = @()
if ($BuildRoot) { $buildArguments += @("--build-root", $BuildRoot) }
if ($BundleOnly) { $buildArguments += "--bundle-only" }
if ($SkipBuild) { $buildArguments += "--skip-build" }
& $Python (Join-Path $root "build_tools\common\build.py") @buildArguments
exit $LASTEXITCODE
