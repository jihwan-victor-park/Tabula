"""
Raw inbound provider events (webhooks, polling results).

Store first, ack second, process from the stored copy. Duplicate deliveries
of the same external_event_id collapse onto one row.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.persistence.models import ConnectorEvent


@dataclass(frozen=True)
class StoredEvent:
    event: ConnectorEvent
    is_new: bool


def store_event(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    provider: str,
    external_event_id: str,
    payload: dict[str, Any],
    event_type: str | None = None,
    source_timestamp: datetime | None = None,
) -> StoredEvent:
    inserted = session.execute(
        insert(ConnectorEvent)
        .values(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            provider=provider,
            external_event_id=external_event_id,
            event_type=event_type,
            source_timestamp=source_timestamp,
            payload=payload,
        )
        .on_conflict_do_nothing(index_elements=["tenant_id", "provider", "external_event_id"])
        .returning(ConnectorEvent.id)
    ).scalar_one_or_none()
    event = session.scalars(
        select(ConnectorEvent).where(
            ConnectorEvent.tenant_id == tenant_id,
            ConnectorEvent.provider == provider,
            ConnectorEvent.external_event_id == external_event_id,
        )
    ).one()
    return StoredEvent(event=event, is_new=inserted is not None)
