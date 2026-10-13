from datetime import timedelta

import pytest

from app.market_data.domain import BarFrequency
from app.market_data.market_data_service import MarketDataError
from app.market_data.market_read_service import MarketReadWindowError
from test_market_read_service import (
    DAY_2, LIVE_END, _bar, _replay_service, _replay_window,
)


def test_direction_uses_expected_endpoint_not_latest_available_bar():
    endpoint = LIVE_END - timedelta(minutes=15)
    service, reader = _replay_service((_bar(endpoint, DAY_2),), ())
    reader.expected_contract_replay_endpoints = lambda **kwargs: ((endpoint, DAY_2),)
    result = service.subing_direction_window(_replay_window(), BarFrequency.M15)
    assert result.cutoff == endpoint
    assert result.bars == (_bar(endpoint, DAY_2),)
    reader.expected_contract_replay_endpoints = lambda **kwargs: ((LIVE_END, DAY_2),)
    with pytest.raises(MarketReadWindowError, match='MARKET_READ_CUTOFF_BAR_MISSING'):
        service.subing_direction_window(_replay_window(), BarFrequency.M15)


def test_direction_rejects_incomplete_ema_prefix():
    service, reader = _replay_service((_bar(LIVE_END, DAY_2),), ())
    reader.expected_contract_replay_endpoints = lambda **kwargs: ((LIVE_END, DAY_2),)
    def incomplete(**kwargs):
        assert kwargs['after'] is None
        raise MarketDataError('CONTRACT_REPLAY_COVERAGE_UNAVAILABLE')
    reader.validate_contract_replay_coverage = incomplete
    with pytest.raises(MarketReadWindowError, match='MARKET_READ_CONTRACT_HISTORY_UNAVAILABLE'):
        service.subing_direction_window(_replay_window(), BarFrequency.M15)


def test_direction_rejects_one_minute():
    service, _ = _replay_service((), ())
    with pytest.raises(MarketReadWindowError, match='MARKET_READ_IDENTITY_UNSUPPORTED'):
        service.subing_direction_window(_replay_window(), BarFrequency.M1)


@pytest.mark.parametrize('frequency', [BarFrequency.D1, BarFrequency.W1])
def test_canonical_direction_never_reads_live_and_keeps_whole_prefix(frequency):
    from dataclasses import replace
    service, reader = _replay_service((_bar(LIVE_END, DAY_2),), ())
    original = reader.query_page
    reader.query_page = lambda request: original(replace(request, frequency=BarFrequency.M15))
    reader.expected_contract_replay_endpoints = lambda **kwargs: ((LIVE_END, DAY_2),)
    def forbidden(**kwargs):
        raise AssertionError('daily/weekly cannot consume Live')
    service._verified_live_bars = forbidden
    result = service.subing_direction_window(_replay_window(), frequency)
    assert result.frequency == frequency.value
    assert result.after is None
    assert result.bars == (_bar(LIVE_END, DAY_2),)


@pytest.mark.parametrize('frequency', [BarFrequency.D1, BarFrequency.W1])
def test_daily_weekly_replay_proves_canonical_owner_without_redis(frequency):
    from dataclasses import replace
    from app.market_data.domain import ResolvedContractSegment, SeriesKind
    service, reader = _replay_service((_bar(LIVE_END, DAY_2),), ())
    original = reader.query_page
    def query(request):
        page = original(replace(request, frequency=BarFrequency.M15,
                                series_kind=SeriesKind.CONTRACT, contract='RB2610', limit=2000))
        if request.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return replace(page, resolved_contract_segments=(ResolvedContractSegment('RB2610', DAY_2, DAY_2),))
        return page
    reader.query_page = query
    class ForbiddenLive:
        def __getattr__(self, name):
            raise AssertionError('daily/weekly cannot consume Redis authority')
    service._live_store = ForbiddenLive()
    decision = replace(_replay_window(), frequency=frequency.value)
    result = service.current_contract_replay_window(decision, after=None)
    assert result.bars == decision.bars
    reader.query_page = lambda request: replace(query(request), resolved_contract_segments=())
    with pytest.raises(MarketReadWindowError, match='MARKET_READ_CONTRACT_UNAVAILABLE'):
        service.current_contract_replay_window(decision, after=None)


def test_real_daily_weekly_direction_uses_completed_session_and_week(tmp_path):
    from datetime import UTC, date, datetime
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.market_data.catalog import MarketCatalog
    from app.market_data.domain import DatasetKey
    from app.market_data.market_data_service import MarketDataService
    from app.market_data.market_read_service import MarketReadService
    from app.market_data.storage import CanonicalMonthlyStore, PublishRequest
    from app.models import TradingCalendar
    from test_market_read_service import (
        _add_replay_metadata, _ContractReplayLiveStore, _ForbiddenPhaseReader,
    )
    from dataclasses import replace

    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    monday = date(2026, 8, 24)
    all_days = tuple(monday + timedelta(days=i) for i in range(14))
    weekdays = tuple(day for day in all_days if day.weekday() < 5)
    with Session(engine) as session:
        _add_replay_metadata(session, weekdays)
        session.add_all(TradingCalendar(exchange_code='SHFE', trade_date=day,
                                       is_trading_day=False, provider='rqdata')
                        for day in all_days if day.weekday() >= 5)
        session.commit()
        catalog = MarketCatalog(session, tmp_path)
        store = CanonicalMonthlyStore(tmp_path)
        mds = MarketDataService(catalog, store)
        decision_end = datetime(2026, 9, 2, 1, 45, tzinfo=UTC)
        decision_day = date(2026, 9, 2)
        full = {}
        for frequency in (BarFrequency.D1, BarFrequency.W1):
            endpoints = mds.expected_contract_replay_endpoints(
                symbol='rb', contract='RB2610', frequency=frequency,
                trading_day=weekdays[-1], cutoff=datetime.max.replace(tzinfo=UTC))
            bars = tuple(_bar(end, day) for end, day in endpoints)
            full[frequency] = bars
            for month in (8, 9):
                monthly = tuple(bar for bar in bars if bar.trading_day.month == month)
                catalog.register_partition(store.publish(PublishRequest(
                    DatasetKey('contract', 'rb', 'RB2610', frequency), 2026, month,
                    monthly, tuple(bar.bar_end for bar in monthly))))
        session.commit()
        service = MarketReadService(market_data=mds, phase_resolver=_ForbiddenPhaseReader(),
                                    operational_products=('rb',), live_store=_ContractReplayLiveStore(()))
        decision = replace(_replay_window(), cutoff=decision_end, trading_day=decision_day,
                           bars=(_bar(decision_end, decision_day),))
        daily = service.subing_direction_window(decision, BarFrequency.D1)
        weekly = service.subing_direction_window(decision, BarFrequency.W1)
        assert daily.trading_day == date(2026, 9, 1)
        assert daily.cutoff == datetime(2026, 9, 1, 2, tzinfo=UTC)
        assert weekly.trading_day == date(2026, 8, 28)
        assert weekly.cutoff == datetime(2026, 8, 28, 2, tzinfo=UTC)
        assert daily.bars == tuple(bar for bar in full[BarFrequency.D1] if bar.bar_end <= decision_end)
        assert weekly.bars == full[BarFrequency.W1][:1]
    engine.dispose()


def test_alignment_derived_cache_reuses_only_identical_verified_input(monkeypatch):
    from dataclasses import replace
    from decimal import Decimal
    import app.alerts.subing_alignment as alignment
    bars = tuple(_bar(LIVE_END - timedelta(minutes=15 * offset), DAY_2) for offset in range(30, -1, -1))
    expected = alignment._verified_period_facts("RB2610", "15m", LIVE_END, bars)
    original = alignment.step_ema
    def forbidden(*_args, **_kwargs):
        raise AssertionError("same verified EMA prefix must not be recomputed")
    monkeypatch.setattr(alignment, "step_ema", forbidden)
    reused = alignment._verified_period_facts("RB2610", "15m", LIVE_END, bars)
    assert reused == expected
    reused["direction"] = "mutated"
    assert alignment._verified_period_facts("RB2610", "15m", LIVE_END, bars) == expected
    monkeypatch.setattr(alignment, "step_ema", original)
    changed = (*bars[:-1], replace(bars[-1], close=Decimal("1000"), high=Decimal("1000")))
    assert alignment._verified_period_facts("RB2610", "15m", LIVE_END, changed)["input_snapshot_hash"] != expected["input_snapshot_hash"]
    assert alignment._verified_period_facts("RB2701", "15m", LIVE_END, bars)["input_snapshot_hash"] != expected["input_snapshot_hash"]
    assert alignment._verified_period_facts("RB2610", "30m", LIVE_END, bars)["input_snapshot_hash"] != expected["input_snapshot_hash"]


def test_intraday_replay_reads_one_authoritative_physical_prefix():
    service, reader = _replay_service((_bar(LIVE_END - timedelta(minutes=15), DAY_2),), (_bar(LIVE_END, DAY_2),))
    calls = []
    def prefix(**kwargs):
        calls.append(kwargs)
        return tuple(bar for bar in reader._bars if bar.bar_end <= kwargs["cutoff"])
    reader.read_alert_physical_prefix = prefix
    reader.query_page = lambda *_args: pytest.fail("intraday full prefix must not repeatedly paginate/validate")
    assert len(service.current_contract_replay_window(_replay_window(), after=None).bars) == 2
    assert len(calls) == 1
    assert calls[0]["cutoff"] == LIVE_END and calls[0]["after"] is None
