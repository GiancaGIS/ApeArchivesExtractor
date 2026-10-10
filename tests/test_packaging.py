# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import re
from pathlib import Path


def test_file_association_script_registers_only_archive_entry_volumes() -> None:
    script = Path("scripts/register_file_associations.ps1").read_text(encoding="utf-8")
    registered_extensions = set(re.findall(r'^\s*"(\.\w+)"\s*=', script, flags=re.MULTILINE))

    assert registered_extensions == {".zip", ".7z", ".rar", ".001", ".r00", ".r01", ".z01"}
    assert "for ($index" not in script
