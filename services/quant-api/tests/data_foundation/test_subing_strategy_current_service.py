from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from importlib import import_module
from types import MappingProxyType, SimpleNamespace

import pytest

from app.market_data.domain import BarFrequency, ResolvedContractSegment, SeriesKind
from app.market_data.aggregation import SessionWindow
from app.market_data.market_data_service import MarketDataError
from app.market_data.subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchItem,
    SubingDailyWatchSnapshot,
)
from app.market_data.subing_ema_trend import PriceSide, SubingStitchedEmaTrendSnapshot
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_strategy.contracts import (
    SubingStrategyDirection,
    SubingStrategyPositionState,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyDirectionContext,
)
from app.market_data.subing_strategy.engine import SubingStrategySegmentResult
from app.market_data.subing_strategy.policy import load_subing_strategy_policy

from research.subing_lifecycle_fixtures import _accepted_calibration
from research.subing_strategy_fixtures import (
    FakeDirectionContextResolver,
    FakeSegmentLoader,
    loaded_series,
    recorded_strategy_stream,
)
from research.test_subing_strategy_engine import CONTRACT, _bar, _context


SOURCE_DAY = date(2026, 8, 3)
TARGET_DAY = date(2026, 8, 4)
SEGMENT_START = date(2026, 8, 1)
NOW = datetime(2026, 8, 4, 3, 0, tzinfo=UTC)


def _current_module():
    try:
        return import_module("app.market_data.subing_strategy.current_service")
    except ModuleNotFoundError:
        pytest.fail("current Strategy projection service is not implemented")


def _trend(frequency: BarFrequency) -> SubingStitchedEmaTrendSnapshot:
    return SubingStitchedEmaTrendSnapshot(
        timeframe=frequency,
        bar_end=datetime(2026, 8, 3, 7, 0, tzinfo=UTC),
        trading_day=SOURCE_DAY,
        contract=CONTRACT,
        current_segment_start_trading_day=SEGMENT_START,
        warmup_start_trading_day=date(2026, 6, 1),
        warmup_bar_count=30,
        warmup_segment_count=2,
        history_mode="rank1_stitched_raw",
        close=Decimal("102"),
        ema21=Decimal("100"),
        price_side=PriceSide.ABOVE,
        slope_5_raw=Decimal("1"),
        slope_10_raw=Decimal("2"),
        slope_5_bps_per_bar=Decimal("1"),
        slope_10_bps_per_bar=Decimal("2"),
    )


def _snapshot(
    *,
    source_day: date = SOURCE_DAY,
    target_day: date = TARGET_DAY,
) -> SubingDailyWatchSnapshot:
    return SubingDailyWatchSnapshot(
        source_trading_day=source_day,
        target_trading_day=target_day,
        generated_at=datetime(2026, 8, 3, 10, 30, tzinfo=UTC),
        items=(
            SubingDailyWatchItem(
                symbol="jm",
                product_name="焦煤",
                sector="黑色",
                decision=SubingDailyWatchDecision.LONG_WATCH,
                reason_codes=("D1_H1_LONG_ALIGNED",),
                daily=_trend(BarFrequency.D1),
                hourly=_trend(BarFrequency.H1),
                unavailable_reasons=(),
            ),
        ),
    )


class _Store:
    def __init__(self, value: SubingDailyWatchSnapshot | None) -> None:
        self.value = value
        self.reads = 0

    def read_current(self) -> SubingDailyWatchSnapshot | None:
        self.reads += 1
        return self.value


class _MarketRead:
    def __init__(self, live=None, *, contract: str = CONTRACT) -> None:
        self.live = live or {}
        self.contract = contract
        self.trading_day = TARGET_DAY
        self.state_requests = []
        self.live_requests = []

    def state(self, identity, now):
        self.state_requests.append((identity, now))
        return SimpleNamespace(
            symbol=identity.symbol,
            series_kind=identity.series_kind.value,
            frequency=identity.frequency.value,
            trading_day=self.trading_day,
            live_eligible=True,
            live_available=bool(self.live),
            live_contract=self.contract,
        )

    def live_snapshot(self, identity, after, now):
        self.live_requests.append((identity, after, now))
        return self.live.get(identity.frequency, ())


class _CurrentLoader(FakeSegmentLoader):
    def sessions(self, *, symbol, trading_days):
        days = tuple(trading_days)
        self.session_requests.append((symbol, days))
        bars = self.result.results[BarFrequency.M15].bars
        anchor = bars[0].bar_end
        return MappingProxyType(
            {
                day: (
                    SessionWindow(
                        start=anchor - timedelta(minutes=15),
                        end=anchor + timedelta(hours=12),
                    ),
                )
                for day in days
            }
        )


def _canonical_stream():
    first = replace(_bar(1), trading_day=SOURCE_DAY)
    second = replace(_bar(2), trading_day=SOURCE_DAY)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, SOURCE_DAY)
    return (first, second), loaded_series(
        segments=(segment,),
        bars_1m=(first, second),
        bars_5m=(first, second),
        bars_15m=(first, second),
    )


def _service(*, live=None, snapshot: SubingDailyWatchSnapshot | None = None):
    module = _current_module()
    bars, loaded = _canonical_stream()
    loader = _CurrentLoader(loaded)
    historical = FakeDirectionContextResolver(
        {
            SOURCE_DAY: replace(
                _context(bars[0], SubingStrategyDirection.NO_NEW_ENTRY),
                target_trading_day=SOURCE_DAY,
            )
        }
    )
    store = _Store(_snapshot() if snapshot is None else snapshot)
    market_read = _MarketRead(live)
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=store,
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )
    return service, loader, historical, store, market_read


def _request(*, frequency: BarFrequency = BarFrequency.M15):
    module = _current_module()
    return module.SubingStrategyCurrentRequest(
        series_kind=SeriesKind.ACTUAL_DOMINANT,
        symbol="JM",
        frequency=frequency,
    )


def _empty_result(*, final=SubingStrategyPositionState.FLAT):
    return SubingStrategySegmentResult(
        actions=(),
        episodes=(),
        consumed_opportunity_ids=(),
        canceled_pending=(),
        pending_action=None,
        final_position=final,
    )


def test_current_request_supports_only_actual_dominant_15m() -> None:
    module = _current_module()

    with pytest.raises(ValueError, match="INVALID_SUBING_STRATEGY_CURRENT_REQUEST"):
        module.SubingStrategyCurrentRequest(
            series_kind=SeriesKind.ACTUAL_DOMINANT,
            symbol="jm",
            frequency=BarFrequency.M5,
        )


def test_current_restores_only_current_segment_and_uses_causal_contexts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, loader, historical, store, _market_read = _service()
    captured = {}
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_segment",
        lambda **kwargs: captured.update(kwargs) or _empty_result(),
    )

    result = service.current(_request(), NOW)

    assert loader.requests == [
        (
            "jm",
            (BarFrequency.M1, BarFrequency.M5, BarFrequency.M15),
            SEGMENT_START,
            SOURCE_DAY,
        )
    ]
    assert historical.requests == [("jm", (SOURCE_DAY,))]
    assert store.reads == 1
    assert captured["segment"] == ResolvedContractSegment(
        CONTRACT, SEGMENT_START, TARGET_DAY
    )
    assert captured["direction_contexts"][SOURCE_DAY].direction is (
        SubingStrategyDirection.NO_NEW_ENTRY
    )
    assert captured["direction_contexts"][TARGET_DAY].direction is (
        SubingStrategyDirection.LONG_ONLY
    )
    assert result.contract == CONTRACT
    assert result.segment_start_trading_day == SEGMENT_START
    assert result.direction_context.target_trading_day == TARGET_DAY


def test_runtime_restore_returns_the_shared_incremental_machine_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, *_ = _service()
    captured = {}
    expected = object()
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_machine",
        lambda **kwargs: captured.update(kwargs) or expected,
    )

    restored = service.restore_machine(symbol="jm", now=NOW)

    assert restored is expected
    assert captured["segment"] == ResolvedContractSegment(
        CONTRACT, SEGMENT_START, TARGET_DAY
    )
    assert captured["bars_1m"]
    assert captured["bars_5m"]
    assert captured["bars_15m"]


def test_restore_uses_latest_mapped_day_when_expected_session_has_no_occupancy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Next-session Daily Watch day must not fail restore when rank1 occupancy
    still ends on the last Canonical day."""
    service, _loader, _historical, _store, market_read = _service()
    previous_of_source = SOURCE_DAY - timedelta(days=1)

    def current_segment(_symbol: str, target: date):
        if target == TARGET_DAY:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if target <= SOURCE_DAY:
            return SimpleNamespace(
                symbol="jm",
                contract=CONTRACT,
                start_trading_day=SEGMENT_START,
                end_trading_day=SOURCE_DAY,
            )
        raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    service._current_segment = current_segment
    service._previous_trading_day = (
        lambda target: SOURCE_DAY if target == TARGET_DAY else previous_of_source
    )
    market_read.trading_day = TARGET_DAY
    captured: dict[str, object] = {}
    expected = object()
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_machine",
        lambda **kwargs: captured.update(kwargs) or expected,
    )

    restored = service.restore_machine(symbol="jm", now=NOW)

    assert restored is expected
    assert captured["segment"] == ResolvedContractSegment(
        CONTRACT, SEGMENT_START, SOURCE_DAY
    )
    assert captured["bars_15m"]
    assert market_read.live_requests == []


def test_restore_ignores_next_session_live_contract_when_occupancy_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overnight Live may already point at the next session contract."""
    service, _loader, _historical, _store, market_read = _service()
    previous_of_source = SOURCE_DAY - timedelta(days=1)

    def current_segment(_symbol: str, target: date):
        if target == TARGET_DAY:
            raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")
        if target <= SOURCE_DAY:
            return SimpleNamespace(
                symbol="jm",
                contract=CONTRACT,
                start_trading_day=SEGMENT_START,
                end_trading_day=SOURCE_DAY,
            )
        raise MarketDataError("MAIN_CONTRACT_MAP_MISSING")

    service._current_segment = current_segment
    service._previous_trading_day = (
        lambda target: SOURCE_DAY if target == TARGET_DAY else previous_of_source
    )
    market_read.trading_day = TARGET_DAY
    market_read.contract = "JM9999"
    market_read.live = {
        BarFrequency.M1: (_bar(9),),
        BarFrequency.M5: (_bar(9),),
        BarFrequency.M15: (_bar(9),),
    }
    captured: dict[str, object] = {}
    expected = object()
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_machine",
        lambda **kwargs: captured.update(kwargs) or expected,
    )

    restored = service.restore_machine(symbol="jm", now=NOW)

    assert restored is expected
    assert captured["segment"] == ResolvedContractSegment(
        CONTRACT, SEGMENT_START, SOURCE_DAY
    )
    assert market_read.live_requests == []


def test_current_reports_canonical_only_source_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service, *_ = _service()
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_segment",
        lambda **_kwargs: _empty_result(),
    )

    result = service.current(_request(), NOW)

    assert result.source_mode == "canonical"
    assert result.cutoff == _canonical_stream()[0][-1].bar_end


def test_current_merges_completed_live_as_separate_observation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical_stream()[0][-1]
    live_bar = replace(
        canonical,
        bar_end=canonical.bar_end + timedelta(minutes=15),
        trading_day=TARGET_DAY,
    )
    live = {
        BarFrequency.M1: (live_bar,),
        BarFrequency.M5: (live_bar,),
        BarFrequency.M15: (live_bar,),
    }
    service, *_tail, market_read = _service(live=live)
    captured = {}
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_segment",
        lambda **kwargs: captured.update(kwargs) or _empty_result(),
    )

    result = service.current(_request(), NOW)

    assert result.source_mode == "canonical_live"
    assert result.cutoff == live_bar.bar_end
    assert captured["bars_15m"][-1] == live_bar
    assert len(market_read.live_requests) == 3
    assert all(call[1] == canonical.bar_end for call in market_read.live_requests)


def test_incomplete_live_after_latest_15m_cutoff_does_not_change_source_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical = _canonical_stream()[0][-1]
    incomplete_1m = replace(
        canonical,
        bar_end=canonical.bar_end + timedelta(minutes=1),
        trading_day=TARGET_DAY,
    )
    service, *_ = _service(live={BarFrequency.M1: (incomplete_1m,)})
    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_segment",
        lambda **_kwargs: _empty_result(),
    )

    result = service.current(_request(), NOW)

    assert result.cutoff == canonical.bar_end
    assert result.source_mode == "canonical"


@pytest.mark.parametrize(
    "snapshot",
    (
        None,
        _snapshot(
            source_day=SOURCE_DAY - timedelta(days=1),
            target_day=SOURCE_DAY,
        ),
    ),
)
def test_missing_or_stale_current_context_blocks_entry_but_keeps_exit_replay(
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SubingDailyWatchSnapshot | None,
) -> None:
    module = _current_module()
    service, loader, historical, _store, market_read = _service()
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda _symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=_Store(snapshot),
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )
    captured = {}
    completed = SimpleNamespace(exit_action=object())

    def replay(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            actions=(),
            episodes=(completed,),
            pending_action=None,
            final_position=SubingStrategyPositionState.FLAT,
        )

    monkeypatch.setattr(
        "app.market_data.subing_strategy.current_service.replay_subing_strategy_segment",
        replay,
    )

    result = service.current(_request(), NOW)

    current = captured["direction_contexts"][TARGET_DAY]
    assert current.direction is SubingStrategyDirection.UNAVAILABLE
    assert current.reason_codes == (
        "SUBING_DAILY_WATCH_NOT_GENERATED"
        if snapshot is None
        else "SUBING_DAILY_WATCH_STALE",
    )
    assert result.latest_completed_episode is completed


def test_current_artifact_symbol_identity_mismatch_fails_closed() -> None:
    module = _current_module()
    service, loader, historical, _store, market_read = _service()
    invalid = replace(
        _snapshot(),
        items=(replace(_snapshot().items[0], symbol="rb"),),
    )
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda _symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=_Store(invalid),
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_current_artifact_source_identity_reason_fails_closed() -> None:
    module = _current_module()
    service, loader, historical, _store, market_read = _service()
    invalid_item = SubingDailyWatchItem(
        symbol="jm",
        product_name="焦煤",
        sector="黑色",
        decision=SubingDailyWatchDecision.UNAVAILABLE,
        reason_codes=(),
        daily=None,
        hourly=None,
        unavailable_reasons=("DATA_IDENTITY_MISMATCH",),
    )
    invalid = replace(_snapshot(), items=(invalid_item,))
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda _symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=_Store(invalid),
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_current_artifact_contract_must_belong_to_item_symbol() -> None:
    module = _current_module()
    service, loader, historical, _store, market_read = _service()
    other_product_item = replace(
        _snapshot().items[0],
        daily=replace(_trend(BarFrequency.D1), contract="RB2610"),
        hourly=replace(_trend(BarFrequency.H1), contract="RB2610"),
    )
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda _symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=_Store(
            replace(_snapshot(), items=(other_product_item,))
        ),
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_current_artifact_contract_must_match_source_day_rank1_owner() -> None:
    module = _current_module()
    service, loader, historical, store, market_read = _service()

    def segment_for_day(_symbol: str, target: date) -> ResolvedContractSegment:
        if target == SOURCE_DAY:
            return ResolvedContractSegment("JM2609", SEGMENT_START, SOURCE_DAY)
        return ResolvedContractSegment(CONTRACT, SEGMENT_START, TARGET_DAY)

    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=segment_for_day,
        historical_direction_context_resolver=historical,
        current_snapshot_store=store,
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_live_contract_identity_failure_is_typed() -> None:
    module = _current_module()
    live_bar = replace(_canonical_stream()[0][-1], trading_day=TARGET_DAY)
    service, *_ = _service(
        live={
            BarFrequency.M1: (live_bar,),
            BarFrequency.M5: (live_bar,),
            BarFrequency.M15: (live_bar,),
        }
    )
    service._market_read.contract = "JM2609"

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_current_segment_symbol_identity_failure_is_typed() -> None:
    module = _current_module()
    _service_value, loader, historical, store, market_read = _service()
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=market_read,
        current_segment=lambda _symbol, target: SimpleNamespace(
            symbol="rb",
            contract=CONTRACT,
            start_trading_day=SEGMENT_START,
            end_trading_day=target,
        ),
        historical_direction_context_resolver=historical,
        current_snapshot_store=store,
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceIdentityError):
        service.current(_request(), NOW)


def test_source_read_failure_is_typed() -> None:
    module = _current_module()
    loader = FakeSegmentLoader(MarketDataError("MAPPED_CONTRACT_DATASET_MISSING"))
    service = module.SubingStrategyCurrentProjectionService(
        loader,
        products=("jm",),
        market_read=_MarketRead(),
        current_segment=lambda _symbol, target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target
        ),
        historical_direction_context_resolver=FakeDirectionContextResolver(
            MappingProxyType({})
        ),
        current_snapshot_store=_Store(_snapshot()),
        target_trading_day=lambda _now: TARGET_DAY,
        previous_trading_day=lambda _target: SOURCE_DAY,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    with pytest.raises(module.SubingStrategyCurrentSourceUnavailableError):
        service.current(_request(), NOW)


def test_current_service_replays_the_real_unified_machine() -> None:
    module = _current_module()
    recorded = recorded_strategy_stream(7, SubingStrategyDirection.NO_NEW_ENTRY)
    source_day = recorded.bars_15m[0].trading_day
    target_day = source_day + timedelta(days=1)
    segment = ResolvedContractSegment(CONTRACT, SEGMENT_START, source_day)
    loaded = loaded_series(
        segments=(segment,),
        bars_1m=recorded.bars_1m,
        bars_5m=recorded.bars_5m,
        bars_15m=recorded.bars_15m,
    )

    class Loader(FakeSegmentLoader):
        def sessions(self, *, symbol, trading_days):
            self.session_requests.append((symbol, tuple(trading_days)))
            return MappingProxyType({source_day: recorded.sessions})

    service = module.SubingStrategyCurrentProjectionService(
        Loader(loaded),
        products=("jm",),
        market_read=_MarketRead(),
        current_segment=lambda _symbol, _target: ResolvedContractSegment(
            CONTRACT, SEGMENT_START, target_day
        ),
        historical_direction_context_resolver=FakeDirectionContextResolver(
            {
                source_day: SubingStrategyDirectionContext(
                    symbol="jm",
                    target_trading_day=source_day,
                    source_trading_day=source_day - timedelta(days=1),
                    direction=SubingStrategyDirection.NO_NEW_ENTRY,
                    reason_codes=("D1_TREND_NEUTRAL",),
                    daily_bar_end=None,
                    hourly_bar_end=None,
                    physical_contract=CONTRACT,
                )
            }
        ),
        current_snapshot_store=_Store(None),
        target_trading_day=lambda _now: target_day,
        previous_trading_day=lambda _target: source_day,
        calibration=_accepted_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
    )

    result = service.current(_request(), NOW)

    assert result.cutoff == recorded.bars_15m[-1].bar_end
    assert result.position_state is SubingStrategyPositionState.FLAT
    assert result.source_mode == "canonical"
