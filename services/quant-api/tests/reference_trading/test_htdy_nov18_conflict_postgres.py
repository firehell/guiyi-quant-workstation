"""The JD boundary uses the existing immutable PostgreSQL transaction contract."""

import pytest

from tests.reference_trading.test_htdy_conflict_postgres import pg_setup as _pg_setup
from tests.reference_trading.test_htdy_nov18_conflict_scope import configure, assert_atomic_interruption

pytestmark = pytest.mark.isolated_postgresql


@pytest.fixture
def pg_setup(request):
    yield from _pg_setup.__wrapped__(request)


@pytest.mark.parametrize("pg_setup", [["jd", "rb"]], indirect=True)
def test_jd_postgres_atomic_interruption_preserves_originals(pg_setup, monkeypatch):
    factory, recovery, _ = pg_setup
    factory, recovery, ids = configure(factory, recovery, monkeypatch)
    assert_atomic_interruption(factory, recovery, ids)
