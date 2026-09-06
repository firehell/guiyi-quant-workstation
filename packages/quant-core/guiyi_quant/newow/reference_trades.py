"""Pure projection of explicit Newow BUILD/CLEAR actions into reference trades."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from enum import StrEnum

from .product_contracts import (
    ActionKind,
    OwnerBoundary,
    ProductFrequency,
    ProductStrategy,
    StrategyAction,
    StrategyHint,
    StrategyReplay,
    TradeEligibility,
)
from .product_identity import (
    FUTURES_ADAPTATION_VERSION,
    REFERENCE_MODEL_VERSION,
    build_reference_trade_id,
    utc_timestamp,
)


class ReferenceTradeStatus(StrEnum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ROLLOVER_INTERRUPTED = "ROLLOVER_INTERRUPTED"


def _text(value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("NEWOW_REFERENCE_INVALID_TEXT")


def _price(value: object) -> None:
    if (
        not isinstance(value, Decimal)
        or not value.is_finite()
        or value <= Decimal("0")
    ):
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
        object.__setattr__(self, "strategy_code", ProductStrategy(self.strategy_code))
        object.__setattr__(self, "frequency", ProductFrequency(self.frequency))
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
            object.__setattr__(self, "mark_bar_end", utc_timestamp(self.mark_bar_end))
            _price(self.mark_reference_price)
            _metric(self.mark_change_pct)

        if self.status is ReferenceTradeStatus.ROLLOVER_INTERRUPTED:
            if self.interrupted_at is None or self.interruption_reason is None:
                raise ValueError("NEWOW_REFERENCE_INCONSISTENT_INTERRUPTION")
            object.__setattr__(
                self, "interrupted_at", utc_timestamp(self.interrupted_at)
            )
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


def _open_trade(entry: StrategyAction, holding_bars: int = 0) -> ReferenceTrade:
    identity = entry.identity
    return ReferenceTrade(
        reference_trade_id=build_reference_trade_id(entry),
        product=identity.product,
        strategy_code=identity.strategy,
        frequency=identity.frequency,
        physical_contract=entry.physical_contract,
        segment_id=entry.segment_id,
        formula_versions=identity.formula_versions,
        reference_model_version=REFERENCE_MODEL_VERSION,
        futures_adaptation_version=FUTURES_ADAPTATION_VERSION,
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


def _interruption_mark(
    replay: StrategyReplay,
    owner: tuple[str, str],
    boundary: OwnerBoundary,
    entry: StrategyAction,
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
        if entry.bar_end <= bar.bar_end <= boundary.effective_at:
            _price(bar.close)
            result = (bar.bar_end, bar.close, position)
        position += 1
    return result


def _visible_hints(
    replay: StrategyReplay, as_of: datetime
) -> tuple[StrategyHint, ...]:
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
    attached: list[list[str]] = [[] for _ in trades]
    bar_level: list[StrategyHint] = []
    unassigned: list[StrategyHint] = []

    for hint in hints:
        if hint.sequence is None or (
            hint.physical_contract,
            hint.segment_id,
            hint.bar_end,
            hint.sequence,
        ) in action_positions:
            bar_level.append(hint)
            continue

        hint_position = (hint.bar_end, hint.sequence)
        owners = (hint.physical_contract, hint.segment_id)
        matches: list[int] = []
        for index, trade in enumerate(trades):
            if owners != (trade.physical_contract, trade.segment_id):
                continue
            entry = actions_by_id[trade.entry_signal_id]
            if hint_position <= (entry.bar_end, entry.sequence):
                continue
            if trade.status is ReferenceTradeStatus.CLOSED:
                exit_action = actions_by_id[trade.exit_signal_id]
                if hint_position >= (exit_action.bar_end, exit_action.sequence):
                    continue
            elif trade.status is ReferenceTradeStatus.ROLLOVER_INTERRUPTED:
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
    ) -> ReferenceProjection:
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

        actions = _dedupe_actions(tuple(replay.actions))
        _validate_segment_local_order(actions)
        positions, last_positions = _effective_bar_positions(replay, as_of)
        diagnostics = [
            diagnostic
            for diagnostic in dict.fromkeys(replay.diagnostics)
            if diagnostic != "NO_ELIGIBLE_ENTRY"
        ]
        trades: list[ReferenceTrade] = []
        open_by_owner: dict[tuple[str, str], tuple[int, StrategyAction, int]] = {}
        warmup_witnesses: dict[str, StrategyAction] = {}

        for action in actions:
            if action.bar_end > as_of:
                _validate_action(replay, action, positions, require_position=False)
                continue
            boundary = effective_boundaries.get(
                (action.physical_contract, action.segment_id)
            )
            if (
                boundary is not None
                and action.kind is ActionKind.CLEAR
                and action.bar_end >= boundary.effective_at
            ):
                _validate_action(replay, action, positions)
                continue
            action_index = _validate_action(replay, action, positions)
            owner = (action.physical_contract, action.segment_id)

            if action.trade_eligibility is TradeEligibility.WARMUP_ONLY:
                if (
                    action.kind is not ActionKind.BUILD
                    or action.related_build_id is not None
                ):
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                warmup_witnesses[action.signal_id] = action
                continue

            if action.trade_eligibility is TradeEligibility.NO_ELIGIBLE_ENTRY:
                witness = warmup_witnesses.get(action.related_build_id or "")
                if (
                    action.kind is not ActionKind.CLEAR
                    or witness is None
                    or open_by_owner.get(owner) is not None
                    or witness.identity != action.identity
                    or witness.physical_contract != action.physical_contract
                    or witness.segment_id != action.segment_id
                ):
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                if "NO_ELIGIBLE_ENTRY" not in diagnostics:
                    diagnostics.append("NO_ELIGIBLE_ENTRY")
                continue

            if action.trade_eligibility is not TradeEligibility.ELIGIBLE:
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")

            if action.kind is ActionKind.BUILD:
                if action.related_build_id is not None or owner in open_by_owner:
                    raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
                trade = _open_trade(action)
                trades.append(trade)
                open_by_owner[owner] = (len(trades) - 1, action, action_index)
                continue

            current = open_by_owner.get(owner)
            if (
                action.kind is not ActionKind.CLEAR
                or current is None
                or action.related_build_id != current[1].signal_id
            ):
                raise ValueError("NEWOW_REFERENCE_PAIRING_CONFLICT")
            trade_position, entry, entry_index = current
            trades[trade_position] = replace(
                trades[trade_position],
                exit_signal_id=action.signal_id,
                exit_bar_end=action.bar_end,
                exit_trading_day=action.trading_day,
                exit_reference_price=action.reference_price,
                status=ReferenceTradeStatus.CLOSED,
                holding_bars=action_index - entry_index,
                reference_return_pct=_reference_return(
                    entry.reference_price, action.reference_price
                ),
            )
            del open_by_owner[owner]

        for owner, (trade_position, _entry, entry_index) in open_by_owner.items():
            boundary = effective_boundaries.get(owner)
            if boundary is None:
                last_index = last_positions.get(owner, entry_index)
                trades[trade_position] = replace(
                    trades[trade_position], holding_bars=last_index - entry_index
                )
                continue
            mark = _interruption_mark(replay, owner, boundary, _entry, as_of)
            if mark is None:
                trades[trade_position] = replace(
                    trades[trade_position],
                    status=ReferenceTradeStatus.ROLLOVER_INTERRUPTED,
                    interrupted_at=boundary.effective_at,
                    interruption_reason="OWNER_BOUNDARY_MARK_UNAVAILABLE",
                )
                continue
            mark_bar_end, mark_price, mark_index = mark
            trades[trade_position] = replace(
                trades[trade_position],
                status=ReferenceTradeStatus.ROLLOVER_INTERRUPTED,
                holding_bars=mark_index - entry_index,
                mark_bar_end=mark_bar_end,
                mark_reference_price=mark_price,
                mark_change_pct=_reference_return(_entry.reference_price, mark_price),
                interrupted_at=boundary.effective_at,
                interruption_reason="OWNER_BOUNDARY",
            )

        visible_hints = _visible_hints(replay, as_of)
        trades, bar_level_hints, unassigned_hints = _attach_hints(
            trades, actions, visible_hints, as_of
        )
        return ReferenceProjection(
            trades=tuple(trades),
            bar_level_hints=bar_level_hints,
            unassigned_hints=unassigned_hints,
            diagnostics=tuple(diagnostics),
            as_of=as_of,
        )
