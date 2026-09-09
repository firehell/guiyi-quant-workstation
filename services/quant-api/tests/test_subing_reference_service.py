from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest

from app.market_data.aggregation import SessionWindow
from app.market_data.domain import (
    CanonicalBar,
    MarketSeriesResult,
    ResolvedContractSegment,
)
from app.market_data.subing_reference import (
    SubingReferenceError,
    SubingReferenceQuery,
    SubingReferenceService,
)


class Market:
    def __init__(self):
        self.days = tuple(date(2026, 7, 1) + timedelta(days=n) for n in range(25))
        self.bars = tuple(
            self.bar(day, n, i) for n, day in enumerate(self.days) for i in range(20)
        )
        self.owner = ResolvedContractSegment("RB2610", self.days[2], self.days[-1])
        self.physical = self.bars
        self.requests = []
        self.bad_identity = False
        self.missing_owned = False

    def bar(self, day, n, i):
        close = Decimal(
            100 if n * 20 + i < 50 else (120 if (n * 20 + i) % 2 == 0 else 80)
        )
        end = datetime.combine(day, time(1), UTC) + timedelta(minutes=15 * (i + 1))
        return CanonicalBar(
            end, day, close, close, close, close, Decimal(1), None, None
        )

    def completed_trading_days(
        self, *, symbol, start, as_of, latest, calendar_since=None
    ):
        return tuple(
            day
            for day in self.days
            if day >= start.date()
            and day <= latest
            and self.session_windows(symbol=symbol, trading_day=day)[0].end <= as_of
        )

    def session_windows(self, *, symbol, trading_day):
        return (
            SessionWindow(
                datetime.combine(trading_day, time(1), UTC),
                datetime.combine(trading_day, time(6), UTC),
            ),
        )

    def actual_dominant_segments(self, symbol, since, through):
        return (self.owner,)

    def query_actual_dominant_trading_days(self, request):
        self.requests.append(request)
        bars = tuple(
            bar
            for bar in self.bars
            if request.since <= bar.trading_day <= request.through
        )
        if self.missing_owned:
            bars = bars[:-1]
        return MarketSeriesResult(
            {
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "frequency": "15m",
                "contract": None,
            },
            bars,
            (bars[0].bar_end, bars[-1].bar_end),
            (self.owner,),
            (request.since, request.through),
        )

    def expected_contract_replay_endpoints(self, **kwargs):
        return tuple(
            (bar.bar_end, bar.trading_day)
            for bar in self.bars
            if bar.bar_end <= kwargs["cutoff"]
        )

    def query_contract_trading_days(self, request):
        self.requests.append(request)
        bars = tuple(
            bar
            for bar in self.physical
            if request.since <= bar.trading_day <= request.through
        )
        return MarketSeriesResult(
            {
                "series_kind": "contract",
                "symbol": "rb",
                "frequency": "15m",
                "contract": "RB2701" if self.bad_identity else request.contract,
            },
            bars,
            (bars[0].bar_end, bars[-1].bar_end),
            (),
            (request.since, request.through),
        )


class Coverage:
    def product_start(self, symbol):
        return date(2026, 7, 1)


@pytest.fixture
def case():
    market = Market()
    now = datetime(2026, 7, 25, 7, tzinfo=UTC)
    service = SubingReferenceService(
        market, coverage=Coverage(), active_products={"rb"}, now=lambda: now
    )
    return service, market, now


def test_defaults_twenty_complete_days_and_explicit_identity(case):
    service, market, now = case
    result = service.query(SubingReferenceQuery("rb"))
    assert result["performance_since"] == "2026-07-06"
    assert result["performance_through"] == "2026-07-25"
    assert result["reference_cutoff"] == "2026-07-25T06:00:00+00:00"
    assert result["formula_version"] == "subing_ths_15m_v3"
    assert result["source"] == "historical_replay"
    assert result["executable"] is False and result["auto_order"] is False
    assert result["signals"] and result["items"]
    assert all(
        isinstance(item["entry_reference_price"], str) for item in result["items"]
    )
    assert market.requests[-1].since == market.days[0]


def test_paging_keeps_summary_signals_and_snapshot_stable(case):
    service, _, now = case
    q = SubingReferenceQuery("rb", as_of=now, limit=2)
    first = service.query(q)
    second = service.query(replace(q, before=first["next_before"]))
    assert first["summary"] == second["summary"]
    assert first["signals"] == second["signals"]
    assert first["input_snapshot_hash"] == second["input_snapshot_hash"]
    assert {i["reference_trade_id"] for i in first["items"]}.isdisjoint(
        i["reference_trade_id"] for i in second["items"]
    )


def test_cursor_binds_input_and_query(case):
    service, market, now = case
    first = service.query(SubingReferenceQuery("rb", as_of=now, limit=1))
    with pytest.raises(SubingReferenceError, match="SNAPSHOT_CHANGED"):
        service.query(
            SubingReferenceQuery(
                "rb", since=date(2026, 7, 7), as_of=now, before=first["next_before"]
            )
        )
    bar = market.bars[0]
    price = bar.close + 1
    market.bars = (
        replace(bar, open=price, high=price, low=price, close=price),
        *market.bars[1:],
    )
    market.physical = market.bars
    with pytest.raises(SubingReferenceError, match="SNAPSHOT_CHANGED"):
        service.query(
            SubingReferenceQuery("rb", as_of=now, before=first["next_before"])
        )


@pytest.mark.parametrize("fault", ["missing_physical", "bad_identity", "missing_owned"])
def test_missing_or_conflicting_input_fails_closed(case, fault):
    service, market, _ = case
    if fault == "missing_physical":
        market.physical = market.physical[1:]
    else:
        setattr(market, fault, True)
    with pytest.raises(SubingReferenceError):
        service.query(SubingReferenceQuery("rb"))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"symbol": "../rb"},
        {"symbol": "ag"},
        {"symbol": "rb", "limit": 0},
        {"symbol": "rb", "as_of": datetime(2027, 1, 1, tzinfo=UTC)},
        {"symbol": "rb", "as_of": datetime(2026, 7, 25)},
        {"symbol": "rb", "since": date(2026, 7, 26), "through": date(2026, 7, 25)},
        {"symbol": "rb", "through": date(2026, 7, 26)},
    ],
)
def test_invalid_queries_never_read_series(case, kwargs):
    service, market, _ = case
    with pytest.raises(SubingReferenceError):
        service.query(SubingReferenceQuery(**kwargs))
    assert not market.requests


def test_explicit_window_does_not_shorten_to_available_data(case):
    service, market, _ = case
    market.physical = market.physical[:-20]
    with pytest.raises(SubingReferenceError):
        service.query(
            SubingReferenceQuery(
                "rb", since=date(2026, 7, 24), through=date(2026, 7, 25)
            )
        )


class RollingMarket(Market):
    def __init__(self):
        super().__init__()
        self.owners = (
            replace(self.owner, end_trading_day=self.days[11]),
            ResolvedContractSegment("RB2701", self.days[12], self.days[-1]),
        )
        self.second = tuple(
            replace(
                bar,
                open=bar.open * 2,
                high=bar.high * 2,
                low=bar.low * 2,
                close=bar.close * 2,
            )
            for bar in self.bars
        )
        self.drop_old_last_day = False

    def actual_dominant_segments(self, symbol, since, through):
        return self.owners

    def query_actual_dominant_trading_days(self, request):
        bars = tuple(
            bar
            for bar in self.bars
            if request.since <= bar.trading_day <= self.days[11]
        ) + tuple(
            bar
            for bar in self.second
            if self.days[12] <= bar.trading_day <= request.through
        )
        if self.drop_old_last_day:
            bars = tuple(bar for bar in bars if bar.trading_day != self.days[11])
        return MarketSeriesResult(
            {
                "series_kind": "actual_dominant",
                "symbol": request.symbol,
                "frequency": "15m",
                "contract": None,
            },
            bars,
            (bars[0].bar_end, bars[-1].bar_end),
            self.owners,
            (request.since, request.through),
        )

    def query_contract_trading_days(self, request):
        source = self.bars if request.contract == "RB2610" else self.second
        bars = tuple(
            bar for bar in source if request.since <= bar.trading_day <= request.through
        )
        return MarketSeriesResult(
            {
                "series_kind": "contract",
                "symbol": request.symbol,
                "frequency": "15m",
                "contract": request.contract,
            },
            bars,
            (bars[0].bar_end, bars[-1].bar_end),
            (),
            (request.since, request.through),
        )


def test_rollover_uses_own_physical_prices_and_explicit_session_boundary():
    market = RollingMarket()
    service = SubingReferenceService(
        market,
        coverage=Coverage(),
        active_products={"rb"},
        now=lambda: datetime(2026, 7, 25, 7, tzinfo=UTC),
    )
    result = service.query(
        SubingReferenceQuery(
            "rb", since=date(2026, 7, 6), through=date(2026, 7, 15), limit=200
        )
    )
    interrupted = [
        trade for trade in result["items"] if trade["status"] == "ROLLOVER_INTERRUPTED"
    ]
    assert len(interrupted) == 1
    assert interrupted[0]["physical_contract"] == "RB2610"
    assert interrupted[0]["exit_reference_price"] is None
    assert interrupted[0]["interrupted_at"] == "2026-07-13T01:00:00+00:00"
    assert all(
        Decimal(trade["entry_reference_price"]) >= 160
        for trade in result["items"]
        if trade["physical_contract"] == "RB2701"
    )


def test_missing_final_day_of_old_owner_must_not_silently_shorten():
    market = RollingMarket()
    market.drop_old_last_day = True
    service = SubingReferenceService(
        market,
        coverage=Coverage(),
        active_products={"rb"},
        now=lambda: datetime(2026, 7, 25, 7, tzinfo=UTC),
    )
    with pytest.raises(SubingReferenceError):
        service.query(SubingReferenceQuery("rb"))


def test_mds_strict_completed_days_rejects_missing_calendar_tail():
    from types import SimpleNamespace
    from app.market_data.market_data_service import MarketDataService, MarketDataError

    sessions = Market().session_windows(symbol="rb", trading_day=date(2026, 7, 24))
    catalog = SimpleNamespace(
        calendar_days=lambda *_: ((date(2026, 7, 24), True),),
        session_windows_overlapping_window=lambda *_: ((date(2026, 7, 24), sessions),),
    )
    mds = MarketDataService(catalog, object())
    with pytest.raises(MarketDataError, match="TRADING_CALENDAR_MISSING"):
        mds.completed_trading_days(
            symbol="rb",
            start=datetime(2026, 7, 23, tzinfo=UTC),
            as_of=datetime(2026, 7, 25, 7, tzinfo=UTC),
            latest=date(2026, 7, 25),
            calendar_since=date(2026, 7, 24),
        )


def test_historical_window_does_not_request_future_session_facts(case):
    service, market, _ = case
    original = market.completed_trading_days

    def completed(**kwargs):
        assert kwargs["as_of"] == datetime(2026, 7, 15, 6, tzinfo=UTC)
        return original(**kwargs)

    market.completed_trading_days = completed
    result = service.query(
        SubingReferenceQuery("rb", since=date(2026, 7, 12), through=date(2026, 7, 15))
    )
    assert result["performance_through"] == "2026-07-15"


def test_wire_decimal_is_fixed_point_even_for_cancellation_zero():
    from app.market_data.subing_reference import _wire

    zero = Decimal("1.123456789012345678901234567") + Decimal(
        "-1.123456789012345678901234567"
    )
    assert str(zero) == "0E-27"
    assert _wire({"sum": zero, "price": Decimal("1E+3")}) == {
        "sum": "0.000000000000000000000000000",
        "price": "1000",
    }
