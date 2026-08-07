from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from PyQt6.QtCore import QLockFile, QObject, QStandardPaths, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

SERVER_NAME = "GiancaGIS.ApeArchivesExtractor.Gui"
LOCK_FILE_NAME = "GiancaGIS-ApeArchivesExtractor-Gui.lock"
MAX_REQUEST_BYTES = 1024 ** 2


class InstanceCoordinator(QObject):
    """Forwards shell requests to the first ApeArchivesExtractor GUI process."""

    request_received = pyqtSignal(dict)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._accept_connections)
        self._buffers: dict[QLocalSocket, bytearray] = {}
        lock_dir = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation))
        self._primary_lock = QLockFile(str(lock_dir / LOCK_FILE_NAME))
        self._primary_lock.setStaleLockTime(30_000)

    def listen(self) -> bool:
        if not self._primary_lock.tryLock(0):
            return False
        if self._server.listen(SERVER_NAME):
            return True
        self._primary_lock.unlock()
        return False

    def close(self) -> None:
        self._server.close()
        if self._primary_lock.isLocked():
            self._primary_lock.unlock()

    @staticmethod
    def forward(request: Mapping[str, object], timeout_ms: int = 500) -> bool:
        payload = json.dumps(dict(request), ensure_ascii=True).encode("utf-8") + b"\n"
        if len(payload) > MAX_REQUEST_BYTES:
            return False

        socket = QLocalSocket()
        socket.connectToServer(SERVER_NAME)
        if not socket.waitForConnected(timeout_ms):
            return False

        if socket.write(payload) != len(payload):
            socket.abort()
            return False
        socket.flush()
        sent = socket.bytesToWrite() == 0 or socket.waitForBytesWritten(timeout_ms)
        socket.disconnectFromServer()
        return sent

    def _accept_connections(self) -> None:
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.setReadBufferSize(MAX_REQUEST_BYTES + 1)
            self._buffers[socket] = bytearray()
            socket.readyRead.connect(lambda current=socket: self._read_socket(current))
            socket.disconnected.connect(lambda current=socket: self._discard_socket(current))
            self._read_socket(socket)

    def _read_socket(self, socket: QLocalSocket) -> None:
        buffer = self._buffers.get(socket)
        if buffer is None:
            return
        incoming = bytes(socket.readAll())
        if len(buffer) + len(incoming) > MAX_REQUEST_BYTES:
            self._buffers.pop(socket, None)
            socket.abort()
            socket.deleteLater()
            return
        buffer.extend(incoming)

        while b"\n" in buffer:
            raw_line, _, remaining = buffer.partition(b"\n")
            buffer[:] = remaining
            if not raw_line:
                continue
            try:
                request = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(request, dict):
                self.request_received.emit(request)

    def _discard_socket(self, socket: QLocalSocket) -> None:
        self._read_socket(socket)
        self._buffers.pop(socket, None)
        socket.deleteLater()
