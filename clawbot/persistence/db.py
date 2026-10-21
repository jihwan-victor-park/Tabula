"""
PostgreSQL engine and session factory — the operational system of record.

Reads:
  DATABASE_URL — SQLAlchemy URL (default: postgresql+psycopg://localhost/tabula_dev)

MongoDB (clawbot/tools/mongodb.py) remains for legacy agents until their data
is migrated; new tenant-scoped state lives here.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://localhost/tabula_dev"

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def database_url() -> str:
    return os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)


def get_engine() -> Engine:
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(database_url(), pool_pre_ping=True)
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
    return _engine


def reset_engine() -> None:
    """Dispose the cached engine (tests switch DATABASE_URL between runs)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None


def new_session() -> Session:
    get_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


@contextmanager
def transaction() -> Iterator[Session]:
    """One unit of work: commits on success, rolls back on any exception."""
    with new_session() as session, session.begin():
        yield session
