"""
Square connection lifecycle and sync (spec 3.2).

- OAuth with a single-use state bound to the tenant and person; tokens encrypted at rest.
- The merchant picks which Square location feeds which Tabula location; that
  Tabula location's stock is then owned by Square (Tabula never double-writes it).
- Catalog sync only *proposes* item mappings; a person confirms them or adopts
  unmatched POS items as new variants (spec 6.1, 8).
- Sales and stock come in through the same domain services as imports, as the
  `square-sync` system actor: sales keyed by Square's own order/line UIDs
  (key_scheme provider_line), counts as snapshots.
- Webhooks are stored first; processing re-reads the current state from Square
  rather than trusting the event body or its order.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from clawbot.connectors.base import Capabilities
from clawbot.connectors.square import config as square_config
from clawbot.connectors.square import normalize
from clawbot.connectors.square.client import SquareClient, SquareError
from clawbot.connectors.square.mock import FakeSquare
from clawbot.domain import audit, catalog, inventory, sales, tenancy
from clawbot.domain.errors import DomainError, NotFound, PermissionDenied, StateConflict, ValidationFailed
from clawbot.domain.matching import resolve_item
from clawbot.persistence.models import ConnectorAccount, ConnectorEvent, ConnectorLocationLink, OAuthState
from clawbot.policies.permissions import Actor, authorize, system
from clawbot.security import secrets as token_crypto

PROVIDER = "square"
SYNC_ACTOR = system("square-sync")
STATE_TTL = timedelta(minutes=10)
CAPABILITIES = Capabilities(sales_read=True, inventory_read=True, catalog_read=True)  # writes: CP8

# Test/dev hook: an httpx transport replacing the network (mock mode uses an in-memory Square).
_transport: httpx.BaseTransport | None = None
_mock: FakeSquare | None = None


def use_transport(transport: httpx.BaseTransport | None) -> None:
    global _transport
    _transport = transport


def _transport_for(environment: str) -> httpx.BaseTransport | None:
    global _mock
    if _transport is not None:
        return _transport
    if environment == "mock":
        _mock = _mock or FakeSquare.demo()
        return _mock.transport()
    return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _oauth_http(cfg: square_config.SquareConfig) -> httpx.Client:
    return httpx.Client(base_url=cfg.base_url, timeout=20.0, transport=_transport_for(cfg.environment),
                        headers={"Square-Version": cfg.api_version, "Content-Type": "application/json"})


# ---------------------------------------------------------------------------
# OAuth
# ---------------------------------------------------------------------------


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def start_authorization(session: Session, *, tenant_id: uuid.UUID, actor: Actor) -> tuple[str, str]:
    """
    Return (Square consent URL, browser binding). The caller sets the binding as an
    HttpOnly cookie; the callback is accepted only from the browser holding it.
    The state is random, single-use, and expires in 10 minutes.
    """
    authorize(actor, "connectors.manage")
    cfg = square_config.load()
    cfg.require_oauth()
    state, binding = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session.add(OAuthState(state_hash=_sha(state), browser_binding_hash=_sha(binding), tenant_id=tenant_id,
                           user_id=actor.user_id, provider=PROVIDER, environment=cfg.environment,
                           expires_at=_now() + STATE_TTL))
    session.flush()
    query = {"client_id": cfg.application_id or "mock-app", "scope": " ".join(square_config.READ_SCOPES),
             "session": "false", "state": state}
    if cfg.redirect_url:
        query["redirect_uri"] = cfg.redirect_url
    return f"{cfg.base_url}/oauth2/authorize?{urlencode(query)}", binding


@dataclass(frozen=True)
class StateClaim:
    tenant_id: uuid.UUID
    user_id: uuid.UUID
    environment: str


def consume_state(session: Session, *, state: str, browser_binding: str | None) -> StateClaim:
    """
    Mark the OAuth state used. Call this in its own committed transaction, before
    talking to Square, so a failed code exchange can never make the state reusable.
    """
    cfg = square_config.load()
    row = session.get(OAuthState, _sha(state), with_for_update=True)
    if row is None or row.used_at is not None or row.expires_at < _now() or row.environment != cfg.environment:
        raise PermissionDenied("This Square authorization link is invalid or expired; start again")
    row.used_at = _now()  # consumed even if the browser check below fails
    session.flush()
    if not browser_binding or not secrets.compare_digest(_sha(browser_binding), row.browser_binding_hash):
        raise PermissionDenied("Finish connecting Square in the same browser that started it")
    return StateClaim(row.tenant_id, row.user_id, row.environment)


def complete_authorization(session: Session, *, claim: StateClaim, code: str) -> ConnectorAccount:
    """Handle the OAuth redirect for a consumed state: exchange the code and store the connection."""
    cfg = square_config.load()
    row = claim
    actor = tenancy.actor_for(session, tenant_id=row.tenant_id, user_id=row.user_id)
    authorize(actor, "connectors.manage")

    with _oauth_http(cfg) as http:
        resp = http.post("/oauth2/token", json={
            "client_id": cfg.application_id or "mock-app", "client_secret": cfg.application_secret or "mock-secret",
            "code": code, "grant_type": "authorization_code", **({"redirect_uri": cfg.redirect_url} if cfg.redirect_url else {}),
        })
    if resp.status_code != 200:
        raise PermissionDenied("Square did not accept the authorization code")
    token = resp.json()
    merchant_id = token["merchant_id"]
    client = SquareClient(cfg, token["access_token"], transport=_transport_for(cfg.environment))
    try:
        merchant = client.merchant()
    except SquareError as exc:
        raise ValidationFailed(f"Square rejected the new connection ({exc.category})")
    finally:
        client.close()

    account = session.scalars(select(ConnectorAccount).where(
        ConnectorAccount.provider == PROVIDER, ConnectorAccount.environment == cfg.environment,
        ConnectorAccount.external_merchant_id == merchant_id, ConnectorAccount.status != "revoked",
    ).with_for_update()).one_or_none()
    if account is not None and account.tenant_id != row.tenant_id:
        raise StateConflict("This Square account is already connected to another Tabula workspace")
    if account is None:
        account = ConnectorAccount(tenant_id=row.tenant_id, provider=PROVIDER, environment=cfg.environment,
                                   external_merchant_id=merchant_id, created_by_user_id=actor.user_id)
        session.add(account)
    account.display_name = merchant.get("business_name")
    account.status, account.last_error = "active", None
    account.scopes = list(square_config.READ_SCOPES)
    account.access_token_enc = token_crypto.encrypt(token["access_token"])
    account.refresh_token_enc = token_crypto.encrypt(token["refresh_token"]) if token.get("refresh_token") else None
    account.token_expires_at = (datetime.fromisoformat(token["expires_at"].replace("Z", "+00:00"))
                                if token.get("expires_at") else None)
    account.updated_at = _now()
    session.flush()
    audit.record(session, tenant_id=row.tenant_id, actor=actor, action="connector.connected", object_type="connector_account",
                 object_id=account.id, after={"provider": PROVIDER, "environment": cfg.environment,
                                              "merchant": merchant_id, "scopes": account.scopes})
    return account


def get_account(session: Session, *, tenant_id: uuid.UUID, account_id: uuid.UUID, for_update: bool = False) -> ConnectorAccount:
    stmt = select(ConnectorAccount).where(ConnectorAccount.tenant_id == tenant_id, ConnectorAccount.id == account_id)
    if for_update:
        stmt = stmt.with_for_update()
    account = session.scalars(stmt).one_or_none()
    if account is None:
        raise NotFound(f"Connection not found: {account_id}")
    return account


def list_accounts(session: Session, *, tenant_id: uuid.UUID) -> list[ConnectorAccount]:
    return list(session.scalars(select(ConnectorAccount).where(ConnectorAccount.tenant_id == tenant_id)
                                .order_by(ConnectorAccount.created_at)))


def mark_needs_reauth(session: Session, account: ConnectorAccount, why: str) -> None:
    """Square refused our token (revoked or expired): stop syncing until someone reconnects."""
    account.status, account.last_error, account.updated_at = "needs_reauth", why[:2000], _now()
    session.flush()


def client_for(account: ConnectorAccount) -> SquareClient:
    if account.status != "active" or not account.access_token_enc:
        raise StateConflict(f"Square connection is {account.status}; reconnect it")
    cfg = square_config.load()
    if cfg.environment != account.environment:
        raise StateConflict(f"Server is configured for Square {cfg.environment}, connection is {account.environment}")
    return SquareClient(cfg, token_crypto.decrypt(account.access_token_enc), transport=_transport_for(account.environment))


def revoke(session: Session, *, tenant_id: uuid.UUID, actor: Actor, account_id: uuid.UUID) -> ConnectorAccount:
    authorize(actor, "connectors.manage")
    account = get_account(session, tenant_id=tenant_id, account_id=account_id, for_update=True)
    cfg = square_config.load()
    if account.access_token_enc and account.status == "active":
        with _oauth_http(cfg) as http:
            http.post("/oauth2/revoke", json={"client_id": cfg.application_id or "mock-app",
                                              "access_token": token_crypto.decrypt(account.access_token_enc)},
                      headers={"Authorization": f"Client {cfg.application_secret or 'mock-secret'}"})
    account.status = "revoked"
    account.access_token_enc = account.refresh_token_enc = None
    account.updated_at = _now()
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="connector.revoked", object_type="connector_account",
                 object_id=account.id)
    return account


# ---------------------------------------------------------------------------
# Locations
# ---------------------------------------------------------------------------


def external_locations(account: ConnectorAccount) -> list[dict[str, Any]]:
    client = client_for(account)
    try:
        return [vars(normalize.location(raw)) for raw in client.locations()]
    finally:
        client.close()


def link_location(session: Session, *, tenant_id: uuid.UUID, actor: Actor, account_id: uuid.UUID,
                  external_location_id: str, location_id: uuid.UUID) -> ConnectorLocationLink:
    """One Square location feeds one Tabula location; that location's stock is then owned by Square."""
    authorize(actor, "connectors.manage")
    account = get_account(session, tenant_id=tenant_id, account_id=account_id)
    location = tenancy.get_location(session, tenant_id=tenant_id, location_id=location_id)
    if external_location_id not in {l["external_id"] for l in external_locations(account)}:
        raise ValidationFailed(f"Square location {external_location_id} is not in this account")
    if session.scalars(select(ConnectorLocationLink).where(ConnectorLocationLink.tenant_id == tenant_id,
                                                           ConnectorLocationLink.location_id == location_id)).first():
        raise StateConflict(f"{location.name} is already linked to a POS location")
    if location.inventory_write_owner not in ("tabula", "square"):
        raise StateConflict(f"{location.name}'s stock is owned by {location.inventory_write_owner}")
    before = location.inventory_write_owner
    location.inventory_write_owner = "square"
    link = ConnectorLocationLink(connector_account_id=account.id, external_location_id=external_location_id,
                                 tenant_id=tenant_id, location_id=location_id)
    session.add(link)
    session.flush()
    audit.record(session, tenant_id=tenant_id, actor=actor, action="connector.location_linked", object_type="location",
                 object_id=location_id, before={"inventory_write_owner": before},
                 after={"inventory_write_owner": "square", "square_location": external_location_id})
    return link


def _links(session: Session, account: ConnectorAccount) -> dict[str, uuid.UUID]:
    return {l.external_location_id: l.location_id for l in session.scalars(
        select(ConnectorLocationLink).where(ConnectorLocationLink.tenant_id == account.tenant_id,
                                            ConnectorLocationLink.connector_account_id == account.id))}


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


@dataclass
class SyncResult:
    kind: str
    counts: dict[str, int] = field(default_factory=dict)
    unmatched: list[dict[str, Any]] = field(default_factory=list)

    def add(self, key: str, n: int = 1) -> None:
        self.counts[key] = self.counts.get(key, 0) + n


def _variant_for(session: Session, account: ConnectorAccount, external_id: str | None):
    if not external_id:
        return None
    return resolve_item(session, tenant_id=account.tenant_id, source_system=PROVIDER,
                        source_account=account.external_merchant_id, external_id=external_id).variant_id


def _ignored(session: Session, account: ConnectorAccount, external_id: str | None) -> bool:
    """Custom-amount lines, and items a person marked 'not an inventory item' (rejected mapping)."""
    if not external_id:
        return True
    from clawbot.persistence.models import ExternalItemMapping

    return session.scalars(select(ExternalItemMapping.id).where(
        ExternalItemMapping.tenant_id == account.tenant_id, ExternalItemMapping.source_system == PROVIDER,
        ExternalItemMapping.source_account == account.external_merchant_id,
        ExternalItemMapping.external_id == external_id, ExternalItemMapping.status == "rejected")).first() is not None


def sync_catalog(session: Session, account: ConnectorAccount) -> SyncResult:
    """Propose mappings for Square variations that match a Tabula item by SKU or GTIN; report the rest."""
    authorize(SYNC_ACTOR, "connectors.sync")
    result = SyncResult("catalog")
    client = client_for(account)
    try:
        for item in client.catalog_items():
            for v in normalize.variants(item):
                match = resolve_item(session, tenant_id=account.tenant_id, source_system=PROVIDER,
                                     source_account=account.external_merchant_id, external_id=v.external_id,
                                     sku=v.sku, barcode=v.barcode)
                if match.method == "provider_id":
                    result.add("already_mapped")
                elif match.variant_id is not None and not match.conflicts:
                    catalog.propose_external_mapping(
                        session, tenant_id=account.tenant_id, actor=SYNC_ACTOR, source_system=PROVIDER,
                        source_account=account.external_merchant_id, external_id=v.external_id,
                        variant_id=match.variant_id, match_method=match.method, external_sku=v.sku,
                        external_barcode=v.barcode, external_name=v.name,
                    )
                    result.add("proposed")
                else:
                    result.add("unmatched")
                    result.unmatched.append({"external_id": v.external_id, "sku": v.sku, "barcode": v.barcode,
                                             "name": v.name, "conflicts": match.conflicts})
    finally:
        client.close()
    return result


def sync_sales(session: Session, account: ConnectorAccount, *, start: datetime, end: datetime) -> SyncResult:
    """Completed orders in [start, end) for linked locations → sales lines (idempotent per Square line UID)."""
    authorize(SYNC_ACTOR, "connectors.sync")
    result = SyncResult("sales")
    links = _links(session, account)
    if not links:
        return result
    client = client_for(account)
    try:
        for order in client.completed_orders(sorted(links), start, end):
            _record_order(session, account, order, links, result)
    finally:
        client.close()
    # Whole local days inside [start, end) are known-complete — but only if every line was recorded.
    # Lines for items nobody has mapped yet (or lines that failed) leave the window uncovered, so
    # their demand is never read as zero; re-sync the window once the items are mapped.
    if result.counts.get("unmapped_item") or result.counts.get("error"):
        state = dict(account.sync_state)
        state["incomplete_windows"] = sorted(set(state.get("incomplete_windows", [])) | {f"{start.isoformat()}/{end.isoformat()}"})
        account.sync_state = state
        return result
    for location_id in links.values():
        location = tenancy.get_location(session, tenant_id=account.tenant_id, location_id=location_id)
        days = _whole_days(start, end, location.timezone)
        if days:
            sales.record_coverage(session, tenant_id=account.tenant_id, actor=SYNC_ACTOR, location_id=location_id,
                                  source_system=PROVIDER, source_ref=f"square-sync:{start.isoformat()}/{end.isoformat()}",
                                  starts_on=days[0], ends_on=days[1])
    state = dict(account.sync_state)
    through = end.astimezone(timezone.utc).isoformat()  # one format so string order = time order
    state["sales_synced_through"] = max(state.get("sales_synced_through", ""), through)
    account.sync_state = state
    return result


def _whole_days(start: datetime, end: datetime, timezone_name: str):
    """First and last local dates fully inside [start, end), or None."""
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(timezone_name)
    s, e = start.astimezone(tz), end.astimezone(tz)
    first = s.date() if s.time() == datetime.min.time() else s.date() + timedelta(days=1)
    last = e.date() - timedelta(days=1)
    return (first, last) if first <= last else None


def _record_order(session: Session, account: ConnectorAccount, order: dict[str, Any], links: dict[str, uuid.UUID],
                  result: SyncResult) -> None:
    location_id = links.get(order.get("location_id"))
    if location_id is None:
        result.add("other_location")
        return
    for line in normalize.sale_lines(order):
        variant_id = _variant_for(session, account, line.external_variant_id)
        if variant_id is None:
            if _ignored(session, account, line.external_variant_id):
                result.add("ignored_item")
            else:
                result.add("unmapped_item")
                result.unmatched.append({"order_id": line.order_id, "external_id": line.external_variant_id})
            continue
        savepoint = session.begin_nested()
        try:
            recorded = sales.record_sales_line(
                session, tenant_id=account.tenant_id, actor=SYNC_ACTOR, variant_id=variant_id, location_id=location_id,
                source_system=PROVIDER, external_order_id=line.order_id, external_line_key=line.line_key,
                key_scheme="provider_line", sold_at=line.sold_at, quantity=line.quantity, line_type=line.line_type,
                unit_price=line.unit_price, currency=line.currency,
            )
            savepoint.commit()
            result.add(recorded.outcome)  # created | unchanged | conflict | other_path (already imported by CSV)
        except DomainError as exc:  # e.g. a weight item with 5 decimals: one line, not the whole sync
            savepoint.rollback()
            result.add("error")
            result.unmatched.append({"order_id": line.order_id, "error": str(exc)})


def sync_inventory(session: Session, account: ConnectorAccount, *, catalog_object_ids: list[str] | None = None,
                   external_location_ids: list[str] | None = None) -> SyncResult:
    """Current Square counts for linked locations → snapshots (one per Square calculated_at)."""
    authorize(SYNC_ACTOR, "connectors.sync")
    result = SyncResult("inventory")
    links = _links(session, account)
    wanted = sorted(set(external_location_ids or links) & set(links))
    if not wanted:
        return result
    client = client_for(account)
    try:
        for raw in client.inventory_counts(wanted, catalog_object_ids=catalog_object_ids):
            count = normalize.count(raw)
            if count is None:
                continue
            variant_id = _variant_for(session, account, count.external_variant_id)
            if variant_id is None:
                result.add("unmapped_item")
                continue
            _, is_new = inventory.record_snapshot(
                session, tenant_id=account.tenant_id, actor=SYNC_ACTOR, variant_id=variant_id,
                location_id=links[count.external_location_id], quantity=count.quantity, as_of=count.calculated_at,
                source_system=PROVIDER, source_ref=f"square:{count.calculated_at.isoformat()}",
            )
            result.add("recorded" if is_new else "unchanged")
    finally:
        client.close()
    return result


def handle_event(session: Session, account: ConnectorAccount, event: ConnectorEvent) -> SyncResult:
    """Re-read current state for whatever the event points at (never trust event bodies or order)."""
    data = event.payload.get("data", {})
    if event.event_type and event.event_type.startswith("inventory.count"):
        counts = data.get("object", {}).get("inventory_counts", [])
        ids = sorted({c["catalog_object_id"] for c in counts if c.get("catalog_object_id")}) or None
        locations = sorted({c["location_id"] for c in counts if c.get("location_id")}) or None
        return sync_inventory(session, account, catalog_object_ids=ids, external_location_ids=locations)
    if event.event_type == "oauth.authorization.revoked":
        account.status, account.access_token_enc, account.refresh_token_enc = "revoked", None, None
        account.updated_at = _now()
        session.flush()
        return SyncResult("revoked")
    if event.event_type and event.event_type.startswith("refund."):
        order_id = data.get("object", {}).get("refund", {}).get("order_id")
        data = {"id": order_id}
    if event.event_type and (event.event_type.startswith("order.") or event.event_type.startswith("refund.")):
        order_id = data.get("id")
        result = SyncResult("order")
        if order_id:
            client = client_for(account)
            try:
                _record_order(session, account, client.order(order_id), _links(session, account), result)
            finally:
                client.close()
        return result
    if event.event_type and event.event_type.startswith("catalog."):
        return sync_catalog(session, account)
    return SyncResult("ignored")


def adopt_unmatched(session: Session, *, tenant_id: uuid.UUID, actor: Actor, account_id: uuid.UUID,
                    external_ids: list[str]) -> list[uuid.UUID]:
    """A person creates Tabula items for chosen unmatched Square variations, with confirmed mappings."""
    authorize(actor, "catalog.edit")
    authorize(actor, "mapping.decide")
    account = get_account(session, tenant_id=tenant_id, account_id=account_id)
    wanted = set(external_ids)
    created: list[uuid.UUID] = []
    client = client_for(account)
    try:
        for item in client.catalog_items():
            for v in normalize.variants(item):
                if v.external_id not in wanted:
                    continue
                if not v.sku:
                    raise ValidationFailed(f"Square item {v.name!r} has no SKU; add one in Square first")
                variant = catalog.create_variant(session, tenant_id=tenant_id, actor=actor, sku=v.sku, name=v.name,
                                                 barcode=v.barcode)
                mapping = catalog.propose_external_mapping(
                    session, tenant_id=tenant_id, actor=actor, source_system=PROVIDER,
                    source_account=account.external_merchant_id, external_id=v.external_id, variant_id=variant.id,
                    match_method="manual", external_sku=v.sku, external_barcode=v.barcode, external_name=v.name)
                catalog.decide_external_mapping(session, tenant_id=tenant_id, actor=actor, mapping_id=mapping.id,
                                                decision="confirmed", expected_variant_id=variant.id)
                created.append(variant.id)
    finally:
        client.close()
    if len(created) != len(wanted):
        raise NotFound(f"{len(wanted) - len(created)} Square item(s) not found in the catalog")
    return created


def record_sync(session: Session, account: ConnectorAccount, error: str | None) -> None:
    if error is None:
        account.last_success_at, account.last_error = _now(), None
    else:
        account.last_error = error[:2000]
    account.updated_at = _now()
    session.flush()


__all__ = [
    "CAPABILITIES", "SquareError", "DomainError", "adopt_unmatched", "complete_authorization", "external_locations",
    "get_account", "handle_event", "link_location", "list_accounts", "revoke", "start_authorization", "sync_catalog",
    "sync_inventory", "sync_sales", "use_transport",
]
