from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
import os
from typing import Any

import pytest

from app.alerts.subing_strategy_runtime import (
    SubingStrategyRuntimeActionFact,
    SubingStrategyRuntimeEvaluator,
    SubingStrategyRuntimeProductSourceError,
)
from app.market_data.aggregation import SessionWindow, bucket_window_for_bar
from app.market_data.domain import BarFrequency, CanonicalBar, ResolvedContractSegment
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
    LOCAL_READ_ONLY_COMPOSITION,
    NoShadowCacheWriter,
    NoShadowRuntimeStatusWriter,
    NullShadowEventWriter,
    NullShadowNotificationSender,
    SHADOW_COMPOSITION_ENV,
    SHADOW_ENABLE_ENV,
    SubingStrategyShadowAuthorizationError,
    SubingStrategyShadowCompositionNotConfigured,
    SubingStrategyShadowDependencies,
    SubingStrategyShadowDependencyError,
    SubingStrategyShadowWriteBlocked,
    authorize_subing_strategy_shadow,
    bind_shadow_read_service,
    build_local_readonly_subing_strategy_shadow_dependencies,
    build_manual_subing_strategy_shadow,
    build_subing_strategy_shadow_dependencies,
)
from app.market_data.subing_strategy.stream_contracts import (
    AuthoritativeSegmentTerminal,
)
from research.subing_strategy_fixtures import RecordedStrategyStream, recorded_strategy_stream


_SHADOW_ENABLED = os.environ.get(SHADOW_ENABLE_ENV) == "1"
_TRADING_DAY = date(2026, 8, 3)
_STARTED_AT = datetime(2026, 8, 3, 9, 59, 30, tzinfo=UTC)
_READY_AT = datetime(2026, 8, 3, 10, 1, 30, tzinfo=UTC)


def _context(
    *,
    symbol: str,
    contract: str,
    bar: CanonicalBar,
) -> SubingStrategyDirectionContext:
    return SubingStrategyDirectionContext(
        symbol=symbol,
        target_trading_day=bar.trading_day,
        source_trading_day=bar.trading_day - timedelta(days=1),
        direction=SubingStrategyDirection.LONG_ONLY,
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
    context = _context(symbol=symbol, contract=contract, bar=recorded.bars_15m[0])
    return (
        recorded,
        context,
        ResolvedContractSegment(contract, _TRADING_DAY, _TRADING_DAY),
        SubingStrategySourceIdentity(symbol, contract, _TRADING_DAY),
    )


class _RestoreReader:
    def __init__(self, unavailable_symbol: str) -> None:
        self.unavailable_symbol = unavailable_symbol

    def restore_machine(
        self,
        *,
        symbol: str,
        now: datetime,
    ) -> SubingStrategyMachineState:
        assert now == _STARTED_AT
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


class _CurrentReader:
    def completed_live_after(
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

    def session_windows(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> tuple[SessionWindow, ...]:
        assert trading_day == _TRADING_DAY
        assert symbol == source_identity.symbol
        return _recorded_identity(
            symbol=symbol,
            contract=source_identity.contract,
        )[0].sessions

    def authoritative_terminal(
        self,
        *,
        symbol: str,
        trading_day: date,
        source_identity: SubingStrategySourceIdentity,
    ) -> AuthoritativeSegmentTerminal | None:
        del symbol, trading_day, source_identity
        return None


class _ReadOnlySession:
    def __init__(self, ledger: list[tuple[str, int]], identity: int) -> None:
        self.ledger = ledger
        self.identity = identity

    def __enter__(self) -> _ReadOnlySession:
        self.ledger.append(("enter", self.identity))
        return self

    def __exit__(self, *_args: object) -> None:
        self.ledger.append(("exit", self.identity))

    def execute(self, statement: object) -> None:
        assert str(statement) == "SET TRANSACTION READ ONLY"
        self.ledger.append(("set_read_only", self.identity))

    def scalar(self, statement: object) -> str:
        assert str(statement) == "SHOW transaction_read_only"
        self.ledger.append(("verify_read_only", self.identity))
        return "on"

    def rollback(self) -> None:
        self.ledger.append(("rollback", self.identity))


class _RecordedReadService:
    def __init__(
        self,
        session: _ReadOnlySession,
        restore_reader: _RestoreReader,
        current_reader: _CurrentReader,
    ) -> None:
        self._session = session
        self._restore = restore_reader
        self._current = current_reader

    def _read(self, name: str) -> None:
        self._session.ledger.append((name, self._session.identity))

    def restore_machine(self, **kwargs: Any) -> SubingStrategyMachineState:
        self._read("restore_machine")
        return self._restore.restore_machine(**kwargs)

    def completed_live_after(
        self, **kwargs: Any
    ) -> Mapping[BarFrequency, tuple[CanonicalBar, ...]]:
        self._read("completed_live_after")
        return self._current.completed_live_after(**kwargs)

    def session_windows(self, **kwargs: Any) -> tuple[SessionWindow, ...]:
        self._read("session_windows")
        return self._current.session_windows(**kwargs)

    def authoritative_terminal(
        self, **kwargs: Any
    ) -> AuthoritativeSegmentTerminal | None:
        self._read("authoritative_terminal")
        return self._current.authoritative_terminal(**kwargs)


def _safe_dependencies(
    *,
    unavailable_symbol: str = "zz",
    ledger: list[tuple[str, int]] | None = None,
) -> SubingStrategyShadowDependencies:
    audit = ledger if ledger is not None else []
    counter = iter(range(1, 100_000))
    restore = _RestoreReader(unavailable_symbol)
    current = _CurrentReader()
    return build_subing_strategy_shadow_dependencies(
        session_factory=lambda: _ReadOnlySession(audit, next(counter)),
        service_factory=lambda session: bind_shadow_read_service(
            session,
            _RecordedReadService(session, restore, current),
        ),
        clock=lambda: _READY_AT,
    )


@pytest.mark.parametrize("raw", (None, "", "0", "true", "TRUE", "2"))
def test_shadow_authorization_requires_exact_enable_marker(raw: str | None) -> None:
    environment = {} if raw is None else {SHADOW_ENABLE_ENV: raw}
    with pytest.raises(SubingStrategyShadowAuthorizationError):
        authorize_subing_strategy_shadow(
            environment=environment,
            dependencies=_safe_dependencies(),
        )


def test_marker_without_exact_composition_fails_closed() -> None:
    with pytest.raises(
        SubingStrategyShadowCompositionNotConfigured,
        match="SHADOW_COMPOSITION_NOT_CONFIGURED",
    ):
        build_manual_subing_strategy_shadow(
            environment={SHADOW_ENABLE_ENV: "1"},
            composition_factories={},
        )


def test_injected_exact_composition_is_independent_and_default_off() -> None:
    built = _safe_dependencies()
    assert (
        build_manual_subing_strategy_shadow(
            environment={
                SHADOW_ENABLE_ENV: "1",
                SHADOW_COMPOSITION_ENV: "recorded_readonly",
            },
            composition_factories={"recorded_readonly": lambda: built},
        )
        is built
    )


@pytest.mark.parametrize(
    "field",
    (
        "event_writer",
        "notification_sender",
        "cache_writer",
        "runtime_status_writer",
        "canonical_reader",
        "live_reader",
    ),
)
def test_shadow_dependencies_reject_non_exact_adapters(field: str) -> None:
    safe = _safe_dependencies()
    values = {
        name: getattr(safe, name)
        for name in SubingStrategyShadowDependencies.__dataclass_fields__
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


def test_read_only_adapters_do_not_expose_raw_reader_session_or_generic_read() -> None:
    dependencies = _safe_dependencies()
    assert not hasattr(dependencies, "postgres_transaction")
    assert {
        name for name in dir(dependencies) if not name.startswith("_")
    } == {
        "event_writer",
        "notification_sender",
        "cache_writer",
        "runtime_status_writer",
        "canonical_reader",
        "live_reader",
    }
    for adapter in (dependencies.canonical_reader, dependencies.live_reader):
        for capability in (
            "reader",
            "session",
            "service",
            "transaction",
            "raw",
            "read",
            "run",
            "_run",
            "operation",
        ):
            assert not hasattr(adapter, capability)
        assert not hasattr(adapter, "__dict__")

    assert {
        name
        for name in dir(dependencies.canonical_reader)
        if not name.startswith("_")
    } == {"restore", "restore_rollover"}
    assert {
        name for name in dir(dependencies.live_reader) if not name.startswith("_")
    } == {
        "read_completed_bars",
        "read_session_windows",
        "read_authoritative_terminal",
    }


def test_postgres_verification_and_catalog_read_share_exact_session() -> None:
    ledger: list[tuple[str, int]] = []
    dependencies = _safe_dependencies(ledger=ledger)
    dependencies.canonical_reader.restore(symbol="jm", started_at=_STARTED_AT)

    assert ledger == [
        ("enter", 1),
        ("set_read_only", 1),
        ("verify_read_only", 1),
        ("restore_machine", 1),
        ("rollback", 1),
        ("exit", 1),
    ]


def test_service_factory_bound_to_a_different_session_is_rejected() -> None:
    wrong_session = _ReadOnlySession([], 99)
    restore = _RestoreReader("zz")
    current = _CurrentReader()
    dependencies = build_subing_strategy_shadow_dependencies(
        session_factory=lambda: _ReadOnlySession([], 1),
        service_factory=lambda _verified_session: bind_shadow_read_service(
            wrong_session,
            _RecordedReadService(wrong_session, restore, current),
        ),
    )
    with pytest.raises(SubingStrategyShadowDependencyError):
        dependencies.canonical_reader.restore(symbol="jm", started_at=_STARTED_AT)


def test_service_factory_must_return_exact_bound_result() -> None:
    restore = _RestoreReader("zz")
    current = _CurrentReader()
    dependencies = build_subing_strategy_shadow_dependencies(
        session_factory=lambda: _ReadOnlySession([], 1),
        service_factory=lambda session: _RecordedReadService(  # type: ignore[arg-type,return-value]
            session,
            restore,
            current,
        ),
    )
    with pytest.raises(SubingStrategyShadowDependencyError):
        dependencies.canonical_reader.restore(symbol="jm", started_at=_STARTED_AT)


def test_write_capable_service_is_rejected_before_any_read() -> None:
    class _MaliciousService:
        def write(self) -> None:
            raise AssertionError("must not be called")

        def restore_machine(self, **_kwargs: object) -> None:
            raise AssertionError("must not be called")

    dependencies = build_subing_strategy_shadow_dependencies(
        session_factory=lambda: _ReadOnlySession([], 1),
        service_factory=lambda session: bind_shadow_read_service(
            session,
            _MaliciousService(),
        ),
    )
    with pytest.raises(SubingStrategyShadowDependencyError):
        dependencies.canonical_reader.restore(symbol="jm", started_at=_STARTED_AT)


@pytest.mark.manual_acceptance
@pytest.mark.skipif(
    not _SHADOW_ENABLED,
    reason="requires exact per-run authorization and sealed read-only composition",
)
def test_authorized_real_read_only_shadow_composition() -> None:
    try:
        dependencies = build_manual_subing_strategy_shadow(
            environment=os.environ,
            composition_factories={
                LOCAL_READ_ONLY_COMPOSITION: (
                    build_local_readonly_subing_strategy_shadow_dependencies
                )
            },
        )
    except SubingStrategyShadowCompositionNotConfigured:
        pytest.skip("SHADOW_COMPOSITION_NOT_CONFIGURED")

    evaluator = SubingStrategyRuntimeEvaluator(
        load_active_products(),
        restore_reader=dependencies.canonical_reader,
        current_reader=dependencies.live_reader,
    )
    restored = evaluator.restore_all(started_at=datetime.now(UTC))
    caught_up = evaluator.final_catch_up(ready_at=datetime.now(UTC))
    assert len(restored) == len(caught_up) == 60


@pytest.mark.parametrize("boundary_order", ("5m_first", "15m_first"))
def test_recorded_stream_evaluator_matches_historical_for_every_checked_prefix(
    boundary_order: str,
) -> None:
    recorded, context, segment, identity = _recorded_identity()
    dependencies = _safe_dependencies()
    evaluator = SubingStrategyRuntimeEvaluator(
        ("jm",),
        restore_reader=dependencies.canonical_reader,
        current_reader=dependencies.live_reader,
    )
    evaluator.restore_all(started_at=_STARTED_AT)
    ready = evaluator.final_catch_up(ready_at=_READY_AT)
    assert ready[0].product_status.state == "ready"
    assert not ready[0].action_facts

    events_by_end: dict[datetime, list[tuple[BarFrequency, CanonicalBar]]] = defaultdict(
        list
    )
    for frequency, bars in (
        (BarFrequency.M1, recorded.bars_1m),
        (BarFrequency.M5, recorded.bars_5m),
        (BarFrequency.M15, recorded.bars_15m),
    ):
        for bar in bars:
            events_by_end[bar.bar_end].append((frequency, bar))

    rank = {
        BarFrequency.M1: 0,
        BarFrequency.M5: 1 if boundary_order == "5m_first" else 2,
        BarFrequency.M15: 2 if boundary_order == "5m_first" else 1,
    }
    emitted: list[SubingStrategyRuntimeActionFact] = []
    boundary_count = 0
    for bar_end in sorted(events_by_end):
        group = sorted(events_by_end[bar_end], key=lambda item: rank[item[0]])
        for frequency, bar in group:
            result = evaluator.process_completed_bar(
                bar,
                frequency,
                source_identity=identity,
            )
            assert result.product_status.state == "ready"
            emitted.extend(result.action_facts)
        if any(frequency is BarFrequency.M15 for frequency, _ in group):
            boundary_count += 1
            historical = _expected_historical_prefix(boundary_count)
            assert tuple(fact.action for fact in emitted) == historical
            if boundary_count <= 12:
                assert not emitted

    assert tuple(fact.action for fact in emitted) == _historical_prefix(
        recorded=recorded,
        segment=segment,
        context=context,
        boundary_count=60,
    )


def test_recorded_stream_proves_active60_bounded_unavailable_and_no_writes() -> None:
    active_products = load_active_products()
    unavailable_symbol = active_products[-1]
    dependencies = _safe_dependencies(unavailable_symbol=unavailable_symbol)
    evaluator = SubingStrategyRuntimeEvaluator(
        active_products,
        restore_reader=dependencies.canonical_reader,
        current_reader=dependencies.live_reader,
    )
    restored = evaluator.restore_all(started_at=_STARTED_AT)
    caught_up = evaluator.final_catch_up(ready_at=_READY_AT)

    assert len(restored) == len(caught_up) == 60
    assert sum(item.product_status.state == "ready" for item in caught_up) == 59
    unavailable = tuple(
        item.product_status for item in caught_up if item.product_status.state == "unavailable"
    )
    assert len(unavailable) == 1
    assert unavailable[0].symbol == unavailable_symbol
    assert unavailable[0].reason_codes == ("RESTORE_UNAVAILABLE",)
    assert not any(item.action_facts for item in caught_up)
    assert type(dependencies.event_writer) is NullShadowEventWriter
    assert type(dependencies.notification_sender) is NullShadowNotificationSender
    assert type(dependencies.cache_writer) is NoShadowCacheWriter
    assert type(dependencies.runtime_status_writer) is NoShadowRuntimeStatusWriter


def test_recorded_stream_exact_first_1m_open_and_cross_identity_fail_closed() -> None:
    recorded, context, segment, identity = _recorded_identity()
    actions = _historical_prefix(
        recorded=recorded,
        segment=segment,
        context=context,
        boundary_count=60,
    )
    first_1m_by_interval = {
        bucket_window_for_bar(
            recorded.sessions[0], BarFrequency.M15, bar.bar_end
        ).end: bar
        for bar in recorded.bars_1m
        if bar.bar_end
        == bucket_window_for_bar(
            recorded.sessions[0], BarFrequency.M15, bar.bar_end
        ).start
        + timedelta(minutes=1)
    }
    next_open_actions = tuple(
        action
        for action in actions
        if action.fill_basis is SubingStrategyFillBasis.NEXT_BAR_OPEN
    )
    assert next_open_actions
    for action in next_open_actions:
        first_1m = first_1m_by_interval[action.effective_bar_end]
        assert action.reference_price == first_1m.open
        assert action.effective_open_at == first_1m.bar_end - timedelta(minutes=1)

    state = _stream_state(recorded=recorded, context=context)
    for foreign_identity in (
        replace(identity, contract="JM2705"),
        replace(
            identity,
            segment_start_trading_day=identity.segment_start_trading_day
            + timedelta(days=1),
        ),
    ):
        with pytest.raises(SubingStrategyMachineError, match="SOURCE_IDENTITY_MISMATCH"):
            step_subing_strategy_machine(
                state,
                # Duplicate input is sufficient: identity is checked first.
                _completed_1m(recorded.bars_1m[-1]),
                source_identity=foreign_identity,
            )


def _historical_prefix(
    *,
    recorded: RecordedStrategyStream,
    segment: ResolvedContractSegment,
    context: SubingStrategyDirectionContext,
    boundary_count: int,
) -> tuple[SubingStrategyAction, ...]:
    return replay_subing_strategy_segment(
        symbol="jm",
        segment=segment,
        bars_1m=recorded.bars_1m[: boundary_count * 15],
        bars_5m=recorded.bars_5m[: boundary_count * 3],
        bars_15m=recorded.bars_15m[:boundary_count],
        sessions=recorded.sessions,
        direction_contexts={_TRADING_DAY: context},
        calibration=load_subing_calibration(),
        lifecycle_policy=load_subing_lifecycle_policy(),
        strategy_policy=load_subing_strategy_policy(),
        terminal_bar_end=None,
    ).actions


@lru_cache(maxsize=60)
def _expected_historical_prefix(
    boundary_count: int,
) -> tuple[SubingStrategyAction, ...]:
    recorded, context, segment, _ = _recorded_identity()
    return _historical_prefix(
        recorded=recorded,
        segment=segment,
        context=context,
        boundary_count=boundary_count,
    )


def _stream_state(
    *,
    recorded: RecordedStrategyStream,
    context: SubingStrategyDirectionContext,
) -> SubingStrategyMachineState:
    identity = SubingStrategySourceIdentity("jm", "JM2701", _TRADING_DAY)
    state = initial_subing_strategy_machine(
        symbol="jm",
        contract="JM2701",
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
    events = [
        *((bar.bar_end, 0, _completed_1m(bar)) for bar in recorded.bars_1m),
        *((bar.bar_end, 1, _completed_15m(bar)) for bar in recorded.bars_15m),
        *((bar.bar_end, 2, _completed_5m(bar)) for bar in recorded.bars_5m),
    ]
    for _, _, event in sorted(events, key=lambda item: (item[0], item[1])):
        state, _ = step_subing_strategy_machine(state, event, source_identity=identity)
    return state


def _completed_1m(bar: CanonicalBar):
    from app.market_data.subing_strategy.stream_contracts import Completed1mBar

    return Completed1mBar(bar)


def _completed_5m(bar: CanonicalBar):
    from app.market_data.subing_strategy.stream_contracts import Completed5mBar

    return Completed5mBar(bar)


def _completed_15m(bar: CanonicalBar):
    from app.market_data.subing_strategy.stream_contracts import Completed15mBar

    return Completed15mBar(bar)
