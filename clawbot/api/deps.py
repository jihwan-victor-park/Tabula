"""
Request dependencies for the v1 API: DB session, authenticated user, tenant context.

Tenant selection: the client sends `X-Tenant-Id`; the server only trusts it after
finding a membership for the authenticated user. IDs supplied by clients or by
agent tool calls are never used to widen scope.

Auth modes (TABULA_AUTH_MODE):
  auth0 (default) — Bearer JWT validated by clawbot.auth.auth0
  dev             — `X-Dev-User: <subject>` header, local only; refused when
                    TABULA_ENV=production
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from clawbot.auth.auth0 import decode_token
from clawbot.domain import tenancy
from clawbot.persistence.db import new_session
from clawbot.persistence.models import User
from clawbot.policies.permissions import Actor, allowed_roles, human

_bearer = HTTPBearer(auto_error=False)


def get_session() -> Iterator[Session]:
    """One transaction per request: committed on success, rolled back on any error."""
    with new_session() as session, session.begin():
        yield session


# scope="function" commits before the response is sent, so a 2xx is never
# returned for a transaction that later fails to commit.
DbSession = Depends(get_session, scope="function")


def auth_mode() -> str:
    mode = os.getenv("TABULA_AUTH_MODE", "auth0")
    if mode == "dev" and os.getenv("TABULA_ENV") == "production":
        raise RuntimeError("TABULA_AUTH_MODE=dev is not allowed when TABULA_ENV=production")
    return mode


def get_current_user(
    session: Session = DbSession,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    x_dev_user: str | None = Header(default=None),
) -> User:
    if auth_mode() == "dev":
        if not x_dev_user:
            raise HTTPException(status_code=401, detail="X-Dev-User header required in dev auth mode")
        return tenancy.get_or_create_user(session, auth_subject=f"dev|{x_dev_user}", email=x_dev_user)

    if credentials is None:
        raise HTTPException(status_code=401, detail="Bearer token required")
    claims = decode_token(credentials.credentials)
    subject = claims.get("sub")
    if not subject:
        raise HTTPException(status_code=401, detail="Token has no subject")
    return tenancy.get_or_create_user(session, auth_subject=subject, email=claims.get("email"))


@dataclass(frozen=True)
class TenantContext:
    tenant_id: uuid.UUID
    user: User
    role: str

    @property
    def actor(self) -> Actor:
        return human(self.user.id, self.role)


def get_tenant_context(
    session: Session = DbSession,
    user: User = Depends(get_current_user),
    x_tenant_id: str = Header(...),
) -> TenantContext:
    try:
        tenant_id = uuid.UUID(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be a UUID")
    membership = tenancy.get_membership(session, tenant_id=tenant_id, user_id=user.id)
    if membership is None:
        raise HTTPException(status_code=403, detail="Not a member of this tenant")
    return TenantContext(tenant_id=tenant_id, user=user, role=membership.role)


def require_permission(permission: str) -> Callable[[TenantContext], TenantContext]:
    """Early 403 from the same table the domain enforces (clawbot.policies.permissions)."""
    roles = allowed_roles(permission)

    def check(ctx: TenantContext = Depends(get_tenant_context)) -> TenantContext:
        if ctx.role not in roles:
            raise HTTPException(status_code=403, detail=f"Role '{ctx.role}' may not {permission}")
        return ctx

    return check
