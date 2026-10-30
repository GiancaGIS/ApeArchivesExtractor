# Third-party components

PySide6, Shiboken6 and the Qt modules used by the application are distributed
under their applicable LGPL/GPL open-source licenses. Components embedded in
Qt may have additional license terms.
py7zr, multivolumefile, inflate64, pybcj and pyppmd use LGPL-2.1-or-later.
rarfile uses ISC, and the other compression and
support libraries retain their respective licenses.

For an installation from Python source, consult the license files installed with
each dependency. For a frozen binary, the build generates a version-specific
THIRD_PARTY_NOTICES.md and component-manifest.json in legal/, together with the
collected license texts and source-manifest.json. The release source companion
contains the corresponding source archives.

PyInstaller's special exception permits distributing the generated application
under its own license; it does not remove the licenses of bundled dependencies.
RAR, WinRAR, UnRAR and 7-Zip executables are not redistributed by this project.
