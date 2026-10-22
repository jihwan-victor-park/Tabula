from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, Header, Request, Response
from fastapi.responses import RedirectResponse
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, TenantContext, get_tenant_context, require_permission
from clawbot.connectors.square import config as square_config
from clawbot.connectors.square import service as square
from clawbot.connectors.square.webhooks import SIGNATURE_HEADER, verify_and_parse
from clawbot.domain import connector_events, outbox
from clawbot.domain.errors import ValidationFailed
from clawbot.persistence.db import transaction
from clawbot.persistence.models import ConnectorAccount, ConnectorLocationLink

router = APIRouter(tags=["connectors"])


def _account_view(session: Session, a: ConnectorAccount) -> dict[str, Any]:
    links = session.scalars(select(ConnectorLocationLink).where(ConnectorLocationLink.tenant_id == a.tenant_id,
                                                                ConnectorLocationLink.connector_account_id == a.id))
    return {
        "id": str(a.id), "provider": a.provider, "environment": a.environment, "merchant_id": a.external_merchant_id,
        "display_name": a.display_name, "status": a.status, "scopes": a.scopes,
        "capabilities": vars(square.CAPABILITIES), "token_expires_at": a.token_expires_at,
        "last_success_at": a.last_success_at, "last_error": a.last_error, "sync_state": a.sync_state,
        "locations": [{"external_location_id": l.external_location_id, "location_id": str(l.location_id)} for l in links],
    }


class LinkBody(BaseModel):
    external_location_id: str = Field(min_length=1, max_length=120)
    location_id: uuid.UUID


class SyncBody(BaseModel):
    kind: Literal["catalog", "inventory", "sales", "reconcile"]
    start: AwareDatetime | None = Field(default=None, description="sales: window start (default 90 days ago)")
    end: AwareDatetime | None = Field(default=None, description="sales: window end (default now)")


class AdoptBody(BaseModel):
    external_ids: list[str] = Field(min_length=1, max_length=500)


@router.get("/connectors")
def get_connectors(session: Session = DbSession, ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    return [_account_view(session, a) for a in square.list_accounts(session, tenant_id=ctx.tenant_id)]


@router.get("/connectors/square/status")
def get_square_status(ctx: TenantContext = Depends(get_tenant_context)) -> dict[str, Any]:
    """Can this server connect to Square right now, and if not, what is missing (setting names only)?"""
    try:
        cfg = square_config.load()
    except Exception as exc:  # noqa: BLE001 — a bad setting is reported, not raised
        return {"environment": None, "available": False, "missing": [str(exc)]}
    missing = [name for name, value in (("SQUARE_APPLICATION_ID", cfg.application_id),
                                        ("SQUARE_APPLICATION_SECRET", cfg.application_secret),
                                        ("SQUARE_REDIRECT_URL", cfg.redirect_url)) if not value]
    if not os.getenv("TABULA_TOKEN_ENCRYPTION_KEY"):
        missing.append("TABULA_TOKEN_ENCRYPTION_KEY")
    return {"environment": cfg.environment, "available": cfg.environment == "mock" or not missing,
            "missing": [] if cfg.environment == "mock" else missing, "demo": cfg.environment == "mock"}


OAUTH_COOKIE = "tabula_square_oauth"


@router.post("/connectors/square/authorize")
def post_authorize(response: Response, request: Request, session: Session = DbSession,
                   ctx: TenantContext = Depends(require_permission("connectors.manage"))) -> dict[str, str]:
    """
    Start OAuth: open `authorize_url` in this browser. An HttpOnly cookie binds the
    flow to this browser, so a forwarded link cannot connect someone else's account.
    """
    url, binding = square.start_authorization(session, tenant_id=ctx.tenant_id, actor=ctx.actor)
    response.set_cookie(OAUTH_COOKIE, binding, max_age=600, httponly=True, samesite="lax",
                        secure=request.url.scheme == "https", path="/v1/connectors/square")
    return {"authorize_url": url}


@router.get("/connectors/square/callback")
def get_callback(request: Request, state: str, code: str | None = None, error: str | None = None,
                 session: Session = DbSession) -> Any:
    """OAuth redirect target. Authenticated by the single-use `state` plus the starting browser's cookie."""
    # Consume the state first, in its own transaction: whatever happens next, it cannot be replayed.
    with transaction() as consume:
        claim = square.consume_state(consume, state=state, browser_binding=request.cookies.get(OAUTH_COOKIE))
    if error or not code:
        raise ValidationFailed(f"Square authorization was not completed ({error or 'no code'})")
    account = square.complete_authorization(session, claim=claim, code=code)
    if "text/html" in request.headers.get("accept", ""):
        # A person's browser coming back from Square: land on the Connections screen.
        ui = os.getenv("TABULA_UI_URL", "http://127.0.0.1:5173").rstrip("/")
        return RedirectResponse(f"{ui}/app/data/square?connected={account.id}", status_code=303)
    return _account_view(session, account)


@router.get("/connectors/{account_id}/external-locations")
def get_external_locations(account_id: uuid.UUID, session: Session = DbSession,
                           ctx: TenantContext = Depends(get_tenant_context)) -> list[dict[str, Any]]:
    return square.external_locations(square.get_account(session, tenant_id=ctx.tenant_id, account_id=account_id))


@router.post("/connectors/{account_id}/locations", status_code=201)
def post_link(account_id: uuid.UUID, body: LinkBody, session: Session = DbSession,
              ctx: TenantContext = Depends(require_permission("connectors.manage"))) -> dict[str, Any]:
    """Choose which Square location feeds which Tabula location (never summed automatically)."""
    square.link_location(session, tenant_id=ctx.tenant_id, actor=ctx.actor, account_id=account_id,
                         external_location_id=body.external_location_id, location_id=body.location_id)
    return _account_view(session, square.get_account(session, tenant_id=ctx.tenant_id, account_id=account_id))


@router.post("/connectors/{account_id}/sync", status_code=202)
def post_sync(account_id: uuid.UUID, body: SyncBody, session: Session = DbSession,
              ctx: TenantContext = Depends(require_permission("connectors.sync"))) -> dict[str, Any]:
    """Queue a sync job; the connector worker runs it. Re-running is safe (idempotent)."""
    square.get_account(session, tenant_id=ctx.tenant_id, account_id=account_id)
    payload: dict[str, Any] = {"account_id": str(account_id), "kind": body.kind}
    if body.kind in ("sales", "reconcile"):
        end = body.end or datetime.now(timezone.utc)
        start = body.start or end - (timedelta(days=90) if body.kind == "sales" else timedelta(days=3))
        if start >= end:
            raise ValidationFailed("start must be before end")
        payload.update(start=start.isoformat(), end=end.isoformat())
    # Every request is its own run (re-syncing a window after mapping items must really run);
    # the sync itself is idempotent, so repeats never duplicate data.
    key = f"square:{account_id}:{body.kind}:{uuid.uuid4()}"
    message = outbox.enqueue(session, tenant_id=ctx.tenant_id, topic="square.sync", operation_key=key,
                             payload=payload, retry_safe=True)
    return {"job_id": str(message.id), "status": message.status}


@router.post("/connectors/{account_id}/adopt-items", status_code=201)
def post_adopt(account_id: uuid.UUID, body: AdoptBody, session: Session = DbSession,
               ctx: TenantContext = Depends(require_permission("catalog.edit"))) -> dict[str, Any]:
    """Create Tabula items for chosen unmatched Square variations (a person's decision; mappings confirmed)."""
    ids = square.adopt_unmatched(session, tenant_id=ctx.tenant_id, actor=ctx.actor, account_id=account_id,
                                 external_ids=body.external_ids)
    return {"variant_ids": [str(i) for i in ids]}


@router.delete("/connectors/{account_id}")
def delete_connector(account_id: uuid.UUID, session: Session = DbSession,
                     ctx: TenantContext = Depends(require_permission("connectors.manage"))) -> dict[str, Any]:
    """Revoke Square access and delete stored tokens."""
    return _account_view(session, square.revoke(session, tenant_id=ctx.tenant_id, actor=ctx.actor, account_id=account_id))


@router.post("/connectors/square/webhook")
async def post_webhook(request: Request, signature: str | None = Header(default=None, alias=SIGNATURE_HEADER),
                       session: Session = DbSession) -> Response:
    """
    Square webhook. Verify signature → store raw event (dedupe by event_id) →
    queue processing → 200. Processing re-reads current state from Square.
    """
    cfg = square_config.load()
    body = await request.body()
    event = verify_and_parse(signature_key=cfg.webhook_signature_key, notification_url=cfg.webhook_url,
                             body=body, signature=signature)
    account = session.scalars(select(ConnectorAccount).where(
        ConnectorAccount.provider == "square", ConnectorAccount.environment == cfg.environment,
        ConnectorAccount.external_merchant_id == event.merchant_id)).one_or_none()
    if account is None or account.status != "active":
        return Response(status_code=200)  # not ours (any more); acknowledging stops Square retrying
    stored = connector_events.store_event(
        session, tenant_id=account.tenant_id, provider="square", external_event_id=event.event_id,
        event_type=event.event_type, payload={"merchant_id": event.merchant_id, "type": event.event_type,
                                              "created_at": event.created_at, "data": event.data},
    )
    if stored.is_new:
        outbox.enqueue(session, tenant_id=account.tenant_id, topic="square.event",
                       operation_key=f"square-event:{event.event_id}", retry_safe=True,
                       payload={"account_id": str(account.id), "connector_event_id": str(stored.event.id)})
    return Response(status_code=200)
