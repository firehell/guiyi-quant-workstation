"""Weekly audit real read-only transaction and shared lease on a guarded disposable DB."""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.weekly_audit import run_weekly_audit
from app.models import Contract, Exchange, Instrument
from tests.data_foundation.test_catalog_publication_postgresql import isolated_postgresql  # noqa: F401
from tests.data_foundation.test_daily_maintenance import daily_manager
from tests.data_foundation.test_weekly_audit import IDENTITY, NOW, _assert_full_audit_preserves_facts


@pytest.mark.isolated_postgresql
def test_weekly_real_postgresql_readonly_and_nonblocking_shared_lock(isolated_postgresql, tmp_path):  # noqa: F811
    Base.metadata.create_all(isolated_postgresql)
    with Session(isolated_postgresql) as db:
        db.add(Exchange(code="DCE", name="DCE"))
        db.add(Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True))
        db.flush()
        db.add(Contract(contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
                        listed_date=date(2025, 1, 1), expired_date=date(2026, 1, 1), provider="rqdata"))
        db.commit()
        manager = daily_manager.__wrapped__(db, tmp_path)
        with Session(isolated_postgresql) as other:
            lease = MarketCatalog(other, manager.store.root).acquire_maintenance_lock()
            assert lease is not None
            try:
                result = run_weekly_audit(manager, status_path=tmp_path / "busy.json", products=("jm",),
                                          identity=IDENTITY, now=lambda: NOW)
                assert result["status"] == "skipped_busy"
            finally:
                lease.release()
        audit = manager.audit
        def readonly_audit(*args, **kwargs):
            assert db.scalar(text("SHOW transaction_read_only")) == "on"
            assert db.scalar(text("SHOW transaction_isolation")) == "repeatable read"
            return audit(*args, **kwargs)
        manager.audit = readonly_audit
        _assert_full_audit_preserves_facts(manager, tmp_path / "weekly.json")
