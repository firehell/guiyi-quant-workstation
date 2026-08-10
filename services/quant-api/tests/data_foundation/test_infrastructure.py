from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.market_data.domain import DatasetKey
from app.market_data import infrastructure
from app.market_data.infrastructure import (
    SHANGHAI,
    DatabaseCoverageSource,
    InfrastructureError,
    RQDataClient,
    RQDataMarketAdapter,
)
from app.models import (
    Contract,
    Exchange,
    Instrument,
    MainContractMap,
    TradingCalendar,
    TradingSession,
)


def _session(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="jm", name="焦煤", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="JM2509",
            instrument_symbol="jm",
            exchange_code="DCE",
            listed_date=date(2025, 1, 1),
            expired_date=date(2025, 1, 11),
            maturity_date=date(2025, 12, 31),
            provider="rqdata",
        )
    )
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


def _add_provider_calendar_facts(session: Session, start: date, end: date) -> None:
    existing = {
        value
        for value in session.scalars(
            select(TradingCalendar.trade_date).where(TradingCalendar.exchange_code == "DCE")
        )
    }
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day not in existing:
            session.add(
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=day,
                    is_trading_day=day.weekday() < 5,
                    provider="rqdata",
                )
            )


def _add_date_scoped_session_facts(session: Session, days: tuple[date, ...]) -> None:
    for day in days:
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="provider_day",
                start_time=time(9),
                end_time=time(9, 5),
                effective_from=day,
                effective_to=day,
                crosses_midnight=False,
                is_active=True,
                provider="rqdata",
            )
        )


def test_rqdata_client_requires_both_future_readiness_categories() -> None:
    class Api:
        def is_data_ready(self, **kwargs):
            assert kwargs == {
                "categories": ["future_daybar", "future_minbar"],
                "expected_date": date(2026, 8, 10),
                "market": "cn",
            }
            return pd.DataFrame(
                {"ready": [True, False]},
                index=["future_daybar", "future_minbar"],
            )

    client = object.__new__(RQDataClient)
    client.api = Api()

    assert client.is_future_data_ready(date(2026, 8, 10)) is False


def test_rqdata_client_normalizes_exactly_one_dominant_contract() -> None:
    class Futures:
        def get_dominant(self, symbol, **kwargs):
            assert symbol == "JM"
            assert kwargs == {
                "start_date": date(2026, 8, 10),
                "end_date": date(2026, 8, 10),
                "rule": 2,
                "rank": 1,
            }
            return pd.DataFrame({"dominant": ["jm2609"]})

    class Api:
        futures = Futures()

    client = object.__new__(RQDataClient)
    client.api = Api()

    assert client.dominant_for_day("jm", date(2026, 8, 10)) == "JM2609"


def test_rqdata_client_creates_the_provider_live_client_without_subscription() -> None:
    created = object()

    class Api:
        def LiveMarketDataClient(self):
            return created

    client = object.__new__(RQDataClient)
    client.api = Api()

    assert client.live_market_client() is created


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


def test_latest_complete_day_falls_back_when_current_session_metadata_is_pending(
    tmp_path,
) -> None:
    """A calendar lead must not make a read-only audit depend on today's session sync."""
    session, starts = _session(tmp_path)
    current_session = session.scalar(
        select(TradingSession).where(TradingSession.instrument_symbol == "jm")
    )
    assert current_session is not None
    current_session.effective_to = date(2025, 1, 9)
    session.commit()
    coverage = DatabaseCoverageSource(
        session,
        starts,
        now=lambda: datetime(2025, 1, 10, 10, tzinfo=SHANGHAI),
    )

    assert coverage.latest_complete_day(("jm",)) == date(2025, 1, 9)
    session.close()


def test_metadata_complete_returns_false_before_active_metadata_sync(tmp_path) -> None:
    session, starts = _session(tmp_path)
    instrument = session.scalar(select(Instrument).where(Instrument.symbol == "jm"))
    assert instrument is not None
    instrument.is_active = False
    session.commit()

    coverage = DatabaseCoverageSource(session, starts)

    assert coverage.metadata_complete(("jm",), date(2025, 1, 10)) is False
    session.close()


def test_database_coverage_excludes_exchange_days_without_listed_contract(tmp_path) -> None:
    session, starts = _session(tmp_path)
    contract = session.scalar(select(Contract).where(Contract.contract_code == "JM2509"))
    assert contract is not None
    contract.listed_date = date(2025, 1, 8)
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)

    ends = coverage.expected_bar_ends(
        DatasetKey("continuous", "jm", "MAIN", "1d"),
        2025,
        1,
        date(2025, 1, 6),
        date(2025, 1, 10),
    )

    assert tuple(value.astimezone(SHANGHAI).date() for value in ends) == (
        date(2025, 1, 8),
        date(2025, 1, 9),
        date(2025, 1, 10),
    )
    session.close()


def test_database_coverage_excludes_days_on_or_after_contract_delisting(tmp_path) -> None:
    session, starts = _session(tmp_path)
    contract = session.scalar(select(Contract).where(Contract.contract_code == "JM2509"))
    assert contract is not None
    contract.expired_date = date(2025, 1, 9)
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)

    ends = coverage.expected_bar_ends(
        DatasetKey("continuous", "jm", "MAIN", "1d"),
        2025,
        1,
        date(2025, 1, 6),
        date(2025, 1, 10),
    )

    assert tuple(value.astimezone(SHANGHAI).date() for value in ends) == (
        date(2025, 1, 6),
        date(2025, 1, 7),
        date(2025, 1, 8),
    )
    session.close()


def test_metadata_complete_allows_history_before_first_provider_main_map(tmp_path) -> None:
    session, starts = _session(tmp_path)
    for day in (date(2025, 1, 8), date(2025, 1, 9), date(2025, 1, 10)):
        session.add(
            MainContractMap(
                symbol="jm",
                trade_date=day,
                contract_code="JM2509",
                rank=1,
                rule="volume_open_interest",
            )
            )
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)

    assert coverage.metadata_complete(("jm",), date(2025, 1, 10)) is True
    session.close()


def test_rqdata_adapter_maps_only_explicit_quota_errors(tmp_path) -> None:
    session, _ = _session(tmp_path)

    class Client:
        def price(self, *_args):
            error = RuntimeError("daily download quota exceeded")
            error.code = "RQDATA_DAILY_QUOTA_EXCEEDED"
            raise error

    adapter = RQDataMarketAdapter(session=session, client=Client())
    key = DatasetKey("continuous", "jm", "MAIN", "1d")

    with pytest.raises(InfrastructureError, match="PROVIDER_QUOTA_EXHAUSTED"):
        adapter.fetch(key, (datetime(2025, 1, 6, 7, tzinfo=UTC),))
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


class SplitContinuousClient:
    version = "test"

    def __init__(self, frames: dict[str, pd.DataFrame]) -> None:
        self.frames = frames
        self.calls: list[tuple[str, date, date, str]] = []

    def price(self, order_book_id, start, end, frequency):
        self.calls.append((order_book_id, start, end, frequency))
        return self.frames[order_book_id]


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


def test_continuous_main_does_not_fall_back_from_88_to_99(tmp_path) -> None:
    session, _starts = _session(tmp_path)
    expected = datetime(2025, 1, 6, 1, 5, tzinfo=UTC)
    index_frame = pd.DataFrame(
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
    client = SplitContinuousClient({"JM88": pd.DataFrame(), "JM99": index_frame})
    adapter = RQDataMarketAdapter(session=session, client=client)

    batch = adapter.fetch(DatasetKey("continuous", "jm", "MAIN", "1d"), (expected,))

    assert batch.bars == ()
    assert client.calls == [("JM88", date(2025, 1, 6), date(2025, 1, 6), "1d")]
    session.close()


def test_rqdata_weekly_adapter_requests_full_iso_context_and_rejects_other_weeks(
    tmp_path,
) -> None:
    """A provider row can only satisfy the ISO week it actually belongs to."""
    session, _starts = _session(tmp_path)
    expected = datetime(2026, 1, 2, 1, 5, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "datetime": datetime(2025, 12, 26),
                "trading_date": date(2025, 12, 26),
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

    batch = adapter.fetch(DatasetKey("continuous", "jm", "MAIN", "1w"), (expected,))

    assert client.calls == [("JM88", date(2025, 12, 29), date(2026, 1, 4), "1w")]
    assert batch.bars == ()
    session.close()


def test_rqdata_weekly_adapter_maps_rows_by_iso_week_not_provider_position(tmp_path) -> None:
    session, _starts = _session(tmp_path)
    first = datetime(2026, 1, 2, 1, 5, tzinfo=UTC)
    second = datetime(2026, 1, 9, 1, 5, tzinfo=UTC)
    frame = pd.DataFrame(
        [
            {
                "datetime": datetime(2026, 1, 9),
                "trading_date": date(2026, 1, 9),
                "open": 200,
                "high": 201,
                "low": 199,
                "close": 200,
                "volume": 10,
                "total_turnover": 2000,
                "open_interest": 20,
            },
            {
                "datetime": datetime(2026, 1, 2),
                "trading_date": date(2026, 1, 2),
                "open": 100,
                "high": 101,
                "low": 99,
                "close": 100,
                "volume": 10,
                "total_turnover": 1000,
                "open_interest": 20,
            },
        ]
    )
    adapter = RQDataMarketAdapter(session=session, client=FakeClient(frame))

    batch = adapter.fetch(DatasetKey("continuous", "jm", "MAIN", "1w"), (first, second))

    assert [(bar.bar_end, bar.close) for bar in batch.bars] == [
        (first, Decimal("100")),
        (second, Decimal("200")),
    ]
    session.close()


def test_rqdata_weekly_adapter_accepts_native_multiindex_short_week_label(tmp_path) -> None:
    session, _starts = _session(tmp_path)
    expected = datetime(2024, 4, 3, 7, tzinfo=UTC)
    frame = pd.DataFrame(
        {
            "open": [100],
            "high": [101],
            "low": [99],
            "close": [100],
            "volume": [10],
            "total_turnover": [1000],
            "open_interest": [20],
        },
        index=pd.MultiIndex.from_tuples(
            [("JM88", date(2024, 4, 3))], names=("order_book_id", "date")
        ),
    )
    client = FakeClient(frame)
    adapter = RQDataMarketAdapter(session=session, client=client)

    batch = adapter.fetch(DatasetKey("continuous", "jm", "MAIN", "1w"), (expected,))

    assert client.calls == [("JM88", date(2024, 4, 1), date(2024, 4, 7), "1w")]
    assert [(bar.bar_end, bar.trading_day) for bar in batch.bars] == [
        (expected, date(2024, 4, 3))
    ]
    session.close()


def test_historical_session_coverage_rejects_missing_provider_context(tmp_path) -> None:
    """A current session template cannot certify the required historical context."""
    session, starts = _session(tmp_path)
    coverage = DatabaseCoverageSource(session, starts)

    with pytest.raises(infrastructure.InfrastructureError, match="HISTORICAL_SESSION_FACT_MISSING"):
        coverage.require_historical_session_facts(("jm",), date(2025, 1, 10))

    session.close()


def test_historical_session_coverage_rejects_open_ended_current_hours_row(tmp_path) -> None:
    session, starts = _session(tmp_path)
    _add_provider_calendar_facts(session, date(2024, 12, 1), date(2025, 1, 12))
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)

    with pytest.raises(infrastructure.InfrastructureError, match="HISTORICAL_SESSION_FACT_MISSING"):
        coverage.require_historical_session_facts(("jm",), date(2025, 1, 10))

    session.close()


def test_historical_session_coverage_requires_full_iso_week_calendar_context(tmp_path) -> None:
    session, starts = _session(tmp_path)
    _add_provider_calendar_facts(session, date(2024, 12, 1), date(2025, 1, 10))
    _add_date_scoped_session_facts(session, tuple(date(2025, 1, day) for day in range(6, 11)))
    session.commit()
    coverage = DatabaseCoverageSource(session, starts)

    with pytest.raises(infrastructure.InfrastructureError, match="HISTORICAL_SESSION_FACT_MISSING"):
        coverage.require_historical_session_facts(("jm",), date(2025, 1, 10))

    _add_provider_calendar_facts(session, date(2025, 1, 11), date(2025, 1, 12))
    session.commit()

    coverage.require_historical_session_facts(("jm",), date(2025, 1, 10))
    session.close()


def test_rqdata_adapter_does_not_initialize_client_until_provider_read(
    tmp_path, monkeypatch
) -> None:
    session, _starts = _session(tmp_path)
    calls: list[str] = []

    class LazyClient:
        def __init__(self) -> None:
            calls.append("init")

    monkeypatch.setattr(infrastructure, "RQDataClient", LazyClient)
    adapter = RQDataMarketAdapter(session=session)

    assert calls == []
    assert isinstance(adapter.client, LazyClient)
    assert calls == ["init"]
    session.close()


def test_metadata_refresh_ignores_history_before_first_provider_main_map(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Exchange(code="DCE", name="DCE"))
        session.add(
            Instrument(
                symbol="jm",
                name="焦煤",
                exchange_code="DCE",
                is_active=True,
            )
        )
        session.add(
            Contract(
                contract_code="JM2509",
                instrument_symbol="jm",
                exchange_code="DCE",
                listed_date=date(2025, 1, 20),
                maturity_date=date(2025, 12, 31),
                provider="rqdata",
            )
        )
        for day in range(1, 32):
            session.add(
                TradingCalendar(
                    exchange_code="DCE",
                    trade_date=date(2025, 1, day),
                    is_trading_day=True,
                )
            )
        for day in range(20, 32):
            session.add(
                MainContractMap(
                    symbol="jm",
                    trade_date=date(2025, 1, day),
                    contract_code="JM2509",
                    rank=1,
                    rule="volume_open_interest",
                )
            )
        session.commit()
        requested = []

        class Client:
            def metadata_snapshot(self, products, through, starts):
                requested.append(dict(starts))
                return object()

        adapter = RQDataMarketAdapter(session=session, client=Client())

        adapter.fetch_metadata(
            ("jm",),
            date(2025, 1, 31),
            {"jm": date(2025, 1, 1)},
        )

        assert requested == [{"jm": date(2025, 1, 17)}]


def test_current_day_metadata_adapter_uses_dedicated_single_day_provider_call(tmp_path) -> None:
    session, _starts = _session(tmp_path)
    requested = []

    class Client:
        def current_day_metadata_snapshot(self, products, trading_day):
            requested.append((products, trading_day))
            return object()

        def metadata_snapshot(self, *_args, **_kwargs):
            raise AssertionError("current-day metadata must not use history refresh")

    adapter = RQDataMarketAdapter(session=session, client=Client())

    result = adapter.fetch_current_day_metadata(("jm",), date(2025, 1, 10))

    assert result is not None
    assert requested == [(("jm",), date(2025, 1, 10))]
    session.close()


def test_rqdatac_client_requests_unadjusted_bars() -> None:
    calls = []

    class Api:
        def get_price(self, order_book_id, **kwargs):
            calls.append((order_book_id, kwargs))
            return pd.DataFrame()

    client = object.__new__(infrastructure.RQDataClient)
    client.api = Api()

    client.price("JM88", date(2025, 1, 2), date(2025, 1, 3), "1m")

    assert calls[0][1]["adjust_type"] == "none"


def test_rqdata_zero_date_sentinel_normalizes_to_none() -> None:
    assert infrastructure._optional_date("0000-00-00") is None


def test_rqdata_metadata_uses_volume_open_interest_dominant_rule() -> None:
    calls = []

    class FuturesApi:
        def get_dominant(
            self, underlying_symbol, start_date, end_date, rule=0, rank=1
        ):
            calls.append((underlying_symbol, rule, rank))
            return pd.Series(
                ["JM2509"],
                index=pd.to_datetime(["2025-01-02"]),
                name="dominant",
            )

        def get_trading_parameters(self, order_book_id, start_date, end_date):
            return pd.DataFrame()

    class Api:
        futures = FuturesApi()

        def all_instruments(self, type):
            return pd.DataFrame(
                [
                    {
                        "underlying_symbol": "JM",
                        "exchange": "DCE",
                        "order_book_id": "JM2509",
                        "symbol": "JM2509",
                        "contract_multiplier": 60,
                        "listed_date": date(2025, 1, 1),
                        "de_listed_date": date(2025, 9, 25),
                        "maturity_date": date(2025, 9, 30),
                        "trading_hours": "09:00-09:01",
                    }
                ]
            )

        def get_trading_dates(self, start_date, end_date):
            return (date(2025, 1, 2),)

        def get_trading_periods(self, order_book_ids, start_date, end_date, frequency):
            return pd.DataFrame(
                {"trading_hours": ["09:00-09:01"]},
                index=pd.MultiIndex.from_tuples(
                    [("JM2509", date(2025, 1, 2))],
                    names=("order_book_id", "date"),
                ),
            )

        def get_tick_size(self, order_book_id):
            return pd.Series({order_book_id: 0.5})

    client = object.__new__(infrastructure.RQDataClient)
    client.api = Api()

    snapshot = client.metadata_snapshot(
        ("jm",),
        date(2025, 1, 2),
        {"jm": date(2025, 1, 1)},
    )

    assert calls == [("JM", 2, 1)]
    assert snapshot.contracts[0]["expired_date"] == date(2025, 9, 25)


def test_rqdata_metadata_uses_historical_trading_period_facts_not_current_hours() -> None:
    class FuturesApi:
        def get_dominant(
            self, underlying_symbol, start_date, end_date, rule=0, rank=1
        ):
            return pd.Series(
                ["JM2509"],
                index=pd.to_datetime(["2025-01-02"]),
                name="dominant",
            )

        def get_trading_parameters(self, order_book_id, start_date, end_date):
            return pd.DataFrame()

    class Api:
        futures = FuturesApi()

        def all_instruments(self, type):
            return pd.DataFrame(
                [
                    {
                        "underlying_symbol": "JM",
                        "exchange": "DCE",
                        "order_book_id": "JM2509",
                        "symbol": "JM2509",
                        "contract_multiplier": 60,
                        "listed_date": date(2025, 1, 1),
                        "de_listed_date": date(2025, 9, 25),
                        "maturity_date": date(2025, 9, 30),
                        "trading_hours": "21:00-23:00",
                    }
                ]
            )

        def get_trading_dates(self, start_date, end_date):
            return (date(2025, 1, 2),)

        def get_trading_periods(self, order_book_ids, start_date, end_date, frequency):
            assert order_book_ids == ("JM2509",)
            assert (start_date, end_date, frequency) == (
                date(2024, 12, 1),
                date(2025, 1, 2),
                "1m",
            )
            return pd.DataFrame(
                {"trading_hours": ["09:00-15:00"]},
                index=pd.MultiIndex.from_tuples(
                    [("JM2509", date(2025, 1, 2))],
                    names=("order_book_id", "date"),
                ),
            )

        def get_tick_size(self, order_book_id):
            return pd.Series({order_book_id: 0.5})

    client = object.__new__(infrastructure.RQDataClient)
    client.api = Api()

    snapshot = client.metadata_snapshot(
        ("jm",),
        date(2025, 1, 2),
        {"jm": date(2025, 1, 1)},
    )

    assert snapshot.sessions == (
        {
            "exchange_code": "DCE",
            "instrument_symbol": "jm",
            "session_name": "session_1",
            "start_time": time(9),
            "end_time": time(15),
            "effective_from": date(2025, 1, 2),
            "effective_to": date(2025, 1, 2),
            "crosses_midnight": False,
            "is_active": True,
            "provider": "rqdata",
        },
    )


def test_intraday_dataset_start_floors_to_rqdata_minute_history(tmp_path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE"))
    session.add(Instrument(symbol="a", name="A", exchange_code="DCE", is_active=True))
    session.add(
        Contract(
            contract_code="A0305",
            instrument_symbol="a",
            exchange_code="DCE",
            listed_date=date(2002, 1, 1),
            expired_date=date(2002, 5, 1),
            maturity_date=date(2002, 5, 1),
            provider="rqdata",
        )
    )
    for day in (date(2002, 3, 15), date(2002, 3, 18), date(2010, 1, 4), date(2010, 1, 5)):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=day,
                is_trading_day=True,
            )
        )
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="a",
            session_name="day",
            start_time=time(9),
            end_time=time(9, 5),
            effective_from=date(2002, 1, 1),
            effective_to=None,
            crosses_midnight=False,
            is_active=True,
        )
    )
    session.commit()
    starts = tmp_path / "starts.csv"
    starts.write_text("product,window_start,note\na,2002-03-15,test\n")
    floor = tmp_path / "floor.txt"
    floor.write_text("1900-01-01\n")
    coverage = DatabaseCoverageSource(session, starts, history_floor_path=floor)
    minute = DatasetKey("continuous", "a", "MAIN", "1m")
    daily = DatasetKey("continuous", "a", "MAIN", "1d")

    assert coverage.dataset_start(minute) == date(2010, 1, 4)
    assert coverage.dataset_start(daily) == date(2002, 3, 15)
    assert coverage.expected_bar_ends(minute, 2002, 3, date(2002, 3, 15), date(2002, 3, 18)) == ()
    assert len(coverage.expected_bar_ends(daily, 2002, 3, date(2002, 3, 15), date(2002, 3, 18))) == 2
    session.close()


def test_product_start_applies_active_history_floor(tmp_path) -> None:
    session, starts = _session(tmp_path)
    starts.write_text(
        "product,window_start,note\n"
        "jm,2013-03-22,provider\n"
        "ao,2023-06-19,provider\n"
        "bz,2025-07-08,provider\n"
    )
    floor = tmp_path / "floor.txt"
    floor.write_text("2023-01-01\n")
    for symbol in ("ao", "bz"):
        session.add(Instrument(symbol=symbol, name=symbol.upper(), exchange_code="DCE", is_active=True))
    session.commit()
    coverage = DatabaseCoverageSource(session, starts, history_floor_path=floor)

    assert coverage.provider_start("jm") == date(2013, 3, 22)
    assert coverage.product_start("jm") == date(2023, 1, 1)
    assert coverage.product_start("ao") == date(2023, 6, 19)
    assert coverage.product_start("bz") == date(2025, 7, 8)
    session.close()


def test_calendar_context_start_is_previous_natural_month() -> None:
    from app.market_data.infrastructure import _calendar_context_start

    assert _calendar_context_start(date(2023, 1, 1)) == date(2022, 12, 1)
    assert _calendar_context_start(date(2023, 6, 19)) == date(2023, 5, 1)
    assert _calendar_context_start(date(2025, 7, 8)) == date(2025, 6, 1)
