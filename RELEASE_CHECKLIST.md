# Binary release review

The build collects installed license files and exact dependency versions. Source
preparation mirrors source archives and native notices. These automated steps
cannot establish ownership of assets, the provenance of every DLL, or the rights
provided by the compiler installation.

Before publishing any binary:

1. Build from the intended source revision. Use the generated
   `legal/build-environment.txt` to record the environment; also record the Git
   tag/commit in the release notes. Rebuild an old release when its legal files
   were omitted: changing only the repository license does not update that binary.
2. Run `python scripts/prepare_release_sources.py` after the portable build and
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
7. Add `release-review.json` to the generated legal directory using this shape:

   ```json
   {
     "component_manifest_sha256": "SHA256 of component-manifest.json",
     "source_manifest_sha256": "SHA256 of source-manifest.json",
     "reviewer": "Name of the person who completed the review",
     "evidence": "Specific provenance, build configuration and rights evidence",
     "native_components_reviewed": true,
     "asset_rights_confirmed": true,
     "corresponding_source_verified": true
   }
   ```

   Do not set these values until the checks have actually been completed. The
   release checker validates the shape and ties the review to the two manifests;
   it cannot verify that the reviewer's statements are true. This review does not
   replace actual missing license texts, notices or source/build materials.
8. Run `python scripts/check_release.py`. It rejects missing source companions,
   missing legal files, altered binary hashes and missing/stale release review.
   Compile the installer from the reviewed portable directory with
   `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/build_windows_installer.ps1 -SkipBuild`.
   `-SkipBuild` preserves the reviewed material instead of clearing it with a new
   build. For local installer testing only, also pass `-DevelopmentBuild`; that
   produces a visibly marked development installer even when review is pending.
   Review the final installer contents as well.
9. Upload the source companion next to the binary and put an explicit download
   link in the release notes. Keep both available. Existing GitHub release assets
   must be replaced or supplemented explicitly; local changes do not do this.

Local development builds are allowed while review is pending. The installer
script stops before compiling a distributable installer until review passes.
