# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from importlib.resources import files
import json


def legal_documents() -> list[tuple[str, str]]:
    """Read packaged notices in editable, wheel and frozen installations."""
    root = files("apearchivesextractor").joinpath("legal")
    documents = []

    def visit(directory, prefix: str = "") -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            name = prefix + entry.name
            if entry.is_dir():
                visit(entry, name + "/")
            elif entry.is_file() and not entry.name.endswith((".docx", ".pyc")):
                documents.append((name, entry.read_text(encoding="utf-8", errors="replace")))

    visit(root)
    return documents


def legal_sections() -> list[tuple[str, str]]:
    """Present the actual bundled documents by topic, preserving all notices."""
    documents = dict(legal_documents())
    sections = []
    used = set()

    for key, filenames in (
        ("legal.program", ("generated/LICENSE", "LICENSE.txt")),
        ("legal.copyright", ("generated/NOTICE", "NOTICE.txt")),
        ("legal.third_party", ("generated/THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")),
        ("legal.source_code", ("generated/SOURCES.md", "SOURCES.md")),
    ):
        available = [name for name in filenames if name in documents]
        if available:
            sections.append((key, documents[available[0]]))
            used.update(available)

    inventory_name = "generated/component-manifest.json"
    source_name = "generated/source-manifest.json"
    inventory = json.loads(documents[inventory_name]) if inventory_name in documents else {}
    components = {c["name"].lower(): c for c in inventory.get("components", [])}
    grouped: dict[str, list[str]] = {}
    for name in documents:
        parts = name.split("/")
        if len(parts) >= 4 and parts[0] == "generated" and parts[1] in {"licenses", "native"}:
            group = parts[2]
            if group.startswith(("pyqt6", "qt")):
                group = "Qt / PyQt6"
            grouped.setdefault(group, []).append(name)

    for group in sorted(grouped, key=lambda name: (name != "Qt / PyQt6", name.lower())):
        component = components.get(group.lower())
        title = group
        header = ""
        if component:
            license_name = " ".join(component["license"].split())
            title = component["name"]
            if len(license_name) <= 70:
                title += f" — {license_name}"
            header = f"{component['name']} {component['version']}\n{component['license']}\n\n"
        sections.append((title, header + "\n\n".join(f"{name}\n\n{documents[name]}" for name in grouped[group])))
        used.update(grouped[group])

    if inventory:
        versions = [f"ApeArchivesExtractor {inventory['application_version']}",
                    f"Python {inventory['python_version']}", ""]
        versions.extend(f"{c['name']} {c['version']} — {' '.join(c['license'].split())}"
                        for c in inventory.get("components", []))
        sections.append(("legal.versions", "\n".join(versions)))
        used.add(inventory_name)
    if source_name in documents:
        sources = json.loads(documents[source_name])
        sections.append(("legal.source_archives", "\n\n".join(
            f"{s['name']} {s['version']}\n{s['filename']}\n{s['url']}\nSHA-256: {s['sha256']}"
            for s in sources.get("sources", []))))
        used.add(source_name)

    for name, text in documents.items():
        if name not in used:
            title = "legal.build_environment" if name == "generated/build-environment.txt" else name
            sections.append((title, text))
    return sections


def license_notice() -> str:
    root = files("apearchivesextractor").joinpath("legal")
    return root.joinpath("NOTICE.txt").read_text(encoding="utf-8") + "\n" + root.joinpath("LICENSE.txt").read_text(encoding="utf-8")
