# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from apearchivesextractor.gui.instance_coordinator import InstanceCoordinator
from apearchivesextractor.gui.main_window import MainWindow

MAX_FORWARDED_PATHS = 4096
MAX_FORWARDED_PATH_CHARS = 32_767


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ApeArchivesExtractor", add_help=True)
    parser.add_argument("archive", nargs="?", type=Path, help="Archivio da aprire nella GUI.")
    parser.add_argument(
        "--extract-here",
        type=Path,
        help="Estrae l'archivio nella stessa cartella, utile dal menu contestuale di Windows.",
    )
    parser.add_argument(
        "--open-as-zip",
        type=Path,
        help="Apre il file forzando il backend ZIP anche se l'estensione non e' .zip.",
    )
    parser.add_argument(
        "--create-archive",
        nargs="+",
        type=Path,
        help="Apre il dialog di creazione archivio con file/cartelle gia' selezionati.",
    )
    return parser


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("ApeArchivesExtractor")
    app.setOrganizationName("GiancaGIS")
    args = _build_parser().parse_args(sys.argv[1:])

    create_request = _create_request(args.create_archive)
    if create_request is not None and _forward_with_retry(create_request, timeout_ms=500):
        return 0

    coordinator = InstanceCoordinator()
    is_primary_instance = coordinator.listen()
    if create_request is not None and not is_primary_instance:
        if _forward_with_retry(create_request, timeout_ms=4000):
            return 0

    window = MainWindow()
    window.show()
    QTimer.singleShot(1000, window.check_startup_updates)

    pending_create_paths: list[Path] = []
    create_dialog_open = False
    create_timer = QTimer()
    create_timer.setSingleShot(True)
    create_timer.setInterval(350)

    def queue_create_paths(paths: list[Path]) -> None:
        existing = {str(path).casefold() for path in pending_create_paths}
        for path in paths:
            normalized = path.resolve(strict=False)
            key = str(normalized).casefold()
            if key not in existing:
                pending_create_paths.append(normalized)
                existing.add(key)
        create_timer.start()

    def open_pending_create_dialog() -> None:
        nonlocal create_dialog_open
        if create_dialog_open or not pending_create_paths:
            if pending_create_paths:
                create_timer.start()
            return

        paths = list(pending_create_paths)
        pending_create_paths.clear()
        create_dialog_open = True
        window.showNormal()
        window.raise_()
        window.activateWindow()
        try:
            window.open_create_dialog(paths)
        finally:
            create_dialog_open = False
            if pending_create_paths:
                create_timer.start()

    def handle_forwarded_request(request: dict) -> None:
        if request.get("action") != "create_archive":
            return
        raw_paths = request.get("paths")
        if not isinstance(raw_paths, list) or len(raw_paths) > MAX_FORWARDED_PATHS:
            return
        paths = [
            Path(value)
            for value in raw_paths
            if isinstance(value, str) and 0 < len(value) <= MAX_FORWARDED_PATH_CHARS
        ]
        if paths:
            queue_create_paths(paths)

    create_timer.timeout.connect(open_pending_create_dialog)
    if is_primary_instance:
        coordinator.request_received.connect(handle_forwarded_request)

    if args.open_as_zip is not None:
        QTimer.singleShot(0, lambda: window.load_archive_as_zip(args.open_as_zip))
    elif args.extract_here is not None:
        QTimer.singleShot(0, lambda: window.extract_archive_here_from_shell(args.extract_here))
    elif args.create_archive:
        queue_create_paths(args.create_archive)
    elif args.archive is not None and args.archive.exists():
        window.load_archive(args.archive)

    return app.exec()


def _create_request(paths: list[Path] | None) -> dict[str, object] | None:
    if not paths:
        return None
    return {
        "action": "create_archive",
        "paths": [str(path.resolve(strict=False)) for path in paths],
    }


def _forward_with_retry(request: dict[str, object], timeout_ms: int) -> bool:
    deadline = time.monotonic() + (timeout_ms / 1000)
    while True:
        remaining_ms = int((deadline - time.monotonic()) * 1000)
        if remaining_ms <= 0:
            return False
        if InstanceCoordinator.forward(request, timeout_ms=min(remaining_ms, 500)):
            return True
        time.sleep(0.1)


if __name__ == "__main__":
    raise SystemExit(main())
