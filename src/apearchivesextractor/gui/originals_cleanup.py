from __future__ import annotations

import shutil
from pathlib import Path
from typing import Iterable


def output_is_inside_inputs(output_path: Path, input_paths: Iterable[Path]) -> Path | None:
    """Return the input that would remove output_path, if any."""

    output = output_path.resolve(strict=False)
    for input_path in input_paths:
        existing_input = input_path.resolve(strict=True)
        if existing_input.is_dir() and not existing_input.is_symlink():
            try:
                output.relative_to(existing_input)
            except ValueError:
                continue
            return input_path
        if existing_input == output:
            return input_path
    return None


def delete_original_inputs(input_paths: Iterable[Path]) -> list[Path]:
    """Delete original input files/folders after a successful archive creation."""

    deleted: list[Path] = []
    for path in _top_level_existing_paths(input_paths):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink()
        deleted.append(path)
    return deleted


def _top_level_existing_paths(input_paths: Iterable[Path]) -> list[Path]:
    resolved_paths = [path.resolve(strict=True) for path in input_paths if path.exists()]
    top_level: list[Path] = []

    for path in sorted(resolved_paths, key=lambda value: (len(value.parts), str(value).casefold())):
        if any(_is_same_or_child(path, parent) for parent in top_level):
            continue
        top_level.append(path)

    return top_level


def _is_same_or_child(path: Path, parent: Path) -> bool:
    if path == parent:
        return True
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
