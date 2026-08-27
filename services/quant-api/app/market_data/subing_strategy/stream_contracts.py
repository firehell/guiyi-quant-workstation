"""Immutable completed-Bar inputs for the SuBing Strategy V1 state machine."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import ClassVar, TypeAlias

from ..domain import BarFrequency, CanonicalBar, normalize_contract_for_symbol
from .contracts import (
    SubingStrategyAction,
    SubingStrategyActionKind,
    SubingStrategyContractError,
)
from .engine import SubingStrategyPendingCancellation


def _aware(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )


def _validated_bar(value: object) -> CanonicalBar:
    if (
        type(value) is not CanonicalBar
        or not _aware(value.bar_end)
        or type(value.trading_day) is not date
    ):
        raise SubingStrategyContractError()
    return value


@dataclass(frozen=True, slots=True)
class Completed1mBar:
    bar: CanonicalBar
    frequency: ClassVar[BarFrequency] = BarFrequency.M1

    def __post_init__(self) -> None:
        if type(self).frequency is not BarFrequency.M1:
            raise SubingStrategyContractError()
        object.__setattr__(self, "bar", _validated_bar(self.bar))


@dataclass(frozen=True, slots=True)
class Completed5mBar:
    bar: CanonicalBar
    frequency: ClassVar[BarFrequency] = BarFrequency.M5

    def __post_init__(self) -> None:
        if type(self).frequency is not BarFrequency.M5:
            raise SubingStrategyContractError()
        object.__setattr__(self, "bar", _validated_bar(self.bar))


@dataclass(frozen=True, slots=True)
class Completed15mBar:
    bar: CanonicalBar
    frequency: ClassVar[BarFrequency] = BarFrequency.M15

    def __post_init__(self) -> None:
        if type(self).frequency is not BarFrequency.M15:
            raise SubingStrategyContractError()
        object.__setattr__(self, "bar", _validated_bar(self.bar))


@dataclass(frozen=True, slots=True)
class AuthoritativeSegmentTerminal:
    symbol: str
    contract: str
    segment_start_trading_day: date
    terminal_bar: CanonicalBar

    def __post_init__(self) -> None:
        terminal_bar = _validated_bar(self.terminal_bar)
        if (
            not isinstance(self.symbol, str)
            or self.symbol != self.symbol.strip().lower()
            or not self.symbol.isascii()
            or not self.symbol.isalpha()
            or normalize_contract_for_symbol(self.symbol, self.contract)
            != self.contract
            or type(self.segment_start_trading_day) is not date
            or terminal_bar.trading_day < self.segment_start_trading_day
        ):
            raise SubingStrategyContractError()
        object.__setattr__(self, "terminal_bar", terminal_bar)


SubingStrategyStreamInput: TypeAlias = (
    Completed1mBar | Completed5mBar | Completed15mBar | AuthoritativeSegmentTerminal
)


@dataclass(frozen=True, slots=True)
class SubingStrategyStepOutput:
    actions: tuple[SubingStrategyAction, ...]
    cancellations: tuple[SubingStrategyPendingCancellation, ...]
    state_changed: bool

    def __post_init__(self) -> None:
        if (
            type(self.actions) is not tuple
            or any(type(action) is not SubingStrategyAction for action in self.actions)
            or type(self.cancellations) is not tuple
            or type(self.state_changed) is not bool
        ):
            raise SubingStrategyContractError()
        normalized_cancellations: list[SubingStrategyPendingCancellation] = []
        for cancellation in self.cancellations:
            if (
                type(cancellation) is not SubingStrategyPendingCancellation
                or not isinstance(cancellation.kind, SubingStrategyActionKind)
                or not _aware(cancellation.decision_at)
                or not isinstance(cancellation.opportunity_id, str)
                or not cancellation.opportunity_id.startswith("subing-opportunity:")
                or not isinstance(cancellation.reason_code, str)
                or not cancellation.reason_code
            ):
                raise SubingStrategyContractError()
            normalized_cancellations.append(
                replace(
                    cancellation,
                    decision_at=cancellation.decision_at.astimezone(UTC),
                )
            )
        object.__setattr__(self, "cancellations", tuple(normalized_cancellations))
