from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.domain import DatasetKey
from app.market_data import infrastructure
from app.market_data.infrastructure import SHANGHAI, DatabaseCoverageSource, RQDataMarketAdapter
from app.models import Exchange, Instrument, TradingCalendar, TradingSession


def _session(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    for day in range(6, 11):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2025, 1, day),
                is_trading_day=True,
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9),
            end_time=time(9, 5),
            effective_from=date(2025, 1, 1),
            effective_to=None,
            crosses_midnight=False,
            is_active=True,
        )
    )
    session.commit()
    starts = tmp_path / "starts.csv"
    starts.write_text("product,window_start,note\njm,2025-01-06,test\n")
    return session, starts


def test_database_coverage_uses_actual_exchange_sessions_and_complete_iso_week(tmp_path) -> None:
    session, starts = _session(tmp_path)
    coverage = DatabaseCoverageSource(session, starts)
    minute_key = DatasetKey("continuous", "jm", "MAIN", "1m")
    five_key = DatasetKey("continuous", "jm", "MAIN", "5m")
    daily_key = DatasetKey("continuous", "jm", "MAIN", "1d")
    weekly_key = DatasetKey("continuous", "jm", "MAIN", "1w")

    minute_ends = coverage.expected_bar_ends(
        minute_key, 2025, 1, date(2025, 1, 6), date(2025, 1, 10)
    )
    five_ends = coverage.expected_bar_ends(
        five_key, 2025, 1, date(2025, 1, 6), date(2025, 1, 10)
    )
    daily_ends = coverage.expected_bar_ends(
        daily_key, 2025, 1, date(2025, 1, 6), date(2025, 1, 10)
    )
    weekly_ends = coverage.expected_bar_ends(
        weekly_key, 2025, 1, date(2025, 1, 6), date(2025, 1, 10)
    )

    assert len(minute_ends) == 25
    assert len(five_ends) == 5
    assert len(daily_ends) == 5
    assert weekly_ends == (daily_ends[-1],)
    assert coverage.valid_boundary(minute_key, _bar(minute_ends[0], date(2025, 1, 6)))
    session.close()


def test_latest_complete_day_excludes_open_session_and_accepts_closed_session(tmp_path) -> None:
    session, starts = _session(tmp_path)
    midday = DatabaseCoverageSource(
        session,
        starts,
        now=lambda: datetime(2025, 1, 10, 9, 3, tzinfo=SHANGHAI),
    )
    after_close = DatabaseCoverageSource(
        session,
        starts,
        now=lambda: datetime(2025, 1, 10, 9, 6, tzinfo=SHANGHAI),
    )

    assert midday.latest_complete_day(("jm",)) == date(2025, 1, 9)
    assert after_close.latest_complete_day(("jm",)) == date(2025, 1, 10)
    session.close()


def test_metadata_complete_returns_false_before_candidate_metadata_bootstrap(tmp_path) -> None:
    session, starts = _session(tmp_path)
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == "jm"))
    assert instrument is not None
    instrument.is_active = False
    session.commit()

    coverage = DatabaseCoverageSource(session, starts)

    assert coverage.metadata_complete(("jm",), date(2025, 1, 10)) is False
    session.close()


def test_database_coverage_selects_only_session_regime_effective_on_trading_day(
    tmp_path,
) -> None:
    session, starts = _session(tmp_path)
    current = session.scalar(
        select(TradingSession).where(TradingSession.instrument_symbol == "jm")
    )
    assert current is not None
    current.effective_to = date(2025, 1, 7)
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9),
            end_time=time(9, 3),
            effective_from=date(2025, 1, 8),
            effective_to=None,
            crosses_midnight=False,
            is_active=True,
        )
    )
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)
    key = DatasetKey("continuous", "jm", "MAIN", "1m")

    assert len(
        coverage.expected_bar_ends(key, 2025, 1, date(2025, 1, 7), date(2025, 1, 7))
    ) == 5
    assert len(
        coverage.expected_bar_ends(key, 2025, 1, date(2025, 1, 8), date(2025, 1, 8))
    ) == 3
    session.close()


class FakeClient:
    version = "test"

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls = []

    def price(self, order_book_id, start, end, frequency):
        self.calls.append((order_book_id, start, end, frequency))
        return self.frame


def _bar(end: datetime, trading_day: date):
    from app.market_data.domain import CanonicalBar

    return CanonicalBar(end, trading_day, 1, 1, 1, 1, 1, 1, 1)


def test_rqdata_bar_adapter_normalizes_continuous_and_daily_bar_end(tmp_path) -> None:
    session, starts = _session(tmp_path)
    expected = datetime(2025, 1, 6, 1, 5, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "datetime": datetime(2025, 1, 6),
                "trading_date": date(2025, 1, 6),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
                "total_turnover": 1000,
                "open_interest": 20,
            }
        ]
    )
    client = FakeClient(frame)
    adapter = RQDataMarketAdapter(session=session, client=client)
    key = DatasetKey("continuous", "jm", "MAIN", "1d")

    batch = adapter.fetch(key, (expected,))

    assert client.calls[0][0] == "JM88"
    assert batch.bars[0].bar_end == expected
    assert batch.bars[0].turnover == Decimal("1000")
    assert len(batch.source_digest) == 64
    session.close()


def test_rqdata_adapter_does_not_initialize_client_until_provider_read(
    tmp_path, monkeypatch
) -> None:
    session, _starts = _session(tmp_path)
    calls: list[str] = []

    class LazyClient:
        def __init__(self) -> None:
            calls.append("init")

    monkeypatch.setattr(infrastructure, "_RqdatacClient", LazyClient)
    adapter = RQDataMarketAdapter(session=session)

    assert calls == []
    assert isinstance(adapter.client, LazyClient)
    assert calls == ["init"]
    session.close()


def test_rqdatac_client_requests_unadjusted_bars() -> None:
    calls = []

    class Api:
        def get_price(self, order_book_id, **kwargs):
            calls.append((order_book_id, kwargs))
            return pd.DataFrame()

    client = object.__new__(infrastructure._RqdatacClient)
    client.api = Api()

    client.price("JM88", date(2025, 1, 2), date(2025, 1, 3), "1m")

    assert calls[0][1]["adjust_type"] == "none"


def test_rqdata_zero_date_sentinel_normalizes_to_none() -> None:
    assert infrastructure._optional_date("0000-00-00") is None


def test_rqdata_contract_specs_extract_tick_size_from_series() -> None:
    class FuturesApi:
        def get_trading_parameters(self, order_book_id, start_date, end_date):
            return pd.DataFrame()

    class Api:
        futures = FuturesApi()

        def get_tick_size(self, order_book_id):
            return pd.Series({order_book_id: 0.5})

    client = object.__new__(infrastructure._RqdatacClient)
    client.api = Api()

    specs = client._contract_specs(
        [("jm", date(2025, 1, 2), "JM2509")],
        {"jm": "DCE"},
        {"JM2509": Decimal("60")},
    )

    assert specs[0]["price_tick"] == Decimal("0.5")
