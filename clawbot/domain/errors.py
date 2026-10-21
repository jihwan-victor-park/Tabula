from __future__ import annotations

from typing import Any


class DomainError(Exception):
    """Base class for business-rule failures the API maps to 4xx responses."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details


class NotFound(DomainError):
    """Object does not exist inside the caller's tenant (never reveals other tenants)."""


class IdempotencyConflict(DomainError):
    """The same idempotency key was reused with a different payload."""


class StaleVersion(DomainError):
    """The caller edited an older version of the object (optimistic concurrency)."""


class StateConflict(DomainError):
    """The object's current state does not allow this action."""


class PermissionDenied(DomainError):
    """The actor (person, agent or system) is not allowed to perform this action."""


class ValidationFailed(DomainError):
    pass
