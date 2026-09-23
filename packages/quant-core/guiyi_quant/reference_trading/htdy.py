"""Candidate first-seen HTDY reference model; never an account trade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .contracts import (
    ActionKind, CompletedReferenceBar, ReferenceAction, ReferenceState,
    ReferenceTransition, Side,
)
from .reducer import reduce_reference


MODEL_VERSION = "htdy_first_seen_reverse_close_v1"
CONTEXT_BARS = 32


@dataclass(frozen=True, slots=True)
class HtdyBarFact:
    bar_end: datetime
    trading_day: date
    physical_contract: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int


@dataclass(frozen=True, slots=True)
class HtdyForwardState:
    model_version: str
    observation_policy_version: str
    window: tuple[HtdyBarFact, ...] = ()

    def __post_init__(self) -> None:
        if self.model_version != MODEL_VERSION or not self.observation_policy_version:
            raise ValueError("HTDY_MODEL_IDENTITY_INVALID")
        object.__setattr__(self, "window", tuple(self.window))
        if len(self.window) > CONTEXT_BARS or any(
            not isinstance(bar, HtdyBarFact) for bar in self.window
        ):
            raise ValueError("HTDY_WINDOW_INVALID")


def project_first_seen(
    state: ReferenceState, *, observations: tuple[str, ...],
    physical_contract: str, owner_segment_id: str, calculation_segment_id: str,
    bar_end: datetime, trading_day: date, close: Decimal,
) -> tuple[tuple[ReferenceAction, ...], ReferenceTransition]:
    """Map only the current observed candidate; historical repainting is irrelevant."""
    if state.stream.reference_model_version != MODEL_VERSION:
        raise ValueError("HTDY_MODEL_IDENTITY_INVALID")
    kinds = set(observations)
    if len(kinds) != len(observations) or kinds - {"buy", "sell"} or len(kinds) > 1:
        raise ValueError("HTDY_SIGNAL_CONFLICT")
    target = None if not kinds else (Side.LONG if "buy" in kinds else Side.SHORT)
    current = None if state.open_trade is None else state.open_trade.side
    actions: list[ReferenceAction] = []
    common = dict(
        stream=state.stream, physical_contract=physical_contract,
        owner_segment_id=owner_segment_id, calculation_segment_id=calculation_segment_id,
        bar_end=bar_end, trading_day=trading_day, reference_price=close,
        reference_price_type="bar_close",
    )
    if target is not None and target != current:
        if state.open_trade is not None:
            actions.append(ReferenceAction(
                source_action_id=f"htdy:{physical_contract}:{bar_end.isoformat()}:close",
                sequence=0, kind=ActionKind.CLOSE,
                entry_action_id=state.open_trade.entry_action_id, **common,
            ))
        actions.append(ReferenceAction(
            source_action_id=f"htdy:{physical_contract}:{bar_end.isoformat()}:{target.value.lower()}",
            sequence=len(actions),
            kind=ActionKind.OPEN_LONG if target is Side.LONG else ActionKind.OPEN_SHORT,
            **common,
        ))
    frozen_actions = tuple(actions)
    return frozen_actions, reduce_reference(
        state, actions=frozen_actions,
        completed_bar=CompletedReferenceBar(
            physical_contract, owner_segment_id, calculation_segment_id,
            bar_end, trading_day, close,
        ),
    )
