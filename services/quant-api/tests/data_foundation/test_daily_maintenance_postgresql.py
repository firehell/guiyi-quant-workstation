"""Daily maintenance against explicitly isolated PostgreSQL and temporary Parquet."""
from datetime import date

import pytest
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.historical_data_manager import UpdateRequest
from app.models import Contract, Exchange, Instrument
from tests.data_foundation.test_catalog_publication_postgresql import isolated_postgresql  # noqa: F401
from tests.data_foundation.test_daily_maintenance import daily_manager


@pytest.mark.isolated_postgresql
def test_daily_postgresql_publish_and_restart_readback(isolated_postgresql, tmp_path):  # noqa: F811
    Base.metadata.create_all(isolated_postgresql)
    with Session(isolated_postgresql) as db:
        db.add(Exchange(code="DCE", name="DCE"))
        db.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
        db.flush()
        db.add(Contract(
            contract_code="JM2509", instrument_symbol="jm", exchange_code="DCE",
            listed_date=date(2025, 1, 1), expired_date=date(2026, 1, 1), provider="rqdata",
        ))
        db.commit()
        manager = daily_manager.__wrapped__(db, tmp_path)
        events = []
        result = manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        ), observer=events.append)
        assert result.status == "passed"
        published = [item for item in events if item.phase == "publishing" and item.state == "completed"]
        assert published[-1].completed == result.applied
        with Session(isolated_postgresql) as reader:
            from app.market_data.catalog import MarketCatalog
            rows = MarketCatalog(reader, manager.store.root).product_partitions("jm")
            assert len(rows) == 42
            assert all(manager.store.read_catalog_partition(row) for row in rows)
        assert manager.update(UpdateRequest(
            ("jm",), None, date(2025, 3, 7), apply=True, mode="daily",
        )).status == "noop"
