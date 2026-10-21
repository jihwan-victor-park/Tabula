"""
Encryption at rest for provider tokens (spec 3.2: "token은 서버에서 암호화해 보관").

  TABULA_TOKEN_ENCRYPTION_KEY = a Fernet key. Generate one with
      python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  and keep it in your secret store / .env (never in git). Rotating it: set
  TABULA_TOKEN_ENCRYPTION_KEYS_OLD to the previous key(s), comma-separated,
  so existing tokens still decrypt; new writes use the current key.
"""

from __future__ import annotations

import os

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from clawbot.domain.errors import ValidationFailed


def _fernet() -> MultiFernet:
    current = os.getenv("TABULA_TOKEN_ENCRYPTION_KEY")
    if not current:
        raise ValidationFailed("TABULA_TOKEN_ENCRYPTION_KEY is not set; provider tokens cannot be stored")
    old = [k for k in os.getenv("TABULA_TOKEN_ENCRYPTION_KEYS_OLD", "").split(",") if k.strip()]
    try:
        return MultiFernet([Fernet(current.encode())] + [Fernet(k.strip().encode()) for k in old])
    except ValueError:
        raise ValidationFailed("TABULA_TOKEN_ENCRYPTION_KEY is not a valid Fernet key")


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        raise ValidationFailed("Stored token cannot be decrypted with the configured key(s)")
