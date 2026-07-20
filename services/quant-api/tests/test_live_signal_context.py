from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataProfile,
    LiveAggregatedBar,
    MarketDataFile,
    ProfileActiveBinding,
    TradingCalendar,
)
from app.services.live_signal_context import (
    HistoricalLiveContextResolver,
    HistoricalLiveContextError,
    historical_context_hash,
    merge_historical_live_bars,
)
from app.services.rqdata_ingest.parquet import sha256_file


def _bar(timestamp: datetime, *, close: float, source: str) -> dict:
    return {
        "symbol": "jm",
        "contract": "JM2609",
        "period": "15m",
        "datetime": timestamp,
        "trading_day": date(2026, 7, 20),
        "open": close - 1,
        "high": close + 2,
        "low": close - 2,
        "close": close,
        "volume": 100,
        "context_source": source,
    }


def test_merge_keeps_historical_for_exact_duplicate_and_preserves_live_trigger() -> None:
    first = _bar(datetime(2026, 7, 20, 9, 15), close=1000, source="historical")
    duplicate = _bar(datetime(2026, 7, 20, 9, 30), close=1001, source="historical")
    live_duplicate = {**duplicate, "context_source": "live", "live_bar_id": 41, "revision": 2}

    result = merge_historical_live_bars(
        historical_bars=[first, duplicate],
        live_bars=[live_duplicate],
        actual_contract="JM2609",
        period="15m",
    )

    assert result.exact_duplicate_count == 1
    assert len(result.bars) == 2
    assert result.bars[-1]["context_source"] == "historical"
    assert result.live_trigger["live_bar_id"] == 41
    assert result.live_trigger["datetime"] == result.bars[-1]["datetime"]


def test_merge_fails_closed_for_same_key_ohlcv_conflict() -> None:
    historical = _bar(datetime(2026, 7, 20, 9, 30), close=1001, source="historical")
    live = {**historical, "close": 1002, "context_source": "live", "live_bar_id": 42}

    with pytest.raises(HistoricalLiveContextError, match="historical_live_bar_conflict"):
        merge_historical_live_bars(
            historical_bars=[historical],
            live_bars=[live],
            actual_contract="JM2609",
            period="15m",
        )


def test_merge_requires_latest_merged_key_to_be_live_trigger() -> None:
    live = _bar(datetime(2026, 7, 20, 9, 15), close=1000, source="live")
    later_historical = _bar(datetime(2026, 7, 20, 9, 30), close=1001, source="historical")

    with pytest.raises(HistoricalLiveContextError, match="live_trigger_not_latest_merged_bar"):
        merge_historical_live_bars(
            historical_bars=[later_historical],
            live_bars=[live],
            actual_contract="JM2609",
            period="15m",
        )


def test_historical_context_hash_is_stable_for_numeric_equivalence() -> None:
    timestamp = datetime(2026, 7, 18, 15, 0)
    integer_bar = _bar(timestamp, close=1001, source="historical")
    float_bar = {**integer_bar, "close": 1001.0, "volume": 100.0}

    assert historical_context_hash([integer_bar]) == historical_context_hash([float_bar])


def test_resolver_loads_passed_profile_context_and_latest_live_trading_day(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        market_file = _seed_historical_context(session, tmp_path, last_trading_day=date(2026, 7, 17))
        _seed_calendar(session)
        _seed_live_bar(session, datetime(2026, 7, 17, 15, 0), trading_day=date(2026, 7, 17), close=999)
        current = _seed_live_bar(session, datetime(2026, 7, 20, 9, 15), trading_day=date(2026, 7, 20), close=1003)
        session.commit()

        result = HistoricalLiveContextResolver(session, project_root=tmp_path).resolve(
            symbol="jm",
            actual_contract="JM2609",
            period="15m",
            profile_id="live_observation_v1",
            provider="rqdata",
            source_mode="live_1m_sequential_bucket",
            limit=100,
        )

    assert result.status == "ready"
    assert result.historical_context_file_id == market_file.id
    assert result.historical_context_max_trading_day == date(2026, 7, 17)
    assert result.previous_trading_day == date(2026, 7, 17)
    assert result.live_trigger["live_bar_id"] == current.id
    assert result.live_trigger["trading_day"] == date(2026, 7, 20)
    assert all(row["trading_day"] == date(2026, 7, 20) for row in result.live_bars)


def test_resolver_fail_closes_stale_historical_context(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        _seed_historical_context(session, tmp_path, last_trading_day=date(2026, 7, 16))
        _seed_calendar(session)
        _seed_live_bar(session, datetime(2026, 7, 20, 9, 15), trading_day=date(2026, 7, 20), close=1003)
        session.commit()

        with pytest.raises(HistoricalLiveContextError, match="historical_context_stale"):
            HistoricalLiveContextResolver(session, project_root=tmp_path).resolve(
                symbol="jm",
                actual_contract="JM2609",
                period="15m",
                profile_id="live_observation_v1",
                provider="rqdata",
                source_mode=None,
                limit=100,
            )


def test_resolver_fail_closes_missing_previous_trading_day(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        _seed_historical_context(session, tmp_path, last_trading_day=date(2026, 7, 17))
        session.add(TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 20), is_trading_day=True, provider="rqdata"))
        _seed_live_bar(session, datetime(2026, 7, 20, 9, 15), trading_day=date(2026, 7, 20), close=1003)
        session.commit()

        with pytest.raises(HistoricalLiveContextError, match="historical_context_calendar_missing"):
            HistoricalLiveContextResolver(session, project_root=tmp_path).resolve(
                symbol="jm",
                actual_contract="JM2609",
                period="15m",
                profile_id="live_observation_v1",
                provider="rqdata",
                source_mode=None,
                limit=100,
            )


def test_resolver_fail_closes_physical_checksum_drift(tmp_path: Path) -> None:
    factory = _session_factory()
    with factory() as session:
        market_file = _seed_historical_context(session, tmp_path, last_trading_day=date(2026, 7, 17))
        _seed_calendar(session)
        _seed_live_bar(session, datetime(2026, 7, 20, 9, 15), trading_day=date(2026, 7, 20), close=1003)
        session.commit()
        path = Path(market_file.file_path)
        frame = pd.read_parquet(path)
        frame.loc[0, "close"] = 9999
        frame.to_parquet(path, index=False)

        with pytest.raises(HistoricalLiveContextError, match="historical_context_file_drift"):
            HistoricalLiveContextResolver(session, project_root=tmp_path).resolve(
                symbol="jm",
                actual_contract="JM2609",
                period="15m",
                profile_id="live_observation_v1",
                provider="rqdata",
                source_mode=None,
                limit=100,
            )


def _session_factory():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_historical_context(session, tmp_path: Path, *, last_trading_day: date) -> MarketDataFile:
    rows = []
    start = datetime.combine(last_trading_day, datetime.min.time()).replace(hour=14, minute=30)
    for index in range(3):
        timestamp = start + timedelta(minutes=15 * index)
        rows.append(
            {
                **_bar(timestamp, close=1000 + index, source="historical"),
                "trading_day": last_trading_day,
                "exchange": "DCE",
                "open_interest": 1000,
                "turnover": 10000,
                "provider": "rqdata",
                "data_version": "actual-15m-v1",
                "source_interval": "1m",
            }
        )
    path = tmp_path / "canonical" / "jm2609_15m.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path, index=False)
    session.add(
        DataProfile(
            profile_id="live_observation_v1",
            label="Live observation",
            contract_roles=["actual_contract"],
            periods=["15m"],
            quality_policy="passed_only",
            provider="rqdata",
            is_active=True,
        )
    )
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="JM2609",
        period="15m",
        start_time=rows[0]["datetime"],
        end_time=rows[-1]["datetime"],
        file_path=str(path),
        row_count=len(rows),
        file_size_bytes=path.stat().st_size,
        checksum=sha256_file(path),
        data_version="actual-15m-v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    session.add(
        ProfileActiveBinding(
            profile_id="live_observation_v1",
            instrument_symbol="jm",
            contract_code="JM2609",
            contract_role="actual_contract",
            period="15m",
            data_version=market_file.data_version,
            market_data_file_id=market_file.id,
            binding_status="active",
        )
    )
    return market_file


def _seed_calendar(session) -> None:
    session.add_all(
        [
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 17), is_trading_day=True, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 18), is_trading_day=False, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 19), is_trading_day=False, provider="rqdata"),
            TradingCalendar(exchange_code="DCE", trade_date=date(2026, 7, 20), is_trading_day=True, provider="rqdata"),
        ]
    )


def _seed_live_bar(session, timestamp: datetime, *, trading_day: date, close: int) -> LiveAggregatedBar:
    row = LiveAggregatedBar(
        provider="rqdata",
        instrument_symbol="jm",
        contract_code="JM2609",
        exchange_code="DCE",
        period="15m",
        source_period="1m",
        source_mode="live_1m_sequential_bucket",
        bar_datetime=timestamp,
        trading_day=trading_day,
        source_start_datetime=timestamp - timedelta(minutes=14),
        source_end_datetime=timestamp,
        source_bar_count=15,
        expected_bar_count=15,
        open=close - 1,
        high=close + 2,
        low=close - 2,
        close=close,
        volume=100,
        open_interest=1000,
        turnover=10000,
        bar_status="confirmed",
        quality_status="passed",
        confirmed_at=timestamp + timedelta(seconds=2),
        revision=0,
    )
    session.add(row)
    session.flush()
    return row
