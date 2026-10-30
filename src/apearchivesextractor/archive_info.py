# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS
"""Read archive metadata without extracting members or testing their contents."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from contextlib import nullcontext
from datetime import datetime
import gzip
from pathlib import Path, PurePosixPath
import stat
import tarfile

from apearchivesextractor.adapters.sevenz_adapter import _open_seven_zip
from apearchivesextractor.adapters.zip_adapter import _open_zip, _zip_part_paths
from apearchivesextractor.errors import ArchiveLimitExceededError, UnsafeArchivePathError
from apearchivesextractor.models import ArchiveEntry, ArchiveFormat
from apearchivesextractor.security import normalize_archive_name, validate_extraction_plan
from apearchivesextractor.spanned import (
    canonical_volume_path, detect_archive_format, numbered_volume_paths,
    numeric_volume_base, open_numeric_volumes,
)

MAX_INFO_ENTRIES = 100_000
MAX_TAR_SCAN_BYTES = 64 * 1024**2


@dataclass
class ArchiveInfo:
    path: str
    format: str
    archive_bytes: int
    modified: str
    volumes: int = 1
    files: int | None = None
    folders: int | None = None
    uncompressed_bytes: int | None = None
    compression_ratio: float | None = None
    space_saving_percent: float | None = None
    methods: list[str] = field(default_factory=list)
    encrypted: bool | None = None
    solid: bool | None = None
    unsafe_names: int = 0
    links: int | None = None
    status: str = "ok"
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return asdict(self)


class _LimitedTarReader:
    def __init__(self, stream, limit: int):
        self.stream, self.remaining = stream, limit

    def read(self, size: int = -1) -> bytes:
        if self.remaining <= 0:
            raise ArchiveLimitExceededError("TAR metadata scan exceeded its decompression budget.")
        data = self.stream.read(min(size if size >= 0 else self.remaining, self.remaining))
        self.remaining -= len(data)
        return data


def inspect_archive(path: str | Path) -> ArchiveInfo:
    path = Path(path).absolute()
    file_stat = path.stat()
    fmt = detect_archive_format(path)
    result = ArchiveInfo(str(path), fmt.value, file_stat.st_size,
                         datetime.fromtimestamp(file_stat.st_mtime).astimezone().isoformat(timespec="seconds"))
    base = numeric_volume_base(path)
    volumes = numbered_volume_paths(base) if base else []
    if not volumes and fmt == ArchiveFormat.ZIP:
        canonical = canonical_volume_path(path)
        parts = _zip_part_paths(canonical)
        if parts:
            volumes = [*parts, canonical]
    if volumes:
        result.volumes = len(volumes)
        result.archive_bytes = sum(volume.stat().st_size for volume in volumes)

    entries: list[ArchiveEntry] = []
    folders: set[str] = set()
    methods: set[str] = set()

    def record(name: str, size: int | None, compressed: int | None, directory: bool, link: bool = False):
        if len(entries) >= MAX_INFO_ENTRIES:
            raise ArchiveLimitExceededError("Archive metadata contains too many entries.")
        entries.append(ArchiveEntry(name, size, compressed, directory))
        if result.links is not None:
            result.links += int(link)
        try:
            safe = normalize_archive_name(name)
        except UnsafeArchivePathError:
            result.unsafe_names += 1
            return
        parents = PurePosixPath(safe).parents
        folders.update(str(parent) for parent in parents if str(parent) != ".")
        if directory:
            folders.add(safe)

    try:
        if fmt == ArchiveFormat.ZIP:
            names = {0: "Stored", 8: "Deflate", 12: "BZIP2", 14: "LZMA", 93: "Zstandard"}
            result.encrypted, result.links = False, 0
            with _open_zip(path) as archive:
                for item in archive.infolist():
                    result.encrypted |= bool(item.flag_bits & 1)
                    methods.add(names.get(item.compress_type, f"ZIP method {item.compress_type}"))
                    record(item.filename, item.file_size, item.compress_size, item.is_dir(),
                           stat.S_ISLNK(item.external_attr >> 16))
        elif fmt == ArchiveFormat.SEVEN_Z:
            with _open_seven_zip(path, None) as archive:
                result.encrypted = archive.needs_password()
                for item in archive.list():
                    record(item.filename, item.uncompressed, item.compressed, item.is_directory)
                if base is None and entries:
                    details = archive.archiveinfo()
                    methods.update(details.method_names)
                    result.solid = details.solid
        elif fmt == ArchiveFormat.RAR:
            import rarfile
            # File-like input inspects numbered parts without joining them on disk.
            source = open_numeric_volumes(path) if base else nullcontext(canonical_volume_path(path))
            with source as stream, rarfile.RarFile(stream, errors="strict") as archive:
                result.encrypted, result.links = archive.needs_password(), 0
                result.solid = archive.is_solid()
                for item in archive.infolist():
                    methods.add(f"RAR 0x{item.compress_type:02x}")
                    record(item.filename, item.file_size, item.compress_size, item.isdir(), item.is_symlink())
                if result.encrypted and not entries:
                    result.status = "locked"
                    result.notes.append("Archive headers require a password.")
                if base is None:
                    known = [Path(name) for name in archive.volumelist() if isinstance(name, (str, Path))]
                    if known and all(volume.is_file() for volume in known):
                        result.volumes = len(known)
                        result.archive_bytes = sum(volume.stat().st_size for volume in known)
        else:
            result.encrypted, result.links = False, 0
            methods.add("GZIP / TAR")
            # TAR metadata requires traversing the gzip stream. Limit decompressed
            # reads, do not extract members, and report partial counts explicitly.
            with gzip.open(path, "rb") as stream:
                with tarfile.open(fileobj=_LimitedTarReader(stream, MAX_TAR_SCAN_BYTES), mode="r|") as archive:
                    for item in archive:
                        record(item.name, item.size, None, item.isdir(), item.issym() or item.islnk())
    except ArchiveLimitExceededError as exc:
        result.status = "limited"
        result.notes.append(str(exc))
    except Exception as exc:
        if type(exc).__name__ == "PasswordRequired":
            result.encrypted, result.status = True, "locked"
        else:
            result.status = "error"
        result.notes.append(f"{type(exc).__name__}: {str(exc)[:2000]}")

    result.methods = sorted(methods)
    if result.unsafe_names:
        result.notes.append("Archive contains member paths that are unsafe to extract.")
    if result.links:
        result.notes.append("Archive contains links; extraction requires link-safety checks.")
    if result.status != "locked" and (entries or result.status == "ok"):
        result.files = sum(not entry.is_dir for entry in entries)
        result.folders = len(folders)
        sizes = [entry.size for entry in entries if not entry.is_dir]
        if all(size is not None for size in sizes):
            result.uncompressed_bytes = sum(sizes)
        try:
            validate_extraction_plan(entries)
        except (UnsafeArchivePathError, ArchiveLimitExceededError) as exc:
            result.notes.append(str(exc)[:2000])
        if result.status == "ok" and result.uncompressed_bytes and result.archive_bytes:
            result.compression_ratio = result.uncompressed_bytes / result.archive_bytes
            result.space_saving_percent = 100 * (1 - result.archive_bytes / result.uncompressed_bytes)
    return result


def format_archive_info(info: ArchiveInfo, language: str = "en") -> str:
    italian = language == "it"
    unknown = "Non disponibile" if italian else "Unavailable"

    def value(item):
        if item is None:
            return unknown
        if isinstance(item, bool):
            return ("Si" if italian else "Yes") if item else "No"
        return str(item)

    def size(number):
        if number is None:
            return unknown
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        amount = float(number)
        for unit in units:
            if amount < 1024 or unit == units[-1]:
                return f"{amount:,.2f} {unit} ({number:,} bytes)"
            amount /= 1024

    pairs = [
        ("File", Path(info.path).name),
        ("Formato" if italian else "Format", info.format.upper()),
        ("Dimensione archivio" if italian else "Archive size", size(info.archive_bytes)),
        ("Ultima modifica" if italian else "Last modified", info.modified),
        ("Volumi rilevati" if italian else "Detected volumes", value(info.volumes)),
        ("File contenuti" if italian else "Files", value(info.files)),
        ("Cartelle (incluse implicite)" if italian else "Folders (including implicit)", value(info.folders)),
        ("Dimensione non compressa" if italian else "Uncompressed size", size(info.uncompressed_bytes)),
        ("Rapporto originale / archivio" if italian else "Original / archive ratio",
         f"{info.compression_ratio:.2f}:1" if info.compression_ratio is not None else unknown),
        ("Risparmio (inclusi header)" if italian else "Space saving (including headers)",
         f"{info.space_saving_percent:.1f}%" if info.space_saving_percent is not None else unknown),
        ("Metodi" if italian else "Methods", ", ".join(info.methods) or unknown),
        ("Cifratura / password" if italian else "Encryption / password", value(info.encrypted)),
        ("Archivio solido" if italian else "Solid archive", value(info.solid)),
        ("Percorsi non sicuri" if italian else "Unsafe member paths", value(info.unsafe_names)),
        ("Collegamenti" if italian else "Links", value(info.links)),
    ]
    lines = [f"{label}: {data}" for label, data in pairs]
    if info.status != "ok":
        lines += ["", "Informazioni parziali / non disponibili." if italian else "Information is partial or unavailable."]
    if info.notes:
        lines += ["", "Note:", *info.notes]
    lines += ["", "Solo metadati: contenuto non estratto, integrita dei file non verificata."
              if italian else "Metadata only: contents were not extracted and file integrity was not tested."]
    return "\n".join(lines)
