"""
Cell value parsing for imports. Every parser returns a value or raises
CellError with a message a store owner can act on. Nothing is guessed:
ambiguous inputs (decimal commas, non-ISO dates without a declared format,
a currency symbol that contradicts the declared currency) are errors.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from clawbot.domain.gtin import normalize_gtin


class CellError(ValueError):
    pass


# A symbol is consistent with every currency that writes it; prefixed forms pin one.
_PREFIXED = {"CN¥": {"CNY"}, "JP¥": {"JPY"}, "US$": {"USD"}, "CA$": {"CAD"}, "C$": {"CAD"}, "AU$": {"AUD"}, "A$": {"AUD"}, "MX$": {"MXN"},
             "S$": {"SGD"}, "HK$": {"HKD"}, "NT$": {"TWD"}}
_SYMBOLS = {"$": {"USD", "CAD", "AUD", "MXN", "SGD", "HKD", "TWD"}, "€": {"EUR"}, "£": {"GBP"}, "₩": {"KRW"},
            "¥": {"JPY", "CNY"}, "₹": {"INR"}, "₫": {"VND"}}
_CODE_RE = re.compile(r"\b([A-Z]{3})\b")
MAX_PLACES = 4
MAX_MAGNITUDE = Decimal("1e13")  # fits Numeric(18, 4)
# A little clock skew between the exporting system and us is fine; a date in the future is not.
FUTURE_TOLERANCE_SECONDS = 600
_THOUSANDS = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_PLAIN = re.compile(r"^-?\d+(\.\d+)?$")
_DECIMAL_COMMA = re.compile(r"^-?\d+,\d{1,2}$")

# Declared formats → strptime patterns tried in order (date, then with time).
DATE_FORMATS: dict[str, tuple[str, ...]] = {
    "MM/DD/YYYY": ("%m/%d/%Y", "%m/%d/%Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %I:%M %p", "%m/%d/%Y %I:%M:%S %p"),
    "DD/MM/YYYY": ("%d/%m/%Y", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"),
    "YYYY/MM/DD": ("%Y/%m/%d", "%Y/%m/%d %H:%M", "%Y/%m/%d %H:%M:%S"),
    "MM-DD-YYYY": ("%m-%d-%Y", "%m-%d-%Y %H:%M", "%m-%d-%Y %H:%M:%S"),
}
_TRUE = {"y", "yes", "true", "1", "confirmed", "x"}
_FALSE = {"n", "no", "false", "0", "unconfirmed", ""}


def text(raw: str) -> str:
    return raw.strip()


def bounded_text(max_length: int):
    def parse(raw: str) -> str:
        value = raw.strip()
        if len(value) > max_length:
            raise CellError(f"is longer than {max_length} characters")
        return value

    return parse


def decimal(raw: str, *, currency: str | None = None) -> Decimal:
    """
    "1,234.50" → 1234.50, "(5)" → -5, "$30.00" → 30.00 (when currency is USD).
    "1,5" is refused: it is a decimal comma in some locales and a typo in others.
    """
    value = raw.strip().replace(" ", " ")
    if not value:
        raise CellError("is empty")
    negative = value.startswith("(") and value.endswith(")")
    if negative:
        value = value[1:-1].strip()
    marks: list[tuple[str, set[str]]] = []
    for prefix, codes in _PREFIXED.items():
        if prefix in value:
            marks.append((prefix, codes))
            value = value.replace(prefix, "")
    for symbol, codes in _SYMBOLS.items():
        if symbol in value:
            marks.append((symbol, codes))
            value = value.replace(symbol, "")
    for code in _CODE_RE.findall(value):
        marks.append((code, {code}))
    if currency is not None:
        for mark, codes in marks:
            if currency not in codes:
                raise CellError(f"shows {mark if len(codes) > 1 else next(iter(codes))} but this import is in {currency}")
    value = _CODE_RE.sub("", value).replace(" ", "")
    if value.startswith("-") and negative:
        raise CellError(f"{raw!r} is not a number")
    if _DECIMAL_COMMA.fullmatch(value):
        raise CellError(f"{raw!r} uses a decimal comma; use a dot (1.5) so it cannot be misread")
    if _THOUSANDS.fullmatch(value):
        value = value.replace(",", "")
    elif not _PLAIN.fullmatch(value):
        raise CellError(f"{raw!r} is not a number")
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise CellError(f"{raw!r} is not a number")
    if abs(number) >= MAX_MAGNITUDE:
        raise CellError(f"{raw!r} is too large")
    if number != number.quantize(Decimal(1).scaleb(-MAX_PLACES)):
        raise CellError(f"{raw!r} has more than {MAX_PLACES} decimal places (often a spreadsheet formula); round it")
    return -number if negative else number


def positive_decimal(raw: str, **kw) -> Decimal:
    number = decimal(raw, **kw)
    if number <= 0:
        raise CellError("must be greater than zero")
    return number


def integer(raw: str) -> int:
    number = decimal(raw)
    if number != number.to_integral_value():
        raise CellError(f"{raw!r} must be a whole number")
    return int(number)


def boolean(raw: str) -> bool:
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise CellError(f"{raw!r} is not yes/no")


def currency_code(raw: str) -> str:
    from clawbot.domain.units import CURRENCY_MINOR_UNITS

    code = raw.strip().upper()
    if code not in CURRENCY_MINOR_UNITS:
        raise CellError(f"unsupported currency {raw!r}")
    return code


def barcode(raw: str) -> str:
    value = raw.strip()
    if len(value) > 64:
        raise CellError("is longer than 64 characters")
    # Spreadsheets turn long barcodes into "3.6000291452E+11" and drop leading zeros.
    if re.fullmatch(r"\d(\.\d+)?[eE]\+\d+", value):
        raise CellError(f"{raw!r} was converted to scientific notation by a spreadsheet; export it as text")
    return value


def gtin_or_raw(raw: str) -> tuple[str, str | None]:
    value = barcode(raw)
    return value, normalize_gtin(value)


def moment(raw: str, *, date_format: str | None, tz: str) -> datetime:
    """
    ISO 8601 always works. Other layouts need a declared `date_format`, because
    03/04/2026 is March 4 in the US and 3 April elsewhere. A time without an
    offset is read in `tz` (the store or supplier timezone).
    """
    value = raw.strip()
    if not value:
        raise CellError("is empty")
    parsed: datetime | None = None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        if date_format is None:
            raise CellError(f"{raw!r} is not an ISO date (YYYY-MM-DD); declare the file's date format")
        for pattern in DATE_FORMATS[date_format]:
            try:
                parsed = datetime.strptime(value, pattern)
                break
            except ValueError:
                continue
        if parsed is None:
            raise CellError(f"{raw!r} does not match the declared format {date_format}")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo(tz))
    return parsed


def past_moment(raw: str, *, date_format: str | None, tz: str) -> datetime:
    """A moment that has already happened (sales, counts, order dates)."""
    from datetime import timedelta, timezone

    parsed = moment(raw, date_format=date_format, tz=tz)
    if parsed > datetime.now(timezone.utc) + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        raise CellError(f"{raw!r} is in the future")
    return parsed


def excel_cell_to_text(value: object) -> str:
    """Normalise an openpyxl cached value to the text a CSV would have held."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    if isinstance(value, float):
        return repr(value) if not value.is_integer() else str(int(value))
    return str(value)
