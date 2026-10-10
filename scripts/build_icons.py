# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import os
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QSize, Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_ENTRIES = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def render_svg_to_png(svg_path: Path, size: int) -> bytes:
    renderer = QSvgRenderer(str(svg_path))
    if not renderer.isValid():
        raise ValueError(f"SVG non valido: {svg_path}")

    image = QImage(QSize(size, size), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)

    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(painter)
    painter.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise RuntimeError(f"Impossibile salvare PNG {size}px per {svg_path}")
    buffer.close()
    return bytes(data)


def write_ico(svg_path: Path, ico_path: Path) -> None:
    png_entries = [(size, render_svg_to_png(svg_path, size)) for size in ICO_SIZES]
    offset = 6 + (16 * len(png_entries))
    directory = bytearray()
    payload = bytearray()

    for size, png_data in png_entries:
        width = 0 if size == 256 else size
        directory += struct.pack(
            "<BBBBHHII",
            width,
            width,
            0,
            0,
            1,
            32,
            len(png_data),
            offset,
        )
        payload += png_data
        offset += len(png_data)

    ico_path.write_bytes(struct.pack("<HHH", 0, 1, len(png_entries)) + directory + payload)


def write_icns(svg_path: Path, icns_path: Path) -> None:
    if sys.platform != "darwin":
        return

    with tempfile.TemporaryDirectory(prefix=f"{icns_path.stem}-") as temp_dir:
        iconset_dir = Path(temp_dir) / f"{icns_path.stem}.iconset"
        iconset_dir.mkdir()
        for filename, size in ICNS_ENTRIES:
            (iconset_dir / filename).write_bytes(render_svg_to_png(svg_path, size))

        subprocess.run(
            ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
            check=True,
        )


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    assets_dir = root / "src" / "apearchivesextractor" / "assets"
    app = QGuiApplication(sys.argv)
    conversions = {
        "apearchivesextractor_icon.svg": ("apearchivesextractor_app.ico", "apearchivesextractor_app.icns"),
        "apearchivesextractor_archive_icon.svg": ("apearchivesextractor_archive.ico", "apearchivesextractor_archive.icns"),
    }
    for svg_name, output_names in conversions.items():
        svg_path = assets_dir / svg_name
        ico_path = assets_dir / output_names[0]
        write_ico(svg_path, ico_path)
        print(f"Generata icona: {ico_path}")
        if sys.platform == "darwin":
            icns_path = assets_dir / output_names[1]
            write_icns(svg_path, icns_path)
            print(f"Generata icona: {icns_path}")
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
