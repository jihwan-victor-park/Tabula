"""
Tabula product API — the single FastAPI application.

Run:  uvicorn clawbot.api.app:app --reload

The per-agent apps (price_routes, inventory_routes, ...) are legacy demos on
their own ports; new domain routes are added as routers under clawbot/api/v1.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

load_dotenv()

from clawbot.api import v1  # noqa: E402
from clawbot.api.deps import auth_mode  # noqa: E402
from clawbot.domain.errors import (  # noqa: E402
    DomainError,
    IdempotencyConflict,
    NotFound,
    PermissionDenied,
    StaleVersion,
    StateConflict,
    ValidationFailed,
)

_ERROR_STATUS: list[tuple[type[DomainError], int]] = [
    (NotFound, 404),
    (PermissionDenied, 403),
    (IdempotencyConflict, 409),
    (StaleVersion, 409),
    (StateConflict, 409),
    (ValidationFailed, 422),
]

# PostgreSQL SQLSTATE → (HTTP status, message)
_INTEGRITY_STATUS: dict[str | None, tuple[int, str]] = {
    "23505": (409, "Already exists"),  # unique_violation
    "23503": (422, "Refers to something that does not exist in this tenant"),  # foreign_key_violation
    "23514": (422, "Violates a data rule"),  # check_violation
    "23502": (422, "A required value is missing"),  # not_null_violation
}


def create_app() -> FastAPI:
    auth_mode()  # fail fast on an unsafe auth configuration

    app = FastAPI(title="Tabula API", version="0.1.0")
    origins = [o for o in os.getenv("TABULA_CORS_ORIGINS", "http://localhost:5173").split(",") if o]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    def _domain_error(_: Request, exc: DomainError) -> JSONResponse:
        status = next((code for cls, code in _ERROR_STATUS if isinstance(exc, cls)), 400)
        content: dict = {"detail": str(exc)}
        if exc.details:
            content["details"] = exc.details
        return JSONResponse(status_code=status, content=content)

    @app.exception_handler(IntegrityError)
    def _integrity_error(_: Request, exc: IntegrityError) -> JSONResponse:
        # Constraint backstops (concurrent duplicates, cross-tenant references) surface
        # as 4xx with the constraint name, never as a 500 with SQL in the body.
        sqlstate = getattr(exc.orig, "sqlstate", None)
        diag = getattr(exc.orig, "diag", None)
        constraint = getattr(diag, "constraint_name", None)
        status, detail = _INTEGRITY_STATUS.get(sqlstate, (409, "Conflicting data"))
        return JSONResponse(status_code=status, content={"detail": detail, "details": {"constraint": constraint}})

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(v1.router)
    return app


app = create_app()
