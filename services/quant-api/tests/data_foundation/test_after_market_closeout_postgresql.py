"""Disposable-only PostgreSQL closeout locking and committed-view verification."""

from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.models import Contract, Exchange, Instrument
from tests.data_foundation.test_catalog_publication_postgresql import isolated_postgresql  # noqa: F401
from tests.data_foundation.test_daily_maintenance import daily_manager
from tests.data_foundation.test_after_market_closeout import (
    close, closeout_case, test_real_partial_catalog_and_parquet_closeout_is_readonly as assert_partial,  # noqa: F401
)

pytestmark = pytest.mark.isolated_postgresql


def test_closeout_postgresql_busy_and_partial_readonly(isolated_postgresql, tmp_path, closeout_case):  # noqa: F811
    Base.metadata.create_all(isolated_postgresql)
    with Session(isolated_postgresql) as db:
        db.add(Exchange(code="DCE", name="DCE"))
        db.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        db.flush()
        db.add(Contract(contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2025, 1, 1), expired_date=date(2026, 1, 1), provider="rqdata"))
        db.commit()
        manager = daily_manager.__wrapped__(db, tmp_path)
        closeout_case["manager"] = manager
        with Session(isolated_postgresql) as other:
            lease = MarketCatalog(other, manager.store.root).acquire_maintenance_lock()
            assert lease is not None
            try:
                result = close(closeout_case, apply=True)
                assert result["status"] == "blocked" and result["status_written"] is False
                assert closeout_case["path"].read_bytes() == closeout_case["content"]
            finally:
                lease.release()
        audit = manager.audit
        def readonly_audit(*args, **kwargs):
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            return audit(*args, **kwargs)
        manager.audit = readonly_audit
        assert_partial(manager, closeout_case)
