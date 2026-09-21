"""Pure BUILD/CLEAR reference projection over owned product facts."""

from copy import copy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_DOWN, ROUND_UP, localcontext
from hashlib import sha256
import json

import pytest

from guiyi_quant.newow.product_contracts import (
    ActionKind,
    DataInterruption,
    FeatureRuntimeStatus,
    StrategyAction,
    StrategyHint,
    TradeEligibility,
)
from guiyi_quant.newow.reference_trades import ReferenceTradeProjector
from guiyi_quant.newow.product_identity import (
    InputQualityPolicy,
    futures_adaptation_version,
)
from guiyi_quant.reference_trading.adapters import AdapterCheckpoint
from guiyi_quant.reference_trading.strategy_checkpoint import (
    adapter_checkpoint_from_json,
    adapter_checkpoint_to_json,
)


def _forged_actions(replay, actions):
    """Bypass upstream validation to exercise the projector's trust boundary."""
    forged = copy(replay)
    object.__setattr__(forged, "actions", tuple(actions))
    return forged


def _forged_lifecycle_evidence(replay, evidence):
    """Bypass upstream validation to exercise the projector's trust boundary."""
    forged = copy(replay)
    object.__setattr__(forged, "lifecycle_evidence", tuple(evidence))
    return forged


def test_closed_trade_covers_the_reference_contract_and_uses_action_prices(
    product_cases,
):
    case = product_cases.closed(entry="100", exit="110")

    result = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    )

    assert result.as_of == case.as_of
    assert result.bar_level_hints == ()
    assert result.unassigned_hints == ()
    assert result.diagnostics == ()
    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.reference_trade_id
    assert trade.product == "rb"
    assert trade.strategy_code == "trend"
    assert trade.frequency == "1d"
    assert trade.physical_contract == "RB2605"
    assert trade.segment_id == case.entry.segment_id
    assert trade.formula_versions == ("newow_trend_band_page_v2",)
    assert trade.reference_model_version == "newow_marker_reference_zero_cost_v3"
    assert (
        trade.futures_adaptation_version
        == "newow_futures_quality_segment_v3"
    )
    assert trade.entry_signal_id == case.entry.signal_id
    assert trade.entry_bar_end == case.entry.bar_end
    assert trade.entry_reference_price == Decimal("100")
    assert trade.exit_signal_id == case.exit.signal_id
    assert trade.exit_bar_end == case.exit.bar_end
    assert trade.exit_reference_price == Decimal("110")
    assert trade.status == "CLOSED"
    assert trade.holding_bars == 1
    assert trade.reference_return_pct == Decimal("10")
    assert trade.mark_bar_end is None
    assert trade.mark_reference_price is None
    assert trade.mark_change_pct is None
    assert trade.interrupted_at is None
    assert trade.interruption_reason is None
    assert trade.statistics_membership is None
    assert trade.hint_ids == ()


def test_public_projector_return_is_independent_of_caller_decimal_rounding(product_cases):
    case = product_cases.closed(entry="3", exit="4")

    values = []
    for rounding in (ROUND_DOWN, ROUND_UP):
        with localcontext() as context:
            context.rounding = rounding
            values.append(ReferenceTradeProjector().project(
                case.replay, case.boundaries, case.as_of,
            ).trades[0].reference_return_pct)

    assert values == [
        Decimal("33.33333333333333333333333330"),
        Decimal("33.33333333333333333333333330"),
    ]


def test_public_projector_routes_trade_transitions_through_shared_reducer(
    product_cases, monkeypatch,
):
    import guiyi_quant.newow.reference_trades as module

    case = product_cases.closed(entry="100", exit="110")
    actual = module.reduce_reference
    calls = []

    def observed(*args, **kwargs):
        calls.append((args, kwargs))
        return actual(*args, **kwargs)

    monkeypatch.setattr(module, "reduce_reference", observed, raising=False)

    result = module.ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of,
    )

    assert result.trades[0].status == "CLOSED"
    assert calls


@pytest.mark.parametrize("strategy", ("trend", "oscillation", "main_rise"))
def test_public_projector_checkpoint_resumes_open_trade_without_prefix_replay(
    product_cases, strategy,
):
    case = product_cases.closed(strategy=strategy, entry="100", exit="110")
    hint = StrategyHint(
        identity=case.identity,
        physical_contract=case.entry.physical_contract,
        segment_id=case.entry.segment_id,
        bar_end=case.entry.bar_end,
        trading_day=case.entry.trading_day,
        kind="D1",
        known_at=case.entry.bar_end,
        anchor_price=case.entry.reference_price,
        sequence=1,
        source_marker_id="owned:checkpoint-hint",
    )
    first_frame = replace(case.replay.frames[0], hints=(hint,))
    case = replace(
        case,
        replay=replace(
            case.replay,
            frames=(first_frame, *case.replay.frames[1:]),
            hints=(hint,),
        ),
    )
    entry_index = next(
        index for index, frame in enumerate(case.replay.frames)
        if any(action.kind.value == "BUILD" for action in frame.actions)
    )
    prefix_frames = case.replay.frames[:entry_index + 1]
    tail_frames = case.replay.frames[entry_index + 1:]

    def sliced(frames):
        return replace(
            case.replay,
            frames=frames,
            actions=tuple(action for frame in frames for action in frame.actions),
            hints=tuple(hint for frame in frames for hint in frame.hints),
            lifecycle_input_bars=tuple(frame.bar for frame in frames),
            lifecycle_evidence=(),
        )

    projector = ReferenceTradeProjector()
    prefix_as_of = prefix_frames[-1].bar.bar.bar_end
    state, prefix = projector.advance(
        None, sliced(prefix_frames), case.boundaries, prefix_as_of,
    )
    assert len(state.active_trades) == 1
    contract, segment, unified = next(
        item for item in state.reference_states if item[2].open_trade is not None
    )
    checkpoint = AdapterCheckpoint(
        state, prefix_as_of, "prefix", contract, segment,
        unified.open_trade.calculation_segment_id, state.stream, unified,
    )
    encoded = adapter_checkpoint_to_json(
        checkpoint, strategy_schema="newow_reference_replay_v1",
    )
    restored = adapter_checkpoint_from_json(
        encoded, expected_stream=state.stream,
        expected_strategy_schema="newow_reference_replay_v1",
    )

    resumed, tail = projector.advance(
        restored.strategy_state, sliced(tail_frames), case.boundaries, case.as_of,
    )
    merged = {trade.reference_trade_id: trade for trade in prefix.trades}
    merged.update({trade.reference_trade_id: trade for trade in tail.trades})
    expected = projector.project(case.replay, case.boundaries, case.as_of)

    assert tuple(merged.values()) == expected.trades
    assert tail.bar_level_hints == expected.bar_level_hints
    assert tail.unassigned_hints == expected.unassigned_hints
    assert tail.diagnostics == expected.diagnostics
    assert resumed.active_trades == ()
    assert '"frames"' not in encoded


def test_public_projector_checkpoint_resumes_into_rollover_interruption(product_cases):
    case = product_cases.interrupted(mark="90")
    projector = ReferenceTradeProjector()
    prefix_as_of = case.replay.frames[-1].bar.bar.bar_end
    state, prefix = projector.advance(
        None, case.replay, case.boundaries, prefix_as_of,
    )
    empty_tail = replace(
        case.replay, frames=(), actions=(), hints=(), lifecycle_input_bars=(),
        lifecycle_evidence=(),
    )

    resumed, tail = projector.advance(
        state, empty_tail, case.boundaries, case.as_of,
    )
    merged = {trade.reference_trade_id: trade for trade in prefix.trades}
    merged.update({trade.reference_trade_id: trade for trade in tail.trades})
    expected = projector.project(case.replay, case.boundaries, case.as_of)

    assert tuple(merged.values()) == expected.trades
    assert resumed.active_trades == ()
    assert len(resumed.processed_event_ids) == 1


def test_incremental_projector_rejects_older_owner_frame_after_close(product_cases):
    case = product_cases.closed()
    projector = ReferenceTradeProjector()
    state, _ = projector.advance(None, case.replay, (), case.as_of)
    snapshot = repr(state)
    entry_only = replace(
        case.replay,
        frames=case.replay.frames[:1],
        actions=(case.entry,),
        hints=(),
        lifecycle_input_bars=case.replay.lifecycle_input_bars[:1],
        lifecycle_evidence=(),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        projector.advance(state, entry_only, (), case.entry.bar_end)
    assert repr(state) == snapshot


def test_newow_checkpoint_rejects_public_open_price_divergence(product_cases):
    case = product_cases.open()
    state, _ = ReferenceTradeProjector().advance(
        None, case.replay, (), case.as_of,
    )
    contract, segment, unified = next(
        item for item in state.reference_states if item[2].open_trade is not None
    )
    checkpoint = AdapterCheckpoint(
        state, case.bars[-1].bar.bar_end, "prefix", contract, segment,
        unified.open_trade.calculation_segment_id, state.stream, unified,
    )
    payload = json.loads(adapter_checkpoint_to_json(
        checkpoint, strategy_schema="newow_reference_replay_v1",
    ))
    payload["strategy_state"]["fields"]["active_trades"]["$tuple"][0][
        "fields"
    ]["entry_reference_price"] = {"$decimal": "999"}
    body = {key: value for key, value in payload.items() if key != "checksum_sha256"}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    payload["checksum_sha256"] = sha256(canonical.encode()).hexdigest()

    with pytest.raises(ValueError, match="active trades"):
        adapter_checkpoint_from_json(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True),
            expected_stream=state.stream,
            expected_strategy_schema="newow_reference_replay_v1",
        )


def test_initial_clear_checkpoint_carries_verified_lifecycle_without_frame_history(
    product_cases,
):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,),
    )
    projector = ReferenceTradeProjector()
    seeded = projector.seed(replay)
    prefix_frames = replay.frames[:-1]
    prefix = replace(
        replay,
        frames=prefix_frames,
        actions=(),
        hints=tuple(hint for frame in prefix_frames for hint in frame.hints),
        lifecycle_input_bars=tuple(frame.bar for frame in prefix_frames),
        lifecycle_evidence=(),
        diagnostics=(),
    )
    prefix_as_of = prefix_frames[-1].bar.bar.bar_end
    state, prefix_projection = projector.advance(seeded, prefix, (), prefix_as_of)
    assert prefix_projection.diagnostics == ()
    assert state.verified_lifecycle_owners == ((
        case.bars[0].bar.physical_contract, case.bars[0].bar.segment_id,
    ),)
    contract, segment, unified = state.reference_states[0]
    checkpoint = AdapterCheckpoint(
        state, prefix_as_of, "prefix", contract, segment,
        prefix_frames[-1].bar.calculation_segment_id, state.stream, unified,
    )
    restored = adapter_checkpoint_from_json(
        adapter_checkpoint_to_json(
            checkpoint, strategy_schema="newow_reference_replay_v1",
        ),
        expected_stream=state.stream,
        expected_strategy_schema="newow_reference_replay_v1",
    )
    clear_frame = replay.frames[-1]
    tail = replace(
        replay,
        frames=(clear_frame,),
        actions=clear_frame.actions,
        hints=clear_frame.hints,
        lifecycle_input_bars=(clear_frame.bar,),
        lifecycle_evidence=(),
        diagnostics=("INITIAL_CLEAR_NO_ENTRY",),
    )

    resumed, projection = projector.advance(
        restored.strategy_state, tail, (), clear_frame.bar.bar.bar_end,
    )
    assert projection.trades == ()
    assert projection.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)

    empty_tail = replace(
        tail, frames=(), actions=(), hints=(), lifecycle_input_bars=(), diagnostics=(),
    )
    _, empty_projection = projector.advance(
        resumed, empty_tail, (), clear_frame.bar.bar.bar_end,
    )
    assert empty_projection.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)

    replayed, duplicate_projection = projector.advance(
        resumed, tail, (), clear_frame.bar.bar.bar_end,
    )
    assert replayed is resumed
    assert duplicate_projection.trades == ()
    assert duplicate_projection.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)


def test_initial_clear_seed_is_bound_to_the_consumed_frame_prefix(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,),
    )
    projector = ReferenceTradeProjector()
    seeded = projector.seed(replay)
    prefix_frames = replay.frames[:-1]
    damaged_first = replace(
        prefix_frames[0],
        main_values=(("ma35", Decimal("0")), ("ma45", Decimal("1"))),
    )
    damaged_frames = (damaged_first, *prefix_frames[1:])
    damaged_prefix = replace(
        replay,
        frames=damaged_frames,
        actions=(),
        hints=tuple(hint for frame in damaged_frames for hint in frame.hints),
        lifecycle_input_bars=tuple(frame.bar for frame in damaged_frames),
        lifecycle_evidence=(),
        diagnostics=(),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        projector.advance(
            seeded, damaged_prefix, (), damaged_frames[-1].bar.bar.bar_end,
        )


def test_initial_clear_completed_window_accepts_later_new_owner_bar(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    prefix_case = product_cases.initial_clear_input()
    prefix_evidence = product_cases.synthetic_lifecycle_evidence(prefix_case.bars)
    prefix_replay = replay_strategy(
        prefix_case.identity, prefix_case.bars,
        lifecycle_evidence=(prefix_evidence,),
    )
    projector = ReferenceTradeProjector()
    state, prefix = projector.advance(
        projector.seed(prefix_replay), prefix_replay, (),
        prefix_case.bars[-1].bar.bar_end,
    )

    extended_case = product_cases.main_rise_lifecycle_input(
        (*([Decimal("100")] * 35), Decimal("90"), Decimal("91"))
    )
    extended_evidence = product_cases.synthetic_lifecycle_evidence(extended_case.bars)
    extended_replay = replay_strategy(
        extended_case.identity, extended_case.bars,
        lifecycle_evidence=(extended_evidence,),
    )
    raw_last_frame = extended_replay.frames[-1]
    build = StrategyAction(
        identity=extended_replay.identity,
        physical_contract=raw_last_frame.bar.bar.physical_contract,
        segment_id=raw_last_frame.bar.bar.segment_id,
        bar_end=raw_last_frame.bar.bar.bar_end,
        trading_day=raw_last_frame.bar.bar.trading_day,
        kind=ActionKind.BUILD,
        reference_price=raw_last_frame.bar.bar.close,
        anchor_price=raw_last_frame.bar.bar.close,
        source_marker_id="owned:post-lifecycle-build",
    )
    last_frame = replace(raw_last_frame, main_state="BUILD", actions=(build,))
    extended_replay = replace(
        extended_replay,
        frames=(*extended_replay.frames[:-1], last_frame),
        actions=(*extended_replay.actions, build),
    )
    tail = replace(
        extended_replay,
        frames=(last_frame,), actions=last_frame.actions, hints=last_frame.hints,
        lifecycle_input_bars=(last_frame.bar,), lifecycle_evidence=(), diagnostics=(),
    )

    resumed, delta = projector.advance(
        state, tail, (), last_frame.bar.bar.bar_end,
    )
    expected = projector.project(
        extended_replay, (), last_frame.bar.bar.bar_end,
    )

    assert prefix.trades == ()
    assert delta.trades == expected.trades
    assert len(delta.trades) == 1
    assert delta.trades[0].status.value == "OPEN"
    assert delta.diagnostics == expected.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)
    assert resumed.lifecycle_consumed == state.lifecycle_consumed

    first_35 = prefix_replay.frames[:-1]
    partial_replay = replace(
        prefix_replay,
        frames=first_35,
        actions=(),
        hints=tuple(hint for frame in first_35 for hint in frame.hints),
        lifecycle_input_bars=tuple(frame.bar for frame in first_35),
        lifecycle_evidence=(),
        diagnostics=(),
    )
    partial_state, _ = projector.advance(
        projector.seed(prefix_replay), partial_replay, (),
        first_35[-1].bar.bar.bar_end,
    )
    cross_boundary_frames = extended_replay.frames[-2:]
    cross_boundary = replace(
        extended_replay,
        frames=cross_boundary_frames,
        actions=tuple(
            action for frame in cross_boundary_frames for action in frame.actions
        ),
        hints=tuple(
            hint for frame in cross_boundary_frames for hint in frame.hints
        ),
        lifecycle_input_bars=tuple(frame.bar for frame in cross_boundary_frames),
        lifecycle_evidence=(),
        diagnostics=("INITIAL_CLEAR_NO_ENTRY",),
    )
    batched_state, batched_delta = projector.advance(
        partial_state, cross_boundary, (), last_frame.bar.bar.bar_end,
    )

    assert batched_state.active_trades == resumed.active_trades
    assert batched_delta.trades == delta.trades
    assert batched_delta.diagnostics == delta.diagnostics


def test_weekly_quality_adaptation_has_its_own_version_without_changing_daily(
    product_cases,
):
    assert futures_adaptation_version("1d") == "newow_futures_quality_segment_v3"
    assert futures_adaptation_version("1w") == "newow_futures_weekly_quality_segment_v1"
    for frequency in ("1d", "1w"):
        case = product_cases.closed(frequency=frequency)
        trade = ReferenceTradeProjector().project(
            case.replay, case.boundaries, case.as_of,
        ).trades[0]
        assert trade.futures_adaptation_version == futures_adaptation_version(frequency)


def test_weekly_v2_reference_identity_isolated_even_without_a_break(product_cases):
    legacy = product_cases.closed(frequency="1w")
    candidate_identity = replace(
        legacy.identity,
        input_quality_policy=InputQualityPolicy.WEEKLY_V2,
    )
    raw_candidate_actions = tuple(
        replace(action, identity=candidate_identity) for action in legacy.replay.actions
    )
    translated = {
        old.signal_id: new.signal_id
        for old, new in zip(legacy.replay.actions, raw_candidate_actions, strict=True)
    }
    candidate_actions = tuple(
        replace(
            action,
            related_build_id=(
                translated[action.related_build_id]
                if action.related_build_id is not None
                else None
            ),
        )
        for action in raw_candidate_actions
    )
    actions_by_id = {action.signal_id: action for action in candidate_actions}
    candidate_replay = replace(
        legacy.replay,
        identity=candidate_identity,
        frames=tuple(
            replace(
                frame,
                actions=tuple(
                    actions_by_id[
                        replace(action, identity=candidate_identity).signal_id
                    ]
                    for action in frame.actions
                ),
                hints=tuple(
                    replace(hint, identity=candidate_identity) for hint in frame.hints
                ),
            )
            for frame in legacy.replay.frames
        ),
        actions=candidate_actions,
        hints=tuple(
            replace(hint, identity=candidate_identity) for hint in legacy.replay.hints
        ),
    )

    projector = ReferenceTradeProjector()
    legacy_stream = projector.seed(legacy.replay).stream
    candidate_stream = projector.seed(candidate_replay).stream
    legacy_trade = projector.project(
        legacy.replay, legacy.boundaries, legacy.as_of,
    ).trades[0]
    candidate_trade = projector.project(
        candidate_replay, legacy.boundaries, legacy.as_of,
    ).trades[0]

    assert legacy_stream.futures_adaptation_version == "newow_futures_weekly_quality_segment_v1"
    assert candidate_stream.futures_adaptation_version == "newow_futures_weekly_quality_segment_v2"
    assert candidate_stream.stream_id != legacy_stream.stream_id
    assert legacy_trade.futures_adaptation_version == "newow_futures_weekly_quality_segment_v1"
    assert candidate_trade.futures_adaptation_version == "newow_futures_weekly_quality_segment_v2"
    assert candidate_trade.input_quality_policy is InputQualityPolicy.WEEKLY_V2
    assert candidate_trade.reference_trade_id != legacy_trade.reference_trade_id


def test_daily_reference_identity_and_values_remain_fixed_after_weekly_quality(product_cases):
    case = product_cases.closed(frequency="1d", entry="100", exit="110")
    trade = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of,
    ).trades[0]
    assert trade.reference_trade_id == (
        "d7fe03fcd7e5d0678d594d454b4fb539717e4eef9e14277734ba2ddb1b2c6cc6"
    )
    assert trade.frequency == "1d"
    assert trade.entry_reference_price == Decimal("100")
    assert trade.exit_reference_price == Decimal("110")
    assert trade.reference_return_pct == Decimal("10")
    assert trade.holding_bars == 1


def test_reference_trade_id_changes_when_reference_model_moves_from_v1_to_v2(
    product_cases, monkeypatch
):
    import guiyi_quant.newow.product_identity as product_identity

    case = product_cases.closed(entry="100", exit="110")
    monkeypatch.setattr(
        product_identity,
        "REFERENCE_MODEL_VERSION",
        "newow_marker_reference_zero_cost_v1",
    )
    v1_id = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0].reference_trade_id
    monkeypatch.setattr(
        product_identity,
        "REFERENCE_MODEL_VERSION",
        "newow_marker_reference_zero_cost_v3",
    )
    v2_id = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0].reference_trade_id

    assert v1_id != v2_id


def test_reference_trade_id_changes_with_futures_no_trade_policy_version(
    product_cases, monkeypatch
):
    import guiyi_quant.newow.product_identity as product_identity

    case = product_cases.closed(entry="100", exit="110")
    monkeypatch.setattr(
        product_identity,
        "FUTURES_ADAPTATION_VERSION",
        "newow_futures_segment_interrupt_v1",
    )
    prior_id = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0].reference_trade_id
    monkeypatch.setattr(
        product_identity,
        "FUTURES_ADAPTATION_VERSION",
        "newow_futures_quality_segment_v3",
    )
    current_id = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0].reference_trade_id

    assert prior_id != current_id


def test_open_trade_has_no_manufactured_exit_or_realized_return(product_cases):
    case = product_cases.open()

    trade = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    ).trades[0]

    assert trade.status == "OPEN"
    assert trade.exit_signal_id is None
    assert trade.exit_bar_end is None
    assert trade.exit_reference_price is None
    assert trade.reference_return_pct is None
    assert trade.holding_bars == 1


def test_holding_bars_counts_effective_frequency_intervals_not_calendar_days(
    product_cases,
):
    case = product_cases.closed()
    exit_end = datetime(2026, 1, 30, 7, tzinfo=UTC)
    exit_bar = replace(
        case.bars[1],
        bar=replace(
            case.bars[1].bar,
            trading_day=date(2026, 1, 30),
            bar_end=exit_end,
            source_identity="owned:sparse-daily-exit",
        ),
    )
    clear = product_cases.action(
        case.identity,
        exit_bar,
        "CLEAR",
        "110",
        related_build_id=case.entry.signal_id,
    )
    replay = product_cases.replay(
        case.identity,
        (case.bars[0], exit_bar),
        (case.entry, clear),
        ("BUILD", "CLEAR"),
    )

    trade = ReferenceTradeProjector().project(
        replay, (), datetime(2026, 2, 1, tzinfo=UTC)
    ).trades[0]

    assert trade.holding_bars == 1


def test_trade_preserves_authoritative_night_session_trading_days(product_cases):
    case = product_cases.closed(frequency="60m")
    entry_end = datetime(2026, 1, 4, 13, tzinfo=UTC)
    exit_end = datetime(2026, 1, 5, 13, tzinfo=UTC)
    entry_bar = replace(
        case.bars[0],
        bar=replace(
            case.bars[0].bar,
            trading_day=date(2026, 1, 5),
            bar_end=entry_end,
            source_identity="owned:night-session-entry",
        ),
    )
    exit_bar = replace(
        case.bars[1],
        bar=replace(
            case.bars[1].bar,
            trading_day=date(2026, 1, 6),
            bar_end=exit_end,
            source_identity="owned:night-session-exit",
        ),
    )
    entry = product_cases.action(case.identity, entry_bar, "BUILD", "100")
    clear = product_cases.action(
        case.identity,
        exit_bar,
        "CLEAR",
        "110",
        related_build_id=entry.signal_id,
    )
    closed_replay = product_cases.replay(
        case.identity,
        (entry_bar, exit_bar),
        (entry, clear),
        ("BUILD", "CLEAR"),
    )

    trade = ReferenceTradeProjector().project(
        closed_replay, (), datetime(2026, 1, 6, 16, tzinfo=UTC)
    ).trades[0]

    assert trade.entry_bar_end.date() == date(2026, 1, 4)
    assert trade.entry_trading_day == date(2026, 1, 5)
    assert trade.exit_bar_end.date() == date(2026, 1, 5)
    assert trade.exit_trading_day == date(2026, 1, 6)
    with pytest.raises(ValueError, match="INCONSISTENT_STATUS"):
        replace(trade, exit_trading_day=None)

    open_replay = product_cases.replay(
        case.identity,
        (entry_bar, exit_bar),
        (entry,),
        ("BUILD", "HOLD"),
    )
    open_trade = ReferenceTradeProjector().project(
        open_replay, (), datetime(2026, 1, 6, 16, tzinfo=UTC)
    ).trades[0]
    assert open_trade.entry_trading_day == date(2026, 1, 5)
    assert open_trade.exit_trading_day is None


def test_pairing_closes_then_rebuilds_on_the_same_bar(product_cases):
    case = product_cases.same_bar_rebuild()

    result = ReferenceTradeProjector().project(
        case.replay, case.boundaries, case.as_of
    )

    assert [trade.status for trade in result.trades] == ["CLOSED", "OPEN"]
    assert result.trades[0].exit_signal_id != result.trades[1].entry_signal_id
    assert result.trades[0].exit_bar_end == result.trades[1].entry_bar_end
    assert result.trades[0].reference_trade_id != result.trades[1].reference_trade_id


def test_same_action_id_and_content_is_idempotent_but_changed_content_fails(
    product_cases,
):
    case = product_cases.closed()
    projector = ReferenceTradeProjector()
    duplicated = _forged_actions(
        case.replay, (case.entry, case.entry, case.exit, case.exit)
    )

    assert projector.project(duplicated, (), case.as_of) == projector.project(
        case.replay, (), case.as_of
    )

    conflicting_entry = replace(case.entry, reference_price=Decimal("101"))
    conflict = _forged_actions(case.replay, (case.entry, conflicting_entry, case.exit))
    with pytest.raises(ValueError, match="ID_CONTENT_CONFLICT"):
        projector.project(conflict, (), case.as_of)


def test_warmup_build_witnesses_do_not_fabricate_a_trade(product_cases):
    case = product_cases.warmup_only_build()
    second_witness = replace(case.entry, sequence=1)
    frames = (
        replace(case.replay.frames[0], actions=(case.entry, second_witness)),
        case.replay.frames[1],
    )
    replay = replace(
        case.replay,
        frames=frames,
        actions=(case.entry, second_witness, case.exit),
    )

    result = ReferenceTradeProjector().project(replay, (), case.as_of)

    assert result.trades == ()
    assert result.diagnostics == ("NO_ELIGIBLE_ENTRY",)


def test_verified_initial_clear_is_a_diagnostic_without_a_reference_trade(
    product_cases,
):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )

    result = ReferenceTradeProjector().project(
        replay, (), case.bars[-1].bar.bar_end
    )

    assert result.trades == ()
    assert result.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)


def test_initial_clear_evidence_survives_later_price_interruption(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.main_rise_lifecycle_input(
        (*([Decimal("100")] * 35), Decimal("90"), Decimal("90"))
    )
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    preceding = case.bars[-2].bar
    following = case.bars[-1].bar
    gap_at = preceding.bar_end + (following.bar_end - preceding.bar_end) / 2
    gap = DataInterruption(
        product=case.identity.product,
        frequency=case.identity.frequency,
        physical_contract=following.physical_contract,
        segment_id=following.segment_id,
        trading_day=gap_at.date(),
        effective_at=gap_at,
        source_identity="market_data_service:price_unavailable:v1",
    )
    replay = replay_strategy(
        case.identity, case.bars,
        lifecycle_evidence=(evidence,), data_interruptions=(gap,),
    )

    result = ReferenceTradeProjector().project(
        replay, (), following.bar_end, data_interruptions=(gap,)
    )

    assert "INITIAL_CLEAR_NO_ENTRY" in result.diagnostics
    assert result.trades == ()


def test_initial_clear_projector_independently_rejects_missing_or_stale_evidence(
    product_cases,
):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )

    for damaged in (
        replace(replay, lifecycle_evidence=()),
        _forged_actions(replace(replay, lifecycle_evidence=()), replay.actions),
    ):
        result = ReferenceTradeProjector().project(
            damaged, (), case.bars[-1].bar.bar_end
        )
        assert result.trades == ()
        assert result.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)


def test_initial_clear_projector_rejects_an_unavailable_current_frame(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )
    current = replay.frames[-1]
    unavailable = replace(
        current.availability,
        status=FeatureRuntimeStatus.UNAVAILABLE,
        reason_code="TEST_UNAVAILABLE",
    )
    damaged = copy(replay)
    object.__setattr__(
        damaged,
        "frames",
        (*replay.frames[:-1], replace(current, availability=unavailable)),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(
            damaged, (), case.bars[-1].bar.bar_end
        )


def test_future_initial_clear_does_not_leak_a_diagnostic(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )

    future_damaged_evidence = replace(evidence, input_sha256="f" * 64)
    replay = _forged_lifecycle_evidence(replay, (future_damaged_evidence,))

    result = ReferenceTradeProjector().project(
        replay, (), case.bars[34].bar.bar_end
    )

    assert result.trades == ()
    assert "INITIAL_CLEAR_NO_ENTRY" not in result.diagnostics


def test_visible_initial_clear_projection_ignores_a_damaged_future_suffix(
    product_cases,
):
    from guiyi_quant.newow.product_adapters import replay_strategy

    closes = tuple(
        Decimal(value)
        for value in (*(["100"] * 35), "90", *(["110"] * 60), "80")
    )
    case = product_cases.main_rise_lifecycle_input(closes, "1d")
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )
    future = replay.frames[-1]
    damaged_bar = replace(
        future.bar,
        bar=replace(future.bar.bar, source_identity="tampered:future"),
    )
    damaged = copy(replay)
    object.__setattr__(
        damaged,
        "frames",
        (*replay.frames[:-1], replace(future, bar=damaged_bar)),
    )

    result = ReferenceTradeProjector().project(
        damaged, (), replay.actions[0].bar_end
    )

    assert result.trades == ()
    assert result.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)
    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(
            damaged, (), case.bars[-1].bar.bar_end
        )


def test_initial_clear_projector_rejects_phantom_future_evidence(product_cases):
    from guiyi_quant.newow.product_adapters import replay_strategy

    case = product_cases.initial_clear_input()
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )
    phantom_end = evidence.last_bar_end + timedelta(days=1)
    phantom = replace(
        evidence,
        last_bar_end=phantom_end,
        verified_cutoff=phantom_end,
        bar_count=evidence.bar_count + 1,
        input_sha256="f" * 64,
    )
    damaged = _forged_lifecycle_evidence(replay, (phantom,))

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(
            damaged, (), case.bars[-1].bar.bar_end
        )


@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_initial_clear_then_real_build_and_clear_projects_exactly_one_trade(
    product_cases, frequency
):
    from guiyi_quant.newow.product_adapters import replay_strategy

    closes = tuple(
        Decimal(value)
        for value in (*(["100"] * 35), "90", *(["110"] * 60), "80")
    )
    case = product_cases.main_rise_lifecycle_input(closes, frequency)
    evidence = product_cases.synthetic_lifecycle_evidence(case.bars)
    replay = replay_strategy(
        case.identity, case.bars, lifecycle_evidence=(evidence,)
    )

    assert [
        case.bars.index(next(bar for bar in case.bars if bar.bar.bar_end == action.bar_end))
        for action in replay.actions
    ] == [35, 36, 96]
    assert [action.kind for action in replay.actions] == ["CLEAR", "BUILD", "CLEAR"]
    assert replay.actions[0].trade_eligibility == "INITIAL_CLEAR_NO_ENTRY"
    projection = ReferenceTradeProjector().project(
        replay, (), case.bars[-1].bar.bar_end
    )

    assert projection.diagnostics == ("INITIAL_CLEAR_NO_ENTRY",)
    assert len(projection.trades) == 1
    trade = projection.trades[0]
    assert trade.entry_signal_id == replay.actions[1].signal_id
    assert trade.exit_signal_id == replay.actions[2].signal_id
    assert trade.status == "CLOSED"


def test_stray_upstream_no_entry_diagnostic_needs_validated_pairing_evidence(
    product_cases,
):
    case = product_cases.open()
    replay = replace(
        case.replay,
        diagnostics=("UPSTREAM_FORMULA_DIAGNOSTIC", "NO_ELIGIBLE_ENTRY"),
    )

    result = ReferenceTradeProjector().project(replay, (), case.as_of)

    assert result.diagnostics == ("UPSTREAM_FORMULA_DIAGNOSTIC",)


def test_no_eligible_entry_requires_the_exact_same_segment_warmup_witness(
    product_cases,
):
    case = product_cases.warmup_only_build()
    damaged = replace(case.exit, related_build_id="missing-warmup-build")
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, damaged),
        ("BUILD", "CLEAR"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


def test_warmup_build_with_a_related_build_id_fails_closed(product_cases):
    case = product_cases.warmup_only_build()
    damaged = replace(case.entry, related_build_id="damaged-build-reference")
    frames = (
        replace(case.replay.frames[0], actions=(damaged,)),
        case.replay.frames[1],
    )
    replay = replace(
        case.replay,
        frames=frames,
        actions=(damaged, case.exit),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


def test_repeated_eligible_build_is_not_treated_as_adding_to_a_trade(product_cases):
    case = product_cases.closed()
    repeated_build = product_cases.action(
        case.identity, case.bars[1], "BUILD", "110"
    )
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, repeated_build),
        ("BUILD", "BUILD"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


@pytest.mark.parametrize("relation", [None, "damaged-related-id"])
def test_clear_without_the_current_explicit_build_reference_fails_closed(
    product_cases, relation
):
    case = product_cases.closed()
    clear = replace(case.exit, related_build_id=relation)
    replay = product_cases.replay(
        case.identity,
        case.bars,
        (case.entry, clear),
        ("BUILD", "CLEAR"),
    )

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)


def test_cross_strategy_frequency_contract_or_segment_reference_fails_closed(
    product_cases,
):
    case = product_cases.closed()
    foreign_cases = (
        product_cases.closed(strategy="main_rise"),
        product_cases.closed(frequency="60m"),
    )
    for foreign in foreign_cases:
        clear = replace(case.exit, related_build_id=foreign.entry.signal_id)
        replay = product_cases.replay(
            case.identity,
            case.bars,
            (case.entry, clear),
            ("BUILD", "CLEAR"),
        )
        with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
            ReferenceTradeProjector().project(replay, (), case.as_of)

    other_segment_entry = replace(
        case.entry, segment_id=f"{case.entry.segment_id}:other"
    )
    for foreign_id in (
        other_segment_entry.signal_id,
        replace(case.entry, physical_contract="RB2610").signal_id,
    ):
        clear = replace(case.exit, related_build_id=foreign_id)
        replay = product_cases.replay(
            case.identity,
            case.bars,
            (case.entry, clear),
            ("BUILD", "CLEAR"),
        )
        with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
            ReferenceTradeProjector().project(replay, (), case.as_of)


def test_projection_validates_segment_local_input_order_without_global_sorting(
    product_cases,
):
    case = product_cases.closed()
    reversed_replay = _forged_actions(case.replay, tuple(reversed(case.replay.actions)))
    with pytest.raises(ValueError, match="INPUT_ORDER"):
        ReferenceTradeProjector().project(reversed_replay, (), case.as_of)

    daily = product_cases.closed()
    hourly = product_cases.closed(frequency="60m")
    second_bar = replace(
        daily.bars[0],
        bar=replace(
            daily.bars[0].bar,
            segment_id=f"{daily.entry.segment_id}:second-owner",
            bar_end=hourly.entry.bar_end,
            trading_day=hourly.entry.trading_day,
            source_identity="owned:second-owner-prefix",
        ),
    )
    second_entry = product_cases.action(
        daily.identity, second_bar, "BUILD", "100"
    )
    second_frame = replace(
        daily.replay.frames[0], bar=second_bar, actions=(second_entry,)
    )
    reset = replace(
        daily.replay,
        frames=(daily.replay.frames[0], second_frame),
        actions=(daily.entry, second_entry),
    )
    result = ReferenceTradeProjector().project(reset, (), daily.as_of)
    assert [trade.status for trade in result.trades] == ["OPEN", "OPEN"]


def test_actions_after_as_of_do_not_change_the_earlier_projection(product_cases):
    case = product_cases.closed()
    as_of = case.entry.bar_end

    trade = ReferenceTradeProjector().project(case.replay, (), as_of).trades[0]

    assert trade.status == "OPEN"
    assert trade.exit_signal_id is None
    assert trade.holding_bars == 0


@pytest.mark.parametrize("strategy", ["trend", "oscillation", "main_rise"])
@pytest.mark.parametrize("frequency", ["1w", "1d", "60m"])
def test_all_nine_strategy_frequency_identities_stay_isolated(
    product_cases, strategy, frequency
):
    case = product_cases.closed(strategy=strategy, frequency=frequency)

    trade = ReferenceTradeProjector().project(case.replay, (), case.as_of).trades[0]

    assert (trade.strategy_code, trade.frequency, trade.formula_versions) == (
        strategy,
        frequency,
        case.identity.formula_versions,
    )
    assert trade.entry_signal_id == case.entry.signal_id


def test_non_finite_prices_and_a_naked_hint_are_rejected_at_the_boundary(
    product_cases,
):
    case = product_cases.closed()
    invalid_entry = copy(case.entry)
    object.__setattr__(invalid_entry, "reference_price", Decimal("NaN"))
    replay = _forged_actions(case.replay, (invalid_entry, case.exit))
    with pytest.raises(ValueError, match="INVALID_PRICE"):
        ReferenceTradeProjector().project(replay, (), case.as_of)

    hint = StrategyHint(
        identity=case.identity,
        physical_contract=case.entry.physical_contract,
        segment_id=case.entry.segment_id,
        bar_end=case.entry.bar_end,
        trading_day=case.entry.trading_day,
        kind="D1",
        known_at=case.entry.bar_end,
    )
    with pytest.raises(ValueError, match="INVALID_REPLAY"):
        ReferenceTradeProjector().project(hint, (), case.as_of)


def test_no_eligible_entry_value_cannot_be_used_on_a_build(product_cases):
    case = product_cases.closed()
    invalid = replace(
        case.entry, trade_eligibility=TradeEligibility.NO_ELIGIBLE_ENTRY
    )
    replay = _forged_actions(case.replay, (invalid,))

    with pytest.raises(ValueError, match="PAIRING_CONFLICT"):
        ReferenceTradeProjector().project(replay, (), case.as_of)
