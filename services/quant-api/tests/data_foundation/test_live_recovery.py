from datetime import UTC, date, datetime, time, timedelta
from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.alerts.evaluators import AlertObservationCandidate
from app.alerts.models import AlertEvent, AlertRule
from app.alerts.notification import ProviderAcceptance
from app.alerts.registry import HTDY_ALERT_RULE_CODE
from app.alerts.runtime import AlertRuntime
from app.db.base import Base
from app.market_data.aggregation import SessionWindow
from app.market_data.domain import CanonicalBar, MarketSeriesPageResult, SeriesPageQuery
from app.market_data.live_market import RedisLiveStore
from app.market_data.market_phase import MarketPhaseResolver
from app.market_data.market_read_service import MarketReadService
from app.market_data.session_clock import SHANGHAI, resolved_session_windows_for_trading_day
from app.models import Contract, Exchange, Instrument, TradingCalendar, TradingSession
from tests.data_foundation.test_live_market import FakeRedis, _bar


def test_recovery_missing_first_minute_rebuilds_completed_buckets_without_publish():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2025, 1, 2)
    snapshot = {"rb": "RB2505"}
    store.set_subscriptions(day, snapshot)
    start = datetime(2025, 1, 2, 1, 0, tzinfo=UTC)
    bars = tuple(_bar(m) for m in range(1, 16))
    for bar in bars[1:]:
        store.put_bar(day, "rb", "1m", bar, contract="RB2505")
    request = LiveRecoveryRequest(
        day,
        "rb",
        "RB2505",
        tuple(snapshot.items()),
        (SessionWindow(start, start + timedelta(minutes=60)),),
        start + timedelta(minutes=15, seconds=3),
    )
    calls = []

    def fetch(req):
        calls.append(req)
        return bars

    outcome = recover_product(
        store, request, fetch, clock=lambda: start + timedelta(minutes=16)
    )
    assert outcome == "RECOVERED"
    assert len(store.bars_after(day, "rb", "15m", None)) == 1
    assert len(store.bars_after(day, "rb", "5m", None)) == 3
    assert store.recovery_state(day, "rb", "RB2505").revision == 1
    assert store.recovery_state(
        day, "rb", "RB2505"
    ).recovered_through == start + timedelta(minutes=16)
    assert redis.published == []
    assert (
        recover_product(
            store, request, fetch, clock=lambda: start + timedelta(minutes=17)
        )
        == "NO_GAP"
    )
    assert len(calls) == 1


def test_normal_put_does_not_overwrite_conflicting_completed_bar():
    store = RedisLiveStore(FakeRedis())
    bar = _bar(1)
    store.put_bar(bar.trading_day, "rb", "1m", bar, contract="RB2505")
    with pytest.raises(ValueError, match="LIVE_BAR_CONFLICT"):
        store.put_bar(
            bar.trading_day,
            "rb",
            "1m",
            replace(bar, volume=bar.volume + 1),
            contract="RB2505",
        )
    assert store.bars_after(bar.trading_day, "rb", "1m", None) == (bar,)


def _setup():
    from app.market_data.live_recovery import LiveRecoveryRequest

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    start = datetime(2025, 1, 2, 1, tzinfo=UTC)
    bars = tuple(_bar(m) for m in range(1, 16))
    store.set_subscriptions(bars[0].trading_day, {"rb": "RB2505"})
    for bar in bars[1:]:
        store.put_bar(bar.trading_day, "rb", "1m", bar, contract="RB2505")
    request = LiveRecoveryRequest(
        bars[0].trading_day,
        "rb",
        "RB2505",
        (("rb", "RB2505"),),
        (SessionWindow(start, start + timedelta(hours=1)),),
        start + timedelta(minutes=15, seconds=3),
    )
    return redis, store, request, bars


@pytest.mark.parametrize(
    "failure", ["incomplete", "future", "duplicate", "wrong_day", "conflict", "drift"]
)
def test_invalid_recovery_never_changes_bars_or_barrier(failure):
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    original = {k: dict(v) for k, v in redis.zsets.items()}

    def fetch(req):
        if failure == "incomplete":
            return bars[1:]
        if failure == "future":
            return (
                *bars,
                replace(bars[-1], bar_end=bars[-1].bar_end + timedelta(minutes=1)),
            )
        if failure == "duplicate":
            return (bars[0], *bars[:-1])
        if failure == "wrong_day":
            return (replace(bars[0], trading_day=date(2025, 1, 3)), *bars[1:])
        if failure == "conflict":
            return (*bars[:-1], replace(bars[-1], volume=bars[-1].volume + 1))
        store.set_subscriptions(req.trading_day, {"rb": "RB2510"})
        return bars

    with pytest.raises(ValueError):
        recover_product(store, request, fetch, clock=lambda: request.cutoff)
    assert redis.zsets == original
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
    assert redis.published == []


def test_retry_budget_survives_store_restart_and_new_session_resets():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    calls = []

    def fetch(req):
        calls.append(req)
        raise ValueError("PROVIDER_UNAVAILABLE")

    for minute in range(3):
        current = replace(request, cutoff=request.cutoff + timedelta(minutes=minute))
        with pytest.raises(ValueError):
            recover_product(
                RedisLiveStore(redis), current, fetch, clock=lambda: current.cutoff
            )
    assert (
        recover_product(
            RedisLiveStore(redis),
            replace(request, cutoff=request.cutoff + timedelta(minutes=3)),
            fetch,
            clock=lambda: request.cutoff,
        )
        == "RETRY_BUDGET_BLOCKED"
    )
    assert len(calls) == 3


def test_permission_circuit_stops_other_products_and_restart():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()

    def denied(req):
        raise ValueError("PROVIDER_ACCESS_DENIED")

    with pytest.raises(ValueError):
        recover_product(store, request, denied, clock=lambda: request.cutoff)
    assert (
        recover_product(
            RedisLiveStore(redis),
            replace(request, cutoff=request.cutoff + timedelta(minutes=2)),
            lambda _: pytest.fail("network after circuit"),
            clock=lambda: request.cutoff,
        )
        == "RETRY_BUDGET_BLOCKED"
    )


def test_worker_no_gap_does_not_instantiate_provider():
    from app.market_data.live_recovery import LiveRecoveryWorker

    redis, store, request, bars = _setup()
    store.put_bar(request.trading_day, "rb", "1m", bars[0], contract="RB2505")
    worker = LiveRecoveryWorker(
        store,
        lambda: pytest.fail("provider factory on no gap"),
        clock=lambda: request.cutoff,
    )
    worker._run((request,))
    assert worker.outcomes == (("rb", "RECOVERED"),)
    worker._run((request,))
    assert worker.outcomes == (("rb", "NO_GAP"),)
    worker._executor.shutdown(wait=True)


def test_all_60_products_recover_afternoon_first_minute_and_all_derived_buckets():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product
    from app.market_data.operational_universe import load_operational_products

    products = load_operational_products()
    assert len(products) == 60
    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2026, 9, 7)
    start = datetime(2026, 9, 7, 5, 30, tzinfo=UTC)
    snapshot = {symbol: f"{symbol.upper()}2611" for symbol in products}
    store.set_subscriptions(day, snapshot)
    bars = tuple(
        replace(_bar(1), bar_end=start + timedelta(minutes=i), trading_day=day)
        for i in range(1, 61)
    )
    for symbol, contract in snapshot.items():
        request = LiveRecoveryRequest(
            day,
            symbol,
            contract,
            tuple(snapshot.items()),
            (SessionWindow(start, start + timedelta(minutes=60)),),
            start + timedelta(minutes=60, seconds=3),
        )
        for bar in bars[1:]:
            store.put_bar(day, symbol, "1m", bar, contract=contract)
        assert (
            recover_product(
                store, request, lambda _: bars, clock=lambda: request.cutoff
            )
            == "RECOVERED"
        )
        for frequency in ("5m", "15m", "30m", "60m"):
            assert (
                len(store.bars_after(day, symbol, frequency, None))
                == {"5m": 12, "15m": 4, "30m": 2, "60m": 1}[frequency]
            )
    assert redis.published == []


def test_monday_open_freezes_60_contracts_and_schedules_45_night_prefixes():
    """The normal foreground snapshot owns Monday recovery identity and sessions."""
    from app.market_data.live_market import LiveMarketService, RQDataLiveProvider
    from app.market_data.operational_universe import load_operational_products
    from tests.data_foundation.test_live_market import (
        FakeDominants,
        FakeLiveClient,
        FakePhases,
        _phase,
    )

    products = load_operational_products()
    trading_day = date(2026, 9, 14)
    now = datetime(2026, 9, 14, 1, 0, tzinfo=UTC)
    morning = SessionWindow(now, now + timedelta(hours=1))
    night = SessionWindow(
        datetime(2026, 9, 11, 13, 0, tzinfo=UTC),
        datetime(2026, 9, 11, 15, 0, tzinfo=UTC),
    )
    night_products = frozenset(
        (
            "a", "ag", "al", "ao", "au", "b", "bu", "bz", "c", "cf", "cu",
            "eb", "eg", "fg", "fu", "hc", "i", "j", "jm", "l", "m", "ma",
            "ni", "oi", "p", "pb", "pf", "pg", "pl", "pp", "pr", "px", "rb",
            "rm", "ru", "sa", "sc", "sh", "sn", "sr", "ss", "ta", "v", "y",
            "zn",
        )
    )
    assert len(products) == 60
    assert len(night_products) == 45
    assert night_products < set(products)
    contracts = {symbol: f"{symbol.upper()}2701" for symbol in products}
    fake_redis = FakeRedis()

    class RecordingWorker:
        requests = ()

        @staticmethod
        def due(_now):
            return True

        def schedule(self, requests, _now):
            self.requests = requests

    worker = RecordingWorker()
    service = LiveMarketService(
        provider_factory=lambda: RQDataLiveProvider(FakeLiveClient()),
        dominant_source=FakeDominants(
            {(symbol, trading_day): contract for symbol, contract in contracts.items()}
        ),
        phase_resolver=FakePhases(
            {symbol: _phase(symbol, trading_day, morning) for symbol in products}
        ),
        store=RedisLiveStore(fake_redis),
        operational_products=products,
    )
    service._recovery_sessions = lambda symbol, _day: (
        (night, morning) if symbol in night_products else (morning,)
    )
    service._recovery_worker = worker

    assert service.reconcile(now) is None

    snapshot = RedisLiveStore(fake_redis).subscriptions(trading_day)
    assert snapshot == contracts
    assert len(worker.requests) == 60
    for request in worker.requests:
        assert dict(request.snapshot) == contracts
        assert request.contract == contracts[request.symbol]
        assert request.trading_day == trading_day
        assert request.sessions == (
            (night, morning) if request.symbol in night_products else (morning,)
        )
    assert fake_redis.published == [
        ("market:state", '{"trading_day":"2026-09-14"}')
    ]


def test_monday_snapshot_recovers_through_real_session_adapter_store_and_read():
    """Catches replacing the 60/45 recovery chain with a schedule-only double."""
    from app.market_data.live_market import LiveMarketService, RQDataLiveProvider
    from app.market_data.live_recovery import recover_product
    from app.market_data.operational_universe import load_operational_products
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from tests.data_foundation.test_live_market import FakeDominants, FakeLiveClient

    products = load_operational_products()
    night_products = frozenset(
        (
            "a", "ag", "al", "ao", "au", "b", "bu", "bz", "c", "cf", "cu",
            "eb", "eg", "fg", "fu", "hc", "i", "j", "jm", "l", "m", "ma",
            "ni", "oi", "p", "pb", "pf", "pg", "pl", "pp", "pr", "px", "rb",
            "rm", "ru", "sa", "sc", "sh", "sn", "sr", "ss", "ta", "v", "y",
            "zn",
        )
    )
    assert len(products) == 60
    assert len(night_products) == 45
    trading_day = date(2026, 9, 14)
    prior_trading_day = date(2026, 9, 11)
    contracts = {symbol: f"{symbol.upper()}2701" for symbol in products}
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(Exchange(code="SHFE", name="SHFE"))
        session.add_all(
            Instrument(
                symbol=symbol,
                name=symbol.upper(),
                exchange_code="SHFE",
                is_active=True,
            )
            for symbol in products
        )
        session.add_all(
            Contract(
                contract_code=contract,
                instrument_symbol=symbol,
                exchange_code="SHFE",
                listed_date=date(2026, 1, 1),
                expired_date=date(2027, 1, 1),
            )
            for symbol, contract in contracts.items()
        )
        session.add_all(
            TradingCalendar(
                exchange_code="SHFE",
                trade_date=day,
                is_trading_day=day in {prior_trading_day, trading_day},
                has_night_session=day == trading_day,
                provider="rqdata",
            )
            for day in (
                prior_trading_day,
                date(2026, 9, 12),
                date(2026, 9, 13),
                trading_day,
            )
        )
        for symbol in products:
            if symbol in night_products:
                session.add(
                    TradingSession(
                        exchange_code="SHFE",
                        instrument_symbol=symbol,
                        session_name="night",
                        start_time=time(21),
                        end_time=time(22, 30),
                        effective_from=trading_day,
                        effective_to=trading_day,
                        crosses_midnight=False,
                        is_active=True,
                        provider="rqdata",
                    )
                )
            session.add(
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol=symbol,
                    session_name="day",
                    start_time=time(9),
                    end_time=time(10),
                    effective_from=trading_day,
                    effective_to=trading_day,
                    crosses_midnight=False,
                    is_active=True,
                    provider="rqdata",
                )
            )
        session.commit()

        def recovery_sessions(symbol: str, day: date) -> tuple[SessionWindow, ...]:
            calendar = session.scalar(
                select(TradingCalendar).where(
                    TradingCalendar.exchange_code == "SHFE",
                    TradingCalendar.trade_date == day,
                )
            )
            assert calendar is not None and calendar.is_trading_day
            return tuple(
                resolved.window
                for resolved in resolved_session_windows_for_trading_day(
                    session,
                    exchange="SHFE",
                    symbol=symbol,
                    trading_day=day,
                )
                if not resolved.is_night or calendar.has_night_session
            )

        class RecoveryClient:
            def __init__(self) -> None:
                self.requests: dict[str, object] = {}
                self.calls: list[tuple[str, date, date, str]] = []

            def price(self, contract, start, end, frequency):
                self.calls.append((contract, start, end, frequency))
                request = self.requests[contract]
                rows = []
                for index, endpoint in enumerate(request.endpoints(), start=1):
                    value = Decimal(100 + index)
                    rows.append(
                        {
                            "order_book_id": contract,
                            "datetime": endpoint.isoformat(),
                            "trading_date": trading_day.isoformat(),
                            "open": str(value),
                            "high": str(value + 1),
                            "low": str(value - 1),
                            "close": str(value + Decimal("0.5")),
                            "volume": str(index),
                            "turnover": str(index * 100),
                            "open_interest": str(1000 + index),
                        }
                    )
                return rows

        client = RecoveryClient()
        adapter = RQDataLiveRecoveryAdapter(client)
        redis = FakeRedis()
        store = RedisLiveStore(redis)

        class SynchronousRecoveryWorker:
            def __init__(self) -> None:
                self.batches: list[tuple[object, ...]] = []
                self.outcomes: list[tuple[str, str]] = []

            @staticmethod
            def due(_now):
                return True

            def schedule(self, requests, _now):
                self.batches.append(requests)
                for request in requests:
                    client.requests[request.contract] = request
                    outcome = recover_product(
                        store,
                        request,
                        adapter,
                        clock=lambda request=request: request.cutoff
                        + timedelta(seconds=1),
                    )
                    self.outcomes.append((request.symbol, outcome))

        worker = SynchronousRecoveryWorker()
        service = LiveMarketService(
            provider_factory=lambda: RQDataLiveProvider(FakeLiveClient()),
            dominant_source=FakeDominants(
                {
                    (symbol, trading_day): contract
                    for symbol, contract in contracts.items()
                }
            ),
            phase_resolver=MarketPhaseResolver(session),
            store=store,
            operational_products=products,
            recovery_sessions=recovery_sessions,
        )
        service._recovery_worker = worker

        monday_open = datetime(2026, 9, 14, 9, 0, 3, tzinfo=SHANGHAI)
        assert service.reconcile(monday_open) is None
        snapshot = store.subscriptions(trading_day)
        assert snapshot == contracts
        assert len(worker.batches[0]) == 60
        open_night_targets = {
            request.symbol
            for request in worker.batches[0]
            if request.endpoints()
        }
        assert open_night_targets == night_products
        assert len(client.calls) == 45
        assert all(
            start == end == trading_day and frequency == "1m"
            for _contract, start, end, frequency in client.calls
        )

        later_cutoff = datetime(2026, 9, 14, 9, 15, 3, tzinfo=SHANGHAI)
        assert service.reconcile(later_cutoff) is None
        assert len(worker.batches[1]) == 60
        assert len(client.calls) == 105
        assert all(
            start == end == trading_day and frequency == "1m"
            for _contract, start, end, frequency in client.calls
        )
        assert all(
            request.sessions == recovery_sessions(request.symbol, trading_day)
            for batch in worker.batches
            for request in batch
        )

        night_symbol = min(night_products)
        day_symbol = next(symbol for symbol in products if symbol not in night_products)
        assert len(store.bars_after(trading_day, night_symbol, "15m", None)) == 7
        assert len(store.bars_after(trading_day, night_symbol, "60m", None)) == 2
        assert len(store.bars_after(trading_day, day_symbol, "15m", None)) == 1
        assert store.bars_after(trading_day, day_symbol, "60m", None) == ()

        class EmptyHistory:
            @staticmethod
            def query_page(request):
                return MarketSeriesPageResult(
                    request_identity={"symbol": request.symbol},
                    bars=(),
                    canonical_coverage=None,
                    has_more_before=False,
                    next_before=None,
                    resolved_contract_segments=(),
                )

            @staticmethod
            def validate_actual_dominant_alert_window(**_kwargs):
                return None

        market_read = MarketReadService(
            market_data=EmptyHistory(),
            phase_resolver=MarketPhaseResolver(session),
            operational_products=products,
            live_store=store,
        )
        day_end = datetime(2026, 9, 14, 9, 15, tzinfo=SHANGHAI).astimezone(UTC)
        night_window = market_read.bars_until(
            SeriesPageQuery("actual_dominant", night_symbol, "15m"),
            trading_day=trading_day,
            end=day_end,
            limit=64,
        )
        day_window = market_read.bars_until(
            SeriesPageQuery("actual_dominant", day_symbol, "15m"),
            trading_day=trading_day,
            end=day_end,
            limit=64,
        )
        assert night_window.contract == contracts[night_symbol]
        assert day_window.contract == contracts[day_symbol]
        assert night_window.bars[-1] == CanonicalBar(
            day_end,
            trading_day,
            Decimal("191"),
            Decimal("206"),
            Decimal("190"),
            Decimal("205.5"),
            Decimal("1470"),
            Decimal("147000"),
            Decimal("1105"),
        )
        assert day_window.bars[-1] == CanonicalBar(
            day_end,
            trading_day,
            Decimal("101"),
            Decimal("116"),
            Decimal("100"),
            Decimal("115.5"),
            Decimal("120"),
            Decimal("12000"),
            Decimal("1015"),
        )
        night_end = datetime(
            2026, 9, 11, 22, 30, tzinfo=SHANGHAI
        ).astimezone(UTC)
        hour_window = market_read.bars_until(
            SeriesPageQuery("actual_dominant", night_symbol, "60m"),
            trading_day=trading_day,
            end=night_end,
            limit=64,
        )
        assert hour_window.bars[-1] == CanonicalBar(
            night_end,
            trading_day,
            Decimal("161"),
            Decimal("191"),
            Decimal("160"),
            Decimal("190.5"),
            Decimal("2265"),
            Decimal("226500"),
            Decimal("1090"),
        )
        assert not night_window.notification_eligible

        class Evaluator:
            @staticmethod
            def evaluate_candidates(_market_read, window):
                return (
                    AlertObservationCandidate(
                        window.cutoff,
                        window.trading_day,
                        window.contract,
                        ("buy",),
                    ),
                )

        class Sender:
            calls = 0

            def send(self, _message):
                self.calls += 1
                return ProviderAcceptance("accepted")

        session.add(
            AlertRule(
                rule_code=HTDY_ALERT_RULE_CODE,
                enabled=True,
                scope_product_frequencies={night_symbol: ["15m"]},
            )
        )
        session.commit()
        sender = Sender()
        runtime = AlertRuntime(
            session_factory=lambda: Session(engine),
            market_read_factory=lambda _session: market_read,
            evaluators={HTDY_ALERT_RULE_CODE: Evaluator()},
            sender=sender,
            operational_products=(night_symbol,),
            taxonomy={night_symbol: SimpleNamespace(name=night_symbol.upper())},
            clock=lambda: datetime(2026, 9, 14, 9, 31, tzinfo=SHANGHAI),
        )

        def trigger_payload(bar: CanonicalBar) -> dict[str, str | None]:
            return {
                "bar_end": bar.bar_end.isoformat(),
                "trading_day": bar.trading_day.isoformat(),
                "open": str(bar.open),
                "high": str(bar.high),
                "low": str(bar.low),
                "close": str(bar.close),
                "volume": str(bar.volume),
                "turnover": None if bar.turnover is None else str(bar.turnover),
                "open_interest": (
                    None if bar.open_interest is None else str(bar.open_interest)
                ),
            }

        runtime.process_message(
            f"live:bar:{night_symbol}:15m",
            trigger_payload(night_window.bars[-1]),
        )
        with Session(engine) as event_session:
            assert event_session.scalar(select(func.count()).select_from(AlertEvent)) == 0
        assert sender.calls == 0

        new_end = datetime(2026, 9, 14, 9, 30, tzinfo=SHANGHAI).astimezone(UTC)
        store.put_bar(
            trading_day,
            night_symbol,
            "15m",
            replace(night_window.bars[-1], bar_end=new_end),
            contract=contracts[night_symbol],
        )
        new_window = market_read.bars_until(
            SeriesPageQuery("actual_dominant", night_symbol, "15m"),
            trading_day=trading_day,
            end=new_end,
            limit=64,
        )
        assert new_window.notification_eligible
        runtime.process_message(
            f"live:bar:{night_symbol}:15m",
            trigger_payload(new_window.bars[-1]),
        )
        assert redis.published == [
            ("market:state", '{"trading_day":"2026-09-14"}')
        ]
        with Session(engine) as event_session:
            assert event_session.scalar(select(func.count()).select_from(AlertEvent)) == 1
        assert sender.calls == 1

    engine.dispose()


@pytest.mark.parametrize(
    "failure",
    ("missing", "wrong_day", "wrong_contract", "future", "snapshot_drift"),
)
def test_catalog_derived_recovery_failure_never_commits_partial_results(
    failure: str,
) -> None:
    """Catches accepting corrupt provider facts after real Session resolution."""
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter

    trading_day = date(2026, 9, 14)
    contract = "RB2701"
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add_all(
            (
                Exchange(code="SHFE", name="SHFE"),
                Instrument(
                    symbol="rb",
                    name="RB",
                    exchange_code="SHFE",
                    is_active=True,
                ),
                Contract(
                    contract_code=contract,
                    instrument_symbol="rb",
                    exchange_code="SHFE",
                    listed_date=date(2026, 1, 1),
                    expired_date=date(2027, 1, 1),
                ),
            )
        )
        session.add_all(
            TradingCalendar(
                exchange_code="SHFE",
                trade_date=day,
                is_trading_day=day in {date(2026, 9, 11), trading_day},
                has_night_session=day == trading_day,
                provider="rqdata",
            )
            for day in (
                date(2026, 9, 11),
                date(2026, 9, 12),
                date(2026, 9, 13),
                trading_day,
            )
        )
        session.add_all(
            (
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="rb",
                    session_name="night",
                    start_time=time(21),
                    end_time=time(22, 30),
                    effective_from=trading_day,
                    effective_to=trading_day,
                    crosses_midnight=False,
                    is_active=True,
                    provider="rqdata",
                ),
                TradingSession(
                    exchange_code="SHFE",
                    instrument_symbol="rb",
                    session_name="day",
                    start_time=time(9),
                    end_time=time(10),
                    effective_from=trading_day,
                    effective_to=trading_day,
                    crosses_midnight=False,
                    is_active=True,
                    provider="rqdata",
                ),
            )
        )
        session.commit()
        sessions = tuple(
            resolved.window
            for resolved in resolved_session_windows_for_trading_day(
                session,
                exchange="SHFE",
                symbol="rb",
                trading_day=trading_day,
            )
        )

    cutoff = datetime(2026, 9, 14, 9, 0, 3, tzinfo=SHANGHAI)
    request = LiveRecoveryRequest(
        trading_day,
        "rb",
        contract,
        (("rb", contract),),
        sessions,
        cutoff,
    )
    rows = [
        {
            "order_book_id": contract,
            "datetime": endpoint.isoformat(),
            "trading_date": trading_day.isoformat(),
            "open": "100",
            "high": "101",
            "low": "99",
            "close": "100",
            "volume": "1",
            "turnover": "100",
            "open_interest": "10",
        }
        for endpoint in request.endpoints()
    ]
    assert len(rows) == 90
    if failure == "missing":
        rows.pop(0)
    elif failure == "wrong_day":
        rows[0]["trading_date"] = "2026-09-11"
    elif failure == "wrong_contract":
        rows[0]["order_book_id"] = "RB2705"

    class Client:
        calls = 0

        def price(self, requested_contract, start, end, frequency):
            self.calls += 1
            assert (requested_contract, start, end, frequency) == (
                contract,
                trading_day,
                trading_day,
                "1m",
            )
            return rows

    client = Client()
    redis = FakeRedis()
    store = RedisLiveStore(redis)
    store.set_subscriptions(trading_day, {"rb": contract})
    if failure == "snapshot_drift":
        store.set_subscriptions(trading_day, {"rb": "RB2705"})
    adapter = RQDataLiveRecoveryAdapter(client)
    if failure == "future":
        source = adapter(request)
        future = replace(
            source[-1],
            bar_end=source[-1].bar_end + timedelta(minutes=1),
        )

        def fetch(_request):
            return (*source, future)
    else:
        fetch = adapter

    with pytest.raises((ValueError, RuntimeError)):
        recover_product(
            store,
            request,
            fetch,
            clock=lambda: cutoff + timedelta(seconds=1),
        )

    for frequency in ("1m", "5m", "15m", "30m", "60m"):
        assert store.bars_after(trading_day, "rb", frequency, None) == ()
    assert store.recovery_state(trading_day, "rb", contract) is None
    assert redis.published == []
    if failure == "snapshot_drift":
        assert client.calls == 0
    engine.dispose()


def test_night_endpoints_keep_exchange_trading_day():
    from app.market_data.live_recovery import LiveRecoveryRequest, recover_product

    redis = FakeRedis()
    store = RedisLiveStore(redis)
    day = date(2026, 9, 7)
    start = datetime(2026, 9, 4, 13, tzinfo=UTC)
    store.set_subscriptions(day, {"rb": "RB2611"})
    request = LiveRecoveryRequest(
        day,
        "rb",
        "RB2611",
        (("rb", "RB2611"),),
        (SessionWindow(start, start + timedelta(hours=2)),),
        start + timedelta(minutes=15, seconds=3),
    )
    bars = tuple(
        replace(_bar(1), bar_end=end, trading_day=day) for end in request.endpoints()
    )
    assert (
        recover_product(store, request, lambda _: bars, clock=lambda: request.cutoff)
        == "RECOVERED"
    )
    assert all(
        bar.trading_day == day for bar in store.bars_after(day, "rb", "1m", None)
    )


def test_lua_atomic_commit_and_concurrent_live_conflict_on_isolated_redis():
    import os
    import redis as redis_module
    from app.market_data.live_recovery import recover_product

    port = os.getenv("GUIYI_TEST_REDIS_PORT")
    if port is None:
        pytest.skip("requires explicitly created disposable Redis container")
    assert int(port) != 6379
    client = redis_module.Redis(host="127.0.0.1", port=int(port), decode_responses=True)
    fake, _, request, bars = _setup()
    store = RedisLiveStore(client)
    # Only this known disposable instance is used; no configured app Redis import.
    for key, value in fake.values.items():
        client.set(key, value)
    for key, values in fake.zsets.items():
        client.delete(key)
        client.zadd(key, values)
    state_key = store._recovery_key(
        request.trading_day, request.symbol, request.contract
    )
    for key in client.scan_iter(match=f"{state_key}*"):
        client.delete(key)
    for frequency in ("5m", "15m", "30m", "60m"):
        client.delete(store._bars_key(request.trading_day, request.symbol, frequency))
    original = store.bars_after(request.trading_day, "rb", "1m", None)

    def concurrent(req):
        store.put_bar(req.trading_day, "rb", "1m", bars[0], contract="RB2505")
        return bars

    with pytest.raises(ValueError, match="SNAPSHOT_DRIFT"):
        recover_product(store, request, concurrent, clock=lambda: request.cutoff)
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
    assert store.bars_after(request.trading_day, "rb", "15m", None) == ()
    # Recreate the gap only in the isolated fixture, then run the successful script.
    client.zremrangebyscore(
        store._bars_key(request.trading_day, "rb", "1m"),
        int(bars[0].bar_end.timestamp() * 1000),
        int(bars[0].bar_end.timestamp() * 1000),
    )
    retry = replace(request, cutoff=request.cutoff + timedelta(minutes=1))
    # Keep expected endpoints at 15m while exercising persisted 60-second retry.
    retry = replace(
        retry, sessions=(SessionWindow(request.sessions[0].start, bars[-1].bar_end),)
    )
    assert (
        recover_product(store, retry, lambda _: bars, clock=lambda: retry.cutoff)
        == "RECOVERED"
    )
    assert (
        len(store.bars_after(request.trading_day, "rb", "1m", None))
        == len(original) + 1
    )
    assert len(store.bars_after(request.trading_day, "rb", "15m", None)) == 1
    assert store.recovery_state(request.trading_day, "rb", "RB2505").revision == 1
    with pytest.raises(ValueError, match="LIVE_BAR_CONFLICT"):
        store.put_bar(
            request.trading_day,
            "rb",
            "1m",
            replace(bars[0], volume=bars[0].volume + 1),
            contract="RB2505",
        )
    assert store.bars_after(request.trading_day, "rb", "1m", None)[0] == bars[0]


def test_default_off_never_schedules_recovery(monkeypatch):
    from app.market_data.live_market import LiveMarketService
    from tests.data_foundation.test_live_market import FakeDominants, FakePhases, _phase

    _, store, request, _ = _setup()
    monkeypatch.setattr(
        "app.market_data.live_recovery.LiveRecoveryWorker",
        lambda *a, **k: pytest.fail("OFF instantiated worker"),
    )
    service = LiveMarketService(
        provider_factory=lambda: None,
        dominant_source=FakeDominants({("rb", request.trading_day): "RB2505"}),
        phase_resolver=FakePhases(
            {"rb": _phase("rb", request.trading_day, request.sessions[0])}
        ),
        store=store,
        operational_products=("rb",),
    )
    service._schedule_recovery(request.cutoff, {})
    assert service._recovery_worker is None


@pytest.mark.parametrize(
    "failure", ["wrong_contract", "wrong_day", "ohlcv", "duplicate", "missing"]
)
def test_public_adapter_validates_identity_schema_and_prefix(failure):
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_market import _bar_payload
    from app.market_data.live_recovery import recover_product

    _, store, request, bars = _setup()
    rows = []
    for bar in bars:
        row = _bar_payload(bar)
        row.update(
            datetime=row.pop("bar_end"),
            trading_date=row.pop("trading_day"),
            order_book_id=request.contract,
        )
        rows.append(row)
    if failure == "wrong_contract":
        rows[0]["order_book_id"] = "RB2510"
    elif failure == "wrong_day":
        rows[0]["trading_date"] = "2025-01-03"
    elif failure == "ohlcv":
        rows[0]["high"] = "0"
    elif failure == "duplicate":
        rows.append(rows[0])
    elif failure == "missing":
        rows.pop(0)

    class Client:
        def price(self, contract, start, end, frequency):
            assert (
                contract == "RB2505"
                and start == end == request.trading_day
                and frequency == "1m"
            )
            return rows

    with pytest.raises((ValueError, RuntimeError)):
        recover_product(
            store,
            request,
            RQDataLiveRecoveryAdapter(Client()),
            clock=lambda: request.cutoff,
        )
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None


def test_full_1m_missing_derived_is_repaired_without_provider_or_attempt():
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    store.put_bar(request.trading_day, "rb", "1m", bars[0], contract="RB2505")
    assert (
        recover_product(
            store,
            request,
            lambda _: pytest.fail("derived repair called provider"),
            clock=lambda: request.cutoff,
        )
        == "RECOVERED"
    )
    assert len(store.bars_after(request.trading_day, "rb", "15m", None)) == 1
    assert store.recovery_state(request.trading_day, "rb", "RB2505").revision == 1
    assert not any(":attempt:" in key for key in redis.values)
    assert redis.published == []
    assert (
        recover_product(
            store,
            request,
            lambda _: pytest.fail("no gap called provider"),
            clock=lambda: request.cutoff,
        )
        == "NO_GAP"
    )


def test_adapter_allows_legal_endpoint_inside_finalization_delay():
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_market import _bar_payload

    _, _, request, bars = _setup()
    request = replace(request, cutoff=bars[-1].bar_end + timedelta(seconds=1))
    rows = []
    for bar in bars:
        row = _bar_payload(bar)
        row.update(
            datetime=row.pop("bar_end"),
            trading_date=row.pop("trading_day"),
            order_book_id=request.contract,
        )
        rows.append(row)

    class Client:
        def price(self, *args):
            return rows

    assert RQDataLiveRecoveryAdapter(Client())(request) == bars[:-1]


def test_worker_logs_bounded_codes_with_identity_without_provider_exception(caplog):
    import logging
    from app.market_data.live_recovery import LiveRecoveryWorker

    _, store, request, _ = _setup()

    def factory():
        def fetch(_):
            raise ValueError("secret provider message")

        return fetch

    worker = LiveRecoveryWorker(store, factory, clock=lambda: request.cutoff)
    with caplog.at_level(logging.INFO, logger="app.market_data.live_recovery"):
        worker._run((request,))
    record = caplog.records[-1]
    assert record.getMessage() == "LIVE_RECOVERY_FAILED"
    assert record.diagnostic_fields == {
        "symbol": "rb",
        "contract": "RB2505",
        "trading_day": "2025-01-02",
    }
    assert "secret provider message" not in caplog.text
    worker._executor.shutdown(wait=True)


@pytest.mark.parametrize("kind", ["denied", "quota"])
def test_provider_initialization_failure_opens_persisted_circuit(monkeypatch, kind):
    from app.market_data.rqdata_adapter import RQDataLiveRecoveryAdapter
    from app.market_data.live_recovery import recover_product

    redis, store, request, _ = _setup()

    class InitError(RuntimeError):
        code = "RQDATA_QUOTA_EXCEEDED" if kind == "quota" else ""

    def denied():
        raise InitError("quota exhausted" if kind == "quota" else "permission denied")

    monkeypatch.setattr("app.market_data.rqdata_adapter.RQDataClient", denied)
    with pytest.raises(RuntimeError, match="PROVIDER_(QUOTA_EXHAUSTED|ACCESS_DENIED)"):
        recover_product(
            store, request, RQDataLiveRecoveryAdapter(), clock=lambda: request.cutoff
        )
    assert redis.get("live:recovery:circuit:2025-01-02") == "STOPPED"


def test_recovery_samples_clock_and_commits_only_inside_guard():
    from contextlib import contextmanager
    from app.market_data.live_recovery import recover_product

    _, store, request, bars = _setup()
    entered = []

    @contextmanager
    def guard():
        entered.append(True)
        yield
        entered.pop()

    def clock():
        assert entered == [True]
        return request.cutoff

    assert (
        recover_product(store, request, lambda _: bars, clock=clock, commit_guard=guard)
        == "RECOVERED"
    )
    assert entered == []


def test_busy_commit_guard_aborts_bars_and_barrier():
    from contextlib import contextmanager
    from app.market_data.live_recovery import recover_product

    redis, store, request, bars = _setup()
    original = {key: dict(value) for key, value in redis.zsets.items()}

    @contextmanager
    def busy():
        raise ValueError("LIVE_RECOVERY_BUSY")
        yield

    with pytest.raises(ValueError, match="LIVE_RECOVERY_BUSY"):
        recover_product(
            store,
            request,
            lambda _: bars,
            clock=lambda: request.cutoff,
            commit_guard=busy,
        )
    assert redis.zsets == original
    assert store.recovery_state(request.trading_day, "rb", "RB2505") is None
