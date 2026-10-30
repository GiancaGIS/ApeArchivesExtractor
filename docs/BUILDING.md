# Building and releasing ApeArchivesExtractor

[Back to the README](../README.md)

## Development environment

Use Python 3.11 or newer. Create a virtual environment and install the development
and packaging extras from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,package]"
.\.venv\Scripts\python.exe -m pytest -q
```

On macOS/Linux, use `.venv/bin/python` instead. For headless tests, set
`QT_QPA_PLATFORM=offscreen` before running pytest.

## Application packages


PyInstaller is not a cross-compiler. Build the Windows package on Windows and the macOS package on macOS.

### Windows

From PowerShell in the project root:

```powershell
.\scripts\build_windows.ps1
```

If script execution is restricted by the system policy, run it explicitly with a process-level bypass:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows.ps1
```

The portable application is generated in:

```text
dist\ApeArchivesExtractor
```

To create the Windows installer, double-click `build_installer.bat`, or run:

```powershell
.\scripts\build_windows_installer.ps1
```

If required by the PowerShell execution policy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_windows_installer.ps1
```

This requires [Inno Setup 6](https://jrsoftware.org/isinfo.php). The generated installer is:

```text
dist\ApeArchivesExtractorSetup-1.0.3.exe
```

The installer includes the collected license texts. The build prepares the
matching source archive and verifies license files, sources and binary checksums
before compilation. For an existing portable build whose sources are already
prepared, use `.\scripts\build_windows_installer.ps1 -SkipBuild`.
Arguments passed to `build_installer.bat` are forwarded to the PowerShell script;
on failure, the launcher keeps the error visible. See
[Publishing a release](#publishing-a-release) for the publishing steps.

The installer asks whether to install ApeArchivesExtractor for the current user only or for
all users:

- Current user: installs under the user's profile, normally
  `%LOCALAPPDATA%\Programs\ApeArchivesExtractor`.
- All users: requests administrator privileges and installs under Program Files,
  normally `C:\Program Files\ApeArchivesExtractor`.

The portable directory includes `ApeArchivesExtractor.exe` (GUI) and
`ape-arch.exe` (console), sharing the same runtime. The **Add ape-arch to PATH**
task is selected by default. It updates the user PATH for a per-user install,
or the machine PATH for an all-users install, preserving existing values and
avoiding duplicates. Uninstall removes only an entry owned by the installer.
Close and reopen the terminal before running `ape-arch --help`.

It creates a Start menu shortcut and registers the application for `.zip` and
`.7z` files for the current Windows user.

Windows 10 and 11 may still require manual confirmation under **Settings > Apps > Default apps** before ApeArchivesExtractor becomes the default double-click handler.

The installer adds these Explorer context-menu actions:

- **Open with ApeArchivesExtractor** for ZIP, 7Z, RAR, and multi-volume archives.
- **Open as ZIP archive with ApeArchivesExtractor** for any file.
- **Extract here with ApeArchivesExtractor** for ZIP, 7Z, RAR, and multi-volume archives.
- **Create archive with ApeArchivesExtractor** for files and folders.

On Windows 11, ApeArchivesExtractor can also expose the same actions in the modern first-level
context menu. This requires two additional Windows build prerequisites:

- Visual Studio 2022 Build Tools with the C++ workload, to build
  `ApeArchivesExtractorShellExtension.dll`.
- Windows SDK with `MakeAppx.exe` and `SignTool.exe`, plus a trusted code-signing
  certificate for the sparse identity package.

When those tools are available, the Windows build script attempts to produce:

```text
dist\ApeArchivesExtractor\ApeArchivesExtractorShellExtension.dll
dist\ApeArchivesExtractor\ApeArchivesExtractorIdentity.msix
```

To sign the identity package during the build, set:

```powershell
$env:APEARCHIVESEXTRACTOR_SIGNING_CERT = "C:\path\to\certificate.pfx"
$env:APEARCHIVESEXTRACTOR_SIGNING_PASSWORD = "certificate-password"
.\scripts\build_windows_installer.ps1
```

If the identity package is missing or not signed with a certificate trusted by
Windows, the installer keeps the legacy context-menu integration and skips the
Windows 11 modern menu registration.

To register the file associations without the installer after building the application:

```powershell
.\scripts\register_file_associations.ps1 -InstallPath ".\dist\ApeArchivesExtractor\ApeArchivesExtractor.exe"
```

Execution-policy-compatible command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\register_file_associations.ps1 `
  -InstallPath ".\dist\ApeArchivesExtractor\ApeArchivesExtractor.exe"
```

To also request ApeArchivesExtractor as the default application:

```powershell
.\scripts\register_file_associations.ps1 `
  -InstallPath ".\dist\ApeArchivesExtractor\ApeArchivesExtractor.exe" `
  -SetDefault
```

Execution-policy-compatible command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\register_file_associations.ps1 `
  -InstallPath ".\dist\ApeArchivesExtractor\ApeArchivesExtractor.exe" `
  -SetDefault
```

To remove the associations:

```powershell
.\scripts\register_file_associations.ps1 -Unregister
```

Execution-policy-compatible command:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File `
  .\scripts\register_file_associations.ps1 `
  -Unregister
```

To manually register only the Windows 11 modern context-menu integration after a
signed build:

```powershell
.\scripts\register_windows11_context_menu.ps1 `
  -InstallDir ".\dist\ApeArchivesExtractor" `
  -PackagePath ".\dist\ApeArchivesExtractor\ApeArchivesExtractorIdentity.msix"
```

To remove it:

```powershell
.\scripts\register_windows11_context_menu.ps1 `
  -InstallDir ".\dist\ApeArchivesExtractor" `
  -PackagePath ".\dist\ApeArchivesExtractor\ApeArchivesExtractorIdentity.msix" `
  -Unregister
```

### Explorer archive property sheet

`native/shell_extension/ArchiveProperties.cpp` implements the COM property-sheet
handler (`IShellExtInit` / `IShellPropSheetExt`) in C++17. It is compiled with
MSVC into `ApeArchivesExtractorShellExtension.dll` by the existing Windows build.
Visual Studio C++ and Windows SDK are required. Its registration is independent
of the signed Windows 11 sparse package, so it also works with classic Explorer
on Windows 10.

The installer task for this tab is selected by default when the DLL is bundled.
It registers for the selected per-user/all-users scope and unregisters on
removal. Existing file associations and other applications' property handlers
are preserved. Manual registration after a build is available with:

```powershell
.\scripts\register_archive_properties.ps1 -InstallDir ".\dist\ApeArchivesExtractor"
# An elevated shell is needed for -Scope Machine.
# Add -Unregister to remove the same installation's registration.
```

The page only starts metadata inspection when it is created. A separate
`ape-arch.exe info` process supplies a UTF-8 report; Explorer never loads Python,
Qt or archive parsers. A Windows job object limits process memory to 512 MiB,
closes the child process on cancellation and bounds analysis to 30 seconds.
Reports are capped at 128 KiB. Metadata enumeration stops at 100,000 entries;
TAR.GZ inspection has a 64 MiB decompression budget and reports partial results.
No member is extracted or CRC-tested.

`tests/test_archive_info.py` checks metadata and inspection limits;
`tests/test_archive_properties_registration.py` uses in-memory registry keys.
For a native smoke test, build
`native/shell_extension/tests/ArchivePropertiesSmoke.vcxproj` with MSVC using
the same x64 toolset, then run its executable with the absolute DLL path and a
ZIP containing one file. An optional third argument saves a BMP screenshot.
The harness uses a private desktop, exercises real COM/property-sheet lifetime
and cancellation, and performs no shell registration.

### macOS

```bash
./scripts/build_macos.sh
```

The generated application is placed in:

```text
dist/ApeArchivesExtractor.app
```

The macOS build must be run on macOS. It generates `.icns` icons from the SVG
assets, creates a native `.app` bundle, and declares ZIP, 7Z, RAR, multi-volume, and TAR.GZ file
types in the app bundle metadata. Distribution outside local use still requires
the usual Apple code-signing and notarization steps.

## Icons and visual identity

The application icon and archive-file icon are editable SVGs in
`src/apearchivesextractor/assets/`. They use the same bee artwork and blue,
teal and honey palette as [APE PDF Studio](https://github.com/GiancaGIS/APE-PDF-Studio).
The folder and zipper identify this application's archive workflow.

```powershell
.\.venv\Scripts\python.exe scripts/build_icons.py
```

This regenerates both Windows ICO files (16–256 px) and the 512 px README logo
at `docs/assets/app-icon.png`. On macOS it also regenerates ICNS files.
The platform build scripts run this step automatically. The README banner is
an independent SVG at `docs/assets/readme-hero.svg`; keep its embedded icon in
sync when changing the artwork. No external fonts or images are required.

## Publishing a release

1. Run the tests and review the security workflow results. Review the actual
   versions selected for the release, including their bundled native libraries.
2. Build on the target operating system. The build collects license texts,
   component versions and checksums from the files actually bundled.
3. Prepare matching sources with `python scripts/prepare_release_sources.py`,
   then run `python scripts/check_release.py`. For macOS, pass
   `--bundle dist/ApeArchivesExtractor.app` to both commands. The Windows
   installer script performs source preparation and integrity checks itself.
4. Publish the generated matching source ZIP beside the installer or portable
   application. See [SOURCES.md](../SOURCES.md) for source availability and
   rebuilding with modified dependencies.
5. Publish a stable GitHub Release with a version tag such as `v1.0.4` to make
   it discoverable by the update checker. A tag alone does not trigger the
   latest-release API. The app opens the release page and leaves installation
   to the user.

Use signing credentials from your local environment or secret storage. Do not
commit certificates or passwords. Compile packages for verification; running an
installer or registering shell extensions changes the local Windows setup.
