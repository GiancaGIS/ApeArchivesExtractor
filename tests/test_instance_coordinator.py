# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import subprocess
import sys
import time
import uuid

from PyQt6.QtCore import QCoreApplication
from PyQt6.QtNetwork import QLocalServer

from apearchivesextractor.gui import instance_coordinator
from apearchivesextractor.gui.instance_coordinator import MAX_REQUEST_BYTES, InstanceCoordinator


def test_forwards_create_request_to_primary_instance(monkeypatch) -> None:
    server_name = f"ApeArchivesExtractor.Test.{uuid.uuid4().hex}"
    monkeypatch.setattr(instance_coordinator, "SERVER_NAME", server_name)
    monkeypatch.setattr(instance_coordinator, "LOCK_FILE_NAME", f"{server_name}.lock")
    app = QCoreApplication.instance() or QCoreApplication([])
    coordinator = InstanceCoordinator()
    received: list[dict] = []
    coordinator.request_received.connect(received.append)

    try:
        assert coordinator.listen()
        request = {
            "action": "create_archive",
            "paths": [r"C:\tmp\uno.txt", r"C:\tmp\due.txt", r"C:\tmp\tre.txt"],
        }
        child_code = (
            "import apearchivesextractor.gui.instance_coordinator as coordinator\n"
            f"coordinator.SERVER_NAME = {server_name!r}\n"
            f"request = {request!r}\n"
            "success = coordinator.InstanceCoordinator.forward(request, timeout_ms=1500)\n"
            "raise SystemExit(0 if success else 1)\n"
        )
        child = subprocess.Popen([sys.executable, "-c", child_code])

        deadline = time.monotonic() + 3
        while (child.poll() is None or not received) and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert child.wait(timeout=1) == 0
        assert received == [request]
    finally:
        coordinator.close()
        QLocalServer.removeServer(server_name)


def test_rejects_oversized_forwarded_request() -> None:
    request = {"action": "create_archive", "paths": ["x" * MAX_REQUEST_BYTES]}

    assert not InstanceCoordinator.forward(request)
