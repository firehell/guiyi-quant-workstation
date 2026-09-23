"""Forward SuBing adapter over the existing incremental formula kernel."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
import json

from ..indicators.subing_ths import SubingThs15mKernel, SubingThs15mState
from .contracts import (
    ActionKind, BoundaryReason, CompletedReferenceBar, ReferenceAction,
    ReferenceBoundary, ReferenceState,
    ReferenceTransition, Side,
)
from .reducer import reduce_reference


@dataclass(frozen=True, slots=True)
class SubingForwardState:
    kernel_state: SubingThs15mState
    processed_count: int = 0
    physical_contract: str | None = None
    calculation_segment_id: str | None = None


def seed_subing_forward() -> SubingForwardState:
    return SubingForwardState(SubingThs15mKernel().initial_state())


def advance_subing_forward(
    strategy: SubingForwardState, reference: ReferenceState, *,
    physical_contract: str, owner_segment_id: str, calculation_segment_id: str,
    bar_end: datetime, trading_day: date, close: Decimal,
) -> tuple[SubingForwardState, tuple[ReferenceAction, ...], ReferenceTransition, dict[str, object]]:
    owner_changed = strategy.physical_contract is not None and (
        strategy.physical_contract != physical_contract
        or strategy.calculation_segment_id != calculation_segment_id
    )
    if owner_changed:
        prior = reference.open_trade
        boundary = () if prior is None else (ReferenceBoundary(
            reference.stream, BoundaryReason.ROLLOVER,
            prior.physical_contract, prior.owner_segment_id,
            prior.calculation_segment_id, bar_end, trading_day,
        ),)
        transition = reduce_reference(
            reference, boundaries=boundary, return_policy="delta_over_entry",
            completed_bar=CompletedReferenceBar(
                physical_contract, owner_segment_id, calculation_segment_id,
                bar_end, trading_day, close,
            ),
        )
        fresh = seed_subing_forward()
        kernel_state, _ = SubingThs15mKernel().step(
            fresh.kernel_state, float(close), bar_end=bar_end.isoformat(),
        )
        return (
            SubingForwardState(kernel_state, 1, physical_contract, calculation_segment_id),
            (), transition,
            {"bar_end": bar_end, "physical_contract": physical_contract,
             "direction": None, "ready": False, "rollover_interrupted": prior is not None},
        )
    kernel_state, result = SubingThs15mKernel().step(
        strategy.kernel_state, float(close), bar_end=bar_end.isoformat(),
    )
    if not result.valid or len(result.result_codes) > 1:
        raise ValueError("SUBING_FORWARD_SIGNAL_CONFLICT")
    actions: list[ReferenceAction] = []
    direction = result.result_codes[0] if result.result_codes else None
    if direction not in (None, "buy", "sell"):
        raise ValueError("SUBING_FORWARD_SIGNAL_CONFLICT")
    target = None if direction is None else (Side.LONG if direction == "buy" else Side.SHORT)
    current = None if reference.open_trade is None else reference.open_trade.side
    if target is not None and target != current:
        digest = sha256(json.dumps([
            reference.stream.stream_id, physical_contract, owner_segment_id,
            calculation_segment_id, bar_end.isoformat(), direction,
        ], separators=(",", ":")).encode()).hexdigest()
        common = dict(
            stream=reference.stream, physical_contract=physical_contract,
            owner_segment_id=owner_segment_id, calculation_segment_id=calculation_segment_id,
            bar_end=bar_end, trading_day=trading_day, reference_price=close,
            reference_price_type="subing_signal_close",
        )
        if reference.open_trade is not None:
            actions.append(ReferenceAction(
                source_action_id=f"subing:{digest}:close", sequence=0,
                kind=ActionKind.CLOSE,
                entry_action_id=reference.open_trade.entry_action_id, **common,
            ))
        actions.append(ReferenceAction(
            source_action_id=f"subing:{digest}:open", sequence=len(actions),
            kind=ActionKind.OPEN_LONG if target is Side.LONG else ActionKind.OPEN_SHORT,
            **common,
        ))
    transition = reduce_reference(
        reference, actions=tuple(actions), return_policy="delta_over_entry",
        completed_bar=CompletedReferenceBar(
            physical_contract, owner_segment_id, calculation_segment_id,
            bar_end, trading_day, close,
        ),
    )
    next_state = SubingForwardState(
        kernel_state, strategy.processed_count + 1, physical_contract,
        calculation_segment_id,
    )
    display = {
        "bar_end": bar_end, "physical_contract": physical_contract,
        "direction": direction, "ready": result.ready,
        "dif": None if result.dif is None else Decimal(str(result.dif)),
        "dea": None if result.dea is None else Decimal(str(result.dea)),
        "macd": None if result.macd is None else Decimal(str(result.macd)),
        "ema21": None if result.ema21 is None else Decimal(str(result.ema21)),
    }
    return next_state, tuple(actions), transition, display
