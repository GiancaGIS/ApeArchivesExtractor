# Binary release checklist

The build collects installed license files and exact dependency versions. Source
preparation mirrors source archives and native notices. The installer build
verifies license files, corresponding source archives and binary checksums.

Before publishing any binary:

1. Build from the intended source revision. Use the generated
   `legal/build-environment.txt` to record the environment; also record the Git
   tag/commit in the release notes. Rebuild an old release when its legal files
   were omitted: changing only the repository license does not update that binary.
2. Run `python scripts/verify_release_provenance.py` to check native bytes against
   the published wheels, official CPython payload and the Visual Studio release
   CRT. This produces `legal/binary-provenance.json`; it does not approve the
   release or assert ownership. Then run `python scripts/prepare_release_sources.py` after the portable build and
   before compiling the installer. Its output must accompany the binary online.
3. Review `legal/component-manifest.json` against the delivered files, including
   native libraries and plugins. Qt attributions and source archives include
   multiple platform/build options: establish which third-party code your binary
   actually includes and ensure all required copyrights/notices are supplied.
4. Verify the provenance and redistribution terms of Microsoft runtimes, macOS
   native libraries, software OpenGL/Mesa, and any DLL not explained by an
   installed distribution. A package-level license is not enough for these.
5. Confirm you hold the necessary rights to application source, SVG/ICO resources
   and screenshots. Existing third-party contributions retain their original
   copyright and license notices. Source headers cannot establish ownership.
6. Confirm the source companion matches the binaries, including native build
   patches/configuration for libraries when required, and that users can rebuild
   and run the app with modified GPL/LGPL dependencies.
7. Run `python scripts/check_release.py`. It rejects missing source companions,
   missing legal files, altered binary hashes and mismatched source contents.
   Compile the installer from the prepared portable directory with
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -SkipBuild`.
   `-SkipBuild` reuses the existing build and source materials. The output is
   `dist/ApeArchivesExtractorSetup-<version>.exe`. Check the final installer
   contents as well.
8. Upload the source companion next to the binary and put an explicit download
   link in the release notes. Keep both available. Existing GitHub release assets
   must be replaced or supplemented explicitly; local changes do not do this.
