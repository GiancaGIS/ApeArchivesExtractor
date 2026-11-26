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


Build on the target platform. For Linux, WSL runs the build inside the chosen
Linux distribution.

Windows and Linux builds copy the current application sources to a temporary
directory under `%SystemDrive%\Users\Public\Documents` or `/tmp`, respectively.
They use an isolated virtual environment and neutral temporary paths. The build
checks packaged files, the bytecode inside PyInstaller executables and archive
metadata for local paths before exporting to `dist/`. It verifies the Windows
installer inputs before compression and checks the resulting executable for
visible paths. Linux archive entries carry root ownership.

Use an existing neutral parent via `-BuildRoot` on Windows or `--build-root` on
Linux. The build rejects checkout and user-profile paths for staging. Logs and
download caches are local build data. See the [commands and layout](../build_tools/README.md).

### Windows

From PowerShell in the project root:

```powershell
.\build_tools\windows\build_installer.bat -BundleOnly
```

If script execution is restricted by the system policy, run it explicitly with a process-level bypass:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_tools\windows\build_windows_installer.ps1 -BundleOnly
```

The portable application is generated in:

```text
dist\ApeArchivesExtractor
```

To create the Windows installer, double-click `build_tools\windows\build_installer.bat`, or run:

```powershell
.\build_tools\windows\build_windows_installer.ps1
```

If required by the PowerShell execution policy:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\build_tools\windows\build_windows_installer.ps1
```

Install [Inno Setup 7](https://jrsoftware.org/inno-setup/downloads). The build
looks for a version 7 compiler on PATH and in the standard installation folders.
The generated installer is:

```text
dist\ApeArchivesExtractorSetup-1.2.0.exe
```

The installer includes the collected license texts. Before compilation, the
build verifies the bundle's notices, inventory and binary checksums.
Use `.\build_tools\windows\build_installer.bat -SkipBuild` to reuse a portable
bundle from the current checkout. The build also exports
`dist/ApeArchivesExtractor-DependencySources-1.2.0.zip`.
Arguments passed to `build_installer.bat` are forwarded to the PowerShell script;
on failure, the launcher keeps the error visible. See
[Publishing a release](#publishing-a-release) for the publishing steps.

On first install, choose who can use ApeArchivesExtractor:

- Current user: installs under the user's profile, normally
  `%LOCALAPPDATA%\Programs\ApeArchivesExtractor`.
- All users: requests administrator privileges and installs under Program Files,
  normally `C:\Program Files\ApeArchivesExtractor`.

When the installer finds an existing installation in one mode, it uses that mode
and offers its directory as the destination. Windows requests elevation for an
all-users update. If both modes are installed, the installer asks which one to
update. Use `/CURRENTUSER` or `/ALLUSERS` to select the mode explicitly from the
command line.

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
.\build_tools\windows\build_installer.bat
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

### Linux

Use Python 3.11+ with a shared library, its upstream license and `venv`.
Use an upstream CPython build to match the Python sources packaged with the
release. If a distro interpreter lacks the upstream license, build CPython from
the [official source release](https://www.python.org/downloads/source/) with
`./configure --enable-shared --prefix=/opt/cpython`. Make its shared library
discoverable by the linker, for example by setting an RPATH to the installation's
`lib` directory when compiling CPython. Use a neutral directory for that build too.

On Debian or Ubuntu, install `dpkg`, `dpkg-dev` and the system libraries needed
by the Qt desktop platform. Build on the oldest target distribution you
intend to support so the bundle uses a compatible glibc.

```bash
bash build_tools/linux/build_linux_installer.sh --python /opt/cpython/bin/python3
```

From Windows with an Ubuntu WSL distribution:

```powershell
.\build_tools\linux\build_linux_installer.bat -Distribution Ubuntu -Python /opt/cpython/bin/python3
```

`dist/linux/` contains the `.deb`, the portable `.tar.gz` and the
`DependencySources` ZIP for the built architecture.
The Debian package installs the desktop launcher and
`ape-arch`. The tarball contains the GUI and CLI in the same directory. On
another Linux distribution, use `--bundle-only` to produce the unpacked bundle
without Debian tooling.

### macOS

```bash
bash build_tools/macos/build_macos_app.sh
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
`src/apearchivesextractor/assets/`. They pair the bee artwork from
[APE PDF Studio](https://github.com/GiancaGIS/APE-PDF-Studio) with a honey-yellow palette.
The folder and zipper identify this application's archive workflow.

```powershell
.\.venv\Scripts\python.exe build_tools/branding/build_icons.py
```

This regenerates both Windows ICO files (16–256 px) and the 512 px README logo
at `docs/assets/app-icon.png`. On macOS it also regenerates ICNS files.
The Windows and Linux builds use the checked-in icons. The README banner is
an independent SVG at `docs/assets/readme-hero.svg`; keep its embedded icon in
sync when changing the artwork. No external fonts or images are required.

## Publishing a release

1. Run the tests and review the security workflow results. Review the actual
   versions selected for the release, including their bundled native libraries.
2. Build on the target operating system. The build collects license texts,
   component versions and checksums from the files actually bundled.
3. Attach the `DependencySources` ZIP from the Windows or Linux build to the
   release draft alongside its binary. The build prepares it for the tag
   `v<version>`. To re-export an archive from a bundle or use another tag,
   run the following command with the matching tag.

   ```sh
   python build_tools/common/prepare_release_sources.py --github-tag v1.2.0
   ```

   Push the matching tag and run `python build_tools/common/check_release.py`
   before publishing. The check compares the GitHub tag's files and the ZIP's
   dependency hashes with the built bundle.

   Both commands default to the portable Windows bundle in `dist/`. On Linux,
   pass `--bundle` with the directory extracted from the portable tarball, or
   with `dist/linux/ApeArchivesExtractor` after a bundle-only build. If the bundle
   and archive are in different directories, pass `--companion` with the ZIP path.
   On macOS,
   pass `--bundle dist/ApeArchivesExtractor.app`. Use `--companion` on both
   commands to set a different ZIP path. On macOS the exporter also prepares
   notices if the bundle has yet to be prepared. For distributions
   without a matching GitHub tag, omit `--github-tag` and run from the exact
   build checkout to export a complete source ZIP.

4. Publish the verified ZIP beside the binary. For `DependencySources`, link
   the verified GitHub source archive printed by the exporter in the release
   notes. Keep the tag on the same commit and both downloads available. See
   [SOURCES.md](../SOURCES.md) for details and rebuilding with modified libraries.
5. Publish a stable GitHub Release with a version tag such as `v1.0.4` to make
   it discoverable by the update checker. A tag alone does not trigger the
   latest-release API. The app opens the release page and leaves installation
   to the user.

Use signing credentials from your local environment or secret storage. Do not
commit certificates or passwords. Compile packages for verification; running an
installer or registering shell extensions changes the local Windows setup.
