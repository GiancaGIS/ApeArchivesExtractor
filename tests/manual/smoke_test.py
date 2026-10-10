# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from pathlib import Path
from tempfile import TemporaryDirectory

from apearchivesextractor import ArchiveService


with TemporaryDirectory() as tmp:
    root = Path(tmp)
    data = root / "data"
    data.mkdir()
    (data / "hello.txt").write_text("Ciao ApeArchivesExtractor!", encoding="utf-8")

    service = ArchiveService()

    zip_path = root / "test.zip"
    targz_path = root / "test.tar.gz"

    service.create(zip_path, [data])
    service.create(targz_path, [data])

    assert service.list_entries(zip_path)
    assert service.list_entries(targz_path)

    service.extract_all(zip_path, root / "out_zip")
    service.extract_all(targz_path, root / "out_targz")

    print("Smoke test OK")
