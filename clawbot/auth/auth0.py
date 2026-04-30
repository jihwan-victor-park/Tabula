"""Auth0 JWT validation for FastAPI endpoints."""

from __future__ import annotations

import os
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

_bearer = HTTPBearer()


@lru_cache(maxsize=1)
def _get_jwks() -> dict:
    domain = os.getenv("AUTH0_DOMAIN", "")
    if not domain:
        raise HTTPException(status_code=500, detail="AUTH0_DOMAIN is not configured")
    url = f"https://{domain}/.well-known/jwks.json"
    resp = httpx.get(url, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _get_signing_key(token: str) -> str:
    from jose.utils import base64url_decode
    import json, base64

    jwks = _get_jwks()
    header = jwt.get_unverified_header(token)
    kid = header.get("kid")

    for key in jwks["keys"]:
        if key["kid"] == kid:
            return key

    raise HTTPException(status_code=401, detail="Unable to find matching signing key")


def verify_token(
    credentials: HTTPAuthorizationCredentials = Security(_bearer),
) -> dict:
    """FastAPI dependency — validates Auth0 JWT and returns the claims."""
    token = credentials.credentials
    domain = os.getenv("AUTH0_DOMAIN", "")
    audience = os.getenv("AUTH0_AUDIENCE", "")
    if not domain or not audience:
        raise HTTPException(status_code=500, detail="Auth0 is not configured")

    try:
        signing_key = _get_signing_key(token)
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=audience,
            issuer=f"https://{domain}/",
        )
        return payload
    except JWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid token: {exc}")
