# Build tools

| Task | Command from the repository root |
| --- | --- |
| Windows installer | `build_tools\windows\build_installer.bat` |
| Windows portable folder | `build_tools\windows\build_installer.bat -BundleOnly` |
| Installer from a prepared Windows bundle | `build_tools\windows\build_installer.bat -SkipBuild` |
| Linux Debian package and portable tarball | `bash build_tools/linux/build_linux_installer.sh --python /opt/cpython/bin/python3` |
| Linux build from Windows through WSL | `build_tools\linux\build_linux_installer.bat -Distribution Ubuntu -Python /opt/cpython/bin/python3` |
| macOS application | `bash build_tools/macos/build_macos_app.sh` |
| Re-export dependency sources for a GitHub release | `python build_tools/common/prepare_release_sources.py --bundle <bundle> --github-tag <tag>` |

Windows and Linux builds include a `DependencySources` ZIP beside the binary
outputs. The ZIP uses the planned tag `v<version>`.

- `windows/` contains the installer launcher, Inno Setup 7 definition, MSVC build
  and sparse identity package.
- `linux/` contains the Debian and tarball packager, desktop launcher and WSL bridge.
- `macos/` contains the native macOS app build entry point.
- `common/` contains neutral staging, the PyInstaller specification, dependency
  notices, source mirrors and distribution checks.
- `branding/` generates platform icons from the SVG artwork.
- `launchers/` contains the frozen command-line entry point.

See [Building and releasing](../docs/BUILDING.md) for platform prerequisites,
privacy checks, output locations and matching sources.
