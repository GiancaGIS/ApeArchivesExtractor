# SPDX-License-Identifier: GPL-3.0-only
# Copyright (c) 2026 GiancaGIS

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from apearchivesextractor.archive_service import ArchiveService
from apearchivesextractor.errors import ApeArchivesExtractorError
from apearchivesextractor.models import ProgressEvent
from apearchivesextractor.volume_size import parse_volume_size
from apearchivesextractor.legal_info import license_notice


def _volume_size_arg(value: str) -> int:
    try:
        return parse_volume_size(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _print_progress(event: ProgressEvent) -> None:
    if event.total_bytes and event.processed_bytes is not None:
        pct = (event.processed_bytes / event.total_bytes) * 100 if event.total_bytes else 0
        print(f"{event.message}: {event.current_item or ''} {pct:5.1f}%")
    else:
        print(f"{event.message}: {event.current_item or ''}".rstrip())


def _password_from_args(value: str | None) -> str | None:
    if value == "-":
        return getpass.getpass("Password: ")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="apearch",
        description="Archive manager for ZIP, 7Z, RAR, TAR.GZ, and multi-volume files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--license", action="version", version=license_notice(),
                        help="Show copyright, redistribution terms and the full GPLv3 license")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List archive content")
    list_parser.add_argument("archive", type=Path)
    list_parser.add_argument(
        "--password",
        "-p",
        help="Password. Use '-' to prompt securely; inline values can be visible in shell history.",
    )

    extract_parser = subparsers.add_parser("extract", help="Extract an archive")
    extract_parser.add_argument("archive", type=Path)
    extract_parser.add_argument("--output", "-o", type=Path, required=True)
    extract_parser.add_argument(
        "--password",
        "-p",
        help="Password. Use '-' to prompt securely; inline values can be visible in shell history.",
    )
    extract_parser.add_argument(
        "--member",
        "-m",
        action="append",
        default=None,
        help="Archive member to extract. Can be repeated. If omitted, extracts everything.",
    )

    create_parser = subparsers.add_parser("create", help="Create an archive")
    create_parser.add_argument("output", type=Path)
    create_parser.add_argument("inputs", type=Path, nargs="+")
    create_parser.add_argument(
        "--format",
        "-f",
        choices=["zip", "7z", "rar", "tar.gz"],
        help="Archive format. If omitted, inferred from output extension.",
    )
    create_parser.add_argument(
        "--password",
        "-p",
        help="Password. Use '-' to prompt securely; inline values can be visible in shell history.",
    )
    create_parser.add_argument(
        "--compression-level",
        "-l",
        type=int,
        default=9,
        help="Compression level. Defaults to maximum (9); ZIP/TAR.GZ use 0-9.",
    )
    create_parser.add_argument(
        "--volume-size",
        "-v",
        type=_volume_size_arg,
        help="Maximum ZIP, 7Z, or RAR volume size, for example 100M, 700MB, or 1.5G.",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    service = ArchiveService()

    try:
        if args.command == "list":
            password = _password_from_args(args.password)
            entries = service.list_entries(args.archive, password=password)
            for entry in entries:
                kind = "DIR " if entry.is_dir else "FILE"
                size = "-" if entry.size is None else str(entry.size)
                compressed = "-" if entry.compressed_size is None else str(entry.compressed_size)
                print(f"{kind:4} {size:>12} {compressed:>12} {entry.path}")
            return 0

        if args.command == "extract":
            password = _password_from_args(args.password)
            if args.member:
                service.extract_members(
                    args.archive,
                    args.output,
                    args.member,
                    password=password,
                    progress=_print_progress,
                )
            else:
                service.extract_all(args.archive, args.output, password=password, progress=_print_progress)
            return 0

        if args.command == "create":
            password = _password_from_args(args.password)
            service.create(
                args.output,
                args.inputs,
                archive_format=args.format,
                password=password,
                compression_level=args.compression_level,
                volume_size=args.volume_size,
                progress=_print_progress,
            )
            return 0

        parser.error("Unknown command")
        return 2

    except ApeArchivesExtractorError as exc:
        print(f"ApeArchivesExtractor error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # CLI guardrail; library code still raises exact exceptions.
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
