from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.market_data.domain import CanonicalBar
from app.market_data.live_market import LiveBarObservation
from app.market_data.market_home_live import MarketHomeLiveService
from app.market_data.market_phase import MarketPhase, ProductMarketPhase


NOW = datetime(2026, 8, 15, 1, 2, 2, tzinfo=UTC)
DAY = date(2026, 8, 15)


def test_snapshot_uses_completed_1m_and_same_contract_previous_day_close() -> None:
    """Catches tick semantics, a synthetic baseline, or a different contract baseline."""
    live = _bar(DAY, NOW - timedelta(seconds=2), "108")
    market = FakeMarketData(
        dominants={"j": "J2609"},
        bars={"J2609": (_bar(date(2026, 8, 14), NOW - timedelta(days=1), "100"),)},
    )
    service = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=FakeLiveStore(
            heartbeat={"available": True, "generated_at": NOW.isoformat()},
            subscriptions={DAY: {"j": "J2609"}},
            latest={"j": LiveBarObservation(live, "J2609")},
        ),
    )

    item = service.snapshot(NOW).items[0]

    assert item.source == "completed_1m"
    assert item.availability == "live"
    assert item.physical_contract == "J2609"
    assert item.price == Decimal("108")
    assert item.previous_close == Decimal("100")
    assert item.price_change == Decimal("0.08")
    assert market.requests == [("j", "J2609", "1d", 5, NOW)]


def test_closed_snapshot_uses_previous_bar_as_baseline_instead_of_quote_itself() -> None:
    """Catches the closed-market fallback silently reporting a zero change."""
    prior = _bar(date(2026, 8, 13), NOW - timedelta(days=2), "100")
    quote = _bar(date(2026, 8, 14), NOW - timedelta(days=1), "105")
    service = _service(
        market=FakeMarketData(dominants={"j": "J2609"}, bars={"J2609": (prior, quote)}),
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(),
    )

    item = service.snapshot(NOW).items[0]

    assert item.source == "completed_1d"
    assert item.availability == "historical"
    assert item.trading_day == date(2026, 8, 14)
    assert item.price == Decimal("105")
    assert item.previous_close == Decimal("100")
    assert item.price_change == Decimal("0.05")


def test_live_snapshot_rejects_old_contract_and_not_yet_completed_bars() -> None:
    """Catches using an old-contract price or a bar before the completion delay."""
    market = FakeMarketData(
        dominants={"j": "J2609"},
        bars={
            "J2609": (
                _bar(date(2026, 8, 13), NOW - timedelta(days=2), "99"),
                _bar(date(2026, 8, 14), NOW - timedelta(days=1), "100"),
            )
        },
    )
    store = FakeLiveStore(
        heartbeat={"available": True, "generated_at": NOW.isoformat()},
        subscriptions={DAY: {"j": "J2609"}},
        latest={
            "j": LiveBarObservation(
                _bar(DAY, NOW - timedelta(seconds=1), "108"),
                "J2605",
            )
        },
    )

    item = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=store,
    ).snapshot(NOW).items[0]

    assert item.source == "completed_1d"
    assert item.availability == "historical"
    assert item.physical_contract == "J2609"
    assert item.price == Decimal("100")
    assert item.previous_close == Decimal("99")


def test_missing_or_zero_same_contract_baseline_is_typed_unavailable() -> None:
    """Catches invented change values when the exact denominator is unusable."""
    quote = _bar(DAY, NOW - timedelta(seconds=2), "108")
    missing = _service(
        market=FakeMarketData(dominants={"j": "J2609"}, bars={"J2609": ()}),
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=FakeLiveStore(
            heartbeat={"available": True, "generated_at": NOW.isoformat()},
            subscriptions={DAY: {"j": "J2609"}},
            latest={"j": LiveBarObservation(quote, "J2609")},
        ),
    ).snapshot(NOW).items[0]
    zero = _service(
        market=FakeMarketData(
            dominants={"j": "J2609"},
            bars={"J2609": (_bar(date(2026, 8, 14), NOW - timedelta(days=1), "0"),)},
        ),
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=FakeLiveStore(
            heartbeat={"available": True, "generated_at": NOW.isoformat()},
            subscriptions={DAY: {"j": "J2609"}},
            latest={"j": LiveBarObservation(quote, "J2609")},
        ),
    ).snapshot(NOW).items[0]

    assert (missing.price, missing.previous_close, missing.price_change, missing.reason) == (
        Decimal("108"), None, None, "PREVIOUS_CLOSE_UNAVAILABLE"
    )
    assert (zero.price, zero.previous_close, zero.price_change, zero.reason) == (
        Decimal("108"), Decimal("0"), None, "PREVIOUS_CLOSE_ZERO"
    )


def test_snapshot_reuses_same_day_authority_without_requerying_d1() -> None:
    """Catches bounded status recovery turning into 60 D1 reads every poll."""
    market = FakeMarketData(
        dominants={"j": "J2609"},
        bars={"J2609": (_bar(date(2026, 8, 14), NOW - timedelta(days=1), "100"),)},
    )
    service = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=FakeLiveStore(
            heartbeat={"available": True, "generated_at": NOW.isoformat()},
            subscriptions={DAY: {"j": "J2609"}},
            latest={"j": LiveBarObservation(_bar(DAY, NOW - timedelta(seconds=2), "101"), "J2609")},
        ),
    )

    first = service.snapshot(NOW)
    second = service.snapshot(NOW + timedelta(seconds=10), previous=first)

    assert second.items[0].price_change == Decimal("0.01")
    assert len(market.requests) == 1


def test_missing_live_baseline_is_reread_after_cache_ttl_during_repeated_refreshes() -> None:
    """Catches each quote refresh indefinitely renewing a missing-baseline cache."""
    quote_day = date(2026, 8, 14)
    market = FakeMarketData(
        dominants={"j": ("J2609", quote_day)},
        bars={"J2609": ()},
        previous_days={quote_day: date(2026, 8, 13)},
    )
    service = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(
            subscriptions={quote_day: {"j": "J2609"}},
            latest={
                "j": LiveBarObservation(
                    _bar(quote_day, NOW - timedelta(hours=1), "108"),
                    "J2609",
                )
            },
        ),
    )

    snapshot = service.snapshot(NOW)
    market.bars["J2609"] = (
        _bar(date(2026, 8, 13), NOW - timedelta(days=2), "100"),
    )
    for minute in range(1, 8):
        snapshot = service.snapshot(NOW + timedelta(minutes=minute), previous=snapshot)

    assert snapshot.items[0].previous_close == Decimal("100")
    assert snapshot.items[0].price_change == Decimal("0.08")
    assert snapshot.items[0].facts_observed_at == NOW + timedelta(minutes=6)
    assert len(market.requests) == 2


def test_existing_live_baseline_is_reread_after_cache_ttl_during_repeated_refreshes() -> None:
    """Catches each quote refresh indefinitely renewing a stale positive baseline."""
    quote_day = date(2026, 8, 14)
    market = FakeMarketData(
        dominants={"j": ("J2609", quote_day)},
        bars={
            "J2609": (
                _bar(date(2026, 8, 13), NOW - timedelta(days=2), "100"),
            )
        },
        previous_days={quote_day: date(2026, 8, 13)},
    )
    service = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(
            subscriptions={quote_day: {"j": "J2609"}},
            latest={
                "j": LiveBarObservation(
                    _bar(quote_day, NOW - timedelta(hours=1), "111.1"),
                    "J2609",
                )
            },
        ),
    )

    snapshot = service.snapshot(NOW)
    market.bars["J2609"] = (
        _bar(date(2026, 8, 13), NOW - timedelta(days=2), "101"),
    )
    for minute in range(1, 8):
        snapshot = service.snapshot(NOW + timedelta(minutes=minute), previous=snapshot)

    assert snapshot.items[0].previous_close == Decimal("101")
    assert snapshot.items[0].price_change == Decimal("0.1")
    assert snapshot.items[0].facts_observed_at == NOW + timedelta(minutes=6)
    assert len(market.requests) == 2


def test_closed_snapshot_keeps_last_completed_minute_for_latest_authority_day() -> None:
    """Catches the visible price moving backwards to D1 immediately after close."""
    final_minute = _bar(date(2026, 8, 14), NOW - timedelta(hours=1), "108")
    market = FakeMarketData(
        dominants={"j": ("J2609", date(2026, 8, 14))},
        bars={"J2609": (_bar(date(2026, 8, 13), NOW - timedelta(days=2), "100"),)},
        previous_days={date(2026, 8, 14): date(2026, 8, 13)},
    )
    item = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(
            subscriptions={date(2026, 8, 14): {"j": "J2609"}},
            latest={"j": LiveBarObservation(final_minute, "J2609")},
        ),
    ).snapshot(NOW).items[0]

    assert item.source == "completed_1m"
    assert item.availability == "live"
    assert item.price == Decimal("108")
    assert item.previous_close == Decimal("100")


def test_previous_close_requires_exact_previous_calendar_trading_day() -> None:
    """Catches silently skipping a missing prior trading day and reporting multi-day change."""
    market = FakeMarketData(
        dominants={"j": "J2609"},
        bars={
            "J2609": (
                _bar(date(2026, 8, 12), NOW - timedelta(days=3), "98"),
                _bar(date(2026, 8, 14), NOW - timedelta(days=1), "105"),
            )
        },
        previous_days={date(2026, 8, 14): date(2026, 8, 13)},
    )

    item = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(),
    ).snapshot(NOW).items[0]

    assert item.price == Decimal("105")
    assert item.previous_close is None
    assert item.price_change is None
    assert item.reason == "PREVIOUS_CLOSE_UNAVAILABLE"


def test_stale_available_heartbeat_cannot_authorize_live_price() -> None:
    """Catches an expired producer heartbeat being treated as fresh authority."""
    live = _bar(DAY, NOW - timedelta(seconds=2), "108")
    item = _service(
        market=FakeMarketData(
            dominants={"j": "J2609"},
            bars={
                "J2609": (
                    _bar(date(2026, 8, 13), NOW - timedelta(days=2), "99"),
                    _bar(date(2026, 8, 14), NOW - timedelta(days=1), "100"),
                )
            },
        ),
        phases={"j": _phase("j", MarketPhase.TRADING, DAY)},
        store=FakeLiveStore(
            heartbeat={
                "available": True,
                "generated_at": (NOW - timedelta(minutes=2)).isoformat(),
            },
            subscriptions={DAY: {"j": "J2609"}},
            latest={"j": LiveBarObservation(live, "J2609")},
        ),
    ).snapshot(NOW).items[0]

    assert item.source == "completed_1d"
    assert item.price == Decimal("100")


def test_historical_cache_expires_and_refreshes_completed_daily_facts() -> None:
    """Catches the 18:05 completed D1 or repair result staying hidden all day."""
    market = FakeMarketData(
        dominants={"j": "J2609"},
        bars={
            "J2609": (
                _bar(date(2026, 8, 13), NOW - timedelta(days=2), "100"),
                _bar(date(2026, 8, 14), NOW - timedelta(days=1), "105"),
            )
        },
    )
    service = _service(
        market=market,
        phases={"j": _phase("j", MarketPhase.CLOSED, None)},
        store=FakeLiveStore(),
    )
    first = service.snapshot(NOW)
    market.bars["J2609"] = (
        *market.bars["J2609"],
        _bar(date(2026, 8, 15), NOW + timedelta(minutes=1), "110"),
    )

    cached = service.snapshot(NOW + timedelta(minutes=4), previous=first)
    refreshed = service.snapshot(NOW + timedelta(minutes=6), previous=first)

    assert cached.items[0].price == Decimal("105")
    assert refreshed.items[0].price == Decimal("110")
    assert len(market.requests) == 2


def _bar(day: date, end: datetime, close: str) -> CanonicalBar:
    value = Decimal(close)
    return CanonicalBar(end, day, value, value, value, value, Decimal("1"), None, None)


def _phase(symbol: str, phase: MarketPhase, day: date | None) -> ProductMarketPhase:
    return ProductMarketPhase(symbol, phase, day, None, None)


class FakeMarketData:
    def __init__(
        self,
        *,
        dominants,
        bars: dict[str, tuple[CanonicalBar, ...]],
        previous_days: dict[date, date] | None = None,
    ) -> None:
        self.dominants = dominants
        self.bars = bars
        self.previous_days = previous_days or {}
        self.requests: list[tuple[str, str, str, int, datetime]] = []

    def list_latest_dominants(self):
        return tuple(
            SimpleNamespace(
                symbol=symbol,
                actual_contract=(value[0] if isinstance(value, tuple) else value),
                dominant_mapping_date=(value[1] if isinstance(value, tuple) else date(2026, 8, 14)),
            )
            for symbol, value in self.dominants.items()
        )

    def latest_dominant_segment(self, symbol):
        value = self.dominants[symbol]
        return SimpleNamespace(
            contract=(value[0] if isinstance(value, tuple) else value),
            end_trading_day=(value[1] if isinstance(value, tuple) else date(2026, 8, 14)),
        )

    def contract_daily_bars_as_of(self, *, symbol, contract, as_of, limit):
        self.requests.append((symbol, contract, "1d", limit, as_of))
        return tuple(bar for bar in self.bars[contract] if bar.bar_end <= as_of)

    def previous_trading_day(self, symbol, trading_day):
        return self.previous_days.get(trading_day, trading_day - timedelta(days=1))


class FakeLiveStore:
    def __init__(self, *, heartbeat=None, subscriptions=None, latest=None) -> None:
        self._heartbeat = heartbeat
        self._subscriptions = subscriptions or {}
        self._latest = latest or {}

    def heartbeat(self):
        return self._heartbeat

    def subscriptions(self, trading_day):
        return self._subscriptions.get(trading_day)

    def latest_observation(self, trading_day, symbol, frequency, *, until, expected_contract):
        return self._latest.get(symbol)


def _service(*, market, phases, store) -> MarketHomeLiveService:
    return MarketHomeLiveService(
        market_data=market,
        phase_resolver=SimpleNamespace(resolve=lambda symbol, _now: phases[symbol]),
        live_store=store,
        operational_products=("j",),
    )
