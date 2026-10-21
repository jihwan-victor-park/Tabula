from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from clawbot.persistence.models import AuditEvent
from clawbot.policies.permissions import Actor

# Changes to these can change what replenishment recommends, so they move the
# tenant data version (clawbot/domain/data_version.py).
PLANNING_INPUT_TYPES = frozenset({
    "inventory_movement", "variant", "external_item_mapping", "supplier", "supplier_contact", "supplier_item",
    "location", "replenishment_policy", "external_open_order_line",
})


def record(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    action: str,
    object_type: str,
    object_id: str | uuid.UUID,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    reason: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        tenant_id=tenant_id,
        actor_kind=actor.kind,
        actor_user_id=actor.user_id,
        actor_name=actor.name,
        action=action,
        object_type=object_type,
        object_id=str(object_id),
        before=before,
        after=after,
        reason=reason,
    )
    session.add(event)
    session.flush()
    if object_type in PLANNING_INPUT_TYPES:
        from clawbot.domain import data_version

        data_version.bump(session, tenant_id)
    return event
