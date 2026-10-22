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

from fastapi import Depends, Header, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from clawbot.auth.auth0 import decode_token
from clawbot.domain import accounts, tenancy
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


DEV_ENVIRONMENTS = ("development", "test")
LOOPBACK_CLIENTS = ("127.0.0.1", "::1", "localhost", "testclient")
# A page on another site that resolves its own name to 127.0.0.1 (DNS rebinding) still sends its
# own Host; only requests addressed to a loopback name are accepted in dev mode.
LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "[::1]", "testserver")


def _host_name(host: str) -> str:
    """Host header without the port ("[::1]:8080" -> "[::1]", "localhost:5173" -> "localhost")."""
    return host[: host.index("]") + 1] if host.startswith("[") and "]" in host else host.split(":", 1)[0]


def auth_mode() -> str:
    """
    dev auth (a header names the user) is for a developer's own machine only:
    it needs TABULA_ENV=development|test explicitly, and requests must come from
    loopback (enforced in get_current_user), so exposing the port does not expose it.
    """
    mode = os.getenv("TABULA_AUTH_MODE", "auth0")
    if mode not in ("auth0", "password", "dev"):
        raise RuntimeError(f"Unknown TABULA_AUTH_MODE {mode!r} (auth0 | password | dev)")
    if mode == "dev" and os.getenv("TABULA_ENV") not in DEV_ENVIRONMENTS:
        raise RuntimeError("TABULA_AUTH_MODE=dev requires TABULA_ENV=development (or test)")
    return mode


SESSION_COOKIE = "tabula_session"
CLIENT_HEADER = "x-tabula-client"  # cookie-authenticated changes must carry it (a custom header forces a CORS preflight)


def get_current_user(
    request: Request,
    session: Session = DbSession,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    x_dev_user: str | None = Header(default=None),
) -> User:
    # 1. A signed-in browser (email + password account): works in every mode.
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        user = accounts.user_for_token(session, token)
        if user is not None:
            if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get(CLIENT_HEADER) != "web":
                raise HTTPException(status_code=403, detail="Missing client header")  # cross-site request forgery guard
            return user
        if not x_dev_user and credentials is None:
            raise HTTPException(status_code=401, detail="Your session has ended; sign in again")
    mode = auth_mode()
    if mode == "password":
        raise HTTPException(status_code=401, detail="Sign in required")
    # 2. Demo sign-in by email only (development, this computer only).
    if mode == "dev":
        client = request.client.host if request.client else None
        if client not in LOOPBACK_CLIENTS or _host_name(request.headers.get("host", "")) not in LOOPBACK_HOSTS or request.headers.get("x-forwarded-for"):
            raise HTTPException(status_code=403, detail="Dev sign-in only works from this computer")
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
