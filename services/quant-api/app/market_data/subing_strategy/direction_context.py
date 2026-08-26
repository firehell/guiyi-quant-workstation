"""Historical target-day direction context using the exact Daily Watch V2 seam."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from types import MappingProxyType
from typing import Protocol

from ..subing_daily_watch import (
    SubingDailyWatchDecision,
    SubingDailyWatchItem,
)
from ..subing_daily_watch_calendar import SubingDailyWatchCalendarError
from .contracts import SubingStrategyDirection


_DIRECTION_MAP = {
    SubingDailyWatchDecision.LONG_WATCH: SubingStrategyDirection.LONG_ONLY,
    SubingDailyWatchDecision.SHORT_WATCH: SubingStrategyDirection.SHORT_ONLY,
    SubingDailyWatchDecision.EXCLUDED: SubingStrategyDirection.NO_NEW_ENTRY,
    SubingDailyWatchDecision.UNAVAILABLE: SubingStrategyDirection.UNAVAILABLE,
}
_CONTEXT_IDENTITY_REASONS = frozenset(
    {
        "DATA_IDENTITY_MISMATCH",
        "DOMINANT_SEGMENT_UNAVAILABLE",
        "PRODUCT_METADATA_UNAVAILABLE",
    }
)


class _ItemProjector(Protocol):
    def project(
        self,
        symbol: str,
        *,
        source_trading_day: date,
    ) -> SubingDailyWatchItem: ...


class SubingStrategyContextIdentityError(RuntimeError):
    code = "SUBING_STRATEGY_CONTEXT_IDENTITY_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class SubingStrategyDirectionContext:
    symbol: str
    target_trading_day: date
    source_trading_day: date | None
    direction: SubingStrategyDirection
    reason_codes: tuple[str, ...]
    daily_bar_end: datetime | None
    hourly_bar_end: datetime | None
    physical_contract: str | None


class SubingStrategyDirectionContextResolver:
    def __init__(
        self,
        *,
        projector: _ItemProjector,
        previous_trading_day: Callable[[date], date],
    ) -> None:
        self._projector = projector
        self._previous_trading_day = previous_trading_day

    def resolve(
        self,
        symbol: str,
        target_days: Sequence[date],
    ) -> Mapping[date, SubingStrategyDirectionContext]:
        if (
            not isinstance(symbol, str)
            or not symbol
            or symbol != symbol.strip().lower()
            or any(type(target_day) is not date for target_day in target_days)
        ):
            raise SubingStrategyContextIdentityError()
        resolved: dict[date, SubingStrategyDirectionContext] = {}
        for target_day in dict.fromkeys(target_days):
            resolved[target_day] = self._resolve_one(symbol, target_day)
        return MappingProxyType(resolved)

    def _resolve_one(
        self,
        symbol: str,
        target_day: date,
    ) -> SubingStrategyDirectionContext:
        try:
            source_day = self._previous_trading_day(target_day)
        except SubingDailyWatchCalendarError as exc:
            if exc.code != "PREVIOUS_TRADING_DAY_UNAVAILABLE":
                raise
            return SubingStrategyDirectionContext(
                symbol=symbol,
                target_trading_day=target_day,
                source_trading_day=None,
                direction=SubingStrategyDirection.UNAVAILABLE,
                reason_codes=(exc.code,),
                daily_bar_end=None,
                hourly_bar_end=None,
                physical_contract=None,
            )

        item = self._projector.project(
            symbol,
            source_trading_day=source_day,
        )
        if item.symbol != symbol:
            raise SubingStrategyContextIdentityError()
        reasons = (
            item.unavailable_reasons
            if item.decision is SubingDailyWatchDecision.UNAVAILABLE
            else item.reason_codes
        )
        if frozenset(reasons) & _CONTEXT_IDENTITY_REASONS:
            raise SubingStrategyContextIdentityError()

        facts = tuple(fact for fact in (item.daily, item.hourly) if fact is not None)
        if any(fact.trading_day != source_day for fact in facts):
            raise SubingStrategyContextIdentityError()
        contracts = {fact.contract for fact in facts}
        if len(contracts) > 1:
            raise SubingStrategyContextIdentityError()
        return SubingStrategyDirectionContext(
            symbol=symbol,
            target_trading_day=target_day,
            source_trading_day=source_day,
            direction=_DIRECTION_MAP[item.decision],
            reason_codes=reasons,
            daily_bar_end=item.daily.bar_end if item.daily is not None else None,
            hourly_bar_end=item.hourly.bar_end if item.hourly is not None else None,
            physical_contract=next(iter(contracts), None),
        )
