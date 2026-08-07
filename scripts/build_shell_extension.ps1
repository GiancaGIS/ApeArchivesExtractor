# Run from the project root on Windows PowerShell.
param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release",
    [ValidateSet("x64")]
    [string]$Platform = "x64"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$project = Join-Path $root "native\shell_extension\ApeArchivesExtractorShellExtension.vcxproj"
if (-not (Test-Path -LiteralPath $project -PathType Leaf)) {
    throw "Progetto shell extension non trovato: $project"
}

function Find-MSBuild {
    $command = Get-Command "MSBuild.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $vswhereCandidates = @(
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe",
        "${env:ProgramFiles}\Microsoft Visual Studio\Installer\vswhere.exe"
    )

    foreach ($candidate in $vswhereCandidates) {
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        $path = & $candidate -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" |
            Select-Object -First 1
        if ($path) {
            return $path
        }
    }

    return $null
}

function Find-PlatformToolset {
    param(
        [string]$MSBuildPath,
        [string]$PlatformName
    )

    $msbuildBin = Split-Path -Parent $MSBuildPath
    $visualStudioRoot = Resolve-Path (Join-Path $msbuildBin "..\..\..") -ErrorAction SilentlyContinue
    if (-not $visualStudioRoot) {
        return $null
    }

    $vcMsbuildRoot = Join-Path $visualStudioRoot.Path "MSBuild\Microsoft\VC"
    if (-not (Test-Path -LiteralPath $vcMsbuildRoot -PathType Container)) {
        return $null
    }

    $toolset = Get-ChildItem -LiteralPath $vcMsbuildRoot -Directory -ErrorAction SilentlyContinue |
        ForEach-Object {
            Join-Path $_.FullName "Platforms\$PlatformName\PlatformToolsets"
        } |
        Where-Object { Test-Path -LiteralPath $_ -PathType Container } |
        ForEach-Object { Get-ChildItem -LiteralPath $_ -Directory -ErrorAction SilentlyContinue } |
        Sort-Object Name -Descending |
        Select-Object -First 1

    if ($toolset) {
        return $toolset.Name
    }
    return $null
}

$msbuild = Find-MSBuild
if (-not $msbuild) {
    Write-Warning "MSBuild non trovato. La shell extension Windows 11 non verra' compilata."
    Write-Warning "Installa Visual Studio 2022 Build Tools con workload C++ e rilancia lo script."
    exit 0
}

$platformToolset = Find-PlatformToolset -MSBuildPath $msbuild -PlatformName $Platform
if (-not $platformToolset) {
    Write-Warning "Platform toolset C++ non trovato. La shell extension Windows 11 non verra' compilata."
    Write-Warning "Installa il workload C++ di Visual Studio e rilancia lo script."
    exit 0
}

$pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
if ($pathValue) {
    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $pathValue, "Process")
}

$msbuildArgs = @(
    '"' + $project + '"',
    "/restore",
    "/m",
    "/p:Configuration=$Configuration",
    "/p:Platform=$Platform",
    "/p:PlatformToolset=$platformToolset"
)
$msbuildCommand = 'set "PATH=%Path%" && "' + $msbuild + '" ' + ($msbuildArgs -join " ")
& cmd.exe /d /c $msbuildCommand
if ($LASTEXITCODE -ne 0) {
    throw "Build della shell extension Windows 11 fallita."
}

$output = Join-Path $root "dist\ApeArchivesExtractor\ApeArchivesExtractorShellExtension.dll"
if (-not (Test-Path -LiteralPath $output -PathType Leaf)) {
    throw "Build completata ma DLL non trovata: $output"
}

Write-Host "Shell extension Windows 11 compilata: $output"
