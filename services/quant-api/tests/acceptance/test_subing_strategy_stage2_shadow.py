from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import os

import pytest

from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeEvaluator,
    SubingStrategyRuntimeProductSourceError,
)
from app.market_data.aggregation import SessionWindow, bucket_window_for_bar
from app.market_data.domain import (
    BarFrequency,
    CanonicalBar,
    ResolvedContractSegment,
)
from app.market_data.operational_universe import load_active_products
from app.market_data.subing_calibration import load_subing_calibration
from app.market_data.subing_lifecycle_policy import load_subing_lifecycle_policy
from app.market_data.subing_strategy.contracts import (
    SubingStrategyAction,
    SubingStrategyDirection,
    SubingStrategyFillBasis,
)
from app.market_data.subing_strategy.direction_context import (
    SubingStrategyDirectionContext,
)
from app.market_data.subing_strategy.machine import (
    SubingStrategyMachineError,
    SubingStrategyMachineState,
    SubingStrategySourceIdentity,
    authoritative_subing_strategy_intervals,
    initial_subing_strategy_machine,
    step_subing_strategy_machine,
)
from app.market_data.subing_strategy.policy import load_subing_strategy_policy
from app.market_data.subing_strategy.replay import replay_subing_strategy_segment
from app.market_data.subing_strategy.shadow import (
    NoShadowCacheWriter,
    NoShadowRuntimeStatusWriter,
    NullShadowEventWriter,
    NullShadowNotificationSender,
    ShadowReadOnlyCanonicalReader,
    ShadowReadOnlyLiveReader,
    ShadowReadOnlyPostgresTransaction,
    SubingStrategyShadowAuthorizationError,
    SubingStrategyShadowDependencies,
    SubingStrategyShadowDependencyError,
    SubingStrategyShadowWriteBlocked,
    authorize_subing_strategy_shadow,
)
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
    Completed1mBar,
    Completed5mBar,
    Completed15mBar,
)
from research.subing_strategy_fixtures import (
    RecordedStrategyStream,
    recorded_strategy_stream,
)


_SHADOW_ENABLED = os.environ.get("GUIYI_SUBING_STAGE2_SHADOW") == "1"
_TRADING_DAY = date(2026, 8, 3)
_STARTED_AT = datetime(2026, 8, 3, 9, 59, 30, tzinfo=UTC)
_READY_AT = datetime(2026, 8, 3, 10, 1, 30, tzinfo=UTC)


def _context(
    *,
    symbol: str,
    contract: str,
    bar: CanonicalBar,
    direction: SubingStrategyDirection,
) -> SubingStrategyDirectionContext:
    return SubingStrategyDirectionContext(
        symbol=symbol,
        target_trading_day=bar.trading_day,
        source_trading_day=bar.trading_day - timedelta(days=1),
        direction=direction,
        reason_codes=("D1_H1_ALIGNED",),
        daily_bar_end=bar.bar_end - timedelta(days=1),
        hourly_bar_end=bar.bar_end - timedelta(hours=1),
        physical_contract=contract,
    )


def _recorded_identity(
    *,
    symbol: str = "jm",
    contract: str = "JM2701",
) -> tuple[
    RecordedStrategyStream,
    SubingStrategyDirectionContext,
    ResolvedContractSegment,
    SubingStrategySourceIdentity,
]:
    recorded = recorded_strategy_stream(18, SubingStrategyDirection.LONG_ONLY)
    context = _context(
        symbol=symbol,
        contract=contract,
        bar=recorded.bars_15m[0],
        direction=SubingStrategyDirection.LONG_ONLY,
    )
    segment = ResolvedContractSegment(contract, _TRADING_DAY, _TRADING_DAY)
    identity = SubingStrategySourceIdentity(symbol, contract, _TRADING_DAY)
    return recorded, context, segment, identity


def _stream_prefix(
    *,
    symbol: str,
    contract: str,
    bars_1m: tuple[CanonicalBar, ...],
    bars_5m: tuple[CanonicalBar, ...],
    bars_15m: tuple[CanonicalBar, ...],
    sessions: tuple[SessionWindow, ...],
    context: SubingStrategyDirectionContext,
) -> tuple[SubingStrategyMachineState, tuple[SubingStrategyAction, ...]]:
    intervals = authoritative_subing_strategy_intervals(
        bars_1m=bars_1m,
        bars_15m=bars_15m,
        sessions=sessions,
    )
    state = initial_subing_strategy_machine(
        symbol=symbol,
        contract=contract,
        segment_start_trading_day=_TRADING_DAY,
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        direction_contexts={_TRADING_DAY: context},
        intervals=intervals,
    )
    identity = SubingStrategySourceIdentity(symbol, contract, _TRADING_DAY)
    events = [*(Completed1mBar(bar) for bar in bars_1m)]
    events.extend(Completed5mBar(bar) for bar in bars_5m)
    events.extend(Completed15mBar(bar) for bar in bars_15m)
    events.sort(
        key=lambda event: (
            event.bar.bar_end,
            0
            if isinstance(event, Completed1mBar)
            else 1
            if isinstance(event, Completed15mBar)
            else 2,
        )
    )
    for event in events:
        state, _ = step_subing_strategy_machine(
            state,
            event,
            source_identity=identity,
        )
    return state, state.actions


class _RestoreReader:
    def __init__(self, unavailable_symbol: str) -> None:
        self.unavailable_symbol = unavailable_symbol

    def restore(
        self,
        *,
        symbol: str,
        started_at: datetime,
    ) -> SubingStrategyMachineState:
        assert started_at == _STARTED_AT
        if symbol == self.unavailable_symbol:
            raise SubingStrategyRuntimeProductSourceError()
        recorded, context, _, _ = _recorded_identity(
            symbol=symbol,
            contract=f"{symbol.upper()}2701",
        )
        return initial_subing_strategy_machine(
            symbol=symbol,
            contract=f"{symbol.upper()}2701",
            segment_start_trading_day=_TRADING_DAY,
            calibration=load_subing_calibration(),
            lifecycle_policy=load_subing_lifecycle_policy(),
            strategy_policy=load_subing_strategy_policy(),
            direction_contexts={_TRADING_DAY: context},
            intervals=authoritative_subing_strategy_intervals(
                bars_1m=recorded.bars_1m,
                bars_15m=recorded.bars_15m,
                sessions=recorded.sessions,
            ),
        )

    def restore_rollover(
        self,
        *,
        symbol: str,
        trading_day: date,
        previous_identity: SubingStrategySourceIdentity,
        terminal: AuthoritativeSegmentTerminal,
    ) -> SubingStrategyMachineState:
        raise AssertionError(
            (symbol, trading_day, previous_identity, terminal),
        )


class _CurrentReader:
    def read_completed_bars(
        self,
        *,
        symbol: str,
        source_identity: SubingStrategySourceIdentity,
        after_1m: datetime | None,
        after_5m: datetime | None,
        after_15m: datetime | None,
        through: datetime,
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        del symbol, source_identity, after_1m, after_5m, after_15m
        assert through == _READY_AT
        return {}

    def read_session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        raise AssertionError((symbol, trading_day, source_identity))

    def read_authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        raise AssertionError((symbol, trading_day, source_identity))


def _safe_dependencies(
    *,
    restore_reader: object | None = None,
    current_reader: object | None = None,
) -> SubingStrategyShadowDependencies:
    return SubingStrategyShadowDependencies(
        event_writer=NullShadowEventWriter(),
        notification_sender=NullShadowNotificationSender(),
        cache_writer=NoShadowCacheWriter(),
        runtime_status_writer=NoShadowRuntimeStatusWriter(),
        postgres_transaction=ShadowReadOnlyPostgresTransaction(
            verify_read_only=lambda: True,
            read=lambda operation: operation,
        ),
        canonical_reader=ShadowReadOnlyCanonicalReader(
            reader=restore_reader or _RestoreReader("zz")
        ),
        live_reader=ShadowReadOnlyLiveReader(reader=current_reader or _CurrentReader()),
    )


@pytest.mark.parametrize("raw", (None, "", "0", "true", "TRUE", "2"))
def test_shadow_authorization_requires_exact_enable_marker(raw: str | None) -> None:
    environment = {} if raw is None else {"GUIYI_SUBING_STAGE2_SHADOW": raw}

    with pytest.raises(SubingStrategyShadowAuthorizationError):
        authorize_subing_strategy_shadow(
            environment=environment,
            dependencies=_safe_dependencies(),
        )


@pytest.mark.parametrize(
    "field",
    (
        "event_writer",
        "notification_sender",
        "cache_writer",
        "runtime_status_writer",
        "postgres_transaction",
        "canonical_reader",
        "live_reader",
    ),
)
def test_shadow_dependencies_reject_any_non_exact_write_or_read_adapter(
    field: str,
) -> None:
    values = {
        "event_writer": NullShadowEventWriter(),
        "notification_sender": NullShadowNotificationSender(),
        "cache_writer": NoShadowCacheWriter(),
        "runtime_status_writer": NoShadowRuntimeStatusWriter(),
        "postgres_transaction": ShadowReadOnlyPostgresTransaction(
            verify_read_only=lambda: True,
            read=lambda operation: operation,
        ),
        "canonical_reader": ShadowReadOnlyCanonicalReader(reader=_RestoreReader("zz")),
        "live_reader": ShadowReadOnlyLiveReader(reader=_CurrentReader()),
    }
    values[field] = object()

    with pytest.raises(SubingStrategyShadowDependencyError):
        SubingStrategyShadowDependencies(**values)


@pytest.mark.parametrize(
    "sink_method",
    (
        NullShadowEventWriter().create_event,
        NullShadowNotificationSender().send,
        NoShadowCacheWriter().write,
        NoShadowRuntimeStatusWriter().write,
    ),
)
def test_shadow_sinks_block_every_write_attempt(
    sink_method: Callable[[], object],
) -> None:
    with pytest.raises(SubingStrategyShadowWriteBlocked):
        sink_method()


@pytest.mark.parametrize("verified", (False, None, "on", 1))
def test_shadow_dependencies_require_boolean_true_read_only_verification(
    verified: object,
) -> None:
    with pytest.raises(SubingStrategyShadowDependencyError):
        SubingStrategyShadowDependencies(
            event_writer=NullShadowEventWriter(),
            notification_sender=NullShadowNotificationSender(),
            cache_writer=NoShadowCacheWriter(),
            runtime_status_writer=NoShadowRuntimeStatusWriter(),
            postgres_transaction=ShadowReadOnlyPostgresTransaction(
                verify_read_only=lambda: verified,
                read=lambda operation: operation,
            ),
            canonical_reader=ShadowReadOnlyCanonicalReader(reader=_RestoreReader("zz")),
            live_reader=ShadowReadOnlyLiveReader(reader=_CurrentReader()),
        )


@pytest.mark.manual_acceptance
@pytest.mark.skipif(
    not _SHADOW_ENABLED,
    reason="requires GUIYI_SUBING_STAGE2_SHADOW=1 and authorized read-only inputs",
)
def test_authorized_read_only_shadow_uses_only_sealed_dependencies() -> None:
    active_products = load_active_products()
    dependencies = _safe_dependencies(
        restore_reader=_RestoreReader(active_products[-1]),
        current_reader=_CurrentReader(),
    )

    assert (
        authorize_subing_strategy_shadow(
            environment=os.environ,
            dependencies=dependencies,
        )
        is dependencies
    )
    _assert_recorded_stream_no_write_contract(
        active_products=active_products,
        dependencies=dependencies,
    )


def test_recorded_stream_proves_no_write_stage2_shadow_contract() -> None:
    active_products = load_active_products()
    unavailable_symbol = active_products[-1]
    dependencies = _safe_dependencies(
        restore_reader=_RestoreReader(unavailable_symbol),
        current_reader=_CurrentReader(),
    )
    _assert_recorded_stream_no_write_contract(
        active_products=active_products,
        dependencies=dependencies,
    )


def _assert_recorded_stream_no_write_contract(
    *,
    active_products: tuple[str, ...],
    dependencies: SubingStrategyShadowDependencies,
) -> None:
    unavailable_symbol = active_products[-1]
    evaluator = SubingStrategyRuntimeEvaluator(
        active_products,
        restore_reader=dependencies.canonical_reader.reader,
        current_reader=dependencies.live_reader.reader,
    )

    restored = evaluator.restore_all(started_at=_STARTED_AT)
    caught_up = evaluator.final_catch_up(ready_at=_READY_AT)

    assert len(restored) == len(caught_up) == 60
    unavailable = tuple(
        result.product_status.symbol
        for result in caught_up
        if result.product_status.state == "unavailable"
    )
    assert unavailable == (unavailable_symbol,)
    assert all(
        result.product_status.reason_codes == ("RESTORE_UNAVAILABLE",)
        for result in caught_up
        if result.product_status.symbol == unavailable_symbol
    )
    assert sum(result.product_status.state == "ready" for result in caught_up) == 59
    assert not any(result.action_facts for result in caught_up)

    recorded, context, segment, identity = _recorded_identity()
    for boundary_count in (12, 30, 60):
        bars_1m = recorded.bars_1m[: boundary_count * 15]
        bars_5m = recorded.bars_5m[: boundary_count * 3]
        bars_15m = recorded.bars_15m[:boundary_count]
        historical = replay_subing_strategy_segment(
            symbol="jm",
            segment=segment,
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            bars_15m=bars_15m,
            sessions=recorded.sessions,
            direction_contexts={_TRADING_DAY: context},
            calibration=load_subing_calibration(),
            lifecycle_policy=load_subing_lifecycle_policy(),
            strategy_policy=load_subing_strategy_policy(),
            terminal_bar_end=None,
        )
        state, streamed_actions = _stream_prefix(
            symbol="jm",
            contract="JM2701",
            bars_1m=bars_1m,
            bars_5m=bars_5m,
            bars_15m=bars_15m,
            sessions=recorded.sessions,
            context=context,
        )

        assert streamed_actions == historical.actions
        assert state.contract == "JM2701"
        assert state.segment_start_trading_day == _TRADING_DAY

    assert not replay_subing_strategy_segment(
        symbol="jm",
        segment=segment,
        bars_1m=recorded.bars_1m[: 12 * 15],
        bars_5m=recorded.bars_5m[: 12 * 3],
        bars_15m=recorded.bars_15m[:12],
        sessions=recorded.sessions,
        direction_contexts={_TRADING_DAY: context},
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=None,
    ).actions

    full = replay_subing_strategy_segment(
        symbol="jm",
        segment=segment,
        bars_1m=recorded.bars_1m,
        bars_5m=recorded.bars_5m,
        bars_15m=recorded.bars_15m,
        sessions=recorded.sessions,
        direction_contexts={_TRADING_DAY: context},
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=None,
    )
    first_1m_by_interval = {
        bucket_window_for_bar(
            recorded.sessions[0],
            BarFrequency.M15,
            bar.bar_end,
        ).end: bar
        for bar in recorded.bars_1m
        if bar.bar_end
        == bucket_window_for_bar(
            recorded.sessions[0],
            BarFrequency.M15,
            bar.bar_end,
        ).start
        + timedelta(minutes=1)
    }
    next_open_actions = tuple(
        action
        for action in full.actions
        if action.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN
    )
    assert next_open_actions
    for action in next_open_actions:
        first_1m = first_1m_by_interval[action.effective_bar_end]
        assert action.reference_price == first_1m.open
        assert action.effective_open_at == first_1m.bar_end - timedelta(minutes=1)

    streamed_state, _ = _stream_prefix(
        symbol="jm",
        contract="JM2701",
        bars_1m=recorded.bars_1m,
        bars_5m=recorded.bars_5m,
        bars_15m=recorded.bars_15m,
        sessions=recorded.sessions,
        context=context,
    )
    for foreign_identity in (
        replace(identity, contract="JM2705"),
        replace(
            identity,
            segment_start_trading_day=identity.segment_start_trading_day
            + timedelta(days=1),
        ),
    ):
        with pytest.raises(
            SubingStrategyMachineError,
            match="SOURCE_IDENTITY_MISMATCH",
        ):
            step_subing_strategy_machine(
                streamed_state,
                Completed1mBar(recorded.bars_1m[-1]),
                source_identity=foreign_identity,
            )

    assert type(dependencies.event_writer) is NullShadowEventWriter
    assert type(dependencies.notification_sender) is NullShadowNotificationSender
    assert type(dependencies.cache_writer) is NoShadowCacheWriter
    assert type(dependencies.runtime_status_writer) is NoShadowRuntimeStatusWriter
