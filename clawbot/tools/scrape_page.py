"""
Page scraping tool — uses Browserbase (cloud browser) for JS-rendered storefronts,
falls back to plain httpx for simple pages or when BROWSERBASE_API_KEY is not set.

Browserbase handles:
  - JS-rendered React/Vue/Shopify storefronts
  - Bot detection and CAPTCHAs
  - Dynamic price loading (AJAX, lazy hydration)

Fallback (httpx) handles:
  - Simple static HTML pages
  - Fast scrapes when full rendering isn't needed
"""

from __future__ import annotations

import os
import re

import httpx
from pydantic import BaseModel


class ScrapedPage(BaseModel):
    """Result of fetching and cleaning a product page."""

    url: str
    title: str
    text: str          # cleaned, tag-stripped page text (truncated to 12k chars)
    status_code: int
    success: bool
    via: str = "httpx"  # "browserbase" or "httpx"
    error: str | None = None


_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s{2,}")
_MAX_TEXT_CHARS = 12_000

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def _strip_html(html: str) -> str:
    html = re.sub(
        r"<(script|style)[^>]*>.*?</(script|style)>",
        " ", html, flags=re.DOTALL | re.IGNORECASE,
    )
    text = _TAG_RE.sub(" ", html)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _extract_title(html: str) -> str:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return _TAG_RE.sub("", match.group(1)).strip()
    return ""


def _truncate(text: str) -> str:
    if len(text) > _MAX_TEXT_CHARS:
        return text[:_MAX_TEXT_CHARS] + "\n[... truncated ...]"
    return text


# ---------------------------------------------------------------------------
# Browserbase scraper
# ---------------------------------------------------------------------------

def _get_project_id(bb) -> str:
    """Fetch the first available project ID from the account."""
    projects = bb.projects.list()
    if not projects:
        raise RuntimeError("No Browserbase projects found. Create one at browserbase.com.")
    return projects[0].id


def _scrape_via_browserbase(url: str) -> ScrapedPage:
    """
    Open the URL in a real Chromium browser hosted by Browserbase.
    Waits for the network to settle so JS-rendered prices are visible.
    """
    from browserbase import Browserbase
    from playwright.sync_api import sync_playwright

    api_key = os.getenv("BROWSERBASE_API_KEY", "")
    if not api_key:
        raise RuntimeError("BROWSERBASE_API_KEY is not set")
    bb = Browserbase(api_key=api_key)

    project_id = os.getenv("BROWSERBASE_PROJECT_ID") or _get_project_id(bb)
    session = bb.sessions.create(project_id=project_id)

    print(f"[Browserbase live view] https://www.browserbase.com/sessions/{session.id}", flush=True)

    # Fetch the embeddable debugger URL
    embed_url: str | None = None
    try:
        live_urls = bb.sessions.debug(session.id)
        embed_url = getattr(live_urls, "debugger_fullscreen_url", None) or getattr(live_urls, "debugger_url", None)
    except Exception:
        pass

    from clawbot.tools.session_state import set_session, mark_done
    set_session(session.id, session.connect_url, embed_url=embed_url)

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(session.connect_url)
        context = browser.contexts[0]
        page = context.pages[0]

        try:
            page.goto(url, wait_until="load", timeout=30_000)
            page.wait_for_timeout(1200)
            # Scroll slowly so the live view shows the agent "reading" the page
            page.evaluate("window.scrollTo({top: 400, behavior: 'smooth'})")
            page.wait_for_timeout(1800)
            page.evaluate("window.scrollTo({top: 900, behavior: 'smooth'})")
            page.wait_for_timeout(1800)
            page.evaluate("window.scrollTo({top: 1500, behavior: 'smooth'})")
            page.wait_for_timeout(1800)
            page.evaluate("window.scrollTo({top: 2200, behavior: 'smooth'})")
            page.wait_for_timeout(1800)
            page.evaluate("window.scrollTo({top: 1000, behavior: 'smooth'})")
            page.wait_for_timeout(1200)
            page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
            page.wait_for_timeout(1000)
            html = page.content()
            status = 200
        except Exception as exc:
            browser.close()
            mark_done()
            return ScrapedPage(
                url=url, title="", text="", status_code=0,
                success=False, via="browserbase", error=str(exc),
            )

        browser.close()
    mark_done()

    title = _extract_title(html)
    text = _truncate(_strip_html(html))

    return ScrapedPage(
        url=url, title=title, text=text,
        status_code=status, success=True, via="browserbase",
    )


# ---------------------------------------------------------------------------
# httpx fallback scraper
# ---------------------------------------------------------------------------

def _scrape_via_httpx(url: str) -> ScrapedPage:
    try:
        with httpx.Client(headers=_HEADERS, follow_redirects=True, timeout=20) as client:
            resp = client.get(url)
        html = resp.text
        title = _extract_title(html)
        text = _truncate(_strip_html(html))
        return ScrapedPage(
            url=url, title=title, text=text,
            status_code=resp.status_code,
            success=resp.status_code < 400,
            via="httpx",
        )
    except httpx.TimeoutException:
        return ScrapedPage(
            url=url, title="", text="", status_code=0,
            success=False, via="httpx", error="Request timed out after 20s",
        )
    except Exception as exc:
        return ScrapedPage(
            url=url, title="", text="", status_code=0,
            success=False, via="httpx", error=str(exc),
        )


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

def scrape_page(url: str) -> ScrapedPage:
    """
    Fetch a product or catalog page and return its cleaned text.

    Uses Browserbase (real Chromium) when BROWSERBASE_API_KEY is set —
    handles JS-rendered storefronts, bot detection, and dynamic pricing.
    Falls back to plain httpx for speed or when the key is absent.

    Args:
        url: Full URL to fetch, e.g. 'https://pebblestoys.com/products/bear'

    Returns:
        ScrapedPage with title, cleaned text, status, and which method was used.
    """
    if os.getenv("BROWSERBASE_API_KEY"):
        try:
            return _scrape_via_browserbase(url)
        except Exception as exc:
            result = _scrape_via_httpx(url)
            result.error = f"Browserbase failed ({exc}), used httpx fallback"
            return result

    return _scrape_via_httpx(url)
