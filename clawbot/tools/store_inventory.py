"""
Store inventory scraper — fetches a shop's website to extract its current product catalog.

Tries the main URL and common product-listing paths (/products, /shop, etc.).
Returns combined cleaned text for Claude to parse product names and categories from.
"""

from __future__ import annotations

import re

import httpx

from clawbot.schemas.trend import StoreInventoryResult

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Common product listing paths across Shopify, WooCommerce, and custom stores
_PRODUCT_PATHS = [
    "/products",
    "/shop",
    "/collections/all",
    "/catalog",
    "/store",
    "/all-products",
]

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s{2,}")
_MAX_CHARS_PER_PAGE = 6_000
_MAX_TOTAL_CHARS = 15_000


def _strip_html(html: str) -> str:
    """Remove tags, scripts, nav/footer noise, and collapse whitespace."""
    html = re.sub(
        r"<(script|style|nav|footer|header)[^>]*>.*?</(script|style|nav|footer|header)>",
        " ",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    text = _TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _fetch(client: httpx.Client, url: str) -> str | None:
    try:
        resp = client.get(url, timeout=15)
        if resp.status_code < 400:
            return resp.text
    except Exception:
        pass
    return None


def scrape_store_inventory(store_url: str) -> StoreInventoryResult:
    """
    Fetch a store's website and return cleaned text of its product catalog.

    Scrapes the main page plus the first successful product-listing path found.
    Claude parses the returned text to identify what products the store currently sells.

    Args:
        store_url: The store's website URL, e.g. 'https://pebblestoys.com'

    Returns:
        StoreInventoryResult with combined page text and metadata.
    """
    base = store_url.rstrip("/")
    pages_scraped: list[str] = []
    combined_text = ""

    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as client:
            # Always fetch main page
            html = _fetch(client, base)
            if html:
                pages_scraped.append(base)
                combined_text += f"--- {base} ---\n" + _strip_html(html)[:_MAX_CHARS_PER_PAGE]

            # Try product listing paths and use the first one that returns content
            for path in _PRODUCT_PATHS:
                url = base + path
                html = _fetch(client, url)
                if not html:
                    continue
                cleaned = _strip_html(html)
                # Skip if it's essentially the same page as main (redirect)
                if len(cleaned) > 500 and cleaned[:200] != combined_text[:200]:
                    pages_scraped.append(url)
                    combined_text += f"\n\n--- {url} ---\n" + cleaned[:_MAX_CHARS_PER_PAGE]
                    break

        if not pages_scraped:
            return StoreInventoryResult(
                store_url=store_url,
                pages_scraped=[],
                raw_text="",
                success=False,
                error="Could not fetch any pages from the store URL",
            )

        if len(combined_text) > _MAX_TOTAL_CHARS:
            combined_text = combined_text[:_MAX_TOTAL_CHARS] + "\n[... truncated ...]"

        return StoreInventoryResult(
            store_url=store_url,
            pages_scraped=pages_scraped,
            raw_text=combined_text,
            success=True,
        )

    except Exception as exc:
        return StoreInventoryResult(
            store_url=store_url,
            pages_scraped=[],
            raw_text="",
            success=False,
            error=str(exc),
        )
