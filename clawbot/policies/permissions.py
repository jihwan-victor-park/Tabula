"""
Who may do what — the single permission table (spec 8, 16.4).

Every domain mutator receives an Actor and calls `authorize()`; the HTTP layer
uses the same table for early 403s. Agents and system workers are actors too,
so a tool call that bypasses HTTP still cannot confirm a mapping, approve a
supplier or verify an ordering address: those are decisions only a person in
the right role can make.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from clawbot.domain.errors import PermissionDenied

ActorKind = Literal["human", "agent", "system"]


@dataclass(frozen=True)
class Actor:
    kind: ActorKind
    user_id: uuid.UUID | None = None  # humans only
    role: str | None = None  # humans only: the membership role in this tenant
    name: str | None = None  # agents/systems: e.g. "onboarding-agent", "square-sync"

    def __post_init__(self) -> None:
        if self.kind == "human" and (self.user_id is None or self.role is None):
            raise ValueError("A human actor needs user_id and role")
        if self.kind != "human" and (self.user_id is not None or self.role is not None):
            raise ValueError("Agents and systems act without a user identity or role")

    @property
    def label(self) -> str:
        return f"{self.kind}:{self.name}" if self.kind != "human" else f"human:{self.role}"


def human(user_id: uuid.UUID, role: str) -> Actor:
    return Actor(kind="human", user_id=user_id, role=role)


def agent(name: str) -> Actor:
    return Actor(kind="agent", name=name)


def system(name: str) -> Actor:
    return Actor(kind="system", name=name)


# permission → (human roles allowed, agents allowed?, systems allowed?)
_PERMISSIONS: dict[str, tuple[frozenset[str], bool, bool]] = {
    "members.manage": (frozenset({"owner"}), False, False),
    "members.read": (frozenset({"owner", "manager"}), False, False),
    "location.edit": (frozenset({"owner", "manager"}), False, False),
    "catalog.edit": (frozenset({"owner", "manager"}), False, False),
    "mapping.propose": (frozenset({"owner", "manager"}), True, True),
    "mapping.decide": (frozenset({"owner", "manager"}), False, False),
    "supplier.edit": (frozenset({"owner", "manager"}), False, False),
    "supplier.approve": (frozenset({"owner", "manager"}), False, False),
    "supplier.verify_contact": (frozenset({"owner", "manager"}), False, False),
    "supplier_item.edit": (frozenset({"owner", "manager"}), False, False),
    "price.record": (frozenset({"owner", "manager", "bookkeeper"}), False, False),
    "inventory.move": (frozenset({"owner", "manager", "receiver"}), False, True),
    "audit.read": (frozenset({"owner", "manager", "bookkeeper"}), False, False),
    "inventory.snapshot": (frozenset({"owner", "manager", "receiver"}), False, True),
    "sales.record": (frozenset({"owner", "manager"}), False, True),
    "orders.record_external": (frozenset({"owner", "manager"}), False, True),
    # Imports: anyone handling the books may upload; agents may draft a column
    # mapping (spec 8, "schema 제안") but only a person confirms it.
    "import.upload": (frozenset({"owner", "manager", "bookkeeper"}), False, False),
    "import.draft_mapping": (frozenset({"owner", "manager", "bookkeeper"}), True, False),
    "import.confirm": (frozenset({"owner", "manager", "bookkeeper"}), False, False),
    # A scheduler (system) may compute plans; only people change the policy.
    "replenishment.run": (frozenset({"owner", "manager"}), False, True),
    "replenishment.policy": (frozenset({"owner", "manager"}), False, False),
    "connectors.manage": (frozenset({"owner", "manager"}), False, False),
    "connectors.sync": (frozenset({"owner", "manager"}), False, True),
}


def allowed_roles(permission: str) -> frozenset[str]:
    return _PERMISSIONS[permission][0]


def authorize(actor: Actor, permission: str) -> None:
    roles, agents_ok, systems_ok = _PERMISSIONS[permission]
    if actor.kind == "human":
        ok = actor.role in roles
    elif actor.kind == "agent":
        ok = agents_ok
    else:
        ok = systems_ok
    if not ok:
        raise PermissionDenied(f"{actor.label} may not {permission}")
