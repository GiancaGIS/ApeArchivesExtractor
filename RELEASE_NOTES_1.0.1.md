# ApeArchivesExtractor 1.0.1

This release clarifies and corrects licensing for the application distributed
with PyQt6: the project is now GPL-3.0-only. Earlier releases of the project's
own code distributed under MIT retain their original terms. Third-party
components retain their respective copyrights and licenses.

- GPLv3 text, copyright and warranty notices are included in the Python package
  and in the Windows portable application/installer.
- Help > Licenses and source code displays the included legal material in the
  desktop app. `apearch --license` prints the application license.
- Binary packaging collects the exact component versions and installed license
  files, including licenses of vendored dependencies.
- Unused Qt PDF rendering is excluded from the archive manager bundle.
- A matching source companion mirrors dependency sources, native attribution
  files and the application's source/build snapshot, with SHA-256 hashes.
- Release checks detect missing or changed materials and pending provenance review.

When publishing, attach `ApeArchivesExtractor-sources-1.0.1.zip` alongside the
installer/portable download and add a direct link to that asset here. Keep it
available as long as the binary is distributed. This draft must not describe
an unreviewed development installer as a verified release.

Review/update the previous 1.0.0 download as well: it predates the corrected
license packaging and did not include a source companion. This local change
does not replace any GitHub asset.
