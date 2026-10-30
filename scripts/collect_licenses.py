# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Collect legal material from the components actually selected by PyInstaller."""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import json
import re
import shutil
import sys
import tomllib
from pathlib import Path


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def slug(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def legal_file(path: str) -> bool:
    name = Path(path).name.lower()
    return (name.startswith(("license", "licence", "copying", "copyright", "notice", "authors"))
            or name == "qt_attributions.json"
            or any(part.lower() in {"licenses", "licences"} for part in Path(path).parts))


def application_files(root: Path) -> list[Path]:
    files = [p for p in root.iterdir() if p.is_file() and
             (p.suffix in {".md", ".toml", ".txt", ".bat"} or p.name in {"LICENSE", "NOTICE", ".gitignore"})]
    for folder in ("src", "scripts", "tests", "packaging", "native", "images"):
        files.extend(p for p in (root / folder).rglob("*") if p.is_file() and
                     "__pycache__" not in p.parts and not any(x.endswith(".egg-info") for x in p.parts) and p.suffix != ".pyc")
    return sorted(files)


def source_snapshot(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): digest(p) for p in application_files(root)}


def collect(root: Path, analysis: object, initial_snapshot: dict[str, str] | None = None) -> Path:
    snapshot = source_snapshot(root)
    if initial_snapshot is not None and snapshot != initial_snapshot:
        raise RuntimeError("Application sources changed during the build; rebuild before distributing")
    output = root / "build" / "legal"
    # Never reuse a previous build's legal inventory or source claims.
    if output.exists():
        if output.resolve() != (root.resolve() / "build" / "legal"):
            raise ValueError("Unexpected legal output path")
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for filename in ("LICENSE", "NOTICE", "SOURCES.md"):
        shutil.copyfile(root / filename, output / filename)

    selected: set[str] = set()
    modules = metadata.packages_distributions()
    distributions = {slug(d.metadata["Name"]): d for d in metadata.distributions()}
    # Map extension modules and Qt DLLs to their wheel owners, too.
    owners: dict[Path, str] = {}
    for name, distribution in distributions.items():
        for entry in distribution.files or ():
            owners[distribution.locate_file(entry).resolve()] = name
    for name, source, _kind in analysis.pure:
        selected.update(slug(n) for n in modules.get(name.split(".")[0], ()))
        owner = owners.get(Path(source).resolve()) if source else None
        if owner:
            selected.add(owner)
    binaries = []
    for name, source, kind in analysis.binaries:
        path = Path(source)
        owner = owners.get(path.resolve())
        if owner:
            selected.add(owner)
        binaries.append({"path": name.replace("\\", "/"), "sha256": digest(path), "owner": owner, "kind": kind})
    selected.discard("apearchivesextractor")
    # Include the bootloader exception and runtime-hook licensing.
    selected.update({"pyinstaller", "pyinstaller-hooks-contrib"})

    components = []
    for name in sorted(selected):
        d = distributions[name]
        license_paths = []
        for entry in sorted(d.files or (), key=str):
            if not legal_file(str(entry)):
                continue
            source = d.locate_file(entry)
            if not source.is_file():
                continue
            parts = Path(str(entry)).parts
            if ".." in parts or Path(str(entry)).is_absolute():
                raise ValueError(f"Unsafe license path: {entry}")
            destination = output / "licenses" / name / Path(*parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            license_paths.append(destination.relative_to(output).as_posix())
        classifiers = [c.rsplit(" :: ", 1)[-1] for c in d.metadata.get_all("Classifier", ()) if c.startswith("License ::")]
        license_name = d.metadata.get("License-Expression") or d.metadata.get("License") or "; ".join(classifiers) or "See included license text"
        if not license_paths:
            raise RuntimeError(f"No license text found for bundled component {d.metadata['Name']} {d.version}")
        components.append({"name": d.metadata["Name"], "version": d.version, "license": license_name,
                           "license_files": license_paths, "source_metadata": f"https://pypi.org/pypi/{name}/{d.version}/json"})

    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if not python_license.exists():
        python_license = Path(sys.base_prefix) / "LICENSE"
    if not python_license.exists():
        raise RuntimeError("Python license text is missing from this interpreter installation")
    destination = output / "licenses" / "python" / "LICENSE.txt"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(python_license, destination)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    inventory = {"schema_version": 1, "application_version": project["version"], "application_license": project["license"],
                 "python_version": sys.version.split()[0], "platform": sys.platform,
                 "application_files_sha256": snapshot,
                 "components": components, "binaries": binaries}
    (output / "component-manifest.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
    lines = ["# Third-party notices", "", "ApeArchivesExtractor — Copyright (c) 2026 GiancaGIS; GPL-3.0-only.",
             "No warranty. See LICENSE and SOURCES.md.", "", "Third-party copyrights and terms are preserved in the complete files listed below.",
             "Qt and Python include further native components: consult native/ and the source archives.", ""]
    for component in components:
        lines += [f"## {component['name']} {component['version']}", "", component["license"], ""]
        lines.extend(f"- [{p}]({p})" for p in component["license_files"])
        lines.append("")
    lines += ["## Python " + inventory["python_version"], "", "See licenses/python/LICENSE.txt and the Python source archive.", ""]
    (output / "THIRD_PARTY_NOTICES.md").write_text("\n".join(lines), encoding="utf-8")
    pins = sorted({f"{d.metadata['Name']}=={d.version}" for n, d in distributions.items() if n != "apearchivesextractor"})
    (output / "build-environment.txt").write_text("# Build environment snapshot; use the recorded Python version and platform.\n" + "\n".join(pins) + "\n", encoding="utf-8")
    return output
