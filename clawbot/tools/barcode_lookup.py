"""
Barcode lookup tool.

Primary:  UPC Item DB (upcitemdb.com) — no auth required, 100 req/day free.
Fallback: Go-UPC (go-upc.com)        — requires GO_UPC_API_KEY, 150 req/month free.
Final fallback: returns a minimal result using just the barcode.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from clawbot.schemas.inventory import BarcodeResult


# ---------------------------------------------------------------------------
# UPC Item DB (primary, no auth)
# ---------------------------------------------------------------------------


def _lookup_upcitemdb(barcode: str) -> BarcodeResult | None:
    """
    Query UPC Item DB for product info by barcode.
    Free tier: 100 requests/day, no API key needed.
    """
    url = f"https://api.upcitemdb.com/prod/trial/lookup?upc={urllib.parse.quote(barcode)}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "yhack-inventory/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        items = data.get("items", [])
        if not items:
            return None

        item = items[0]
        offers = item.get("offers", [])
        market_price = None
        if offers:
            try:
                market_price = float(offers[0].get("price", 0)) or None
            except (ValueError, TypeError):
                pass

        images = item.get("images", [])
        return BarcodeResult(
            barcode=barcode,
            name=item.get("title") or barcode,
            brand=item.get("brand") or None,
            category=item.get("category") or None,
            description=item.get("description") or None,
            image_url=images[0] if images else None,
            market_price=market_price,
            source="upcitemdb",
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Go-UPC (fallback, requires GO_UPC_API_KEY)
# ---------------------------------------------------------------------------


def _lookup_goupc(barcode: str, api_key: str) -> BarcodeResult | None:
    """
    Query Go-UPC for product info by barcode.
    Requires GO_UPC_API_KEY env var. 150 req/month free.
    """
    url = f"https://go-upc.com/api/v1/code/{urllib.parse.quote(barcode)}"
    try:
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "yhack-inventory/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        product = data.get("product", {})
        if not product:
            return None

        return BarcodeResult(
            barcode=barcode,
            name=product.get("name") or barcode,
            brand=product.get("brand") or None,
            category=product.get("category") or None,
            description=product.get("description") or None,
            image_url=product.get("imageUrl") or None,
            market_price=None,
            source="go-upc",
        )
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def lookup_barcode(barcode: str) -> BarcodeResult:
    """
    Look up product info for a barcode.

    Tries UPC Item DB first (no auth needed), falls back to Go-UPC
    if GO_UPC_API_KEY is set, then returns a minimal result with just
    the barcode if both fail.

    Args:
        barcode: UPC or EAN barcode string, e.g. '0673419376396' (LEGO set)

    Returns:
        BarcodeResult with product name, brand, category, image, and market price.
    """
    # Primary: UPC Item DB (no auth)
    result = _lookup_upcitemdb(barcode)
    if result:
        return result

    # Fallback: Go-UPC
    go_upc_key = os.getenv("GO_UPC_API_KEY", "").strip()
    if go_upc_key:
        result = _lookup_goupc(barcode, go_upc_key)
        if result:
            return result

    # Final fallback: return minimal result
    return BarcodeResult(
        barcode=barcode,
        name=f"Unknown Product ({barcode})",
        source="unknown",
    )
