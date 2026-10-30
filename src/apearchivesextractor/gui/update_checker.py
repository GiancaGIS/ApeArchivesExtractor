# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from packaging.version import InvalidVersion, Version
from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest

REPOSITORY = "GiancaGIS/ApeArchivesExtractor"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
MAX_RESPONSE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class AvailableUpdate:
    version: str
    url: str


def newer_release(payload: object, current_version: str) -> AvailableUpdate | None:
    """Interpret an official GitHub release, without trusting its text as markup."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid GitHub release")
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = payload.get("tag_name")
    if not isinstance(tag, str) or not tag.strip() or len(tag) > 128:
        raise ValueError("Invalid release tag")
    try:
        latest = Version(tag)
        current = Version(current_version)
    except InvalidVersion as exc:
        raise ValueError("Invalid release version") from exc
    if latest.is_prerelease or latest.is_devrelease or latest <= current:
        return None
    url = payload.get("html_url")
    if not isinstance(url, str):
        raise ValueError("Missing release URL")
    address = urlsplit(url)
    if (address.scheme != "https" or address.netloc != "github.com"
            or not address.path.startswith(f"/{REPOSITORY}/releases/tag/")
            or address.query or address.fragment):
        raise ValueError("Unexpected release URL")
    return AvailableUpdate(str(latest), url)


class UpdateChecker(QObject):
    """One asynchronous public API request; no credentials or background polling."""

    checked = Signal(object)  # AvailableUpdate, or None when no newer release exists.
    failed = Signal(str)

    def __init__(self, current_version: str, parent: QObject | None = None, *, timeout_ms: int = 10000) -> None:
        super().__init__(parent)
        self.current_version = current_version
        self._timeout_ms = timeout_ms
        self._manager = QNetworkAccessManager(self)
        self._reply: QNetworkReply | None = None
        self._payload = bytearray()
        self._deadline = QTimer(self)
        self._deadline.setSingleShot(True)
        self._deadline.timeout.connect(self._timed_out)

    @property
    def is_running(self) -> bool:
        return self._reply is not None

    def check(self) -> bool:
        if self.is_running:
            return False
        request = QNetworkRequest(QUrl(LATEST_RELEASE_API))
        request.setRawHeader(b"Accept", b"application/vnd.github+json")
        request.setRawHeader(b"User-Agent", f"ApeArchivesExtractor/{self.current_version}".encode("ascii"))
        request.setRawHeader(b"X-GitHub-Api-Version", b"2026-03-10")
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute,
                             QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        request.setTransferTimeout(self._timeout_ms)
        self._payload.clear()
        reply = self._manager.get(request)
        self._reply = reply
        reply.setReadBufferSize(MAX_RESPONSE_BYTES + 1)
        reply.readyRead.connect(self._reply_ready)
        reply.finished.connect(self._reply_finished)
        self._deadline.start(self._timeout_ms)
        return True

    def cancel(self) -> None:
        self._deadline.stop()
        reply, self._reply = self._reply, None
        if reply is not None:
            reply.abort()
            reply.deleteLater()

    def _fail(self, reason: str) -> None:
        if not self.is_running:
            return
        self.cancel()
        self.failed.emit(reason)

    @Slot()
    def _timed_out(self) -> None:
        self._fail("timeout")

    @Slot()
    def _reply_ready(self) -> None:
        reply = self.sender()
        if isinstance(reply, QNetworkReply):
            self._read(reply)

    @Slot()
    def _reply_finished(self) -> None:
        reply = self.sender()
        if isinstance(reply, QNetworkReply):
            self._complete(reply)

    def _read(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        chunk = bytes(reply.readAll())
        if len(self._payload) + len(chunk) > MAX_RESPONSE_BYTES:
            self._fail("invalid_response")
            return
        self._payload.extend(chunk)

    def _complete(self, reply: QNetworkReply) -> None:
        if reply is not self._reply:
            return
        self._read(reply)
        if reply is not self._reply:
            return
        self._reply = None
        self._deadline.stop()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        error = reply.error()
        reply.deleteLater()
        if status == 404:
            self.checked.emit(None)
        elif status in (403, 429):
            self.failed.emit("rate_limit")
        elif error in (QNetworkReply.NetworkError.TimeoutError, QNetworkReply.NetworkError.OperationCanceledError):
            self.failed.emit("timeout")
        elif status != 200 or error != QNetworkReply.NetworkError.NoError:
            self.failed.emit("network")
        else:
            try:
                update = newer_release(json.loads(self._payload), self.current_version)
            except (ValueError, UnicodeError):
                self.failed.emit("invalid_response")
            else:
                self.checked.emit(update)
