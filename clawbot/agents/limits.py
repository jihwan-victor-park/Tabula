"""
Bounds for agent tool loops (spec 4.2 #5, spec 8: tool call count, total timeout).

    for _ in agent_steps():
        response = client.messages.create(...)
        ...

Raises AgentBudgetExceeded instead of looping forever when a model keeps calling
tools, so a stuck run fails visibly and stops spending.
"""

from __future__ import annotations

import os
import time
from collections.abc import Iterator


class AgentBudgetExceeded(RuntimeError):
    pass


def agent_steps(max_steps: int | None = None, timeout_s: float | None = None) -> Iterator[int]:
    max_steps = max_steps or int(os.getenv("TABULA_AGENT_MAX_STEPS", "12"))
    timeout_s = timeout_s or float(os.getenv("TABULA_AGENT_TIMEOUT_S", "120"))
    started = time.monotonic()
    for step in range(max_steps):
        if time.monotonic() - started > timeout_s:
            raise AgentBudgetExceeded(f"Agent run exceeded {timeout_s:.0f}s")
        yield step
    raise AgentBudgetExceeded(f"Agent run exceeded {max_steps} tool steps")
