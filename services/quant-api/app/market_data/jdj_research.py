"""Immutable request and result contracts for JDJ 1m research."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from types import MappingProxyType
from typing import Final, Mapping

from .jdj_context import JdjContextError
from .jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjTriggerEvent,
)
from .price_outcome import PriceHorizonEvaluation


JDJ_CANDIDATE_SOURCE_EVENT_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "jdj_trend_follow_1m_candidate_v1": "jdj_trend_follow_triggered",
        "jdj_trend_reentry_6_1m_candidate_v1": (
            "jdj_trend_reentry_6_triggered"
        ),
        "jdj_key_level_breakout_1m_candidate_v1": (
            "jdj_key_level_breakout_triggered"
        ),
    }
)
_HORIZONS = (3, 5, 8, 20)
_EVENT_TYPES = {
    "jdj_trend_follow_1m_candidate_v1": JdjTrendFollowTriggerEvent,
    "jdj_trend_reentry_6_1m_candidate_v1": JdjTrendReentryTriggerEvent,
    "jdj_key_level_breakout_1m_candidate_v1": (
        JdjKeyLevelBreakoutTriggerEvent
    ),
}


class JdjSourceUnavailableError(RuntimeError):
    code = "JDJ_SOURCE_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class JdjResearchRequest:
    since: date
    through: date
    symbol: str | None
    candidate_id: str

    def __post_init__(self) -> None:
        symbol = self.symbol
        if (
            type(self.since) is not date
            or type(self.through) is not date
            or self.since > self.through
            or type(self.candidate_id) is not str
            or self.candidate_id not in JDJ_CANDIDATE_SOURCE_EVENT_KINDS
        ):
            raise JdjContextError()
        if symbol is not None:
            if (
                type(symbol) is not str
                or not symbol.strip()
                or not symbol.strip().isascii()
                or not symbol.strip().isalpha()
            ):
                raise JdjContextError()
            symbol = symbol.strip().lower()
        object.__setattr__(self, "symbol", symbol)


@dataclass(frozen=True, slots=True)
class JdjResearchResult:
    candidate_id: str
    source_event_kind: str
    products: tuple[str, ...]
    segment_count: int
    evaluable_bar_count: int
    trigger_count_long: int
    trigger_count_short: int
    horizon_summary: Mapping[int, PriceHorizonEvaluation]
    events: tuple[JdjTriggerEvent, ...]

    def __post_init__(self) -> None:
        expected_event_kind = JDJ_CANDIDATE_SOURCE_EVENT_KINDS.get(
            self.candidate_id
        )
        summary = dict(self.horizon_summary)
        if (
            expected_event_kind is None
            or self.source_event_kind != expected_event_kind
            or type(self.products) is not tuple
            or not self.products
            or any(
                type(product) is not str
                or not product
                or not product.isascii()
                or not product.isalpha()
                or product != product.lower()
                for product in self.products
            )
            or type(self.segment_count) is not int
            or self.segment_count < 0
            or type(self.evaluable_bar_count) is not int
            or self.evaluable_bar_count < 0
            or type(self.trigger_count_long) is not int
            or self.trigger_count_long < 0
            or type(self.trigger_count_short) is not int
            or self.trigger_count_short < 0
            or set(summary) != set(_HORIZONS)
            or any(
                not _valid_horizon_evaluation(summary[horizon])
                for horizon in _HORIZONS
            )
            or type(self.events) is not tuple
            or any(
                not isinstance(event, _EVENT_TYPES[self.candidate_id])
                or event.candidate_id != self.candidate_id
                or event.source_event_kind != self.source_event_kind
                or event.symbol not in self.products
                for event in self.events
            )
            or tuple(sorted(self.events, key=_event_order_key)) != self.events
            or len({event.event_id for event in self.events})
            != len(self.events)
            or self.trigger_count_long
            != sum(
                event.direction is JdjDirection.LONG
                for event in self.events
            )
            or self.trigger_count_short
            != sum(
                event.direction is JdjDirection.SHORT
                for event in self.events
            )
        ):
            raise JdjContextError()
        object.__setattr__(
            self,
            "horizon_summary",
            MappingProxyType(
                {horizon: summary[horizon] for horizon in _HORIZONS}
            ),
        )


def _valid_horizon_evaluation(value: object) -> bool:
    if not isinstance(value, PriceHorizonEvaluation):
        return False
    medians = (
        value.median_directional_return_bps,
        value.median_mfe_bps,
        value.median_mae_bps,
    )
    if type(value.sample_count) is not int or value.sample_count < 0:
        return False
    if value.sample_count == 0:
        return all(item is None for item in medians)
    return all(isinstance(item, Decimal) and item.is_finite() for item in medians)


def _event_order_key(event: JdjTriggerEvent) -> tuple[object, ...]:
    return event.observed_at, event.segment_bar_index, event.event_id
