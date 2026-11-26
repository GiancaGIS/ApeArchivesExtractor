# Source code and redistribution

This release of ApeArchivesExtractor is GPL-3.0-only. Its canonical repository is
[GiancaGIS/ApeArchivesExtractor](https://github.com/GiancaGIS/ApeArchivesExtractor).
Third-party components retain their original licenses.

For published binaries, use the corresponding [release page](https://github.com/GiancaGIS/ApeArchivesExtractor/releases)
and follow its directions to the matching source downloads. Source availability
covers the exact application code and build scripts, plus corresponding sources
for the bundled GPL/LGPL components. See [GPLv3 section 6](https://www.gnu.org/licenses/gpl-3.0.en.html#section6)
and [LGPLv3 section 4](https://www.gnu.org/licenses/lgpl-3.0.en.html#section4).

Windows and Linux builds export
`ApeArchivesExtractor-DependencySources-<version>.zip` next to the binaries.
It contains dependency sources, legal materials, the recorded build environment
and the GitHub source link for the planned tag `v<version>`. Packages contain
license texts, attribution, the component inventory and
`legal/source-manifest.json` with source URLs and SHA-256 hashes.

To export the same type of ZIP again from a local bundle, use
`python build_tools/common/prepare_release_sources.py --github-tag v<version>`.
You can prepare a release draft before pushing the tag. After pushing it, run
`python build_tools/common/check_release.py` to verify the public tag against
the binary. Publish the ZIP and link to the verified GitHub archive next to the binary.

For a build without a matching public tag, run the same command without
`--github-tag` from the matching checkout. The resulting
`ApeArchivesExtractor-sources-<version>.zip` includes both `application/` and
`dependencies/`. Linux archive names also identify the platform and architecture.

A ZIP is one way to offer equivalent, free access to the corresponding source.
A separate source location can work if it contains the exact materials, remains
available while required, and is clearly linked beside the binary. GitHub's
automatic tag archive covers the repository at that tag. Make the sources of
the bundled GPL/LGPL libraries available as well. See
[Building and releasing](docs/BUILDING.md) for the release procedure.

To modify the application or its GPL/LGPL libraries, obtain both sets of sources,
install the recorded build environment on the same platform/Python version,
replace the relevant dependency with your modified source build and use the
supplied scripts to rebuild. No application restriction prohibits this or reverse
engineering for debugging library modifications. The optional signed Windows
shell identity can be omitted; it is not needed to run the rebuilt archive manager.

RAR/WinRAR/UnRAR/7-Zip backends are not included. Install them separately under
their own terms. Permission to use `rarfile` does not license those executables.
