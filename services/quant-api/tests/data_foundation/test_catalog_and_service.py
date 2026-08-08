from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.catalog import MarketCatalog
from app.market_data.domain import CanonicalBar, DatasetKey
from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
from app.models import Exchange, Instrument


def test_catalog_registers_minimal_month_partition(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all((Exchange(code="DCE", name="DCE"), Instrument(symbol="jm", name="JM", exchange_code="DCE", is_active=True)))
        session.commit()
        key = DatasetKey("continuous", "jm", "MAIN", "1d")
        bar = CanonicalBar(datetime(2025, 1, 2, 7, tzinfo=UTC), date(2025, 1, 2), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), Decimal("1"), None, None)
        store = CanonicalMonthlyStore(tmp_path)
        partition = store.publish(PublishRequest(key, 2025, 1, (bar,), (bar.bar_end,)))
        catalog = MarketCatalog(session, tmp_path)
        catalog.register_partition(partition)
        session.commit()

        row = catalog.all_partitions(key)[0]
        assert row.file_path == partition.parquet_path
        assert row.row_count == 1
        assert not hasattr(row, "manifest_path")
