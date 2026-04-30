"""
Live market-price search tool.

Uses Google Custom Search JSON API when GOOGLE_API_KEY and
GOOGLE_SEARCH_ENGINE_ID are set (free up to 100 queries/day).
Falls back to mock data if credentials are missing.
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


class PriceResult(BaseModel):
    """A single supplier result from a market-price search."""

    supplier: str
    price: float
    currency: str = "USD"
    url: str
    confidence: str = "medium"


class PriceSearchResult(BaseModel):
    """Aggregated market-price search results for a query."""

    query: str
    region: str
    results: list[PriceResult]


# ---------------------------------------------------------------------------
# Mock fallback
# ---------------------------------------------------------------------------

_MOCK_SUPPLIERS = [
    ("Alibaba", "https://www.alibaba.com/trade/search?SearchText={}"),
    ("DHgate", "https://www.dhgate.com/wholesale/search.do?searchkey={}"),
    ("Global Sources", "https://www.globalsources.com/manufacturers/{}"),
    ("Made-in-China", "https://www.made-in-china.com/products-search/{}"),
    ("Faire", "https://www.faire.com/search?q={}"),
]


def _mock_result(query: str, region: str) -> PriceSearchResult:
    """Return placeholder data when Google credentials are unavailable."""
    base_price = round(random.uniform(8.0, 40.0), 2)
    suppliers = random.sample(_MOCK_SUPPLIERS, 3)
    results = []
    for i, (name, url_tpl) in enumerate(suppliers):
        delta = random.uniform(-0.25, 0.10)
        price = round(base_price * (1 + delta), 2)
        results.append(
            PriceResult(
                supplier=name,
                price=price,
                currency="USD",
                url=url_tpl.format(urllib.parse.quote(query)),
                confidence="medium",
            )
        )
    results.sort(key=lambda r: r.price)
    return PriceSearchResult(query=query, region=region, results=results)


# ---------------------------------------------------------------------------
# Price extraction helpers
# ---------------------------------------------------------------------------

_PRICE_RE = re.compile(r"\$\s?([\d,]+(?:\.\d{1,2})?)")


def _extract_price(text: str) -> float | None:
    """Pull the first dollar-amount from a snippet string."""
    match = _PRICE_RE.search(text or "")
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            pass
    return None


def _supplier_from_url(url: str) -> str:
    """Extract a clean domain name to use as the supplier label."""
    try:
        host = urllib.parse.urlparse(url).netloc
        host = host.removeprefix("www.")
        return host.split(".")[0].capitalize()
    except Exception:
        return "Unknown"


# ---------------------------------------------------------------------------
# Google Custom Search
# ---------------------------------------------------------------------------


def _google_search(query: str, api_key: str, cx: str) -> PriceSearchResult:
    """
    Search Google Custom Search JSON API for the query and extract prices
    from the result snippets.

    Docs: https://developers.google.com/custom-search/v1/reference/rest/v1/cse/list
    """
    params = urllib.parse.urlencode({
        "key": api_key,
        "cx": cx,
        "q": f"{query} price buy",
        "num": 10,
    })
    url = f"https://www.googleapis.com/customsearch/v1?{params}"

    with urllib.request.urlopen(url, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    results: list[PriceResult] = []
    for item in data.get("items", []):
        snippet = item.get("snippet", "")
        link = item.get("link", "")
        title = item.get("title", "")

        price = _extract_price(snippet) or _extract_price(title)
        if price is None:
            continue

        supplier = _supplier_from_url(link)
        results.append(
            PriceResult(
                supplier=supplier,
                price=price,
                currency="USD",
                url=link,
                confidence="high",
            )
        )

    if not results:
        return _mock_result(query, "US")

    # Sort by price ascending so the agent sees the cheapest first
    results.sort(key=lambda r: r.price)
    return PriceSearchResult(query=query, region="US", results=results[:5])


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def search_market_prices(query: str, region: str) -> PriceSearchResult:
    """
    Search for market prices for the given product query.

    Uses Google Custom Search JSON API when GOOGLE_API_KEY and
    GOOGLE_SEARCH_ENGINE_ID are set. Falls back to mock data otherwise.

    Args:
        query: Product search term, e.g. 'Pebble Bear Plush 12in'.
        region: City/region string (informational; Google search is global).

    Returns:
        PriceSearchResult with up to 5 results sorted cheapest first.
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()

    if api_key and cx:
        try:
            return _google_search(query, api_key, cx)
        except Exception:
            pass

    return _mock_result(query, region)
