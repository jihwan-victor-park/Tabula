"""
Stock changes made in the app by scanning (or typing) a barcode.

Scanning only finds the item. Stock changes when a person picks what happened and how many:

  stock_in   goods arrived without a Tabula order        → ledger +qty   (reason adjustment)
  used       sold outside the sales data, used, sampled → ledger −qty   (reason adjustment; not counted as demand)
  damaged    broken / expired / lost                    → ledger −qty   (reason damage)
  count      "there are N on the shelf"                 → ledger set to N (reason count; the new stock anchor)

Deliveries for a Tabula order go through Receiving instead (receipts), so they are counted once.

Only stores whose stock Tabula keeps can be changed here. Where the POS owns stock (Square,
read-only for Tabula) the change must be made in the POS; the app says so instead of keeping a
second, diverging count.

Every action records who did it and why, and can be undone: an opposite movement keyed by the
original (so undo is idempotent) — the history keeps both.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from clawbot.domain import catalog, inventory, tenancy
from clawbot.domain.errors import IdempotencyConflict, NotFound, StateConflict, ValidationFailed
from clawbot.domain.gtin import normalize_gtin
from clawbot.persistence.models import InventoryMovement, InventoryPosition, Variant
from clawbot.policies.permissions import Actor

ACTIONS = {"stock_in": ("adjustment", 1), "used": ("adjustment", -1), "damaged": ("damage", -1), "count": ("count", 0)}
SOURCE = "app_scan"


def lookup(session: Session, *, tenant_id: uuid.UUID, code: str) -> Variant | None:
    """A scanned or typed code: barcode (any GTIN length) or SKU, exact."""
    code = code.strip()
    if not code:
        return None
    gtin = normalize_gtin(code)
    conds = [Variant.sku == code, Variant.barcode == code]
    if gtin:
        conds.append(Variant.gtin == gtin)
    return session.scalars(select(Variant).where(Variant.tenant_id == tenant_id, or_(*conds))
                           .order_by(Variant.status)).first()


def apply(session: Session, *, tenant_id: uuid.UUID, actor: Actor, location_id: uuid.UUID, variant_id: uuid.UUID,
          action: str, qty: Decimal, note: str | None, request_key: str) -> InventoryMovement:
    if action not in ACTIONS:
        raise ValidationFailed(f"action must be one of {', '.join(ACTIONS)}")
    if qty < 0 or (qty == 0 and action != "count"):
        raise ValidationFailed("Enter a quantity above zero" if action != "count" else "A count cannot be negative")
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    if location.inventory_write_owner != "tabula":
        raise StateConflict(f"{location.inventory_write_owner.title()} keeps this store's stock; make the change there. "
                            "Tabula reads it on the next sync.", details={"stock_owner": location.inventory_write_owner})
    catalog.get_variant(session, tenant_id=tenant_id, variant_id=variant_id)
    done = session.scalars(select(InventoryMovement).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.source == SOURCE,
        InventoryMovement.source_event_id == request_key)).one_or_none()
    reason, sign = ACTIONS[action]
    if done is not None:
        same = done.variant_id == variant_id and done.location_id == location_id and done.reason == reason and (
            done.counted_qty == qty if action == "count" else done.delta == qty * sign)
        if not same:  # a retry must not silently drop a corrected quantity or action
            raise IdempotencyConflict("This change was already saved with different details — reload and enter it again")
        return done  # the same request again (double tap, retry): already applied
    if action == "count":
        position = session.scalars(select(InventoryPosition).where(
            InventoryPosition.tenant_id == tenant_id, InventoryPosition.variant_id == variant_id,
            InventoryPosition.location_id == location_id).with_for_update()).one_or_none()
        delta = qty - (position.on_hand if position else Decimal(0))
    else:
        delta = qty * sign
    labels = {"stock_in": "Stock in (no order)", "used": "Sold or used outside the sales data", "damaged": "Damaged / lost",
              "count": "Counted"}
    result = inventory.record_movement(
        session, tenant_id=tenant_id, variant_id=variant_id, location_id=location_id, delta=delta, reason=reason,
        source=SOURCE, source_event_id=request_key, actor=actor,
        notes=f"{labels[action]}{': ' + note.strip() if note and note.strip() else ''}")
    return result.movement


def undo(session: Session, *, tenant_id: uuid.UUID, actor: Actor, movement_id: uuid.UUID, note: str | None) -> InventoryMovement:
    original = session.scalars(select(InventoryMovement).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.id == movement_id)).one_or_none()
    if original is None:
        raise NotFound("That change was not found")
    if original.source != SOURCE:
        raise StateConflict("Only changes made in the app can be undone here; receipts are corrected on Receiving")
    if original.reason == "count":
        # A count resets the level; an opposite adjustment would not restore what was there before it.
        raise StateConflict("A count can't be undone — count the item again with the right number")
    later_count = session.scalar(select(InventoryMovement.id).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == original.location_id,
        InventoryMovement.variant_id == original.variant_id, InventoryMovement.reason == "count",
        InventoryMovement.occurred_at > original.occurred_at).limit(1))
    if later_count is not None:
        raise StateConflict("This item was counted after this change, and that count already includes it — "
                            "count again instead of undoing")
    result = inventory.record_movement(
        session, tenant_id=tenant_id, variant_id=original.variant_id, location_id=original.location_id,
        delta=-original.delta, reason="adjustment", source="undo", source_event_id=str(original.id), actor=actor,
        notes=f"Undo of: {original.notes or original.reason}{' — ' + note.strip() if note and note.strip() else ''}")
    return result.movement


def recent(session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, limit: int = 30) -> list[dict[str, Any]]:
    from clawbot.persistence.models import User

    rows = session.scalars(select(InventoryMovement).where(
        InventoryMovement.tenant_id == tenant_id, InventoryMovement.location_id == location_id,
        InventoryMovement.source.in_((SOURCE, "undo"))).order_by(InventoryMovement.occurred_at.desc()).limit(limit)).all()
    undone = {r.source_event_id for r in rows if r.source == "undo"} | set(session.scalars(
        select(InventoryMovement.source_event_id).where(InventoryMovement.tenant_id == tenant_id,
                                                        InventoryMovement.source == "undo")))
    variants = {v.id: v for v in session.scalars(select(Variant).where(Variant.tenant_id == tenant_id))}
    actors = {m.actor_user_id for m in rows if m.actor_user_id}
    emails = dict(session.execute(select(User.id, User.email).where(User.id.in_(actors))).all()) if actors else {}
    return [{"id": str(m.id), "at": m.occurred_at.isoformat(), "sku": variants[m.variant_id].sku,
             "name": variants[m.variant_id].name, "delta": f"{m.delta.normalize():f}", "reason": m.reason,
             "note": m.notes, "by": emails.get(m.actor_user_id), "is_undo": m.source == "undo",
             "undone": str(m.id) in undone} for m in rows]
