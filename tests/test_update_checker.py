# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PySide6.QtCore import QCoreApplication

from apearchivesextractor.gui import update_checker
from apearchivesextractor.gui.update_checker import MAX_RESPONSE_BYTES, UpdateChecker, newer_release


def release(tag="v1.10.0", **changes):
    return {"tag_name": tag, "html_url": f"https://github.com/GiancaGIS/ApeArchivesExtractor/releases/tag/{tag}",
            "draft": False, "prerelease": False, **changes}


@pytest.mark.parametrize("tag,current,expected", [
    ("1.10.0", "1.9.0", "1.10.0"), ("v2.0.0", "1.9.0", "2.0.0"),
    ("1.1.0", "1.1.0", None), ("1.0.2", "1.1.0", None),
    ("1.1.0.0", "1.1.0", None), ("2.0.0rc1", "1.1.0", None),
    ("2.0.0.dev1", "1.1.0", None), ("2.0.0", "2.0.0rc1", "2.0.0"),
], ids=["newer-minor", "v-prefix", "same", "older", "equivalent", "rc", "dev", "stable-after-rc"])
def test_release_version_comparison(tag, current, expected):
    result = newer_release(release(tag), current)
    assert (result.version if result else None) == expected


@pytest.mark.parametrize("flag", ["draft", "prerelease"])
def test_unpublished_or_preview_releases_are_ignored(flag):
    assert newer_release(release(**{flag: True}), "1.0.0") is None


@pytest.mark.parametrize("payload", [
    [], {}, release("not-a-version"),
    release(html_url="https://example.com/setup.exe"),
    release(html_url="http://github.com/GiancaGIS/ApeArchivesExtractor/releases/tag/v2"),
    release(html_url="https://github.com/another/project/releases/tag/v2"),
    release(html_url="https://github.com@evil.example/GiancaGIS/ApeArchivesExtractor/releases/tag/v2"),
])
def test_invalid_release_metadata_or_external_links_are_rejected(payload):
    with pytest.raises(ValueError):
        newer_release(payload, "1.0.0")


@pytest.fixture
def qt_app():
    return QCoreApplication.instance() or QCoreApplication([])


@pytest.fixture
def github_api(monkeypatch):
    servers = []

    def serve(status=200, body=None, delay=0):
        requests = []
        payload = json.dumps(release()).encode() if body is None else body

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, {key.lower(): value for key, value in self.headers.items()}))
                time.sleep(delay)
                try:
                    self.send_response(status)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass  # Timeout/cancellation intentionally closes the connection.

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        thread.start()
        servers.append((server, thread))
        monkeypatch.setattr(update_checker, "LATEST_RELEASE_API", f"http://127.0.0.1:{server.server_port}/releases/latest")
        return requests

    yield serve
    for server, thread in servers:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def wait_for_result(app, checker):
    deadline = time.monotonic() + 3
    while checker.is_running and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert not checker.is_running, "Update request did not finish"


def test_async_check_uses_public_api_headers_and_prevents_overlapping_requests(qt_app, github_api):
    requests = github_api()
    checker = UpdateChecker("1.9.0")
    results = []
    checker.checked.connect(results.append)
    assert checker.check()
    assert not checker.check()
    wait_for_result(qt_app, checker)
    assert len(results) == 1 and results[0].version == "1.10.0"
    assert len(requests) == 1
    path, headers = requests[0]
    assert path == "/releases/latest"
    assert headers["accept"] == "application/vnd.github+json"
    assert headers["x-github-api-version"] == "2026-03-10"
    assert headers["user-agent"] == "ApeArchivesExtractor/1.9.0"
    assert "authorization" not in headers


@pytest.mark.parametrize("status,body,expected", [
    (404, b"{}", None), (403, b"{}", "rate_limit"), (429, b"{}", "rate_limit"),
    (500, b"{}", "network"), (200, b"not JSON", "invalid_response"),
    (200, b"x" * (MAX_RESPONSE_BYTES + 1), "invalid_response"),
], ids=["no-release", "forbidden", "rate-limit", "server-error", "invalid-json", "oversized"])
def test_api_failure_and_empty_release_handling(qt_app, github_api, status, body, expected):
    github_api(status, body)
    checker = UpdateChecker("1.0.0")
    results, errors = [], []
    checker.checked.connect(results.append)
    checker.failed.connect(errors.append)
    checker.check()
    wait_for_result(qt_app, checker)
    assert results == ([None] if expected is None else [])
    assert errors == ([expected] if expected is not None else [])


def test_timeout_and_cancellation_finish_without_late_notifications(qt_app, github_api):
    github_api(delay=0.2)
    checker = UpdateChecker("1.0.0", timeout_ms=30)
    results, errors = [], []
    checker.checked.connect(results.append)
    checker.failed.connect(errors.append)
    checker.check()
    wait_for_result(qt_app, checker)
    assert errors == ["timeout"] and results == []
    errors.clear()
    checker.check()
    checker.cancel()
    qt_app.processEvents()
    assert not checker.is_running and errors == results == []


def test_startup_preference_manual_checks_and_non_modal_toast(tmp_path):
    code = r'''
from pathlib import Path
import sys, time
from PySide6.QtCore import QSettings
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication
from apearchivesextractor.gui.main_window import MainWindow
from apearchivesextractor.gui import settings as settings_module
from apearchivesextractor.gui.settings import AppSettings
from apearchivesextractor.gui.update_checker import AvailableUpdate

root = Path(sys.argv[1])
settings_module.QSettings = lambda *_args: QSettings(str(root / 'settings.ini'), QSettings.Format.IniFormat)
app = QApplication([])
window = MainWindow()
window.show()
app.processEvents()
calls, opened = [], []
window._update_checker.check = lambda: calls.append('check')
QDesktopServices.openUrl = lambda url: opened.append(url.toString()) or True
assert window.settings.check_updates_on_startup()
window.settings.set_check_updates_on_startup(False)
assert not AppSettings().check_updates_on_startup()
window.check_startup_updates()
assert not calls
window.settings.set_check_updates_on_startup(True)
window.check_startup_updates()
assert calls == ['check']

toast = window._update_toast
for language, action in [('it', 'Apri release'), ('en', 'Open release')]:
    window._set_language(language)
    update = AvailableUpdate('9.9.9', 'https://github.com/GiancaGIS/ApeArchivesExtractor/releases/tag/v9.9.9')
    window._on_update_checked(update)
    app.processEvents()
    assert toast.isVisible() and '9.9.9' in toast.title.text()
    assert QApplication.activeModalWidget() is None
    assert toast.action_button.text() == action
    assert window.centralWidget().rect().contains(toast.geometry())
    assert not opened
    toast.dismiss_button.click()
    assert not toast.isVisible()

window._on_update_checked(update)
toast.action_button.click()
assert opened == [update.url] and not toast.isVisible()
window._on_update_failed('network')
assert not toast.isVisible(), 'Automatic failures must be silent'
window._on_update_checked(None)
assert not toast.isVisible(), 'Automatic checks without updates must be silent'

window.settings.set_check_updates_on_startup(False)
window.check_for_updates()
assert len(calls) == 2, 'Manual checks must work with automatic checks disabled'
window._on_update_checked(None)
assert toast.isVisible() and not toast.action_button.isVisible()
toast.hide()
window.check_for_updates()
window._on_update_failed('rate_limit')
assert toast.isVisible()
assert window._update_check_action.isEnabled()

toast._timer.start(10)
deadline = time.monotonic() + 1
while toast.isVisible() and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.002)
assert not toast.isVisible(), 'Toast must disappear automatically'
window.close()
'''
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)],
                            env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
