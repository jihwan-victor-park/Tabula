"""
Supplier replies (spec 5.2/5.4/10, CP7): an answer from the supplier is evidence, not a command.

1. Record: the raw text (pasted email, uploaded .txt/.eml/.csv, or a generated
   mock reply in development) is stored with its sha256. The same text recorded
   twice is the same reply.
2. Read: a deterministic parser (no LLM) proposes, per PO line, what the supplier
   said — accept, partial, out of stock, ETA, price / pack / product change,
   cancel the remainder — each with the line of text it came from. Text in the
   reply is data only; nothing in it is executed or followed.
3. Apply: a person reviews (and may correct) that reading and applies it.
   Confirmed quantities are absolute ("confirmed 5"), so applying the same answer
   twice changes nothing. A reply older (by the supplier's own timestamp) than
   one already applied cannot be applied. Price, product, pack and over-quantity
   changes are not applied: they wait on the line as a proposal for the owner.
"""

from __future__ import annotations

import csv
import email
import email.policy
import hashlib
import io
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import format_datetime, parsedate_to_datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.domain import audit, data_version, po_progress, suppliers
from clawbot.domain.errors import NotFound, StateConflict, ValidationFailed
from clawbot.persistence.models import PO_SENT_STATUSES, PoLine, PurchaseOrder, SupplierItem, SupplierReply
from clawbot.policies.permissions import Actor, authorize

ZERO = Decimal(0)
ACTIONS = ("accept", "partial", "reject", "eta", "cancel_remaining", "change", "none", "unclear")
CHANGE_KINDS = ("price", "pack", "substitute", "qty_increase")
MAX_REPLY_BYTES = 200_000

_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_DATE_ISO = re.compile(r"\b(20\d\d)-(\d{1,2})-(\d{1,2})\b")
_DATE_US = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(20\d\d|\d\d))?\b")
_DATE_WORD = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(20\d\d))?\b")
_SKU_TOKEN = re.compile(r"\b[A-Z0-9]+(?:-[A-Z0-9]+)+\b")
_QUOTE_START = re.compile(r"^(-{2,}\s*original message|on .+ wrote:$|from: .+ sent: )", re.I)
_OWN_PO_LINE = re.compile(r"@\s*[\d.]+\s+[A-Z]{3}\s*=")  # our own PO body, quoted without ">"

_REJECT = re.compile(r"out of stock|unavailable|not available|cannot (?:supply|ship|fill)|can't (?:supply|ship|fill)|"
                     r"no stock|discontinued|unable to (?:supply|ship)", re.I)
_SUBSTITUTE = re.compile(r"substitut\w*|replace(?:ment)? with|instead|alternative|can offer", re.I)
# A price only with a price word ("price is now $33") or a per-unit form ("$33 per case"); never a total.
_PRICE = re.compile(r"(?:price|cost)\w*\b[^0-9$\n]{0,30}\$?\s*(\d+(?:\.\d+)?)|\$\s*(\d+(?:\.\d+)?)\s*(?:per|/|a|each)\b", re.I)
_PACK = re.compile(r"(?:case|pack|box)\s+of\s+(\d+)|(\d+)\s*(?:per|/)\s*(?:case|pack|box)|(\d+)\s*-?\s*(?:pack|ct)\b", re.I)
# Numbers that are never a quantity: removed before quantities are read.
_NOT_QTY = [re.compile(rx, re.I) for rx in (
    r"\$\s*\d+(?:[.,]\d+)*", r"\b\d+(?:\.\d+)?\s*(?:usd|dollars?)\b", r"\b\d+\s*%",
    r"\b\d{1,2}(?::\d\d)?\s*(?:am|pm)\b", r"\b\d{1,2}:\d\d\b",
    r"\b(?:in|within|for|after)?\s*\d+\s*(?:business\s+|working\s+)?(?:days?|weeks?|hours?|hrs?|months?)\b",
    r"\b(?:po|p\.o\.|order|invoice|ref|reference|ticket|account|acct)\s*(?:no\.?|number|#)?\s*:?\s*#?\s*\d+\b", r"#\s*\d+",
    r"\b\d+\s*-?\s*(?:pack|ct|count)\b", r"(?:case|pack|box)\s+of\s+\d+", r"\b\d+\s*(?:per|/)\s*(?:case|pack|box)\b",
    r"\b\d+\s*(?:units?\s+)?(?:on hand|in stock|available|in the warehouse)\b",
)]
# A quantity is a number next to a unit word, or right after a confirming verb ("confirm 5", "can only ship 6").
_QTY = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:of\s*\d+(?:\.\d+)?\s*)?(?:cases?|cs|bags?|units?|boxes?|ctns?|cartons?|packs?)\b"
                  r"|\b(?:confirm(?:ed|ing)?|ship(?:ping)?|send(?:ing)?|can do|only|supply(?:ing)?|allocat\w*)\s+"
                  r"(?:(?:you|only|just|the|a|qty|quantity|of|ship|send)\s+)*(\d+(?:\.\d+)?)\b", re.I)
_ACCEPT = re.compile(r"\b(?:confirm\w*|ok|okay|accept\w*|yes|will ship|ships|shipping|in stock|good to go|approved)\b", re.I)
_BACKORDER = re.compile(r"back.?order\w*|to follow|will follow|later|next (?:week|shipment|truck)|remaining (?:will|to)", re.I)
_CANCEL_REST = re.compile(r"cancel\w*\s+(?:the\s+)?(?:remaining|rest|backorder\w*|balance|outstanding)", re.I)
_GLOBAL_ACCEPT = re.compile(r"(?:all|everything|rest|remaining|other)\s+(?:items?|lines?|of the order|else)?\s*"
                            r"(?:is |are |will be )?(?:confirmed|ok|okay|accepted|good|in stock|will ship)|"
                            r"confirm(?:ing|ed)?\s+(?:the|your|this)\s+(?:order|po)\b|order\s+(?:\S+\s+)?(?:is\s+)?confirmed|"
                            r"(?:accepted|confirmed) in full", re.I)
_ETA_WORD = re.compile(r"\b(?:eta|deliver\w*|arriv\w*|ship\w*|dispatch\w*|on the truck)\b", re.I)


def _num(text: str) -> str:
    return f"{Decimal(text).normalize():f}"


def _year_for(month: int, day: int, today: date) -> date:
    d = date(today.year, month, day)
    return d if d >= today - timedelta(days=60) else date(today.year + 1, month, day)


def find_date(text: str, today: date) -> date | None:
    try:
        if m := _DATE_ISO.search(text):
            return date(int(m[1]), int(m[2]), int(m[3]))
        if m := _DATE_WORD.search(text.lower()):
            month, day = _MONTHS[m[1][:3]], int(m[2])
            return date(int(m[3]), month, day) if m[3] else _year_for(month, day, today)
        if m := _DATE_US.search(text):
            month, day = int(m[1]), int(m[2])
            if m[3]:
                year = int(m[3]) + (2000 if len(m[3]) == 2 else 0)
                return date(year, month, day)
            return _year_for(month, day, today)
    except ValueError:
        return None
    return None


def _strip_dates(text: str) -> str:
    for rx in (_DATE_ISO, _DATE_US):
        text = rx.sub(" ", text)
    return _DATE_WORD.sub(" ", text.lower())


def _po_lines_view(rows: list[PoLine]) -> list[dict[str, Any]]:
    return [{"line_no": l.line_no, "sku": l.sku, "supplier_sku": l.supplier_sku, "order_uom": l.order_uom,
             "ordered_qty": _num(str(l.ordered_qty)), "unit_price": _num(str(l.unit_price)),
             "units_per_order_uom": _num(str(l.units_per_order_uom))} for l in rows]


def _blank(line: dict[str, Any]) -> dict[str, Any]:
    return {"line_no": line["line_no"], "sku": line["sku"], "supplier_sku": line["supplier_sku"], "action": "none",
            "confirmed_qty": None, "eta": None, "backorder": False, "change": None, "evidence": []}


def _qty_text(text: str) -> str:
    clean = _strip_dates(text)
    for token in _SKU_TOKEN.findall(text):
        clean = clean.replace(token.lower(), " ")
    for rx in _NOT_QTY:
        clean = rx.sub(" ", clean)
    return clean


def _read_line(text: str, line: dict[str, Any], today: date) -> dict[str, Any]:
    """What one line of reply text says about one PO line. Unsure → "unclear", never a guessed quantity."""
    out: dict[str, Any] = {}
    ordered = Decimal(line["ordered_qty"])
    upper = text.upper()
    own = min((upper.find(s) for s in (line["supplier_sku"].upper(), line["sku"].upper()) if s in upper), default=-1)
    eta = find_date(text, today)
    if eta:
        out["eta"] = eta.isoformat()
    sub = _SUBSTITUTE.search(text)
    if sub and own >= 0 and own < sub.start():
        # The line being replaced is named before the offer; the substitute after it.
        offered = [t for t in _SKU_TOKEN.findall(text[sub.start():])
                   if t.upper() not in (line["supplier_sku"].upper(), line["sku"].upper())]
        if offered:
            qty = _QTY.search(_qty_text(text))
            out.update(action="change", change={"kind": "substitute", "substitute_sku": offered[0],
                                                 "qty": _num(qty[1] or qty[2]) if qty else line["ordered_qty"]})
            return out
    no_dates = _strip_dates(text)
    price = _PRICE.search(no_dates)
    if price and not re.search(r"(?:sub)?total|amount due", no_dates[max(price.start() - 20, 0):price.start()], re.I):
        new_price = Decimal(price[1] or price[2])
        if new_price != Decimal(line["unit_price"]):
            out.update(action="change", change={"kind": "price", "unit_price": _num(str(new_price))})
            return out
    pack = _PACK.search(no_dates)
    if pack:
        units = Decimal(pack[1] or pack[2] or pack[3])
        if units != Decimal(line["units_per_order_uom"]):
            out.update(action="change", change={"kind": "pack", "units_per_order_uom": _num(str(units))})
            return out
    if _CANCEL_REST.search(text):
        out["action"] = "cancel_remaining"
        return out
    qty_match = _QTY.search(_qty_text(text))
    qty = Decimal(qty_match[1] or qty_match[2]) if qty_match else None
    if _REJECT.search(text) and not (qty and re.search(r"only|can do", text, re.I)):
        out.update(action="reject", confirmed_qty="0")
        return out
    if qty is not None:
        if qty > ordered:
            out.update(action="change", change={"kind": "qty_increase", "qty": _num(str(qty))})
        elif qty == ordered:
            out.update(action="accept", confirmed_qty=_num(str(qty)))
        else:
            out.update(action="partial", confirmed_qty=_num(str(qty)), backorder=bool(_BACKORDER.search(text)))
        return out
    if _ACCEPT.search(text):
        out.update(action="accept", confirmed_qty=line["ordered_qty"])
        return out
    if eta:
        out["action"] = "eta"
        return out
    out["action"] = "unclear"
    return out


def parse_text(text: str, rows: list[PoLine], *, today: date) -> dict[str, Any]:
    """Read a free-text reply. Every reading carries the reply line(s) it came from."""
    view = _po_lines_view(rows)
    result = {line["line_no"]: _blank(line) for line in view}
    replaced = {l.replaces_line_no for l in rows if l.replaces_line_no}
    replied_at: str | None = None
    global_accept: dict[str, Any] | None = None
    global_eta: dict[str, Any] | None = None
    ignored = 0
    for n, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if _QUOTE_START.search(stripped):
            break  # everything below is the quoted original
        if stripped.startswith(">") or _OWN_PO_LINE.search(stripped):
            ignored += 1
            continue
        header = re.match(r"^(date|sent):\s*(.+)$", stripped, re.I)
        if header:
            try:
                replied_at = parsedate_to_datetime(header[2]).astimezone(timezone.utc).isoformat()
            except (TypeError, ValueError):
                pass
            continue
        if re.match(r"^(from|to|subject|cc):", stripped, re.I):
            continue
        evidence = {"line": n, "text": stripped[:300]}
        upper = stripped.upper()
        matched = [l for l in view if re.search(rf"(?<![A-Z0-9-]){re.escape(l['supplier_sku'].upper())}(?![A-Z0-9-])", upper)
                   or re.search(rf"(?<![A-Z0-9-]){re.escape(l['sku'].upper())}(?![A-Z0-9-])", upper)]
        if matched:
            for l in matched:
                reading = _read_line(stripped, l, today)
                entry = result[l["line_no"]]
                if reading.get("action") == "eta" and entry["action"] not in ("none", "unclear"):
                    entry["eta"] = reading["eta"]  # a later line only adds the date
                else:
                    entry.update({k: v for k, v in reading.items()})
                entry["evidence"].append(evidence)
            continue
        if _GLOBAL_ACCEPT.search(stripped):
            global_accept = evidence
        eta = find_date(stripped, today)
        if eta and _ETA_WORD.search(stripped):
            global_eta = {**evidence, "eta": eta.isoformat()}
    for entry in result.values():
        if entry["line_no"] in replaced:
            entry.update(action="none", confirmed_qty=None, change=None)  # superseded by its substitute line
            continue
        if entry["action"] == "none" and global_accept:
            line = next(l for l in view if l["line_no"] == entry["line_no"])
            entry.update(action="accept", confirmed_qty=line["ordered_qty"])
            entry["evidence"].append(global_accept)
        if global_eta and not entry["eta"] and entry["action"] in ("accept", "partial", "eta", "change"):
            entry["eta"] = global_eta["eta"]
            entry["evidence"].append({"line": global_eta["line"], "text": global_eta["text"]})
    warnings = []
    if ignored:
        warnings.append(f"{ignored} quoted line(s) from the original order were ignored")
    if any(e["action"] == "unclear" for e in result.values()):
        warnings.append("Some lines mention an item but could not be read; decide them yourself")
    if all(e["action"] == "none" for e in result.values()):
        warnings.append("No line of this order was recognised in the reply")
    return {"format": "text", "replied_at": replied_at, "lines": list(result.values()), "warnings": warnings}


_CSV_STATUS = {"confirmed": "accept", "accepted": "accept", "ok": "accept", "partial": "partial",
               "backorder": "partial", "out_of_stock": "reject", "out of stock": "reject", "rejected": "reject",
               "unavailable": "reject", "cancelled": "cancel_remaining"}


def parse_csv(text: str, rows: list[PoLine], *, today: date) -> dict[str, Any]:
    """A supplier's confirmation sheet: supplier_sku, status, qty, unit_price, eta, substitute_sku, units_per_case."""
    view = _po_lines_view(rows)
    by_sku = {l["supplier_sku"].upper(): l for l in view}
    result = {line["line_no"]: _blank(line) for line in view}
    warnings = []
    reader = csv.DictReader(io.StringIO(text))
    fields = {f.strip().lower(): f for f in (reader.fieldnames or [])}
    if "supplier_sku" not in fields:
        raise ValidationFailed("The CSV needs a supplier_sku column")

    def get(row: dict[str, str], name: str) -> str:
        return (row.get(fields.get(name, ""), "") or "").strip()

    for n, row in enumerate(reader, start=2):
        line = by_sku.get(get(row, "supplier_sku").upper())
        evidence = {"line": n, "text": ", ".join(f"{k}={v}" for k, v in row.items() if v)[:300]}
        if line is None:
            warnings.append(f"Row {n}: {get(row, 'supplier_sku')} is not on this order")
            continue
        entry = result[line["line_no"]]
        entry["evidence"].append(evidence)
        try:
            qty = Decimal(get(row, "qty")) if get(row, "qty") else None
            price = Decimal(get(row, "unit_price").lstrip("$")) if get(row, "unit_price") else None
            pack = Decimal(get(row, "units_per_case")) if get(row, "units_per_case") else None
        except InvalidOperation:
            entry["action"] = "unclear"
            continue
        eta = find_date(get(row, "eta"), today) if get(row, "eta") else None
        entry["eta"] = eta.isoformat() if eta else None
        status = _CSV_STATUS.get(get(row, "status").lower(), "unclear" if get(row, "status") else "accept")
        ordered = Decimal(line["ordered_qty"])
        if get(row, "substitute_sku"):
            entry.update(action="change", change={"kind": "substitute", "substitute_sku": get(row, "substitute_sku"),
                                                  "qty": _num(str(qty or ordered))})
        elif price is not None and price != Decimal(line["unit_price"]):
            entry.update(action="change", change={"kind": "price", "unit_price": _num(str(price))})
        elif pack is not None and pack != Decimal(line["units_per_order_uom"]):
            entry.update(action="change", change={"kind": "pack", "units_per_order_uom": _num(str(pack))})
        elif status == "reject":
            entry.update(action="reject", confirmed_qty="0")
        elif status == "cancel_remaining":
            entry["action"] = "cancel_remaining"
        elif qty is not None and qty > ordered:
            entry.update(action="change", change={"kind": "qty_increase", "qty": _num(str(qty))})
        elif status in ("accept", "partial"):
            confirmed = qty if qty is not None else ordered
            entry.update(action="accept" if confirmed == ordered else "partial", confirmed_qty=_num(str(confirmed)),
                         backorder=get(row, "status").lower() == "backorder")
        else:
            entry["action"] = status
    return {"format": "csv", "replied_at": None, "lines": list(result.values()), "warnings": warnings}


# ---------------------------------------------------------------------------
# Mock replies (development only — labelled as such everywhere)
# ---------------------------------------------------------------------------

MOCK_SCENARIOS = ("accept_all", "partial", "out_of_stock", "price_change", "eta_change", "substitute")


def mock_text(po: PurchaseOrder, rows: list[PoLine], supplier_email: str | None, scenario: str, *, now: datetime) -> str:
    """A supplier-style reply for testing. Deterministic for a given order, scenario and time."""
    if scenario not in MOCK_SCENARIOS:
        raise ValidationFailed(f"scenario must be one of {', '.join(MOCK_SCENARIOS)}")
    eta = (now + timedelta(days=4)).date()
    first, rest = rows[0], rows[1:]
    body: list[str] = []
    if scenario == "accept_all":
        body = [f"We confirm your order {po.number} in full.", f"ETA {eta.isoformat()} for all items."]
    elif scenario == "partial":
        part = max((first.ordered_qty * Decimal("0.75")).to_integral_value(rounding="ROUND_DOWN"), Decimal(1))
        if part >= first.ordered_qty:
            part = first.ordered_qty - 1 if first.ordered_qty > 1 else first.ordered_qty
        body = [f"{first.supplier_sku}: we can only ship {_num(str(part))} {first.order_uom}, "
                f"the remaining {_num(str(first.ordered_qty - part))} cannot be supplied this month.",
                *(f"{l.supplier_sku}: confirmed {_num(str(l.ordered_qty))} {l.order_uom}." for l in rest),
                f"Delivery {eta.isoformat()}."]
    elif scenario == "out_of_stock":
        body = [f"{first.supplier_sku} is out of stock until further notice.",
                *(f"{l.supplier_sku} confirmed." for l in rest), f"ETA {eta.isoformat()} for the rest."]
    elif scenario == "price_change":
        new = (first.unit_price * Decimal("1.1")).quantize(Decimal("0.01"))
        body = [f"{first.supplier_sku}: price is now ${new} per {first.order_uom} (cost increase from the manufacturer).",
                *(f"{l.supplier_sku} confirmed." for l in rest), f"ETA {eta.isoformat()}."]
    elif scenario == "eta_change":
        late = eta + timedelta(days=5)
        body = [f"All items confirmed, but delivery moves to {late.isoformat()} — truck delayed."]
    elif scenario == "substitute":
        body = [f"{first.supplier_sku} is discontinued; we can offer {first.supplier_sku}-ALT instead, "
                f"same pack, {_num(str(first.ordered_qty))} {first.order_uom}.",
                *(f"{l.supplier_sku} confirmed." for l in rest), f"ETA {eta.isoformat()}."]
    return "\n".join([
        f"From: {supplier_email or 'supplier@example.com'}",
        f"Date: {format_datetime(now)}",
        f"Subject: Re: Purchase order {po.number}",
        "",
        "Hello,",
        "",
        *body,
        "",
        "Thanks,",
        "Order desk (MOCK REPLY — generated by Tabula for testing)",
    ])


# ---------------------------------------------------------------------------
# Record, apply, decide
# ---------------------------------------------------------------------------


def _sent_po(session: Session, tenant_id: uuid.UUID, po_id: uuid.UUID, *, for_update: bool = False) -> PurchaseOrder:
    from clawbot.domain import purchasing

    po = purchasing.get_po(session, tenant_id=tenant_id, po_id=po_id, for_update=for_update)
    if po.status not in PO_SENT_STATUSES and po.status != "closed":
        raise StateConflict(f"A reply can only be recorded for a sent order (this one is {po.status.replace('_', ' ')})")
    return po


def _decode_upload(file_name: str, data: bytes) -> tuple[str, str, datetime | None]:
    """(text, format, replied_at) from an uploaded .txt / .eml / .csv."""
    if len(data) > MAX_REPLY_BYTES:
        raise ValidationFailed("The reply file is too large")
    name = file_name.lower()
    if name.endswith(".eml"):
        msg = email.message_from_bytes(data, policy=email.policy.default)
        part = msg.get_body(preferencelist=("plain",))
        if part is None:
            raise ValidationFailed("The email has no plain-text part to read")
        when = None
        if msg["Date"]:
            try:
                when = parsedate_to_datetime(str(msg["Date"]))
            except (TypeError, ValueError):
                when = None
        return part.get_content(), "text", when
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValidationFailed("The reply file must be UTF-8 text, .eml or .csv") from exc
    return text, "csv" if name.endswith(".csv") else "text", None


def record(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, source: str, text: str | None = None,
           file_name: str | None = None, data: bytes | None = None, replied_at: datetime | None = None,
           scenario: str | None = None) -> tuple[SupplierReply, bool]:
    """Store a reply and the parser's reading of it. Returns (reply, created); the same text is the same reply."""
    authorize(actor, "po.reply")
    po = _sent_po(session, tenant_id, po_id, for_update=True)
    rows = po_progress.lines(session, po)
    now = datetime.now(timezone.utc)
    fmt = "text"
    if source == "mock":
        from clawbot.domain import purchasing
        from clawbot.policies import supplier_contact

        if supplier_contact.send_mode() != "capture":
            raise StateConflict("Mock replies exist only while sending is in capture mode")
        content = purchasing.revision(session, po).content
        text = mock_text(po, rows, content["supplier"]["order_email"], scenario or "accept_all", now=now)
    elif source == "upload":
        if data is None or not file_name:
            raise ValidationFailed("Upload a file")
        text, fmt, file_when = _decode_upload(file_name, data)
        replied_at = replied_at or file_when
    elif source != "paste":
        raise ValidationFailed("source must be mock, paste or upload")
    if not text or not text.strip():
        raise ValidationFailed("The reply is empty")
    if len(text.encode()) > MAX_REPLY_BYTES:
        raise ValidationFailed("The reply is too long")
    sha = hashlib.sha256(_normalised(text).encode()).hexdigest()
    existing = session.scalars(select(SupplierReply).where(
        SupplierReply.tenant_id == tenant_id, SupplierReply.po_id == po.id, SupplierReply.raw_sha256 == sha)).one_or_none()
    if existing is not None:
        return existing, False
    parsed = (parse_csv if fmt == "csv" else parse_text)(text, rows, today=now.date())
    if replied_at is None and parsed.get("replied_at"):
        replied_at = datetime.fromisoformat(parsed["replied_at"])
    if replied_at is not None and replied_at.tzinfo is None:
        raise ValidationFailed("replied_at must include a timezone")
    if replied_at is not None and replied_at > now + timedelta(minutes=5):
        raise ValidationFailed("The reply's time is in the future")
    if replied_at is None:
        # Ordering replies needs the supplier's own time; the time it was pasted could put an old email after a new one.
        raise ValidationFailed("This reply has no Date line. Enter when the supplier sent it.",
                               details={"needs": "replied_at"})
    parsed["replied_at_source"] = "reply" if parsed.get("replied_at") else "given"
    # Kept as evidence either way, but a reply older than one already applied can never be applied.
    stale = po.last_reply_at is not None and replied_at < po.last_reply_at
    reply = SupplierReply(tenant_id=tenant_id, po_id=po.id, source=source, file_name=file_name, raw_text=text,
                          raw_sha256=sha, replied_at=replied_at, parsed=parsed,
                          status="stale" if stale else "pending_review", created_by_user_id=actor.user_id)
    session.add(reply)
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.reply_recorded", object_type="purchase_order",
                 object_id=po.id, after={"reply_id": str(reply.id), "source": source, "sha256": sha})
    return reply, True


def _normalised(text: str) -> str:
    """The same email pasted twice — with or without its headers, other line endings or spacing — is one reply."""
    body = [re.sub(r"\s+", " ", l.strip()) for l in text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    return "\n".join(l for l in body if l and not re.match(r"^(date|sent|from|to|subject|cc):", l, re.I))


def get_reply(session: Session, *, tenant_id: uuid.UUID, reply_id: uuid.UUID) -> SupplierReply:
    reply = session.scalars(select(SupplierReply).where(SupplierReply.tenant_id == tenant_id,
                                                        SupplierReply.id == reply_id)).one_or_none()
    if reply is None:
        raise NotFound("Reply not found")
    return reply


def _decision_digest(decisions: list[dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(sorted(decisions, key=lambda d: d["line_no"]), sort_keys=True).encode()).hexdigest()


def _dec(value: Any, what: str) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValidationFailed(f"{what} must be a number") from exc
    if d < 0 or d != d.quantize(Decimal("0.0001")):
        raise ValidationFailed(f"{what} must be ≥ 0 with at most 4 decimals")
    return d


def apply(session: Session, *, tenant_id: uuid.UUID, actor: Actor, reply_id: uuid.UUID,
          decisions: list[dict[str, Any]]) -> SupplierReply:
    """
    Apply the reading a person reviewed. `decisions` is one entry per line the
    person wants to change (line_no, action, confirmed_qty, eta, backorder, change).
    """
    authorize(actor, "po.reply")
    reply = get_reply(session, tenant_id=tenant_id, reply_id=reply_id)
    po = _sent_po(session, tenant_id, reply.po_id, for_update=True)  # one reply at a time per order
    session.refresh(reply, with_for_update=True)
    digest = _decision_digest(decisions)
    if reply.status == "applied":
        if reply.applied and reply.applied.get("digest") == digest:
            return reply  # the same review submitted twice
        raise StateConflict("This reply was already applied")
    if reply.status == "dismissed":
        raise StateConflict("This reply was dismissed")
    if reply.status == "stale" or (po.last_reply_at is not None and reply.replied_at < po.last_reply_at):
        raise StateConflict("A newer reply from the supplier has already been applied; this older one cannot "
                            "overwrite it", details={"reply_time": reply.replied_at.isoformat(),
                                                     "newest_applied": po.last_reply_at.isoformat() if po.last_reply_at else None})
    rows = {l.line_no: l for l in po_progress.lines(session, po, for_update=True)}
    replaced_by = {l.replaces_line_no: l.line_no for l in rows.values() if l.replaces_line_no}
    reading = {l["line_no"]: l for l in reply.parsed.get("lines", [])}
    # The supplier proposed a change to price / product / pack / quantity; reading it as a plain "accept"
    # would skip the owner's decision. Only the owner may set a proposed change aside, and it is recorded.
    overrides = [d.get("line_no") for d in decisions
                 if reading.get(d.get("line_no"), {}).get("action") == "change" and d.get("action") != "change"]
    if overrides:
        authorize(actor, "po.approve")
    applied = []
    for d in decisions:
        line = rows.get(d.get("line_no"))
        if line is None:
            raise ValidationFailed(f"Unknown line {d.get('line_no')}")
        action = d.get("action")
        if action not in ACTIONS:
            raise ValidationFailed(f"Line {line.line_no}: unknown action {action!r}")
        if action == "unclear":
            raise ValidationFailed(f"Line {line.line_no}: decide what the supplier said before applying")
        if action == "none":
            continue
        eta = date.fromisoformat(d["eta"]) if d.get("eta") else None
        if line.proposal and action != "change":
            raise StateConflict(f"Line {line.line_no} has a change waiting for the owner; decide that first")
        if line.line_no in replaced_by and action in ("accept", "partial", "change"):
            raise ValidationFailed(f"Line {line.line_no} was replaced by substitute line {replaced_by[line.line_no]}; "
                                   "answer for that line instead")
        if action in ("accept", "partial"):
            qty = line.ordered_qty if action == "accept" else _dec(d.get("confirmed_qty"), f"Line {line.line_no} quantity")
            if action == "partial" and not (ZERO < qty < line.ordered_qty) and qty != ZERO:
                raise ValidationFailed(f"Line {line.line_no}: a partial confirmation is between 0 and the "
                                       f"{line.ordered_qty.normalize():f} ordered")
            if qty < line.received_qty - line.replacement_qty:
                raise ValidationFailed(f"Line {line.line_no}: more than {qty.normalize():f} has already arrived")
            line.confirmed_qty = qty
            line.rejected_qty = ZERO if action == "accept" or d.get("backorder") else line.ordered_qty - qty
            line.cancelled_qty = ZERO  # the supplier's newest answer stands (e.g. a cancelled remainder reinstated)
            if eta:
                line.eta = eta
        elif action == "reject":
            if line.received_qty > 0:
                raise ValidationFailed(f"Line {line.line_no}: goods already arrived; record the rest as cancelled instead")
            line.confirmed_qty, line.rejected_qty = ZERO, line.ordered_qty
        elif action == "eta":
            if eta is None:
                raise ValidationFailed(f"Line {line.line_no}: an ETA change needs a date")
            line.eta = eta
        elif action == "cancel_remaining":
            # The remainder of the order is cancelled; confirmed replacements for damaged goods are a separate promise.
            if line.confirmed_qty is None:
                line.confirmed_qty = min(line.received_qty, line.ordered_qty)
            line.rejected_qty = max(line.ordered_qty - line.confirmed_qty, ZERO)
            received_on_order = max(line.received_qty - line.replacement_qty, ZERO)
            line.cancelled_qty = max(line.confirmed_qty - received_on_order, ZERO)
        elif action == "change":
            change = d.get("change") or {}
            if change.get("kind") not in CHANGE_KINDS:
                raise ValidationFailed(f"Line {line.line_no}: change kind must be one of {', '.join(CHANGE_KINDS)}")
            line.proposal = _proposal(line, change, eta, reply)
        line.updated_at = datetime.now(timezone.utc)
        applied.append({k: v for k, v in d.items() if k != "evidence"})
    reply.status, reply.reviewed_by_user_id, reply.reviewed_at = "applied", actor.user_id, datetime.now(timezone.utc)
    reply.applied = {"digest": digest, "decisions": applied, "owner_overrides": overrides}
    po.last_reply_at = max(filter(None, [po.last_reply_at, reply.replied_at]))
    session.flush()
    po_progress.recompute(session, po)
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.reply_applied", object_type="purchase_order",
                 object_id=po.id, after={"reply_id": str(reply.id), "decisions": applied, "status": po.status,
                                         "ack_status": po.ack_status, "owner_overrides": overrides})
    return reply


def session_of(obj: Any) -> Session:
    from sqlalchemy.orm import object_session

    return object_session(obj)


def _substitute_item(session: Session, line: PoLine, sku: str) -> SupplierItem | None:
    from clawbot.persistence.models import PurchaseOrder as PO

    po = session.get(PO, line.po_id)
    return session.scalars(select(SupplierItem).where(
        SupplierItem.tenant_id == line.tenant_id, SupplierItem.supplier_id == po.supplier_id,
        SupplierItem.supplier_sku == sku)).one_or_none()


def _substitute_price(session: Session, line: PoLine, sku: str) -> str | None:
    """Current price of the substitute, shown to the owner with the proposal (None if not a known item yet)."""
    item = _substitute_item(session, line, sku)
    price = suppliers.current_price(session, tenant_id=line.tenant_id, item_id=item.id) if item else None
    return _num(str(price.unit_price)) if price else None


def _proposal(line: PoLine, change: dict[str, Any], eta: date | None, reply: SupplierReply) -> dict[str, Any]:
    kind = change["kind"]
    p: dict[str, Any] = {"kind": kind, "reply_id": str(reply.id), "eta": eta.isoformat() if eta else None,
                         "was": {"unit_price": _num(str(line.unit_price)), "units_per_order_uom": _num(str(line.units_per_order_uom)),
                                 "supplier_sku": line.supplier_sku, "ordered_qty": _num(str(line.ordered_qty))}}
    if kind == "price":
        p["unit_price"] = _num(str(_dec(change.get("unit_price"), "New price")))
    elif kind == "pack":
        units = _dec(change.get("units_per_order_uom"), "New pack size")
        if units <= 0:
            raise ValidationFailed("New pack size must be positive")
        p["units_per_order_uom"] = _num(str(units))
    elif kind == "substitute":
        if not change.get("substitute_sku"):
            raise ValidationFailed("A substitute needs the supplier's SKU")
        p["substitute_sku"] = str(change["substitute_sku"])[:120]
        p["qty"] = _num(str(_dec(change.get("qty") or line.ordered_qty, "Substitute quantity")))
        p["substitute_unit_price"] = _substitute_price(session_of(line), line, p["substitute_sku"])
    elif kind == "qty_increase":
        p["qty"] = _num(str(_dec(change.get("qty"), "Quantity")))
    p["digest"] = hashlib.sha256(json.dumps(p, sort_keys=True).encode()).hexdigest()
    return p


def decide_proposal(session: Session, *, tenant_id: uuid.UUID, actor: Actor, po_id: uuid.UUID, line_no: int,
                    decision: str, proposal_digest: str) -> PurchaseOrder:
    """
    Owner only: the original approval covered the old price / product / pack / quantity,
    so a change needs a new decision bound to exactly the proposal shown.
    Accept → the line is confirmed on the new terms (a substitute becomes its own line,
    the original is rejected). Decline → the supplier will not ship it as ordered: rejected.
    """
    authorize(actor, "po.approve")
    po = _sent_po(session, tenant_id, po_id, for_update=True)
    rows = po_progress.lines(session, po, for_update=True)
    line = next((l for l in rows if l.line_no == line_no), None)
    if line is None or not line.proposal:
        raise StateConflict("There is no change waiting on that line")
    p = line.proposal
    if p.get("digest") != proposal_digest:
        raise StateConflict("The proposed change is not the one you reviewed; reload the order")
    if decision not in ("accept", "decline"):
        raise ValidationFailed("decision must be accept or decline")
    kind = p["kind"]
    eta = date.fromisoformat(p["eta"]) if p.get("eta") else None
    after: dict[str, Any] = {"line_no": line_no, "kind": kind, "decision": decision}
    if decision == "decline" and kind == "qty_increase":
        # Not taking the extra: the supplier did confirm what was ordered.
        line.confirmed_qty, line.rejected_qty = line.ordered_qty, ZERO
    elif decision == "decline":
        # What already arrived stays; the rest will not come.
        line.confirmed_qty, line.rejected_qty = line.received_qty, line.ordered_qty - line.received_qty
    elif kind == "price":
        line.unit_price, line.confirmed_qty, line.rejected_qty = Decimal(p["unit_price"]), line.ordered_qty, ZERO
    elif kind == "pack":
        line.units_per_order_uom, line.confirmed_qty, line.rejected_qty = Decimal(p["units_per_order_uom"]), line.ordered_qty, ZERO
        after["note"] = "update the supplier item's pack size in the supplier master too"
    elif kind == "qty_increase":
        line.confirmed_qty, line.rejected_qty = Decimal(p["qty"]), ZERO
    elif kind == "substitute":
        item = _substitute_item(session, line, p["substitute_sku"])
        if item is None or item.mapping_status != "confirmed" or item.variant_id is None or item.status != "active":
            raise StateConflict(f"Add {p['substitute_sku']} as a supplier item and confirm which product it is "
                                "before accepting it as a substitute",
                                details={"substitute_sku": p["substitute_sku"]})
        price = suppliers.current_price(session, tenant_id=tenant_id, item_id=item.id)
        if price is None or price.currency != po.currency:
            raise StateConflict(f"{p['substitute_sku']} has no current price in {po.currency}")
        if p.get("substitute_unit_price") != _num(str(price.unit_price)):
            raise StateConflict(f"{p['substitute_sku']}'s price is {_num(str(price.unit_price))} {po.currency}, not the "
                                "price shown with this proposal; record the reply again to review it",
                                details={"price_now": _num(str(price.unit_price))})
        from clawbot.persistence.models import Variant

        variant = session.get(Variant, item.variant_id)
        new_no = max(l.line_no for l in rows) + 1
        session.add(PoLine(
            tenant_id=tenant_id, po_id=po.id, line_no=new_no, revision=line.revision, variant_id=item.variant_id,
            supplier_item_id=item.id, sku=variant.sku if variant else p["substitute_sku"], supplier_sku=item.supplier_sku,
            order_uom=item.order_uom, units_per_order_uom=item.units_per_order_uom, unit_price=price.unit_price,
            ordered_qty=Decimal(p["qty"]), confirmed_qty=Decimal(p["qty"]), rejected_qty=ZERO, cancelled_qty=ZERO,
            received_qty=ZERO, damaged_qty=ZERO, replacement_qty=ZERO, eta=eta, replaces_line_no=line.line_no))
        line.confirmed_qty, line.rejected_qty = line.received_qty, line.ordered_qty - line.received_qty
        after["substitute_line_no"] = new_no
    if decision == "accept" and eta and kind != "substitute":
        line.eta = eta
    line.proposal = None
    line.updated_at = datetime.now(timezone.utc)
    session.flush()
    po_progress.recompute(session, po)
    data_version.bump(session, tenant_id)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.change_decided", object_type="purchase_order",
                 object_id=po.id, after={**after, "proposal": p, "status": po.status})
    return po


def dismiss(session: Session, *, tenant_id: uuid.UUID, actor: Actor, reply_id: uuid.UUID, reason: str) -> SupplierReply:
    authorize(actor, "po.reply")
    reply = get_reply(session, tenant_id=tenant_id, reply_id=reply_id)
    _sent_po(session, tenant_id, reply.po_id, for_update=True)
    session.refresh(reply, with_for_update=True)
    if reply.status != "pending_review":
        raise StateConflict(f"This reply is {reply.status}")
    reply.status, reply.reviewed_by_user_id, reply.reviewed_at = "dismissed", actor.user_id, datetime.now(timezone.utc)
    audit.record(session, tenant_id=tenant_id, actor=actor, action="po.reply_dismissed", object_type="purchase_order",
                 object_id=reply.po_id, after={"reply_id": str(reply.id)}, reason=reason)
    return reply
