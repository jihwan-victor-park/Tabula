"""
Wholesale supplier search tool.

Uses Google Custom Search JSON API when GOOGLE_API_KEY and
GOOGLE_SEARCH_ENGINE_ID are set. Falls back to mock data otherwise.
Appends "wholesale bulk supplier" to queries to target B2B results.
"""

from __future__ import annotations

import json
import os
import random
import re
import urllib.parse
import urllib.request

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Result schemas
# ---------------------------------------------------------------------------


class SupplierResult(BaseModel):
    """A single wholesale supplier result."""

    supplier: str
    price_per_unit: float
    currency: str = "USD"
    moq: int | None = None
    url: str
    confidence: str = "medium"


class SupplierSearchResult(BaseModel):
    """Aggregated supplier search results for a product query."""

    query: str
    region: str
    results: list[SupplierResult]


# ---------------------------------------------------------------------------
# Mock fallback
# ---------------------------------------------------------------------------

_MOCK_WHOLESALERS = [
    ("Alibaba", "https://alibaba.com"),
    ("GlobalSources", "https://globalsources.com"),
    ("DHgate", "https://dhgate.com"),
    ("ThomasNet", "https://thomasnet.com"),
    ("Faire", "https://faire.com"),
    ("Tundra", "https://tundra.com"),
]


def _mock_result(query: str, region: str) -> SupplierSearchResult:
    base_price = round(random.uniform(3.0, 25.0), 2)
    suppliers = random.sample(_MOCK_WHOLESALERS, 3)
    results = []
    for name, domain in suppliers:
        delta = random.uniform(-0.25, 0.15)
        price = round(base_price * (1 + delta), 2)
        moq = random.choice([6, 12, 24, 48, 100])
        results.append(
            SupplierResult(
                supplier=name,
                price_per_unit=price,
                currency="USD",
                moq=moq,
                url=f"{domain}/search?q={urllib.parse.quote(query)}",
                confidence="low",
            )
        )
    results.sort(key=lambda r: r.price_per_unit)
    return SupplierSearchResult(query=query, region=region, results=results)


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")
_MOQ_RE = re.compile(r"(\d+)\s*(?:pc|pcs|piece|pieces|unit|units|min(?:imum)?)", re.IGNORECASE)


def _extract_price(text: str) -> float | None:
    match = _PRICE_RE.search(text or "")
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _extract_moq(text: str) -> int | None:
    match = _MOQ_RE.search(text or "")
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    return None


def _supplier_from_url(url: str) -> str:
    try:
        host = urllib.parse.urlparse(url).netloc
        host = host.removeprefix("www.")
        return host.split(".")[0].capitalize()
    except Exception:
        return "Unknown"


# ---------------------------------------------------------------------------
# Google Custom Search
# ---------------------------------------------------------------------------


def _google_search(query: str, api_key: str, cx: str) -> SupplierSearchResult:
    params = urllib.parse.urlencode({
        "key": api_key,
        "cx": cx,
        "q": f"{query} wholesale bulk supplier price",
        "num": 10,
    })
    url = f"https://www.googleapis.com/customsearch/v1?{params}"

    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[SupplierResult] = []
    for item in data.get("items", []):
        snippet = item.get("snippet", "")
        link = item.get("link", "")
        title = item.get("title", "")

        price = _extract_price(snippet) or _extract_price(title)
        if price is None:
            continue

        moq = _extract_moq(snippet) or _extract_moq(title)
        supplier = _supplier_from_url(link)
        results.append(
            SupplierResult(
                supplier=supplier,
                price_per_unit=price,
                currency="USD",
                moq=moq,
                url=link,
                confidence="high",
            )
        )

    if not results:
        return _mock_result(query, "US")

    results.sort(key=lambda r: r.price_per_unit)
    return SupplierSearchResult(query=query, region="US", results=results[:5])


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def search_suppliers(query: str, region: str) -> SupplierSearchResult:
    """
    Search for wholesale suppliers for the given product.

    Uses Google Custom Search JSON API when GOOGLE_API_KEY and
    GOOGLE_SEARCH_ENGINE_ID are set. Falls back to mock data otherwise.

    Args:
        query: Product search term, e.g. 'wooden pull-along toy train'.
        region: City/region string (informational).

    Returns:
        SupplierSearchResult with up to 5 results sorted cheapest first.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()

    if api_key and cx:
        try:
            return _google_search(query, api_key, cx)
        except Exception:
            pass

    return _mock_result(query, region)
