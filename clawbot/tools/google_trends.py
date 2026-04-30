"""Google Trends tool — wraps pytrends with retry logic and a clean result shape."""

from __future__ import annotations

import time
from datetime import datetime, timedelta

from pytrends.request import TrendReq
from pytrends.exceptions import ResponseError

from clawbot.schemas.trend import (
    GoogleTrendPoint,
    GoogleTrendResult,
    TrendDirection,
)

# Map our lookback days to a pytrends timeframe string
_TIMEFRAME_MAP = {
    7: "now 7-d",
    30: "today 1-m",
    90: "today 3-m",
    180: "today 6-m",
    365: "today 12-m",
}


def _pick_timeframe(lookback_days: int) -> str:
    for days, label in sorted(_TIMEFRAME_MAP.items()):
        if lookback_days <= days:
            return label
    return "today 12-m"


def _geo_from_location(location: str) -> str:
    """Best-effort: extract US state abbreviation or return 'US'."""
    state_map = {
        "AL": "US-AL", "AK": "US-AK", "AZ": "US-AZ", "AR": "US-AR",
        "CA": "US-CA", "CO": "US-CO", "CT": "US-CT", "DE": "US-DE",
        "FL": "US-FL", "GA": "US-GA", "HI": "US-HI", "ID": "US-ID",
        "IL": "US-IL", "IN": "US-IN", "IA": "US-IA", "KS": "US-KS",
        "KY": "US-KY", "LA": "US-LA", "ME": "US-ME", "MD": "US-MD",
        "MA": "US-MA", "MI": "US-MI", "MN": "US-MN", "MS": "US-MS",
        "MO": "US-MO", "MT": "US-MT", "NE": "US-NE", "NV": "US-NV",
        "NH": "US-NH", "NJ": "US-NJ", "NM": "US-NM", "NY": "US-NY",
        "NC": "US-NC", "ND": "US-ND", "OH": "US-OH", "OK": "US-OK",
        "OR": "US-OR", "PA": "US-PA", "RI": "US-RI", "SC": "US-SC",
        "SD": "US-SD", "TN": "US-TN", "TX": "US-TX", "UT": "US-UT",
        "VT": "US-VT", "VA": "US-VA", "WA": "US-WA", "WV": "US-WV",
        "WI": "US-WI", "WY": "US-WY",
    }
    for abbr, geo in state_map.items():
        if f", {abbr}" in location.upper() or location.upper().endswith(abbr):
            return geo
    return "US"


def _infer_direction(change_pct: float) -> TrendDirection:
    if change_pct >= 10:
        return TrendDirection.trending
    if change_pct <= -10:
        return TrendDirection.fading
    return TrendDirection.stable


def get_google_trends(
    keyword: str,
    location: str,
    lookback_days: int = 90,
) -> GoogleTrendResult:
    """
    Fetch Google Trends interest-over-time data for a single keyword.

    Args:
        keyword: Search term to analyze (e.g. "power tools", "gardening gloves").
        location: Human-readable location, e.g. "Austin, TX".
        lookback_days: How many days of history to pull (7/30/90/180/365).

    Returns:
        GoogleTrendResult with direction label, change %, and raw data points.
    """
    geo = _geo_from_location(location)
    timeframe = _pick_timeframe(lookback_days)

    pytrends = TrendReq(hl="en-US", tz=360, retries=3, backoff_factor=0.5)

    for attempt in range(3):
        try:
            pytrends.build_payload([keyword], cat=0, timeframe=timeframe, geo=geo)
            df = pytrends.interest_over_time()
            break
        except ResponseError as exc:
            if attempt == 2:
                raise RuntimeError(
                    f"Google Trends request failed for '{keyword}': {exc}"
                ) from exc
            time.sleep(2 ** attempt)

    if df is None or df.empty or keyword not in df.columns:
        # Return a neutral result if no data
        return GoogleTrendResult(
            keyword=keyword,
            geo=geo,
            timeframe=timeframe,
            direction=TrendDirection.stable,
            peak_interest=0,
            current_interest=0,
            change_pct=0.0,
            data_points=[],
        )

    series = df[keyword].dropna()
    data_points = [
        GoogleTrendPoint(date=str(ts.date()), interest=int(val))
        for ts, val in series.items()
    ]

    peak = int(series.max())
    current = int(series.iloc[-1]) if len(series) else 0
    start = int(series.iloc[0]) if len(series) else 0
    change_pct = ((current - start) / max(start, 1)) * 100

    return GoogleTrendResult(
        keyword=keyword,
        geo=geo,
        timeframe=timeframe,
        direction=_infer_direction(change_pct),
        peak_interest=peak,
        current_interest=current,
        change_pct=round(change_pct, 1),
        data_points=data_points,
    )
