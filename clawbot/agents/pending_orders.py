"""
In-memory store for pending orders awaiting owner confirmation.

Keyed by recipient (phone number). Each entry holds the last order summary
so the agent can confirm or cancel when the owner replies YES/NO.
"""
from __future__ import annotations

from typing import Any

_store: dict[str, dict[str, Any]] = {}


def save(recipient: str, order: dict[str, Any]) -> None:
    _store[recipient] = order


def get(recipient: str) -> dict[str, Any] | None:
    return _store.get(recipient)


def clear(recipient: str) -> None:
    _store.pop(recipient, None)
