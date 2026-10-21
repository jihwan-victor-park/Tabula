"""
Tests run against a real PostgreSQL database (unique constraints, row locks and
SKIP LOCKED are the behaviour under test, so SQLite is not a substitute).

  TABULA_TEST_DATABASE_URL  default postgresql+psycopg://localhost/tabula_test

The schema is rebuilt from Alembic migrations once per session, and tables are
truncated before each test.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest

TEST_DB_URL = os.getenv("TABULA_TEST_DATABASE_URL", "postgresql+psycopg://localhost/tabula_test")
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["TABULA_AUTH_MODE"] = "dev"
os.environ.pop("TABULA_ENV", None)

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from clawbot.persistence import db  # noqa: E402
from clawbot.persistence.models import Base  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _schema() -> Iterator[None]:
    db.reset_engine()
    with db.get_engine().begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    cfg = Config("alembic.ini")
    cfg.attributes["database_url"] = TEST_DB_URL
    command.upgrade(cfg, "head")
    yield
    db.reset_engine()


@pytest.fixture(autouse=True)
def _clean_tables() -> None:
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with db.get_engine().begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} CASCADE"))


@pytest.fixture
def client() -> TestClient:
    from clawbot.api.app import create_app

    return TestClient(create_app())


class Api:
    """Thin helper: one dev user acting in one tenant."""

    def __init__(self, client: TestClient, user: str, tenant_id: str | None = None):
        self.client = client
        self.user = user
        self.tenant_id = tenant_id

    def headers(self, **extra: str) -> dict[str, str]:
        h = {"X-Dev-User": self.user, **extra}
        if self.tenant_id:
            h["X-Tenant-Id"] = self.tenant_id
        return h

    def get(self, path: str, **kw):
        return self.client.get(path, headers=self.headers(**kw.pop("headers", {})), **kw)

    def post(self, path: str, json=None, **kw):
        return self.client.post(path, json=json, headers=self.headers(**kw.pop("headers", {})), **kw)


def new_store(client: TestClient, user: str, name: str = "Store") -> Api:
    resp = client.post("/v1/tenants", json={"name": name}, headers={"X-Dev-User": user})
    assert resp.status_code == 201, resp.text
    return Api(client, user, resp.json()["tenant_id"])


def seed_variant_and_location(api: Api, sku: str = "FOOD-5LB") -> tuple[str, str]:
    loc = api.post("/v1/locations", {"name": "Main", "timezone": "America/New_York"})
    assert loc.status_code == 201, loc.text
    var = api.post("/v1/variants", {"sku": sku, "name": "Dog food 5lb bag"})
    assert var.status_code == 201, var.text
    return var.json()["id"], loc.json()["id"]


def idem() -> str:
    return f"test-{uuid.uuid4()}"


def add_member(owner: Api, user: str, role: str) -> Api:
    resp = owner.client.put(
        "/v1/members", json={"auth_subject": f"dev|{user}", "email": user, "role": role}, headers=owner.headers()
    )
    assert resp.status_code == 200, resp.text
    return Api(owner.client, user, owner.tenant_id)
