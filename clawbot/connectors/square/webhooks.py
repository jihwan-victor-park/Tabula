"""
Square webhook verification. Square signs `notification_url + raw_body` with the
subscription's signature key (HMAC-SHA256, base64) in `x-square-hmacsha256-signature`.
The URL must be exactly the one registered for the subscription.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any

from clawbot.domain.errors import PermissionDenied, ValidationFailed

SIGNATURE_HEADER = "x-square-hmacsha256-signature"


@dataclass(frozen=True)
class WebhookEvent:
    event_id: str
    event_type: str
    merchant_id: str
    created_at: str | None
    data: dict[str, Any]


def sign(signature_key: str, notification_url: str, body: bytes) -> str:
    digest = hmac.new(signature_key.encode(), notification_url.encode() + body, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def verify_and_parse(*, signature_key: str | None, notification_url: str | None, body: bytes,
                     signature: str | None) -> WebhookEvent:
    if not signature_key or not notification_url:
        raise PermissionDenied("Square webhooks are not configured")
    if not signature or not hmac.compare_digest(sign(signature_key, notification_url, body), signature):
        raise PermissionDenied("Invalid webhook signature")
    try:
        payload = json.loads(body)
        return WebhookEvent(payload["event_id"], payload["type"], payload["merchant_id"], payload.get("created_at"),
                            payload.get("data", {}))
    except (ValueError, KeyError):
        raise ValidationFailed("Malformed webhook payload")
