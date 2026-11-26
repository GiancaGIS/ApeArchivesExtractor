param(
    [string]$Distribution = "Ubuntu",
    [string]$Python = "python3",
    [string]$BuildRoot,
    [switch]$BundleOnly
)
$ErrorActionPreference = "Stop"
$script = & wsl.exe -d $Distribution --exec wslpath -a (Join-Path $PSScriptRoot "build_linux_installer.sh")
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$buildArguments = @("--python", $Python)
if ($BundleOnly) { $buildArguments += "--bundle-only" }
if ($BuildRoot) { $buildArguments += @("--build-root", $BuildRoot) }
& wsl.exe -d $Distribution --exec bash $script.Trim() @buildArguments
exit $LASTEXITCODE
