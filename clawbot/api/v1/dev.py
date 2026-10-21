"""
Development conveniences (TABULA_AUTH_MODE=dev only — refused otherwise, and dev sign-in itself
only works from this computer). Creates the fictional demo workspace with its files already
imported, so trying the flow does not start with looking up dates in a script's output.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.orm import Session

from clawbot.api.deps import DbSession, auth_mode, get_current_user
from clawbot.persistence.models import User
from clawbot.policies import supplier_contact

router = APIRouter(prefix="/dev", tags=["development"])


def _dev_only() -> None:
    if auth_mode() != "dev":
        raise HTTPException(status_code=404, detail="Not found")


@router.get("/info", dependencies=[Depends(_dev_only)])
def info() -> dict[str, Any]:
    return {"environment": os.getenv("TABULA_ENV"), "auth_mode": "dev", "send_mode": supplier_contact.send_mode(),
            "square_environment": os.getenv("SQUARE_ENVIRONMENT", "mock")}


@router.post("/demo-workspace", status_code=201, dependencies=[Depends(_dev_only)])
def demo_workspace(user: User = Depends(get_current_user), session: Session = DbSession) -> dict[str, Any]:
    """A new 'Paws & Co (demo)' workspace owned by the signed-in user, with sales, a count and open orders imported."""
    email = user.email
    session.commit()  # the sign-in may have just created the user; the seed process must not wait on this transaction
    done = subprocess.run([sys.executable, "-m", "clawbot.devtools.seed_demo", "--import", "--owner", email],
                          capture_output=True, text=True, timeout=180, env=os.environ.copy())
    if done.returncode != 0:
        raise HTTPException(status_code=500, detail=f"Demo setup failed: {done.stderr[-500:]}")
    return {"output": done.stdout[-2000:]}
