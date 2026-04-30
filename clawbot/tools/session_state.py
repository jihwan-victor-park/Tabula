"""Simple in-memory store for the current Browserbase live session URL."""

from __future__ import annotations

import time

_current: dict = {}
_KEEP_ALIVE_SECS = 60  # keep session visible for 60s after scan ends


def set_session(session_id: str, url: str, embed_url: str | None = None) -> None:
    _current["session_id"] = session_id
    _current["url"] = url
    _current["live_view_url"] = f"https://www.browserbase.com/sessions/{session_id}"
    _current["embed_url"] = embed_url
    _current["active"] = True
    _current["expires_at"] = None


def mark_done() -> None:
    """Call when scan finishes — keeps URL visible for KEEP_ALIVE_SECS."""
    if _current:
        _current["active"] = False
        _current["expires_at"] = time.time() + _KEEP_ALIVE_SECS


def clear_session() -> None:
    _current.clear()


def get_session() -> dict | None:
    if not _current:
        return None
    expires_at = _current.get("expires_at")
    if expires_at and time.time() > expires_at:
        _current.clear()
        return None
    return dict(_current)
