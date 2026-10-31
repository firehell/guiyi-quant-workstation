"""Real advisory lock lifecycle against an explicitly isolated database."""
import pytest
from sqlalchemy.orm import Session
from app.market_data.catalog import MarketCatalog
from tests.alembic.conftest import isolated_postgres_engine  # noqa: F401

pytestmark = pytest.mark.isolated_postgresql


def test_release_makes_source_available_to_another_connection(isolated_postgres_engine, tmp_path):
    with Session(isolated_postgres_engine) as first, Session(isolated_postgres_engine) as second:
        a, b = MarketCatalog(first, tmp_path), MarketCatalog(second, tmp_path)
        held = a.acquire_maintenance_lock(caller='reference-history')
        assert held is not None
        try:
            assert b.acquire_maintenance_lock(caller='reference-forward') is None
        finally:
            held.release()
        held.release()  # Cleanup must be idempotent, including a pooled connection.
        available = b.acquire_maintenance_lock(caller='reference-forward')
        assert available is not None
        available.release()
