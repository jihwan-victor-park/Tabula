"""Local events tool — Ticketmaster API with graceful mock fallback."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import httpx

from clawbot.schemas.trend import LocalEvent, LocalEventsResult


_TICKETMASTER_BASE = "https://app.ticketmaster.com/discovery/v2/events.json"

# Map product categories to Ticketmaster segment/genre keywords that imply demand
_CATEGORY_EVENT_KEYWORDS: dict[str, list[str]] = {
    "gardening": ["garden show", "home expo", "flower show"],
    "power tools": ["home improvement expo", "maker faire", "construction expo"],
    "hardware": ["hardware expo", "home show", "maker faire"],
    "kitchen": ["food festival", "restaurant week", "culinary"],
    "sports": ["marathon", "triathlon", "sports expo", "athletic"],
    "automotive": ["car show", "auto expo", "motorsport"],
    "electronics": ["tech expo", "consumer electronics", "gaming convention"],
    "beauty": ["beauty expo", "wellness fair", "cosmetics"],
    "clothing": ["fashion show", "trade show"],
    "default": ["expo", "festival", "fair", "market"],
}


def _get_keywords(category: str) -> list[str]:
    lower = category.lower()
    for key, kws in _CATEGORY_EVENT_KEYWORDS.items():
        if key in lower or lower in key:
            return kws
    return _CATEGORY_EVENT_KEYWORDS["default"]


def _mock_events(location: str, category: str) -> LocalEventsResult:
    today = datetime.now(timezone.utc)
    return LocalEventsResult(
        location=location,
        events=[
            LocalEvent(
                name=f"Spring Home & Garden Expo",
                date=(today + timedelta(days=14)).strftime("%Y-%m-%d"),
                venue="Convention Center",
                category="Home & Garden",
                relevance_note=f"High foot-traffic event likely to drive {category} demand",
            ),
            LocalEvent(
                name="Local Makers Market",
                date=(today + timedelta(days=21)).strftime("%Y-%m-%d"),
                venue="Downtown Square",
                category="DIY / Craft",
                relevance_note="DIY projects drive ancillary hardware/tool purchases",
            ),
        ],
    )


def get_local_events(location: str, category: str, days_ahead: int = 60) -> LocalEventsResult:
    """
    Fetch upcoming local events near the business location.

    Uses the Ticketmaster Discovery API when TICKETMASTER_API_KEY is set,
    returning a broad sample of upcoming events so the agent can judge
    which are relevant to the given category.

    Args:
        location: City/region string, e.g. "Austin, TX".
        category: Product category — passed through for the agent's context.
        days_ahead: How many days into the future to search.

    Returns:
        LocalEventsResult with a list of nearby upcoming events.
    """
    api_key = os.getenv("TICKETMASTER_API_KEY", "").strip()

    if not api_key:
        return _mock_events(location, category)

    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)
    city = location.split(",")[0].strip()

    params = {
        "apikey": api_key,
        "city": city,
        "countryCode": "US",
        "startDateTime": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "endDateTime": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "size": 10,
        "sort": "date,asc",
    }

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(_TICKETMASTER_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()

        events: list[LocalEvent] = []
        for item in data.get("_embedded", {}).get("events", []):
            date_info = item.get("dates", {}).get("start", {})
            events.append(
                LocalEvent(
                    name=item.get("name", "Unknown Event"),
                    date=date_info.get("localDate", "TBD"),
                    venue=(
                        item.get("_embedded", {})
                        .get("venues", [{}])[0]
                        .get("name")
                    ),
                    category=(
                        item.get("classifications", [{}])[0]
                        .get("segment", {})
                        .get("name")
                    ),
                    relevance_note=None,
                )
            )

        if events:
            return LocalEventsResult(location=location, events=events)

    except Exception:
        pass

    return _mock_events(location, category)
