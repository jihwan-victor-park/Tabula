from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_current_user, get_tenant_context, require_permission
from clawbot.domain import accounts, tenancy
from clawbot.persistence.models import User
from clawbot.schemas.core import MemberOut, MemberSet, MeOut, TenantCreate, TenantMembershipOut

router = APIRouter(tags=["tenancy"])


def _me(session: Session, user: User) -> MeOut:
    return MeOut(
        user_id=user.id,
        email=user.email,
        memberships=[
            TenantMembershipOut(tenant_id=t.id, tenant_name=t.name, role=m.role, business_type=t.business_type,  # type: ignore[arg-type]
                                currency=t.currency, is_sample=t.is_sample)
            for m, t in tenancy.list_memberships(session, user_id=user.id)
        ],
    )


@router.get("/me", response_model=MeOut)
def get_me(session: Session = DbSession, user: User = Depends(get_current_user)) -> MeOut:
    return _me(session, user)


@router.post("/tenants", response_model=TenantMembershipOut, status_code=201)
def post_tenant(
    body: TenantCreate,
    session: Session = DbSession,
    user: User = Depends(get_current_user),
) -> TenantMembershipOut:
    tenant = tenancy.create_tenant(session, name=body.name, owner=user)
    return TenantMembershipOut(tenant_id=tenant.id, tenant_name=tenant.name, role="owner")


@router.get("/members", response_model=list[MemberOut])
def get_members(
    session: Session = DbSession, ctx: TenantContext = Depends(require_permission("members.read"))
) -> list[MemberOut]:
    return [
        MemberOut(user_id=u.id, email=u.email, role=m.role)  # type: ignore[arg-type]
        for m, u in tenancy.list_members(session, tenant_id=ctx.tenant_id)
    ]


@router.put("/members", response_model=MemberOut)
def put_member(
    body: MemberSet,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("members.manage")),
) -> MemberOut:
    """Add a member or change a role (owner only). The last owner cannot be demoted."""
    membership = tenancy.set_member_role(
        session, tenant_id=ctx.tenant_id, actor=ctx.actor, auth_subject=body.auth_subject, email=body.email, role=body.role
    )
    user = session.get(User, membership.user_id)
    return MemberOut(user_id=membership.user_id, email=user.email if user else None, role=membership.role)  # type: ignore[arg-type]


class InviteIn(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: Literal["manager", "receiver", "bookkeeper"]


@router.post("/members/invite", status_code=201)
def invite_member(
    body: InviteIn,
    session: Session = DbSession,
    ctx: TenantContext = Depends(require_permission("members.manage")),
) -> dict[str, Any]:
    """
    Give an email access (owner only). For someone without an account, returns a one-time `invite_token` —
    shown once; the owner passes the link on. Without it nobody can sign up with that email.
    """
    token = accounts.invite(session, tenant_id=ctx.tenant_id, actor=ctx.actor, email=body.email, role=body.role)
    return {"email": accounts.normalize_email(body.email), "role": body.role, "has_account": token is None,
            "invite_token": token}
