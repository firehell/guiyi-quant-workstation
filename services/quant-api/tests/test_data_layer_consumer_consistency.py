from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import MarketDataFile
from app.services.market_data_reader import MarketDataReader
from app.services.market_workbench import get_market_bars


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _write_parquet(path, *, close_values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        [
            {
                "symbol": "jm",
                "contract": "jm.MAIN",
                "exchange": "DCE",
                "datetime": datetime(2026, 7, 1, 9, 5 + index * 5),
                "trading_day": datetime(2026, 7, 1).date(),
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 10 + index,
                "open_interest": 1000 + index,
                "turnover": 10000 + index,
                "period": "15m",
                "provider": "rqdata",
                "data_version": "rqdata_jm_15m_active_v2",
            }
            for index, close in enumerate(close_values)
        ]
    )
    frame.to_parquet(path, index=False)


def test_market_and_reader_share_active_data_version(tmp_path) -> None:
    active_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_15m_active.parquet"
    superseded_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=15m/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_15m_old.parquet"
    _write_parquet(active_path, close_values=[4010.0, 4020.0, 4030.0])
    _write_parquet(superseded_path, close_values=[3010.0, 3020.0])

    SessionLocal = _session_factory()
    with SessionLocal() as session:
        session.add_all(
            [
                MarketDataFile(
                    provider="rqdata",
                    data_type="bars",
                    instrument_symbol="jm",
                    contract_code="jm.MAIN",
                    period="15m",
                    start_time=datetime(2026, 7, 1, 9, 15, tzinfo=UTC),
                    end_time=datetime(2026, 7, 1, 9, 45, tzinfo=UTC),
                    file_path=str(active_path),
                    row_count=3,
                    data_version="rqdata_jm_15m_active_v2",
                    data_role="primary",
                    quality_status="passed",
                ),
                MarketDataFile(
                    provider="rqdata",
                    data_type="bars",
                    instrument_symbol="jm",
                    contract_code="jm.MAIN",
                    period="15m",
                    start_time=datetime(2026, 7, 1, 9, 15, tzinfo=UTC),
                    end_time=datetime(2026, 7, 1, 9, 30, tzinfo=UTC),
                    file_path=str(superseded_path),
                    row_count=2,
                    data_version="rqdata_jm_15m_old_v1",
                    data_role="superseded",
                    quality_status="passed",
                ),
            ]
        )
        session.commit()

        reader = MarketDataReader(session, project_root=tmp_path)
        reader_rows = reader.load_bars(
            symbol="jm",
            contract="jm.MAIN",
            period="15m",
            start=datetime(2026, 7, 1, 9, 0),
            end=datetime(2026, 7, 1, 10, 0),
            passed_only=True,
        )
        market = get_market_bars(
            session,
            symbol="jm",
            contract="jm.MAIN",
            period="15m",
            start=datetime(2026, 7, 1, 9, 0),
            end=datetime(2026, 7, 1, 10, 0),
            provider=None,
            data_role=None,
            limit=1000,
        )

    reader_versions = {row.get("data_version") for row in reader_rows}
    market_versions = {bar.get("data_version") for bar in market.bars}
    assert reader_versions == {"rqdata_jm_15m_active_v2"}
    assert market_versions == {"rqdata_jm_15m_active_v2"}
    assert all(bar["close"] >= 4010 for bar in market.bars)
