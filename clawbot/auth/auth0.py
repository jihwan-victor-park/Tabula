"""Auth0 JWT validation for FastAPI endpoints."""

from __future__ import annotations

import os
import threading
import time

import httpx
from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_bearer = HTTPBearer()

# Signing keys rotate. Cache them for an hour, and refetch early when a token
# names a key we have not seen — but at most once a minute, so a flood of
# tokens with bogus `kid`s cannot hammer the JWKS endpoint.
JWKS_TTL_SECONDS = 3600
JWKS_MIN_REFRESH_SECONDS = 60

_jwks_lock = threading.Lock()
_jwks: dict | None = None
_jwks_fetched_at = 0.0


def _fetch_jwks(domain: str) -> dict:
    resp = httpx.get(f"https://{domain}/.well-known/jwks.json", timeout=10)
    resp.raise_for_status()
    return resp.json()


def _get_jwks(*, force: bool = False) -> dict:
    global _jwks, _jwks_fetched_at
    domain = os.getenv("AUTH0_DOMAIN", "")
    if not domain:
        raise HTTPException(status_code=500, detail="AUTH0_DOMAIN is not configured")
    with _jwks_lock:
        age = time.monotonic() - _jwks_fetched_at
        stale = _jwks is None or age > JWKS_TTL_SECONDS
        if stale or (force and age > JWKS_MIN_REFRESH_SECONDS):
            try:
                _jwks = _fetch_jwks(domain)
                _jwks_fetched_at = time.monotonic()
            except httpx.HTTPError:
                if _jwks is None:
                    raise HTTPException(status_code=503, detail="Cannot reach the identity provider")
                # Keep serving the last good keys; try again after the minimum interval.
                _jwks_fetched_at = time.monotonic() - JWKS_TTL_SECONDS + JWKS_MIN_REFRESH_SECONDS
        return _jwks


def reset_jwks_cache() -> None:
    global _jwks, _jwks_fetched_at
    with _jwks_lock:
        _jwks, _jwks_fetched_at = None, 0.0


def _get_signing_key(token: str) -> dict:
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
    for force in (False, True):
        for key in _get_jwks(force=force)["keys"]:
            if key.get("kid") == kid:
                return key
    raise HTTPException(status_code=401, detail="Unable to find matching signing key")


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    """FastAPI dependency — validates Auth0 JWT and returns the claims."""
    return decode_token(credentials.credentials)


def decode_token(token: str) -> dict:
    """Validate an Auth0 RS256 JWT against the tenant JWKS and return its claims."""
    domain = os.getenv("AUTH0_DOMAIN", "")
    audience = os.getenv("AUTH0_AUDIENCE", "")
    if not domain or not audience:
        raise HTTPException(status_code=500, detail="Auth0 is not configured")

    signing_key = _get_signing_key(token)
    try:
        return jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{domain}/",
        )
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
