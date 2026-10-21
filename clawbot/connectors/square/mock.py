"""
An in-memory Square for tests and local development (SQUARE_ENVIRONMENT=mock).

Responds with Square-shaped JSON for the endpoints SquareClient uses, paginates
with small pages so cursor handling is always exercised, and can be told to
return 429/500 to test retries.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import httpx

PAGE_SIZE = 2


@dataclass
class FakeSquare:
    merchant_id: str = "MOCK_MERCHANT_1"
    access_token: str = "mock-access-token"
    locations: list[dict[str, Any]] = field(default_factory=list)
    items: list[dict[str, Any]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)
    counts: list[dict[str, Any]] = field(default_factory=list)
    fail_next: list[int] = field(default_factory=list)  # status codes to return before succeeding
    requests: list[tuple[str, str]] = field(default_factory=list)
    revoked: bool = False
    refresh_token: str = "mock-refresh-token"
    expires_at: str = "2099-01-01T00:00:00Z"
    refreshes: int = 0

    @classmethod
    def demo(cls) -> "FakeSquare":
        """A small pet store: one location, two items, a few orders and counts."""
        sq = cls()
        sq.locations = [{"id": "LOC_MAIN", "name": "Main St", "timezone": "America/New_York", "currency": "USD",
                         "status": "ACTIVE"}]
        sq.add_item("ITEM_LITTER", "Clumping cat litter", [("VAR_LITTER_20", "20lb", "LITTER-20", "036000291452")])
        sq.add_item("ITEM_FOOD", "Dog food", [("VAR_FOOD_5", "5lb", "FOOD-5", None)])
        return sq

    def add_item(self, item_id: str, name: str, variations: list[tuple[str, str, str | None, str | None]]) -> None:
        self.items.append({"type": "ITEM", "id": item_id, "item_data": {"name": name, "variations": [
            {"type": "ITEM_VARIATION", "id": vid, "item_variation_data": {"item_id": item_id, "name": vname,
                                                                          **({"sku": sku} if sku else {}),
                                                                          **({"upc": upc} if upc else {})}}
            for vid, vname, sku, upc in variations]}})

    def add_order(self, order_id: str, closed_at: str, lines: list[tuple[str, str, str, int]],
                  returns: list[tuple[str, str, str, int]] | None = None, location_id: str = "LOC_MAIN",
                  state: str = "COMPLETED") -> None:
        order = {"id": order_id, "location_id": location_id, "state": state, "closed_at": closed_at,
                 "line_items": [{"uid": uid, "catalog_object_id": vid, "quantity": qty,
                                 "base_price_money": {"amount": cents, "currency": "USD"}} for uid, vid, qty, cents in lines]}
        if returns:
            order["returns"] = [{"uid": "RET1", "return_line_items": [
                {"uid": uid, "catalog_object_id": vid, "quantity": qty, "base_price_money": {"amount": cents, "currency": "USD"}}
                for uid, vid, qty, cents in returns]}]
        self.orders = [o for o in self.orders if o["id"] != order_id] + [order]

    def set_count(self, variant_id: str, quantity: int | str, calculated_at: str, location_id: str = "LOC_MAIN") -> None:
        self.counts = [c for c in self.counts if not (c["catalog_object_id"] == variant_id and c["location_id"] == location_id)]
        self.counts.append({"catalog_object_id": variant_id, "catalog_object_type": "ITEM_VARIATION", "state": "IN_STOCK",
                            "location_id": location_id, "quantity": str(quantity), "calculated_at": calculated_at})

    # ------------------------------------------------------------------ transport

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    @staticmethod
    def _page(rows: list, cursor: str | None, key: str) -> dict[str, Any]:
        start = int(cursor or 0)
        page = rows[start:start + PAGE_SIZE]
        out: dict[str, Any] = {key: page}
        if start + PAGE_SIZE < len(rows):
            out["cursor"] = str(start + PAGE_SIZE)
        return out

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        self.requests.append((request.method, path))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"errors": [{"category": "RATE_LIMIT_ERROR", "code": "RATE_LIMITED"}]})
        if path == "/oauth2/token":
            body = json.loads(request.content)
            if body.get("grant_type") == "authorization_code" and body.get("code") != "mock-code":
                return httpx.Response(401, json={"errors": [{"category": "AUTHENTICATION_ERROR", "code": "UNAUTHORIZED"}]})
            if body.get("grant_type") == "refresh_token":
                if self.revoked or body.get("refresh_token") != self.refresh_token:
                    return httpx.Response(401, json={"errors": [{"category": "AUTHENTICATION_ERROR", "code": "UNAUTHORIZED"}]})
                self.refreshes += 1
                self.access_token = f"mock-access-token-{self.refreshes + 1}"
                self.refresh_token = f"mock-refresh-token-{self.refreshes + 1}"
                return httpx.Response(200, json={"access_token": self.access_token, "token_type": "bearer",
                                                 "expires_at": self.expires_at, "merchant_id": self.merchant_id,
                                                 "refresh_token": self.refresh_token})
            self.revoked = False
            return httpx.Response(200, json={"access_token": self.access_token, "token_type": "bearer",
                                             "expires_at": self.expires_at, "merchant_id": self.merchant_id,
                                             "refresh_token": self.refresh_token})
        if path == "/oauth2/revoke":
            self.revoked = True
            return httpx.Response(200, json={"success": True})
        if request.headers.get("Authorization") != f"Bearer {self.access_token}" or self.revoked:
            return httpx.Response(401, json={"errors": [{"category": "AUTHENTICATION_ERROR", "code": "UNAUTHORIZED"}]})
        if path == "/v2/merchants/me":
            return httpx.Response(200, json={"merchant": {"id": self.merchant_id, "business_name": "Mock Pets", "currency": "USD"}})
        if path == "/v2/locations":
            return httpx.Response(200, json={"locations": self.locations})
        if path == "/v2/catalog/list":
            return httpx.Response(200, json=self._page(self.items, request.url.params.get("cursor"), "objects"))
        if path == "/v2/orders/search":
            body = json.loads(request.content)
            window = body["query"]["filter"]["date_time_filter"]["closed_at"]
            start, end = (datetime.fromisoformat(window[k].replace("Z", "+00:00")) for k in ("start_at", "end_at"))
            rows = sorted(
                (o for o in self.orders if o["location_id"] in body["location_ids"] and o["state"] == "COMPLETED"
                 and start <= datetime.fromisoformat(o["closed_at"].replace("Z", "+00:00")) < end),
                key=lambda o: o["closed_at"],
            )
            return httpx.Response(200, json=self._page(rows, body.get("cursor"), "orders"))
        if path.startswith("/v2/orders/"):
            order = next((o for o in self.orders if o["id"] == path.rsplit("/", 1)[1]), None)
            if order is None:
                return httpx.Response(404, json={"errors": [{"category": "INVALID_REQUEST_ERROR", "code": "NOT_FOUND"}]})
            return httpx.Response(200, json={"order": order})
        if path == "/v2/inventory/counts/batch-retrieve":
            body = json.loads(request.content)
            rows = [c for c in self.counts if c["location_id"] in body["location_ids"]
                    and (not body.get("catalog_object_ids") or c["catalog_object_id"] in body["catalog_object_ids"])]
            return httpx.Response(200, json=self._page(rows, body.get("cursor"), "counts"))
        return httpx.Response(404, json={"errors": [{"category": "INVALID_REQUEST_ERROR", "code": "NOT_FOUND"}]})
