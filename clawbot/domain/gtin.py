"""
GTIN normalisation.

UPC-A (12), EAN-13, EAN-8 and GTIN-14 for the same item compare equal once
zero-padded to 14 digits, so "012345678905" and "0012345678905" are one item.
A code that fails its check digit is not treated as a GTIN (likely a typo or a
store-internal code); callers keep the raw barcode separately.
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[\s\-]")
_ASCII_DIGITS = re.compile(r"[0-9]+")
_GTIN_LENGTHS = {8, 12, 13, 14}


def check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits preceding it."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def normalize_gtin(raw: str | None) -> str | None:
    """Return the GTIN-14 form, or None if `raw` is not a check-digit-valid GTIN."""
    if raw is None:
        return None
    digits = _SEPARATORS.sub("", raw)
    # ASCII only: str.isdigit() also accepts "²" and full-width digits.
    if not _ASCII_DIGITS.fullmatch(digits) or len(digits) not in _GTIN_LENGTHS:
        return None
    if check_digit(digits[:-1]) != int(digits[-1]):
        return None
    return digits.zfill(14)
