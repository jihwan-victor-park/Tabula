"""Tenants, users, memberships and locations."""

from __future__ import annotations

import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from clawbot.domain import audit
from clawbot.domain.errors import NotFound, PermissionDenied, StateConflict, ValidationFailed
from clawbot.persistence.models import INVENTORY_WRITE_OWNERS, ROLES, Location, Membership, Tenant, User
from clawbot.policies.permissions import Actor, authorize, human


def get_or_create_user(session: Session, *, auth_subject: str, email: str | None) -> User:
    stmt = (
        insert(User)
        .values(id=uuid.uuid4(), auth_subject=auth_subject, email=email)
        .on_conflict_do_nothing(index_elements=["auth_subject"])
    )
    session.execute(stmt)
    return session.scalars(select(User).where(User.auth_subject == auth_subject)).one()


def create_tenant(session: Session, *, name: str, owner: User) -> Tenant:
    tenant = Tenant(name=name)
    session.add(tenant)
    session.flush()
    session.add(Membership(tenant_id=tenant.id, user_id=owner.id, role="owner"))
    audit.record(
        session,
        tenant_id=tenant.id,
        actor=human(owner.id, "owner"),
        action="tenant.created",
        object_type="tenant",
        object_id=tenant.id,
        after={"name": name},
    )
    return tenant


def get_membership(session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Membership | None:
    return session.scalars(
        select(Membership).where(Membership.tenant_id == tenant_id, Membership.user_id == user_id)
    ).one_or_none()


def actor_for(session: Session, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> Actor:
    """
    The only way to build a human Actor for tool and worker code: the role comes
    from the membership row, never from the caller (spec 8: do not trust IDs or
    roles a model passes in).
    """
    membership = get_membership(session, tenant_id=tenant_id, user_id=user_id)
    if membership is None:
        raise PermissionDenied("Not a member of this tenant")
    return human(user_id, membership.role)


def list_memberships(session: Session, *, user_id: uuid.UUID) -> list[tuple[Membership, Tenant]]:
    rows = session.execute(
        select(Membership, Tenant)
        .join(Tenant, Tenant.id == Membership.tenant_id)
        .where(Membership.user_id == user_id)
        .order_by(Tenant.created_at)
    )
    return [(m, t) for m, t in rows]


def list_members(session: Session, *, tenant_id: uuid.UUID) -> list[tuple[Membership, User]]:
    rows = session.execute(
        select(Membership, User)
        .join(User, User.id == Membership.user_id)
        .where(Membership.tenant_id == tenant_id)
        .order_by(Membership.created_at)
    )
    return [(m, u) for m, u in rows]


def set_member_role(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    auth_subject: str,
    email: str | None,
    role: str,
) -> Membership:
    """Add a member or change their role. The last owner can never be demoted."""
    authorize(actor, "members.manage")
    if role not in ROLES:
        raise ValidationFailed(f"Unknown role: {role}")
    user = get_or_create_user(session, auth_subject=auth_subject, email=email)
    # Lock the tenant's memberships so two concurrent demotions cannot remove both owners.
    session.execute(select(Membership.id).where(Membership.tenant_id == tenant_id).with_for_update())
    membership = get_membership(session, tenant_id=tenant_id, user_id=user.id)
    before = None if membership is None else {"role": membership.role}
    if membership is None:
        membership = Membership(tenant_id=tenant_id, user_id=user.id, role=role)
        session.add(membership)
    else:
        if membership.role == "owner" and role != "owner":
            owners = session.scalar(
                select(func.count()).select_from(Membership).where(
                    Membership.tenant_id == tenant_id, Membership.role == "owner"
                )
            )
            if owners <= 1:
                raise StateConflict("A tenant must keep at least one owner")
        membership.role = role
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="membership.role_set",
        object_type="membership",
        object_id=membership.id,
        before=before,
        after={"user_id": str(user.id), "role": role},
    )
    return membership


def create_location(
    session: Session,
    *,
    tenant_id: uuid.UUID,
    actor: Actor,
    name: str,
    timezone: str,
    inventory_write_owner: str = "tabula",
) -> Location:
    authorize(actor, "location.edit")
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValidationFailed(f"Unknown timezone: {timezone}")
    if inventory_write_owner not in INVENTORY_WRITE_OWNERS:
        raise ValidationFailed(f"Unknown inventory_write_owner: {inventory_write_owner}")
    location = Location(
        tenant_id=tenant_id, name=name, timezone=timezone, inventory_write_owner=inventory_write_owner
    )
    session.add(location)
    session.flush()
    audit.record(
        session,
        tenant_id=tenant_id,
        actor=actor,
        action="location.created",
        object_type="location",
        object_id=location.id,
        after={"name": name, "timezone": timezone, "inventory_write_owner": inventory_write_owner},
    )
    return location


def list_locations(session: Session, *, tenant_id: uuid.UUID) -> list[Location]:
    return list(
        session.scalars(select(Location).where(Location.tenant_id == tenant_id).order_by(Location.name))
    )


def get_location(
    session: Session, *, tenant_id: uuid.UUID, location_id: uuid.UUID, for_share: bool = False
) -> Location:
    stmt = select(Location).where(Location.tenant_id == tenant_id, Location.id == location_id)
    if for_share:
        stmt = stmt.with_for_update(read=True)
    location = session.scalars(stmt).one_or_none()
    if location is None:
        raise NotFound(f"Location not found: {location_id}")
    return location
