"""Public immutable results for the active-product JDJ 1m reference lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from app.research.jdj.jdj_events import JdjDirection


class JdjActionKind(StrEnum):
    ENTRY = "entry"
    ADD = "add"
    REDUCE = "reduce"
    EXIT = "exit"
    DAILY_PAUSE = "daily_pause"
    DAILY_STOP = "daily_stop"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class JdjAction:
    event_id: str
    episode_id: str | None
    kind: JdjActionKind
    source_event_ids: tuple[str, ...]
    primary_setup: str | None
    supporting_setups: tuple[str, ...]
    direction: JdjDirection | None
    contract: str
    trading_day: date
    segment_start_trading_day: date
    decision_at: datetime
    effective_bar_end: datetime | None
    reference_price: Decimal | None
    quantity: int
    position_quantity_after: int
    stop_price: Decimal | None
    target_price: Decimal | None
    reward_risk: Decimal | None
    reason: str
    fill_basis: str | None


@dataclass(frozen=True, slots=True)
class JdjReferenceReplay:
    actions: tuple[JdjAction, ...]
