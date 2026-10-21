"""
Minimal Square REST client for the read paths CP4 needs.

Endpoints and payload shapes follow Square's public API reference (Locations,
Catalog, Orders, Inventory, OAuth). They are exercised here against the mock
transport; confirm them against the Sandbox before relying on them (see
docs/SQUARE_SETUP.md). The access token is never logged or put in errors.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from datetime import datetime
from typing import Any

import httpx

from clawbot.connectors.square.config import SquareConfig

RETRY_STATUSES = {429, 500, 502, 503, 504}


class SquareError(Exception):
    def __init__(self, status: int, category: str, detail: str):
        super().__init__(f"Square API {status} {category}: {detail}")
        self.status, self.category = status, category


class SquareClient:
    def __init__(self, config: SquareConfig, access_token: str, *, transport: httpx.BaseTransport | None = None,
                 max_retries: int = 3, sleep=time.sleep):
        self._http = httpx.Client(
            base_url=config.base_url, timeout=httpx.Timeout(20.0, connect=5.0), transport=transport,
            headers={"Authorization": f"Bearer {access_token}", "Square-Version": config.api_version,
                     "Content-Type": "application/json"},
        )
        self._max_retries, self._sleep = max_retries, sleep

    def close(self) -> None:
        self._http.close()

    def _request(self, method: str, path: str, **kw) -> dict[str, Any]:
        for attempt in range(self._max_retries + 1):
            resp = self._http.request(method, path, **kw)
            if resp.status_code in RETRY_STATUSES and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After")
                self._sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2 ** attempt)
                continue
            if resp.status_code >= 400:
                try:
                    err = resp.json().get("errors", [{}])[0]
                except ValueError:
                    err = {}
                raise SquareError(resp.status_code, err.get("category", "HTTP_ERROR"), err.get("code", resp.reason_phrase))
            return resp.json() if resp.content else {}
        raise AssertionError("unreachable")

    # --- reads -----------------------------------------------------------

    def merchant(self) -> dict[str, Any]:
        return self._request("GET", "/v2/merchants/me")["merchant"]

    def locations(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v2/locations").get("locations", [])

    def catalog_items(self) -> Iterator[dict[str, Any]]:
        cursor = None
        while True:
            params = {"types": "ITEM", **({"cursor": cursor} if cursor else {})}
            data = self._request("GET", "/v2/catalog/list", params=params)
            yield from data.get("objects", [])
            cursor = data.get("cursor")
            if not cursor:
                return

    def completed_orders(self, location_ids: list[str], start: datetime, end: datetime) -> Iterator[dict[str, Any]]:
        cursor = None
        while True:
            body: dict[str, Any] = {
                "location_ids": location_ids, "limit": 500,
                "query": {
                    "filter": {"state_filter": {"states": ["COMPLETED"]},
                               "date_time_filter": {"closed_at": {"start_at": start.isoformat(), "end_at": end.isoformat()}}},
                    "sort": {"sort_field": "CLOSED_AT", "sort_order": "ASC"},
                },
            }
            if cursor:
                body["cursor"] = cursor
            data = self._request("POST", "/v2/orders/search", json=body)
            yield from data.get("orders", [])
            cursor = data.get("cursor")
            if not cursor:
                return

    def order(self, order_id: str) -> dict[str, Any]:
        return self._request("GET", f"/v2/orders/{order_id}")["order"]

    def inventory_counts(self, location_ids: list[str], updated_after: datetime | None = None,
                         catalog_object_ids: list[str] | None = None) -> Iterator[dict[str, Any]]:
        cursor = None
        while True:
            body: dict[str, Any] = {"location_ids": location_ids, "states": ["IN_STOCK"]}
            if updated_after:
                body["updated_after"] = updated_after.isoformat()
            if catalog_object_ids:
                body["catalog_object_ids"] = catalog_object_ids
            if cursor:
                body["cursor"] = cursor
            data = self._request("POST", "/v2/inventory/counts/batch-retrieve", json=body)
            yield from data.get("counts", [])
            cursor = data.get("cursor")
            if not cursor:
                return
