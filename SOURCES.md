# Source code and redistribution

This release of ApeArchivesExtractor is GPL-3.0-only. Its canonical repository is
[GiancaGIS/ApeArchivesExtractor](https://github.com/GiancaGIS/ApeArchivesExtractor).
Third-party components retain their original licenses.

Binary releases must be accompanied by the exact application source snapshot,
build scripts, dependency versions, license notices, and corresponding library
sources required by GPL/LGPL. A link to the current default branch is insufficient
to identify the source of an older binary. Python bytecode is not source code.

After a build, run `python scripts/prepare_release_sources.py`. It downloads the
source distributions of the included Python components and the Qt modules at the
installed Qt version, checks available upstream SHA-256 digests, and creates a
source companion archive in `dist/`. It does not run downloaded code. It also
copies native license/attribution files from the source archives into the app's
`legal/` directory. Run it before compiling the installer.

Publish the resulting `ApeArchivesExtractor-sources-<version>.zip` beside the
portable/installer downloads and identify it explicitly in the release notes.
The archive contains `application/`, `dependencies/`, a pinned build environment,
the exact component inventory and hashes. Keep it available while distributing
the corresponding binary. Do not publish a release if the preparation or the
release check fails. See `RELEASE_CHECKLIST.md` for remaining manual review.

For binaries, the generated `legal/source-manifest.json` identifies the source
archives, original URLs and SHA-256 hashes. URLs alone are not a promise of future
availability: the companion archive carries the copies maintained by this project.

To modify the application or its GPL/LGPL libraries, unpack the source companion,
install the recorded build environment on the same platform/Python version,
replace the relevant dependency with your modified source build and use the
supplied scripts to rebuild. No application restriction prohibits this or reverse
engineering for debugging library modifications. The optional signed Windows
shell identity can be omitted; it is not needed to run the rebuilt archive manager.

RAR/WinRAR/UnRAR/7-Zip backends are not included. Install them separately under
their own terms. Permission to use `rarfile` does not license those executables.
