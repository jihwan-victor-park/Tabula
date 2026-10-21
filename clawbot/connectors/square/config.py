"""
Square connection settings — environment variables only (never chat, never git).

  SQUARE_ENVIRONMENT            sandbox | production | mock     (default: mock)
  SQUARE_APPLICATION_ID         Developer Dashboard → your app → Credentials
  SQUARE_APPLICATION_SECRET     Developer Dashboard → OAuth → Application secret
  SQUARE_REDIRECT_URL           must exactly match the OAuth redirect URL registered in the dashboard
  SQUARE_WEBHOOK_SIGNATURE_KEY  Developer Dashboard → Webhooks → subscription → Signature key
  SQUARE_WEBHOOK_URL            the notification URL exactly as registered (part of the signature)
  SQUARE_API_VERSION            pinned Square-Version header (default below; verify against the dashboard)
  TABULA_TOKEN_ENCRYPTION_KEY   Fernet key encrypting stored OAuth tokens (see clawbot/security/secrets.py)

Production is refused unless TABULA_ENV=production, so development can never
touch a real seller account by accident.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from clawbot.domain.errors import ValidationFailed

BASE_URLS = {
    "sandbox": "https://connect.squareupsandbox.com",
    "production": "https://connect.squareup.com",
    "mock": "https://square.mock",
}
DEFAULT_API_VERSION = "2024-10-17"
# Read-only scopes for CP4. INVENTORY_WRITE is requested only when receipts are posted to Square (CP8).
READ_SCOPES = ("MERCHANT_PROFILE_READ", "ITEMS_READ", "ORDERS_READ", "INVENTORY_READ")


@dataclass(frozen=True)
class SquareConfig:
    environment: str
    application_id: str | None
    application_secret: str | None
    redirect_url: str | None
    webhook_signature_key: str | None
    webhook_url: str | None
    api_version: str

    @property
    def base_url(self) -> str:
        return BASE_URLS[self.environment]

    def require_oauth(self) -> None:
        missing = [name for name, value in (
            ("SQUARE_APPLICATION_ID", self.application_id),
            ("SQUARE_APPLICATION_SECRET", self.application_secret),
            ("SQUARE_REDIRECT_URL", self.redirect_url),
        ) if not value]
        if missing and self.environment != "mock":
            raise ValidationFailed(f"Square OAuth is not configured; set {', '.join(missing)}")

    def __repr__(self) -> str:  # never print secrets
        return f"SquareConfig(environment={self.environment!r}, application_id={'set' if self.application_id else None})"


def load() -> SquareConfig:
    environment = os.getenv("SQUARE_ENVIRONMENT", "mock")
    if environment not in BASE_URLS:
        raise ValidationFailed(f"SQUARE_ENVIRONMENT must be one of {sorted(BASE_URLS)}")
    if environment == "production" and os.getenv("TABULA_ENV") != "production":
        raise ValidationFailed("SQUARE_ENVIRONMENT=production requires TABULA_ENV=production")
    return SquareConfig(
        environment=environment,
        application_id=os.getenv("SQUARE_APPLICATION_ID"),
        application_secret=os.getenv("SQUARE_APPLICATION_SECRET"),
        redirect_url=os.getenv("SQUARE_REDIRECT_URL"),
        webhook_signature_key=os.getenv("SQUARE_WEBHOOK_SIGNATURE_KEY"),
        webhook_url=os.getenv("SQUARE_WEBHOOK_URL"),
        api_version=os.getenv("SQUARE_API_VERSION", DEFAULT_API_VERSION),
    )
