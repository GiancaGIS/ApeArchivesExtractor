# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

from importlib.resources import files


def legal_documents() -> list[tuple[str, str]]:
    """Read packaged notices in editable, wheel and frozen installations."""
    root = files("apearchivesextractor").joinpath("legal")
    documents = []

    def visit(directory, prefix: str = "") -> None:
        for entry in sorted(directory.iterdir(), key=lambda p: p.name):
            name = prefix + entry.name
            if entry.is_dir():
                visit(entry, name + "/")
            elif entry.is_file() and not entry.name.endswith(".docx"):
                documents.append((name, entry.read_text(encoding="utf-8", errors="replace")))

    visit(root)
    return documents


def license_notice() -> str:
    root = files("apearchivesextractor").joinpath("legal")
    return root.joinpath("NOTICE.txt").read_text(encoding="utf-8") + "\n" + root.joinpath("LICENSE.txt").read_text(encoding="utf-8")
