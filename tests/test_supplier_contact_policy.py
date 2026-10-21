"""CP1.14: supplier contact gate — nothing can reach a real supplier in this build."""

import pytest

from clawbot.domain.errors import PermissionDenied
from clawbot.policies.supplier_contact import MOCK_RECIPIENT, check_send


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("TABULA_SUPPLIER_SEND_MODE", raising=False)
    monkeypatch.delenv("TABULA_TEST_RECIPIENTS", raising=False)


def test_disabled_by_default():
    with pytest.raises(PermissionDenied, match="disabled"):
        check_send(MOCK_RECIPIENT)


def test_test_only_allows_mock_and_allow_listed_addresses(monkeypatch):
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "test_only")
    monkeypatch.setenv("TABULA_TEST_RECIPIENTS", "me+po@gmail.com")
    for ok in (MOCK_RECIPIENT, "orders@example.com", "rep@acme.test", "ME+PO@gmail.com"):
        assert check_send(ok).is_test
    with pytest.raises(PermissionDenied, match="not an allowed test recipient"):
        check_send("orders@phillipspet.com")


def test_live_mode_is_refused_for_real_suppliers(monkeypatch):
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "live")
    with pytest.raises(PermissionDenied, match="not enabled in this build"):
        check_send("orders@phillipspet.com")


def test_unknown_mode_fails_closed(monkeypatch):
    monkeypatch.setenv("TABULA_SUPPLIER_SEND_MODE", "yolo")
    with pytest.raises(PermissionDenied):
        check_send(MOCK_RECIPIENT)
