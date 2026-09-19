"""Pure projection of explicit Newow BUILD/CLEAR actions into reference trades."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum
from hashlib import sha256
import json

from ..reference_trading.contracts import (
    ActionKind as UnifiedActionKind,
    BoundaryReason,
    CompletedReferenceBar,
    ReferenceAction as UnifiedReferenceAction,
    ReferenceBoundary,
    ReferenceState as UnifiedReferenceState,
    ReferenceTrade as UnifiedReferenceTrade,
    StreamIdentity,
    TradeStatus as UnifiedTradeStatus,
)
from ..reference_trading.reducer import reduce_reference
from ..reference_trading.adapters import strategy_input_fingerprint

from .product_contracts import (
    ActionKind,
    DataInterruption,
    FeatureRuntimeStatus,
    MainState,
    OwnerBoundary,
    ProductFrequency,
    ProductStrategy,
    StrategyAction,
    StrategyFrame,
    StrategyHint,
    StrategyReplay,
    TradeEligibility,
    lifecycle_input_sha256,
    validate_lifecycle_replay_evidence,
)
from .product_identity import (
    InputQualityPolicy,
    REFERENCE_MODEL_VERSION,
    build_reference_trade_id,
    futures_adaptation_version,
    utc_timestamp,
)


class ReferenceTradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ROLLOVER_INTERRUPTED = "ROLLOVER_INTERRUPTED"
    DATA_INTERRUPTED = "DATA_INTERRUPTED"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_REFERENCE_INVALID_TEXT")


def _price(value: object) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= Decimal("0"):
        raise ValueError("NEWOW_REFERENCE_INVALID_PRICE")


def _metric(value: object) -> None:
    if not isinstance(value, Decimal) or not value.is_finite():
        raise ValueError("NEWOW_REFERENCE_INVALID_METRIC")


def _day(value: object) -> None:
    if type(value) is not date:
        raise ValueError("NEWOW_REFERENCE_INVALID_TRADING_DAY")


@dataclass(frozen=True, slots=True)
class ReferenceTrade:
    reference_trade_id: str
    product: str
    strategy_code: ProductStrategy
    frequency: ProductFrequency
    physical_contract: str
    segment_id: str
    formula_versions: tuple[str, ...]
    reference_model_version: str
    futures_adaptation_version: str
    entry_signal_id: str
    entry_bar_end: datetime
    entry_trading_day: date
    entry_reference_price: Decimal
    exit_signal_id: str | None
    exit_bar_end: datetime | None
    exit_trading_day: date | None
    exit_reference_price: Decimal | None
    status: ReferenceTradeStatus
    holding_bars: int
    reference_return_pct: Decimal | None
    mark_bar_end: datetime | None = None
    mark_reference_price: Decimal | None = None
    mark_change_pct: Decimal | None = None
    interrupted_at: datetime | None = None
    interruption_reason: str | None = None
    statistics_membership: str | None = None
    hint_ids: tuple[str, ...] = ()
    calculation_segment_id: str | None = None
    input_quality_policy: InputQualityPolicy = InputQualityPolicy.V1

    def __post_init__(self) -> None:
        for value in (
            self.reference_trade_id,
            self.product,
            self.physical_contract,
            self.segment_id,
            self.reference_model_version,
            self.futures_adaptation_version,
            self.entry_signal_id,
        ):
            _text(value)
        if self.calculation_segment_id is None:
            object.__setattr__(self, "calculation_segment_id", self.segment_id)
        else:
            _text(self.calculation_segment_id)
        object.__setattr__(self, "strategy_code", ProductStrategy(self.strategy_code))
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
        object.__setattr__(
            self, "input_quality_policy", InputQualityPolicy(self.input_quality_policy)
        )
        object.__setattr__(self, "status", ReferenceTradeStatus(self.status))
        formulas = tuple(self.formula_versions)
        if not formulas:
            raise ValueError("NEWOW_REFERENCE_EMPTY_FORMULAS")
        for formula in formulas:
            _text(formula)
        object.__setattr__(self, "formula_versions", formulas)
        object.__setattr__(self, "entry_bar_end", utc_timestamp(self.entry_bar_end))
        _day(self.entry_trading_day)
        _price(self.entry_reference_price)
        if type(self.holding_bars) is not int or self.holding_bars < 0:
            raise ValueError("NEWOW_REFERENCE_INVALID_HOLDING_BARS")

        exit_values = (
            self.exit_signal_id,
            self.exit_bar_end,
            self.exit_trading_day,
            self.exit_reference_price,
            self.reference_return_pct,
        )
        if self.status is ReferenceTradeStatus.CLOSED:
            if any(value is None for value in exit_values):
                raise ValueError("NEWOW_REFERENCE_INCONSISTENT_STATUS")
            assert self.exit_signal_id is not None
            assert self.exit_bar_end is not None
            assert self.exit_trading_day is not None
            assert self.exit_reference_price is not None
            assert self.reference_return_pct is not None
            _text(self.exit_signal_id)
            object.__setattr__(self, "exit_bar_end", utc_timestamp(self.exit_bar_end))
            _day(self.exit_trading_day)
            _price(self.exit_reference_price)
            _metric(self.reference_return_pct)
        elif any(value is not None for value in exit_values):
            raise ValueError("NEWOW_REFERENCE_INCONSISTENT_STATUS")

        mark_values = (
            self.mark_bar_end,
            self.mark_reference_price,
            self.mark_change_pct,
        )
        if any(value is not None for value in mark_values):
            if any(value is None for value in mark_values):
                raise ValueError("NEWOW_REFERENCE_INCONSISTENT_MARK")
            assert self.mark_bar_end is not None
            assert self.mark_reference_price is not None
            assert self.mark_change_pct is not None
            object.__setattr__(self, "mark_bar_end", utc_timestamp(self.mark_bar_end))
            _price(self.mark_reference_price)
            _metric(self.mark_change_pct)

        if self.status in (ReferenceTradeStatus.ROLLOVER_INTERRUPTED, ReferenceTradeStatus.DATA_INTERRUPTED):
            if self.interrupted_at is None or self.interruption_reason is None:
                raise ValueError("NEWOW_REFERENCE_INCONSISTENT_INTERRUPTION")
            interrupted_at = utc_timestamp(self.interrupted_at)
            if interrupted_at < self.entry_bar_end:
                raise ValueError("NEWOW_REFERENCE_INCONSISTENT_INTERRUPTION")
            object.__setattr__(self, "interrupted_at", interrupted_at)
            _text(self.interruption_reason)
        elif self.interrupted_at is not None or self.interruption_reason is not None:
            raise ValueError("NEWOW_REFERENCE_INCONSISTENT_INTERRUPTION")

        if self.statistics_membership is not None:
            _text(self.statistics_membership)
        hints = tuple(self.hint_ids)
        if len(set(hints)) != len(hints):
            raise ValueError("NEWOW_REFERENCE_DUPLICATE_HINT")
        for hint_id in hints:
            _text(hint_id)
        object.__setattr__(self, "hint_ids", hints)


@dataclass(frozen=True, slots=True)
class ReferenceProjection:
    trades: tuple[ReferenceTrade, ...]
    bar_level_hints: tuple[StrategyHint, ...]
    unassigned_hints: tuple[StrategyHint, ...]
    diagnostics: tuple[str, ...]
    as_of: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "trades", tuple(self.trades))
        object.__setattr__(self, "bar_level_hints", tuple(self.bar_level_hints))
        object.__setattr__(self, "unassigned_hints", tuple(self.unassigned_hints))
        object.__setattr__(self, "diagnostics", tuple(self.diagnostics))
        object.__setattr__(self, "as_of", utc_timestamp(self.as_of))
        if not all(isinstance(trade, ReferenceTrade) for trade in self.trades):
            raise ValueError("NEWOW_REFERENCE_INVALID_TRADE")
        hints = (*self.bar_level_hints, *self.unassigned_hints)
        if not all(isinstance(hint, StrategyHint) for hint in hints):
            raise ValueError("NEWOW_REFERENCE_INVALID_HINT")
        for diagnostic in self.diagnostics:
            _text(diagnostic)


@dataclass(frozen=True, slots=True)
class NewowReferenceReplayState:
    """Bounded restart state for the public reference projection fold."""

    stream: StreamIdentity
    reference_states: tuple[tuple[str, str, UnifiedReferenceState], ...] = ()
    active_trades: tuple[ReferenceTrade, ...] = ()
    active_actions: tuple[StrategyAction, ...] = ()
    warmup_witnesses: tuple[StrategyAction, ...] = ()
    owners_with_prior_actions: tuple[tuple[str, str], ...] = ()
    interrupted_entries: tuple[tuple[str, str, str], ...] = ()
    pending_hints: tuple[StrategyHint, ...] = ()
    processed_event_ids: tuple[str, ...] = ()
    verified_lifecycle_owners: tuple[tuple[str, str], ...] = ()
    verified_lifecycle_inputs: tuple[
        tuple[str, str, tuple[tuple[datetime, str], ...]], ...
    ] = ()
    lifecycle_consumed: tuple[tuple[str, str, int], ...] = ()
    diagnostics: tuple[str, ...] = ()


def _event_id(boundary: ReferenceBoundary) -> str:
    wire = (
        boundary.stream.stream_id, boundary.reason.value,
        boundary.physical_contract, boundary.owner_segment_id,
        boundary.calculation_segment_id, boundary.bar_end.isoformat(),
        boundary.trading_day.isoformat(),
    )
    return sha256(json.dumps(wire, separators=(",", ":")).encode()).hexdigest()


def _stream_for(replay: StrategyReplay) -> StreamIdentity:
    return StreamIdentity(
        strategy_code=f"newow_{replay.identity.strategy.value}",
        formula_versions=replay.identity.formula_versions,
        profile_id=replay.identity.profile_id,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(replay.identity.frequency),
        product=replay.identity.product,
        frequency=replay.identity.frequency.value,
        series_kind=replay.identity.series_kind,
        recording_mode="historical_replay",
        observation_policy_version=None,
    )


def _lifecycle_frame_fingerprint(frame: StrategyFrame) -> str:
    return strategy_input_fingerprint({
        "source_bar": lifecycle_input_sha256((frame.bar,)),
        "main_state": frame.main_state,
        "main_values": frame.main_values,
        "availability_status": frame.availability.status,
        "availability_evidence": frame.availability.evidence_status,
        "availability_reason": frame.availability.reason_code,
        "actions": tuple((
            action.signal_id, action.kind, action.reference_price,
            action.anchor_price, action.sequence, action.related_build_id,
            action.source_marker_id, action.source_related_marker_ids,
            action.trade_eligibility, action.calculation_segment_id,
        ) for action in frame.actions),
        "hints": tuple(hint.hint_id for hint in frame.hints),
    })


def _reference_return(entry: Decimal, exit_: Decimal) -> Decimal:
    _price(entry)
    _price(exit_)
    with localcontext() as context:
        context.prec = 28
        context.rounding = ROUND_HALF_EVEN
        return (exit_ / entry - Decimal("1")) * Decimal("100")


def _dedupe_actions(actions: tuple[StrategyAction, ...]) -> tuple[StrategyAction, ...]:
    seen: dict[str, StrategyAction] = {}
    unique: list[StrategyAction] = []
    for action in actions:
        if not isinstance(action, StrategyAction):
            raise ValueError("NEWOW_REFERENCE_INVALID_REPLAY")
        previous = seen.get(action.signal_id)
        if previous is not None:
            if previous != action:
                raise ValueError("NEWOW_REFERENCE_ID_CONTENT_CONFLICT")
            continue
        seen[action.signal_id] = action
        unique.append(action)
    return tuple(unique)


def _validate_segment_local_order(actions: tuple[StrategyAction, ...]) -> None:
    seen_segments: set[str] = set()
    segment_id: str | None = None
    physical_contract: str | None = None
    previous: tuple[datetime, int] | None = None
    for action in actions:
        if action.segment_id != segment_id:
            if action.segment_id in seen_segments:
                raise ValueError("NEWOW_REFERENCE_INPUT_ORDER")
            if segment_id is not None:
                seen_segments.add(segment_id)
            segment_id = action.segment_id
            physical_contract = action.physical_contract
            previous = None
        elif action.physical_contract != physical_contract:
            raise ValueError("NEWOW_REFERENCE_INPUT_ORDER")
        current = (action.bar_end, action.sequence)
        if previous is not None and previous >= current:
            raise ValueError("NEWOW_REFERENCE_INPUT_ORDER")
        previous = current


def _effective_bar_positions(
    replay: StrategyReplay, as_of: datetime
) -> tuple[dict[tuple[str, str, datetime], int], dict[tuple[str, str], int]]:
    positions: dict[tuple[str, str, datetime], int] = {}
    last_positions: dict[tuple[str, str], int] = {}
    counts: dict[tuple[str, str], int] = {}
    for frame in replay.frames:
        bar = frame.bar.bar
        if (
            frame.bar.frequency != replay.identity.frequency
            or bar.bar_end > as_of
            or not bar.observation_eligible
            or bar.completed is not True
        ):
            continue
        owner = (bar.physical_contract, bar.segment_id)
        index = counts.get(owner, 0)
        positions[(bar.physical_contract, bar.segment_id, bar.bar_end)] = index
        last_positions[owner] = index
        counts[owner] = index + 1
    return positions, last_positions


def _validate_action(
    replay: StrategyReplay,
    action: StrategyAction,
    positions: dict[tuple[str, str, datetime], int],
    *,
    require_position: bool = True,
) -> int:
    if action.identity != replay.identity:
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    _price(action.reference_price)
    key = (action.physical_contract, action.segment_id, action.bar_end)
    if (
        require_position
        and key not in positions
        and action.trade_eligibility is TradeEligibility.ELIGIBLE
    ):
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    return positions.get(key, 0)


def _validate_initial_clear_no_entry(
    replay: StrategyReplay,
    action: StrategyAction,
    positions: dict[tuple[str, str, datetime], int],
    frames_by_owner: dict[tuple[str, str], list[StrategyFrame]],
    verified_owners: frozenset[tuple[str, str]],
    has_prior_actions: bool,
) -> int:
    owner = (action.physical_contract, action.segment_id)
    key = (*owner, action.bar_end)
    frames = frames_by_owner.get(owner, ())
    matching = tuple(frame for frame in frames if frame.bar.bar.bar_end == action.bar_end)
    if (
        action.identity != replay.identity
        or replay.identity.strategy is not ProductStrategy.MAIN_RISE
        or action.kind is not ActionKind.CLEAR
        or action.related_build_id is not None
        or action.sequence != 0
        or action.source_marker_id is not None
        or action.source_related_marker_ids
        or owner not in verified_owners
        or key not in positions
        or has_prior_actions
        or len(matching) != 1
    ):
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    current = matching[0]
    prefix = tuple(frame for frame in frames if frame.bar.bar.bar_end <= action.bar_end)
    prior = prefix[:-1]
    values = dict(current.main_values)
    ma35 = values.get("ma35")
    ma45 = values.get("ma45")
    if (
        not prior
        or current is not prefix[-1]
        or current.availability.status is not FeatureRuntimeStatus.READY
        or not current.bar.bar.observation_eligible
        or current.main_state is not MainState.CLEAR
        or current.actions != (action,)
        or ma35 is None
        or ma45 is None
        or ma35 >= ma45
        or action.reference_price != ma45
    ):
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    for frame in prior:
        frame_values = dict(frame.main_values)
        prior_ma35 = frame_values.get("ma35")
        prior_ma45 = frame_values.get("ma45")
        if (
            frame.availability.status is not FeatureRuntimeStatus.READY
            or prior_ma35 is None
            or prior_ma45 is None
            or prior_ma35 < prior_ma45
            or frame.actions
        ):
            raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    return positions[key]


def _validate_checkpointed_initial_clear(
    replay: StrategyReplay,
    action: StrategyAction,
    positions: dict[tuple[str, str, datetime], int],
    frames_by_owner: dict[tuple[str, str], list[StrategyFrame]],
    verified_owners: set[tuple[str, str]],
    has_prior_actions: bool,
) -> int:
    """Validate the current CLEAR using a previously verified owner lifecycle."""

    owner = (action.physical_contract, action.segment_id)
    key = (*owner, action.bar_end)
    matching = tuple(
        frame for frame in frames_by_owner.get(owner, ())
        if frame.bar.bar.bar_end == action.bar_end
    )
    if (
        action.identity != replay.identity
        or replay.identity.strategy is not ProductStrategy.MAIN_RISE
        or action.kind is not ActionKind.CLEAR
        or action.related_build_id is not None
        or action.sequence != 0
        or action.source_marker_id is not None
        or action.source_related_marker_ids
        or owner not in verified_owners
        or key not in positions
        or has_prior_actions
        or len(matching) != 1
    ):
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    current = matching[0]
    values = dict(current.main_values)
    ma35 = values.get("ma35")
    ma45 = values.get("ma45")
    if (
        current.availability.status is not FeatureRuntimeStatus.READY
        or not current.bar.bar.observation_eligible
        or current.main_state is not MainState.CLEAR
        or current.actions != (action,)
        or ma35 is None
        or ma45 is None
        or ma35 >= ma45
        or action.reference_price != ma45
    ):
        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
    return positions[key]


def _open_trade(entry: StrategyAction, holding_bars: int = 0) -> ReferenceTrade:
    identity = entry.identity
    return ReferenceTrade(
        reference_trade_id=build_reference_trade_id(entry),
        product=identity.product,
        strategy_code=identity.strategy,
        frequency=identity.frequency,
        physical_contract=entry.physical_contract,
        segment_id=entry.segment_id,
        calculation_segment_id=entry.calculation_segment_id,
        formula_versions=identity.formula_versions,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(
            identity.frequency, identity.input_quality_policy
        ),
        entry_signal_id=entry.signal_id,
        entry_bar_end=entry.bar_end,
        entry_trading_day=entry.trading_day,
        entry_reference_price=entry.reference_price,
        exit_signal_id=None,
        exit_bar_end=None,
        exit_trading_day=None,
        exit_reference_price=None,
        status=ReferenceTradeStatus.OPEN,
        holding_bars=holding_bars,
        reference_return_pct=None,
        input_quality_policy=identity.input_quality_policy,
    )


def _effective_boundaries(
    boundaries: tuple[OwnerBoundary, ...], as_of: datetime
) -> dict[tuple[str, str], OwnerBoundary]:
    effective: dict[tuple[str, str], OwnerBoundary] = {}
    for boundary in boundaries:
        if boundary.effective_at > as_of:
            continue
        owner = (boundary.old_contract, boundary.old_segment_id)
        previous = effective.get(owner)
        if previous is not None and previous != boundary:
            raise ValueError("NEWOW_REFERENCE_INVALID_BOUNDARIES")
        effective[owner] = boundary
    return effective


def _latest_owner_mark(
    replay: StrategyReplay,
    owner: tuple[str, str],
    entry: StrategyAction,
    through: datetime,
    as_of: datetime,
) -> tuple[datetime, Decimal, int] | None:
    result: tuple[datetime, Decimal, int] | None = None
    position = 0
    for frame in replay.frames:
        product_bar = frame.bar
        bar = product_bar.bar
        if (
            product_bar.frequency != replay.identity.frequency
            or bar.physical_contract != owner[0]
            or bar.segment_id != owner[1]
            or bar.bar_end > as_of
            or not bar.observation_eligible
            or bar.completed is not True
        ):
            continue
        if entry.bar_end <= bar.bar_end <= through:
            _price(bar.close)
            result = (bar.bar_end, bar.close, position)
        position += 1
    return result


def _visible_hints(replay: StrategyReplay, as_of: datetime) -> tuple[StrategyHint, ...]:
    visible: list[StrategyHint] = []
    for hint in replay.hints:
        if not isinstance(hint, StrategyHint):
            raise ValueError("NEWOW_REFERENCE_INVALID_HINT")
        if hint.identity != replay.identity:
            raise ValueError("NEWOW_REFERENCE_INVALID_HINT")
        if hint.retrospective or hint.kind.casefold() in {
            "control_mirror",
            "zhaoyaojing",
        }:
            raise ValueError("NEWOW_REFERENCE_RETROSPECTIVE_HINT")
        if hint.sequence is not None and type(hint.sequence) is not int:
            raise ValueError("NEWOW_REFERENCE_INVALID_HINT")
        if hint.known_at <= as_of:
            visible.append(hint)
    return tuple(visible)


def _attach_hints(
    trades: list[ReferenceTrade],
    actions: tuple[StrategyAction, ...],
    hints: tuple[StrategyHint, ...],
    as_of: datetime,
) -> tuple[list[ReferenceTrade], tuple[StrategyHint, ...], tuple[StrategyHint, ...]]:
    actions_by_id = {action.signal_id: action for action in actions}
    action_positions = {
        (
            action.physical_contract,
            action.segment_id,
            action.bar_end,
            action.sequence,
        )
        for action in actions
    }
    action_bars = {
        (action.physical_contract, action.segment_id, action.bar_end)
        for action in actions
    }
    attached: list[list[str]] = [[] for _ in trades]
    bar_level: list[StrategyHint] = []
    unassigned: list[StrategyHint] = []
    for hint in hints:
        hint_bar = (hint.physical_contract, hint.segment_id, hint.bar_end)
        if (hint.sequence is None and hint_bar in action_bars) or (
            hint.sequence is not None and (*hint_bar, hint.sequence) in action_positions
        ):
            bar_level.append(hint)
            continue

        owners = (hint.physical_contract, hint.segment_id)
        matches: list[int] = []
        for index, trade in enumerate(trades):
            if owners != (trade.physical_contract, trade.segment_id):
                continue
            entry = actions_by_id[trade.entry_signal_id]
            if hint.sequence is None:
                if hint.bar_end <= entry.bar_end:
                    continue
            elif (hint.bar_end, hint.sequence) <= (entry.bar_end, entry.sequence):
                continue
            if trade.status is ReferenceTradeStatus.CLOSED:
                if trade.exit_signal_id is None:
                    raise ValueError("NEWOW_REFERENCE_INCONSISTENT_STATUS")
                exit_action = actions_by_id[trade.exit_signal_id]
                if hint.sequence is None:
                    if hint.bar_end >= exit_action.bar_end:
                        continue
                elif (hint.bar_end, hint.sequence) >= (
                    exit_action.bar_end,
                    exit_action.sequence,
                ):
                    continue
            elif trade.status is ReferenceTradeStatus.ROLLOVER_INTERRUPTED:
                if trade.interrupted_at is None:
                    raise ValueError("NEWOW_REFERENCE_INCONSISTENT_INTERRUPTION")
                if hint.bar_end > trade.interrupted_at:
                    continue
            elif hint.bar_end > as_of:
                continue
            matches.append(index)

        if len(matches) == 1:
            attached[matches[0]].append(hint.hint_id)
        else:
            unassigned.append(hint)

    return (
        [
            replace(trade, hint_ids=tuple(attached[index]))
            for index, trade in enumerate(trades)
        ],
        tuple(bar_level),
        tuple(unassigned),
    )


class ReferenceTradeProjector:
    """Pair normalized main actions without IO, nearest-marker guesses or exits."""

    def project(
        self,
        replay: StrategyReplay,
        boundaries: tuple[OwnerBoundary, ...],
        as_of: datetime,
        *,
        data_interruptions: tuple[DataInterruption, ...] = (),
    ) -> ReferenceProjection:
        _state, projection = self.advance(
            None, replay, boundaries, as_of, data_interruptions=data_interruptions,
        )
        return projection

    def seed(self, replay: StrategyReplay) -> NewowReferenceReplayState:
        """Verify immutable lifecycle evidence once, without retaining its frames."""

        if not isinstance(replay, StrategyReplay):
            raise ValueError("NEWOW_REFERENCE_INVALID_REPLAY")
        actions = _dedupe_actions(tuple(replay.actions))
        initial_actions = tuple(
            action for action in actions
            if action.trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
        )
        verified: frozenset[tuple[str, str]] = frozenset()
        if replay.lifecycle_evidence and initial_actions:
            try:
                verified = validate_lifecycle_replay_evidence(
                    replay.identity, replay.lifecycle_input_bars,
                    replay.lifecycle_evidence,
                )
            except ValueError as error:
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT") from error
        if initial_actions:
            positions, _ = _effective_bar_positions(
                replay, max(frame.bar.bar.bar_end for frame in replay.frames),
            )
            frames_by_owner: dict[tuple[str, str], list[StrategyFrame]] = {}
            for frame in replay.frames:
                owner = (frame.bar.bar.physical_contract, frame.bar.bar.segment_id)
                frames_by_owner.setdefault(owner, []).append(frame)
            for action in initial_actions:
                owner = (action.physical_contract, action.segment_id)
                has_prior = any(
                    candidate is not action
                    and (candidate.physical_contract, candidate.segment_id) == owner
                    and (candidate.bar_end, candidate.sequence)
                    < (action.bar_end, action.sequence)
                    for candidate in actions
                )
                _validate_initial_clear_no_entry(
                    replay, action, positions, frames_by_owner, verified, has_prior,
                )
        lifecycle_inputs: list[
            tuple[str, str, tuple[tuple[datetime, str], ...]]
        ] = []
        for owner in sorted(verified):
            values = tuple(
                (frame.bar.bar.bar_end, _lifecycle_frame_fingerprint(frame))
                for frame in replay.frames
                if (
                    frame.bar.bar.physical_contract,
                    frame.bar.bar.segment_id,
                ) == owner
            )
            lifecycle_inputs.append((owner[0], owner[1], values))
        return NewowReferenceReplayState(
            stream=_stream_for(replay),
            verified_lifecycle_owners=tuple(sorted(verified)),
            verified_lifecycle_inputs=tuple(lifecycle_inputs),
            lifecycle_consumed=tuple(
                (owner[0], owner[1], 0) for owner in sorted(verified)
            ),
        )

    def advance(
        self,
        state: NewowReferenceReplayState | None,
        replay: StrategyReplay,
        boundaries: tuple[OwnerBoundary, ...],
        as_of: datetime,
        *,
        data_interruptions: tuple[DataInterruption, ...] = (),
    ) -> tuple[NewowReferenceReplayState, ReferenceProjection]:
        if not isinstance(replay, StrategyReplay):
            raise ValueError("NEWOW_REFERENCE_INVALID_REPLAY")
        as_of = utc_timestamp(as_of)
        try:
            boundaries = tuple(boundaries)
        except TypeError as error:
            raise ValueError("NEWOW_REFERENCE_INVALID_BOUNDARIES") from error
        for boundary in boundaries:
            if not isinstance(boundary, OwnerBoundary):
                raise ValueError("NEWOW_REFERENCE_INVALID_BOUNDARIES")
            if boundary.product != replay.identity.product:
                raise ValueError("NEWOW_REFERENCE_INVALID_BOUNDARIES")
        effective_boundaries = _effective_boundaries(boundaries, as_of)
        try:
            data_interruptions = tuple(data_interruptions)
        except TypeError as error:
            raise ValueError("NEWOW_REFERENCE_INVALID_DATA_INTERRUPTION") from error
        if any(
            not isinstance(gap, DataInterruption)
            or gap.product != replay.identity.product
            or gap.frequency is not replay.identity.frequency
            for gap in data_interruptions
        ) or len({(gap.physical_contract, gap.segment_id, gap.effective_at)
                  for gap in data_interruptions}) != len(data_interruptions):
            raise ValueError("NEWOW_REFERENCE_INVALID_DATA_INTERRUPTION")

        actions = _dedupe_actions(tuple(replay.actions))
        _validate_segment_local_order(actions)
        positions, last_positions = _effective_bar_positions(replay, as_of)
        initial_actions = tuple(
            action
            for action in actions
            if action.bar_end <= as_of
            and action.trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
        )
        checkpoint_verified_owners = set(
            () if state is None else state.verified_lifecycle_owners
        )
        verified_owners = set(checkpoint_verified_owners)
        if replay.lifecycle_evidence and initial_actions:
            try:
                verified_owners.update(validate_lifecycle_replay_evidence(
                    replay.identity,
                    replay.lifecycle_input_bars,
                    replay.lifecycle_evidence,
                ))
            except ValueError as error:
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT") from error
        if initial_actions:
            try:
                effective_frames = tuple(
                    frame
                    for frame in replay.frames
                    if frame.bar.bar.bar_end <= as_of
                )
                effective_bars = tuple(frame.bar for frame in effective_frames)
                lifecycle_prefix = tuple(
                    bar
                    for bar in replay.lifecycle_input_bars
                    if bar.bar.bar_end <= as_of
                )
                if (
                    any(
                        (action.physical_contract, action.segment_id)
                        not in checkpoint_verified_owners
                        for action in initial_actions
                    )
                    and effective_bars != lifecycle_prefix
                ):
                    raise ValueError("NEWOW_PRODUCT_INVALID_LIFECYCLE_EVIDENCE")
            except ValueError as error:
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT") from error
        frames_by_owner: dict[tuple[str, str], list[StrategyFrame]] = {}
        for frame in replay.frames:
            if frame.bar.bar.bar_end > as_of:
                continue
            owner = (frame.bar.bar.physical_contract, frame.bar.bar.segment_id)
            frames_by_owner.setdefault(owner, []).append(frame)
        expected_lifecycle_inputs = {
            (contract, segment): values
            for contract, segment, values in (
                () if state is None else state.verified_lifecycle_inputs
            )
        }
        lifecycle_consumed = {
            (contract, segment): count
            for contract, segment, count in (
                () if state is None else state.lifecycle_consumed
            )
        }
        lifecycle_replay_only = bool(replay.frames)
        lifecycle_has_new = False
        for owner, frames in frames_by_owner.items():
            expected = expected_lifecycle_inputs.get(owner)
            if expected is None:
                lifecycle_replay_only = False
                continue
            consumed = lifecycle_consumed.get(owner, 0)
            actual = tuple(
                (frame.bar.bar.bar_end, _lifecycle_frame_fingerprint(frame))
                for frame in frames
            )
            remaining = len(expected) - consumed
            verified_part = actual[:remaining]
            suffix = actual[remaining:]
            if (
                verified_part
                == expected[consumed:consumed + len(verified_part)]
                and (
                    not suffix
                    or all(instant > expected[-1][0] for instant, _digest in suffix)
                )
            ):
                lifecycle_consumed[owner] = consumed + len(verified_part)
                lifecycle_has_new = lifecycle_has_new or bool(actual)
                lifecycle_replay_only = False
                continue
            expected_positions = {item: index for index, item in enumerate(expected)}
            positions_found = tuple(expected_positions.get(item) for item in actual)
            if (
                any(index is None for index in positions_found)
                or tuple(index for index in positions_found if index is not None)
                != tuple(sorted(index for index in positions_found if index is not None))
                or any(
                    index is not None and index >= consumed
                    for index in positions_found
                )
            ):
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
        diagnostics = list(dict.fromkeys((
            *(() if state is None else state.diagnostics),
            *(
                diagnostic for diagnostic in replay.diagnostics
                if diagnostic not in {"NO_ELIGIBLE_ENTRY", "INITIAL_CLEAR_NO_ENTRY"}
            ),
        )))
        stream = _stream_for(replay)
        if state is not None and state.stream != stream:
            raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
        if (
            lifecycle_replay_only
            and not lifecycle_has_new
            and initial_actions
            and all(
                action.trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY
                for action in actions
            )
            and "INITIAL_CLEAR_NO_ENTRY" in (() if state is None else state.diagnostics)
            and not effective_boundaries
            and not data_interruptions
        ):
            assert state is not None
            return state, ReferenceProjection(
                trades=state.active_trades,
                bar_level_hints=(),
                unassigned_hints=(),
                diagnostics=state.diagnostics,
                as_of=as_of,
            )
        reference_states: dict[tuple[str, str], UnifiedReferenceState] = {
            (contract, segment): reference_state
            for contract, segment, reference_state in (
                () if state is None else state.reference_states
            )
        }
        trades: list[ReferenceTrade] = list(
            () if state is None else state.active_trades
        )
        trade_positions: dict[str, int] = {
            trade.entry_signal_id: index for index, trade in enumerate(trades)
        }
        actions_by_id = {
            action.signal_id: action
            for action in (() if state is None else state.active_actions)
        }
        actions_by_id.update({action.signal_id: action for action in actions})
        actions_by_bar: dict[tuple[str, str, datetime], list[StrategyAction]] = {}
        for action in actions:
            actions_by_bar.setdefault(
                (action.physical_contract, action.segment_id, action.bar_end), [],
            ).append(action)
        warmup_witnesses: dict[str, StrategyAction] = {
            action.signal_id: action
            for action in (() if state is None else state.warmup_witnesses)
        }
        owners_with_prior_actions: set[tuple[str, str]] = set(
            () if state is None else state.owners_with_prior_actions
        )
        interrupted_entries: dict[tuple[str, str], str] = {
            (contract, segment): entry
            for contract, segment, entry in (
                () if state is None else state.interrupted_entries
            )
        }
        processed_event_ids = set(
            () if state is None else state.processed_event_ids
        )

        events: list[tuple[datetime, ReferenceBoundary, str]] = []
        for boundary in effective_boundaries.values():
            events.append((
                boundary.effective_at,
                ReferenceBoundary(
                    stream=stream, reason=BoundaryReason.ROLLOVER,
                    physical_contract=boundary.old_contract,
                    owner_segment_id=boundary.old_segment_id,
                    calculation_segment_id=boundary.old_segment_id,
                    bar_end=boundary.effective_at,
                    trading_day=boundary.effective_at.date(),
                ),
                "OWNER_BOUNDARY",
            ))
        for gap in data_interruptions:
            if gap.effective_at <= as_of:
                events.append((
                    gap.effective_at,
                    ReferenceBoundary(
                        stream=stream, reason=BoundaryReason.DATA_INTERRUPTED,
                        physical_contract=gap.physical_contract,
                        owner_segment_id=gap.segment_id,
                        calculation_segment_id=gap.segment_id,
                        bar_end=gap.effective_at,
                        trading_day=gap.trading_day,
                    ),
                    "SOURCE_PRICE_UNAVAILABLE",
                ))
        events.sort(key=lambda item: item[0])
        events = [event for event in events if _event_id(event[1]) not in processed_event_ids]
        event_index = 0

        def sync_transition(
            owner: tuple[str, str], transition, *, interrupted_at: datetime | None = None,
            interruption_reason: str | None = None,
            prior_open: UnifiedReferenceTrade | None = None,
        ) -> None:
            reference_states[owner] = transition.state
            for changed in transition.changed_trades:
                entry_signal_id = changed.entry_action_id
                entry = actions_by_id[entry_signal_id]
                position = trade_positions.get(entry_signal_id)
                if position is None:
                    public = _open_trade(entry)
                    trades.append(public)
                    position = len(trades) - 1
                    trade_positions[entry_signal_id] = position
                public = trades[position]
                if changed.status is UnifiedTradeStatus.CLOSED:
                    trades[position] = replace(
                        public,
                        exit_signal_id=changed.exit_action_id,
                        exit_bar_end=changed.exit_bar_end,
                        exit_trading_day=changed.exit_trading_day,
                        exit_reference_price=changed.exit_reference_price,
                        status=ReferenceTradeStatus.CLOSED,
                        holding_bars=changed.holding_bars,
                        reference_return_pct=changed.reference_return,
                        mark_bar_end=None,
                        mark_reference_price=None,
                        mark_change_pct=None,
                    )
                elif changed.status in (
                    UnifiedTradeStatus.ROLLOVER_INTERRUPTED,
                    UnifiedTradeStatus.DATA_INTERRUPTED,
                ):
                    source = prior_open or changed
                    trades[position] = replace(
                        public,
                        status=(
                            ReferenceTradeStatus.ROLLOVER_INTERRUPTED
                            if changed.status is UnifiedTradeStatus.ROLLOVER_INTERRUPTED
                            else ReferenceTradeStatus.DATA_INTERRUPTED
                        ),
                        holding_bars=source.holding_bars,
                        mark_bar_end=source.mark_bar_end,
                        mark_reference_price=source.mark_reference_price,
                        mark_change_pct=source.mark_return,
                        interrupted_at=interrupted_at,
                        interruption_reason=(
                            interruption_reason
                            if source.mark_bar_end is not None
                            else "OWNER_BOUNDARY_MARK_UNAVAILABLE"
                        ),
                    )
            current = transition.state.open_trade
            if current is not None:
                position = trade_positions[current.entry_action_id]
                trades[position] = replace(
                    trades[position],
                    holding_bars=current.holding_bars,
                    mark_bar_end=current.mark_bar_end,
                    mark_reference_price=current.mark_reference_price,
                    mark_change_pct=current.mark_return,
                )

        def apply_event(event: tuple[datetime, ReferenceBoundary, str]) -> None:
            owner = (event[1].physical_contract, event[1].owner_segment_id)
            reference_state = reference_states.get(owner, UnifiedReferenceState.flat(stream))
            prior_open = reference_state.open_trade
            boundary = event[1]
            if prior_open is not None and (
                prior_open.physical_contract,
                prior_open.owner_segment_id,
            ) == (boundary.physical_contract, boundary.owner_segment_id):
                boundary = replace(
                    boundary,
                    calculation_segment_id=prior_open.calculation_segment_id,
                )
                interrupted_entries[
                    (prior_open.physical_contract, prior_open.owner_segment_id)
                ] = prior_open.entry_action_id
            transition = reduce_reference(reference_state, boundaries=(boundary,))
            sync_transition(
                owner, transition, interrupted_at=event[0],
                interruption_reason=event[2], prior_open=prior_open,
            )
            for witness_id, witness in tuple(warmup_witnesses.items()):
                if (witness.physical_contract, witness.segment_id) == owner:
                    del warmup_witnesses[witness_id]
            processed_event_ids.add(_event_id(event[1]))

        for frame in replay.frames:
            bar = frame.bar.bar
            if bar.bar_end > as_of or frame.bar.frequency is not replay.identity.frequency:
                continue
            while event_index < len(events) and events[event_index][0] < bar.bar_end:
                apply_event(events[event_index])
                event_index += 1
            same_bar_events: list[tuple[datetime, ReferenceBoundary, str]] = []
            while event_index < len(events) and events[event_index][0] == bar.bar_end:
                same_bar_events.append(events[event_index])
                event_index += 1

            bar_owner = (bar.physical_contract, bar.segment_id)
            unrelated_events = [
                event for event in same_bar_events
                if (event[1].physical_contract, event[1].owner_segment_id) != bar_owner
            ]
            for event in unrelated_events:
                apply_event(event)
            same_bar_events = [event for event in same_bar_events if event not in unrelated_events]
            reference_state = reference_states.get(
                bar_owner, UnifiedReferenceState.flat(stream),
            )
            unified_actions: list[UnifiedReferenceAction] = []
            for action in sorted(
                actions_by_bar.get((bar.physical_contract, bar.segment_id, bar.bar_end), ()),
                key=lambda item: item.sequence,
            ):
                owner = (action.physical_contract, action.segment_id)
                action_boundary = effective_boundaries.get(owner)
                if any(
                    event[1].reason is BoundaryReason.DATA_INTERRUPTED
                    and (event[1].physical_contract, event[1].owner_segment_id) == owner
                    for event in same_bar_events
                ):
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                if action.trade_eligibility is TradeEligibility.INITIAL_CLEAR_NO_ENTRY:
                    if reference_state.open_trade is not None or (
                        action_boundary is not None and action.bar_end >= action_boundary.effective_at
                    ):
                        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                    if owner in checkpoint_verified_owners:
                        _validate_checkpointed_initial_clear(
                            replay, action, positions, frames_by_owner, verified_owners,
                            owner in owners_with_prior_actions,
                        )
                    else:
                        _validate_initial_clear_no_entry(
                            replay, action, positions, frames_by_owner,
                            frozenset(verified_owners),
                            owner in owners_with_prior_actions,
                        )
                    owners_with_prior_actions.add(owner)
                    if "INITIAL_CLEAR_NO_ENTRY" not in diagnostics:
                        diagnostics.append("INITIAL_CLEAR_NO_ENTRY")
                    continue
                _validate_action(replay, action, positions)
                if action.trade_eligibility is TradeEligibility.WARMUP_ONLY:
                    if action.kind is not ActionKind.BUILD or action.related_build_id is not None:
                        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                    warmup_witnesses[action.signal_id] = action
                    owners_with_prior_actions.add(owner)
                    continue
                if action.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY:
                    witness = warmup_witnesses.get(action.related_build_id or "")
                    if (
                        action.kind is not ActionKind.CLEAR or witness is None
                        or reference_state.open_trade is not None
                        or witness.identity != action.identity
                        or witness.physical_contract != action.physical_contract
                        or witness.segment_id != action.segment_id
                        or witness.calculation_segment_id != action.calculation_segment_id
                    ):
                        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                    if "NO_ELIGIBLE_ENTRY" not in diagnostics:
                        diagnostics.append("NO_ELIGIBLE_ENTRY")
                    owners_with_prior_actions.add(owner)
                    continue
                if action.trade_eligibility is not TradeEligibility.ELIGIBLE:
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                if action.kind is ActionKind.CLEAR and not action.related_build_id:
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                if action_boundary is not None and action.bar_end >= action_boundary.effective_at:
                    if action.kind is ActionKind.BUILD:
                        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                    if interrupted_entries.get(owner) != action.related_build_id:
                        raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                    del interrupted_entries[owner]
                    continue
                unified_actions.append(UnifiedReferenceAction(
                    stream=stream,
                    source_action_id=action.signal_id,
                    physical_contract=action.physical_contract,
                    owner_segment_id=action.segment_id,
                    calculation_segment_id=action.calculation_segment_id,
                    bar_end=action.bar_end,
                    trading_day=action.trading_day,
                    sequence=action.sequence,
                    kind=(
                        UnifiedActionKind.OPEN_LONG
                        if action.kind is ActionKind.BUILD else UnifiedActionKind.CLOSE
                    ),
                    reference_price=action.reference_price,
                    entry_action_id=(
                        action.related_build_id if action.kind is ActionKind.CLEAR else None
                    ),
                    reference_price_type="newow_strategy_reference",
                ))
                owners_with_prior_actions.add(owner)

            boundaries_for_bar = tuple(
                replace(
                    event[1],
                    calculation_segment_id=(
                        reference_state.open_trade.calculation_segment_id
                        if reference_state.open_trade is not None
                        else frame.bar.calculation_segment_id
                    ),
                )
                for event in same_bar_events
            )
            if not bar.observation_eligible:
                if unified_actions:
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                for event in same_bar_events:
                    apply_event(event)
                continue
            try:
                opening = next(
                    (
                        action for action in reversed(unified_actions)
                        if action.kind in (
                            UnifiedActionKind.OPEN_LONG, UnifiedActionKind.OPEN_SHORT,
                        )
                    ),
                    None,
                )
                completed_calculation_segment = (
                    opening.calculation_segment_id
                    if opening is not None
                    else (
                        reference_state.open_trade.calculation_segment_id
                        if reference_state.open_trade is not None
                        else frame.bar.calculation_segment_id
                    )
                )
                transition = reduce_reference(
                    reference_state,
                    actions=tuple(unified_actions),
                    boundaries=boundaries_for_bar,
                    completed_bar=CompletedReferenceBar(
                        physical_contract=bar.physical_contract,
                        owner_segment_id=bar.segment_id,
                        calculation_segment_id=completed_calculation_segment,
                        bar_end=bar.bar_end,
                        trading_day=bar.trading_day,
                        reference_price=bar.close,
                    ),
                )
            except ValueError as error:
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT") from error
            if transition.diagnostics and any(
                action.kind is UnifiedActionKind.CLOSE for action in unified_actions
            ):
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
            prior_open = reference_state.open_trade
            sync_transition(bar_owner, transition)
            processed_event_ids.update(_event_id(event[1]) for event in same_bar_events)
            if same_bar_events and prior_open is not None and transition.state.open_trade is None:
                interrupted_entries[bar_owner] = prior_open.entry_action_id
                event = same_bar_events[-1]
                position = trade_positions[prior_open.entry_action_id]
                trades[position] = replace(
                    trades[position],
                    holding_bars=prior_open.holding_bars,
                    mark_bar_end=prior_open.mark_bar_end,
                    mark_reference_price=prior_open.mark_reference_price,
                    mark_change_pct=prior_open.mark_return,
                    interrupted_at=event[0],
                    interruption_reason=event[2],
                )

        for action in actions:
            if action.bar_end > as_of:
                _validate_action(replay, action, positions, require_position=False)
        while event_index < len(events) and events[event_index][0] <= as_of:
            apply_event(events[event_index])
            event_index += 1

        if any(
            state.open_trade is not None and state.open_trade.mark_bar_end is None
            for state in reference_states.values()
        ):
            if "OPEN_MARK_UNAVAILABLE" not in diagnostics:
                diagnostics.append("OPEN_MARK_UNAVAILABLE")

        visible_hints = tuple(dict.fromkeys((
            *(() if state is None else state.pending_hints),
            *_visible_hints(replay, as_of),
        )))
        trades, bar_level_hints, unassigned_hints = _attach_hints(
            trades, tuple(actions_by_id.values()), visible_hints, as_of
        )
        projection = ReferenceProjection(
            trades=tuple(trades),
            bar_level_hints=bar_level_hints,
            unassigned_hints=unassigned_hints,
            diagnostics=tuple(diagnostics),
            as_of=as_of,
        )
        active_trades = tuple(
            trade for trade in projection.trades
            if trade.status is ReferenceTradeStatus.OPEN
        )
        active_ids = {trade.entry_signal_id for trade in active_trades}
        active_actions = tuple(
            actions_by_id[entry_id] for entry_id in sorted(active_ids)
        )
        active_hint_ids = {
            hint_id for trade in active_trades for hint_id in trade.hint_ids
        }
        next_state = NewowReferenceReplayState(
            stream=stream,
            reference_states=tuple(
                (owner[0], owner[1], reference_state)
                for owner, reference_state in sorted(reference_states.items())
            ),
            active_trades=active_trades,
            active_actions=active_actions,
            warmup_witnesses=tuple(
                warmup_witnesses[key] for key in sorted(warmup_witnesses)
            ),
            owners_with_prior_actions=tuple(sorted(owners_with_prior_actions)),
            interrupted_entries=tuple(
                (owner[0], owner[1], entry)
                for owner, entry in sorted(interrupted_entries.items())
            ),
            pending_hints=tuple(
                hint for hint in visible_hints if hint.hint_id in active_hint_ids
            ),
            processed_event_ids=tuple(sorted(processed_event_ids)),
            verified_lifecycle_owners=tuple(sorted(verified_owners)),
            verified_lifecycle_inputs=(
                () if state is None else state.verified_lifecycle_inputs
            ),
            lifecycle_consumed=tuple(
                (owner[0], owner[1], count)
                for owner, count in sorted(lifecycle_consumed.items())
            ),
            diagnostics=projection.diagnostics,
        )
        return next_state, projection
