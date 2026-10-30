# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import pytest
from PySide6.QtCore import QCoreApplication


@pytest.fixture(scope="session", autouse=True)
def qt_application():
    """Keep one Qt application alive across IPC and asynchronous network tests.

    PySide owns its application wrapper: dropping the last Python reference can
    destroy Qt while deferred events or other tests still need it. QWidget tests
    use separate processes, since QCoreApplication cannot become QApplication.
    """
    app = QCoreApplication.instance() or QCoreApplication([])
    yield app
    app.processEvents()
