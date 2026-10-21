"""
Supplier contact gate (docs/SUPPLIER_CONTACT_POLICY.md).

Every outbound message to a supplier must pass `check_send()`. Conversational
agents never call it — only the PO send service does. In this development
phase `live` mode is refused outright, so nothing can reach a real supplier.

  TABULA_SUPPLIER_SEND_MODE = disabled (default) | capture | test_only | live
      capture   — the message is stored in Tabula (captured_messages) and delivered to no one
  TABULA_TEST_RECIPIENTS    = comma-separated addresses allowed in test_only
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from clawbot.domain.errors import PermissionDenied

SendMode = Literal["disabled", "capture", "test_only", "live"]
MOCK_RECIPIENT = "mock-supplier@tabula.test"
_TEST_DOMAINS = ("example.com", "example.org", "example.net")


@dataclass(frozen=True)
class SendDecision:
    mode: SendMode
    recipient: str
    is_test: bool
    delivers: bool = False  # True only if something would actually leave the machine


def outcome_verifiable(mode: str) -> bool:
    """
    Can Tabula prove from its own database whether a send it lost track of happened?
    Only for capture: the captured message and the job result commit in one
    transaction, so "no captured message" means nothing was sent. Any transport
    that hands the message to someone else (email, supplier API) cannot: a worker
    that dies after the hand-off leaves the outcome unknown — it may have arrived.
    """
    return mode == "capture"


def send_mode() -> SendMode:
    mode = os.getenv("TABULA_SUPPLIER_SEND_MODE", "disabled")
    if mode not in ("disabled", "capture", "test_only", "live"):
        raise PermissionDenied(f"Unknown TABULA_SUPPLIER_SEND_MODE: {mode!r}")
    return mode  # type: ignore[return-value]


def is_test_recipient(address: str) -> bool:
    address = address.strip().lower()
    allowed = {a.strip().lower() for a in os.getenv("TABULA_TEST_RECIPIENTS", "").split(",") if a.strip()}
    domain = address.rsplit("@", 1)[-1] if "@" in address else ""
    return (
        address == MOCK_RECIPIENT
        or address in allowed
        or domain in _TEST_DOMAINS
        or domain.endswith(".test")
    )


def check_send(recipient: str) -> SendDecision:
    """Raise PermissionDenied unless this send is allowed right now."""
    mode = send_mode()
    if mode == "disabled":
        raise PermissionDenied("Supplier sending is disabled (TABULA_SUPPLIER_SEND_MODE=disabled)")
    if mode == "capture":
        return SendDecision(mode, recipient, True, delivers=False)  # kept in Tabula, sent to no one
    if is_test_recipient(recipient):
        return SendDecision(mode, recipient, True, delivers=True)
    if mode == "test_only":
        raise PermissionDenied(f"{recipient} is not an allowed test recipient in test_only mode")
    # live: real suppliers. Refused until CP7 (verified recipient, owner approval of the
    # exact PO digest, spend limits, dedupe and audit) is implemented and reviewed.
    raise PermissionDenied("Live supplier sending is not enabled in this build")
