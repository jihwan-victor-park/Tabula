"""CSV export that is safe to open in a spreadsheet (no formula injection)."""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable

# Cells starting with these are executed as formulas by Excel/Sheets/LibreOffice.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def to_csv(header: list[str], rows: Iterable[list[object]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([safe_cell(h) for h in header])
    for row in rows:
        writer.writerow([safe_cell(c) for c in row])
    return buffer.getvalue()
