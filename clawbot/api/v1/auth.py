"""Sign-up, sign-in and sign-out for email + password accounts (HttpOnly session cookie), and store setup."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import uuid
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from clawbot.api.deps import SESSION_COOKIE, DbSession, auth_mode, get_current_user
from clawbot.domain import accounts, audit, tenancy
from clawbot.domain.errors import PermissionDenied
from clawbot.domain.units import validate_currency
from clawbot.persistence.models import BUSINESS_TYPES, Tenant, User
from clawbot.policies.permissions import human

router = APIRouter(tags=["accounts"])


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class SignUp(Credentials):
    invite: str | None = Field(default=None, max_length=100, description="token from an invite link")


def _set_cookie(response: Response, request: Request, token: str) -> None:
    # Secure everywhere except a developer's http://127.0.0.1 (dev mode), unless explicitly turned off
    # (TABULA_COOKIE_SECURE=0) — a TLS proxy in front may make the request look like plain http.
    flag = os.getenv("TABULA_COOKIE_SECURE")
    secure = request.url.scheme == "https" or flag == "1" or (flag != "0" and auth_mode() != "dev")
    response.set_cookie(SESSION_COOKIE, token, max_age=int(accounts.SESSION_TTL.total_seconds()), httponly=True,
                        samesite="lax", secure=secure, path="/")


@router.post("/auth/signup", status_code=201)
def signup(body: SignUp, request: Request, response: Response, session: Session = DbSession) -> dict[str, Any]:
    user = accounts.sign_up(session, email=body.email, password=body.password, invite=body.invite)
    _set_cookie(response, request, accounts.start_session(session, user))
    return {"user_id": str(user.id), "email": user.email}


@router.post("/auth/login")
def login(body: Credentials, request: Request, response: Response, session: Session = DbSession) -> dict[str, Any]:
    try:
        user = accounts.sign_in(session, email=body.email, password=body.password)
    except PermissionDenied as exc:
        session.commit()  # keep the failed-attempt count even though the request fails
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_cookie(response, request, accounts.start_session(session, user))
    return {"user_id": str(user.id), "email": user.email}


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: Session = DbSession) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        accounts.end_session(session, token)
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.get("/auth/options")
def options() -> dict[str, Any]:
    """What the sign-in screen may offer: demo sign-in only on a developer's machine."""
    return {"password": True, "demo_sign_in": auth_mode() == "dev"}


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    business_type: Literal[BUSINESS_TYPES]  # type: ignore[valid-type]
    timezone: str = Field(min_length=3, max_length=64, examples=["America/New_York"])
    currency: str = Field(default="USD", min_length=3, max_length=3)
    location_name: str | None = Field(default=None, max_length=200)


@router.post("/stores", status_code=201)
def create_store(body: StoreCreate, session: Session = DbSession, user: User = Depends(get_current_user)) -> dict[str, Any]:
    """A new store: the business (owner = you) and its first location, in one step."""
    currency = validate_currency(body.currency)
    tenant = tenancy.create_tenant(session, name=body.name, owner=user)
    tenant.business_type, tenant.currency = body.business_type, currency
    location = tenancy.create_location(session, tenant_id=tenant.id, actor=human(user.id, "owner"),
                                       name=body.location_name or body.name, timezone=body.timezone)
    audit.record(session, tenant_id=tenant.id, actor=human(user.id, "owner"), action="tenant.settings_set",
                 object_type="tenant", object_id=tenant.id,
                 after={"business_type": body.business_type, "currency": currency, "timezone": body.timezone})
    return {"tenant_id": str(tenant.id), "tenant_name": tenant.name, "location_id": str(location.id)}


_sample_build = threading.Lock()  # one sample build at a time per API process; each takes a worker thread


@router.post("/sample-store", status_code=201)
def sample_store(session: Session = DbSession, user: User = Depends(get_current_user)) -> dict[str, Any]:
    """
    A fictional pet store to look around in (marked as a sample everywhere), one per account.

    Built by the demo seed in a separate process. That process talks to an in-process copy of the API with
    development sign-in; nothing of it is reachable from outside, and this endpoint never signs anyone in.
    Ownership passes to you only once the store is complete, so a failed build leaves you nothing half-made.
    """
    existing = next((t for _, t in tenancy.list_memberships(session, user_id=user.id) if t.is_sample), None)
    if existing is not None:
        return {"tenant_id": str(existing.id), "existing": True}
    subject, email = user.auth_subject, user.email or ""
    session.commit()  # the seed process must not wait on this request's transaction
    if not _sample_build.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="A sample store is being prepared — try again in a minute")
    try:
        env = {**os.environ, "TABULA_ENV": "development", "TABULA_AUTH_MODE": "dev"}  # only inside the child process
        done = subprocess.run([sys.executable, "-m", "clawbot.devtools.seed_demo", "--import", "--sample-for", subject,
                               "--owner", email or "owner@pawsandco.example"], capture_output=True, text=True,
                              timeout=180, env=env)
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=504, detail="The sample store took too long to prepare — try again") from exc
    finally:
        _sample_build.release()
    if done.returncode != 0:
        raise HTTPException(status_code=500, detail="The sample store could not be created")
    tenant_id = next((l.split("tenant", 1)[1].split()[0] for l in done.stdout.splitlines() if l.startswith("Workspace")), None)
    return {"tenant_id": tenant_id, "existing": False}
