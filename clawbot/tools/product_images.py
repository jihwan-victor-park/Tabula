"""Product image tool — Google Custom Search API."""

from __future__ import annotations

import os

import httpx

_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"


def get_product_image(product_name: str) -> str | None:
    """
    Fetch a product image URL via Google Custom Search.

    Returns the best image URL found, or None if unavailable.

    Args:
        product_name: Full product name, e.g. "DEWALT 20V MAX Cordless Drill DCD777C2"
    """
    api_key = os.getenv("GOOGLE_API_KEY", "").strip()
    cx = os.getenv("GOOGLE_SEARCH_ENGINE_ID", "").strip()

    if not api_key or not cx:
        return None

    try:
        with httpx.Client(timeout=8) as client:
            resp = client.get(_SEARCH_URL, params={
                "key": api_key,
                "cx": cx,
                "q": product_name,
                "searchType": "image",
                "num": 1,
                "imgType": "photo",
                "imgSize": "medium",
                "safe": "active",
            })
            resp.raise_for_status()
            items = resp.json().get("items", [])
            if items:
                return items[0].get("link")
    except Exception:
        pass

    return None
