# Working on ApeArchivesExtractor

## Project and layout

- Python 3.11 or newer; a Qt 6 desktop application using **PySide6** and a CLI.
- `src/apearchivesextractor/`: archive service, models, security checks and CLI.
- `adapters/`: ZIP, 7z, RAR and TAR.GZ backends; `gui/`: windows, Qt workers,
  drag and drop, preferences, update checking and toast notifications.
- `scripts/` and `packaging/`: PyInstaller builds, Inno Setup installer, license
  collection, dependency source archives and release integrity verification.
- `native/shell_extension/`: optional Windows Explorer C++ shell extension.
- `tests/`: core, GUI, security and packaging regression tests.

## Environment and commands

Use the repository virtual environment. In PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,package]"
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q
```

On macOS/Linux use `.venv/bin/python`. Run focused tests while implementing a
change, and the full suite for changes spanning multiple components. The
`.github/workflows/security.yml` workflow tests Windows with Python 3.11 and 3.14
and audits resolved dependencies using pip-audit.

## Code and UI conventions

- Use PySide6 exclusively for Qt, including `Signal` and `Slot`. Do not mix Qt
  bindings in the same process or ship them together.
- The runtime dependency is the official `PySide6-Essentials` package. It provides
  the Core, Gui, Widgets, Network, Svg and Test modules used here. Add further Qt
  distributions only when a feature needs them and update the source inventory.
- Keep archive logic independent of the GUI. Run slow operations in workers with
  progress and cancellation support, without blocking the GUI thread.
- Connect worker results to QObject-bound `@Slot` receivers on the GUI thread.
  Contextless lambdas can execute in the worker thread under PySide6; never use
  them to dispatch callbacks that update widgets or reload an archive view.
- Add UI strings in both Italian and English to `gui/i18n.py`. Preserve selections,
  passwords and explicitly selected archive formats across operations.
- Use system palette roles for widget colors, including toasts and dialogs.
  Refresh cached stylesheet brushes after application palette changes. Verify
  light/dark transitions on existing windows without changing Windows settings.
- Keep strong references to Qt applications and active workers for their required
  lifetime. Run QWidget tests in a separate process if the suite already created
  QCoreApplication. Isolate QSettings with an explicit temporary INI file; do not
  change user preferences or file associations from tests.
- Update checks use GitHub's official public releases API, asynchronous requests
  with timeouts and non-modal toast notifications. Keep automatic failures silent
  and respect the setting that disables startup checks.

## Archive safety

- Reuse `security.py`: path normalization, traversal and link protection,
  extraction limits and atomic writes must remain effective.
- Preserve multi-volume handling, selective extraction and password support.
- Drag and drop must preserve the source archive. Retain temporary files while
  the receiver needs them, and clean failed preparations.
- External RAR/WinRAR backends are not redistributed by this project.

## Builds and distribution

- Use `scripts/build_windows.ps1` for portable Windows builds, and
  `build_installer.bat` or `scripts/build_windows_installer.ps1` for the installer.
- The Windows package includes the console command `ape-arch.exe`. Installer
  PATH updates must respect per-user/all-users scope, avoid duplicates and remove
  only entries owned by this installer. Test the updater with in-memory keys.
- `-SkipBuild` reuses a portable build with prepared source archives and retains
  integrity checks. There is one normal installer name, without an experimental
  mode or experimental-version warnings.
- Windows packaging needs Inno Setup 6. The shell extension needs Visual Studio
  C++ and Windows SDK. Build macOS packages on macOS.
- Explorer's archive property page is native C++/COM, compiled with MSVC. Keep
  Python/Qt out of the Explorer process: metadata comes from `ape-arch info` in
  a bounded, cancellable child process. Test COM lifecycle on a private desktop
  and registry updates with in-memory keys; never register the handler as a test.
- Verify licenses, the component inventory, matching sources and checksums after
  dependency changes. PySide6 bundles Qt and depends on Shiboken6: use the actual
  installed versions and paths instead of another binding's old directory layout.
- The project remains GPL-3.0-only. Preserve dependency copyrights and terms. The
  application notice is `src/apearchivesextractor/legal/NOTICE.txt`. Keep
  `SOURCES.md` synchronized with its packaged copy when changing source guidance.
- If changing the version, update `pyproject.toml`, `__init__.py`, the spec,
  installer and Windows manifests together. Avoid incidental version bumps.
- `build/`, `dist/`, caches and virtual environments are local artifacts. Do not
  run installers or shell-registration scripts as automated validation; use
  isolated tests and package compilation.

Preserve existing workspace changes. Prefer `rg` for searches, keep edits within
the requested scope, and report the checks run and any actual limitations.
Commit, push and publish releases when requested.
