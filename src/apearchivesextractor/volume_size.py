from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SIZE_PATTERN = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*([kmgt](?:i?b?)?|b)?\s*$", re.IGNORECASE)
_MULTIPLIERS = {
    "": 1,
    "b": 1,
    "k": 1024,
    "kb": 1024,
    "kib": 1024,
    "m": 1024 ** 2,
    "mb": 1024 ** 2,
    "mib": 1024 ** 2,
    "g": 1024 ** 3,
    "gb": 1024 ** 3,
    "gib": 1024 ** 3,
    "t": 1024 ** 4,
    "tb": 1024 ** 4,
    "tib": 1024 ** 4,
}


def parse_volume_size(value: str) -> int:
    """Parse a positive byte size such as 100M, 700MB, or 1.5GiB."""
    match = _SIZE_PATTERN.match(value)
    if match is None:
        raise ValueError("Use a size such as 100M, 700MB, or 1.5G.")
    try:
        amount = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation as exc:
        raise ValueError("Invalid volume size.") from exc
    unit = (match.group(2) or "").lower()
    size = int(amount * _MULTIPLIERS[unit])
    if size <= 0:
        raise ValueError("Volume size must be greater than zero.")
    return size
