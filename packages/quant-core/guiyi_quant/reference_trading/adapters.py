"""Typed, copy-on-write primitives shared by incremental strategy adapters."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
from math import isfinite
from collections.abc import Mapping
from typing import Callable, Generic, Protocol, TypeVar

from .contracts import ReferenceState, ReferenceTransition, StreamIdentity


StrategyStateT = TypeVar("StrategyStateT")
InputT = TypeVar("InputT")
OutputT = TypeVar("OutputT")


def strategy_input_fingerprint(facts: Mapping[str, object]) -> str:
    """Hash a caller-declared complete input fact set without lossy float coercion."""

    def wire(value: object) -> object:
        if value is None or type(value) in (bool, int, str):
            return value
        if isinstance(value, Decimal):
            if not value.is_finite():
                raise ValueError("fingerprint Decimal must be finite")
            return {"decimal": str(value)}
        if isinstance(value, float):
            if not isfinite(value):
                raise ValueError("fingerprint float must be finite")
            return {"float": repr(value)}
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("fingerprint datetime must be timezone-aware")
            return {"datetime": value.isoformat()}
        if type(value) is date:
            return {"date": value.isoformat()}
        if isinstance(value, (tuple, list)):
            return [wire(item) for item in value]
        if isinstance(value, Mapping):
            if not all(isinstance(key, str) for key in value):
                raise TypeError("fingerprint mapping keys must be strings")
            return {key: wire(value[key]) for key in sorted(value)}
        if isinstance(value, Enum):
            return value.value
        raise TypeError(f"unsupported fingerprint value: {type(value).__name__}")

    if not isinstance(facts, Mapping) or not facts:
        raise ValueError("fingerprint facts must be a non-empty mapping")
    encoded = json.dumps(wire(facts), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return sha256(encoded.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class CompletedStrategyInput(Generic[InputT]):
    payload: InputT
    bar_end: datetime
    trading_day: date
    physical_contract: str
    owner_segment_id: str
    calculation_segment_id: str
    fingerprint: str

    def __post_init__(self) -> None:
        if self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ValueError("bar_end must be timezone-aware")
        if type(self.trading_day) is not date:
            raise ValueError("trading_day must be a date")
        for name in (
            "physical_contract", "owner_segment_id", "calculation_segment_id", "fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be non-empty text")


@dataclass(frozen=True, slots=True)
class AdapterCheckpoint(Generic[StrategyStateT]):
    strategy_state: StrategyStateT
    computed_through: datetime | None = None
    last_fingerprint: str | None = None
    physical_contract: str | None = None
    owner_segment_id: str | None = None
    calculation_segment_id: str | None = None
    stream: StreamIdentity | None = None
    reference_state: ReferenceState | None = None

    def __post_init__(self) -> None:
        if self.reference_state is not None:
            if self.stream is None or self.reference_state.stream != self.stream:
                raise ValueError("reference_state must match checkpoint stream")


def advance_checked(
    checkpoint: AdapterCheckpoint[StrategyStateT],
    inputs: tuple[CompletedStrategyInput[InputT], ...],
    *,
    step: Callable[[StrategyStateT, CompletedStrategyInput[InputT]], OutputT],
) -> tuple[AdapterCheckpoint[StrategyStateT], tuple[OutputT, ...]]:
    """Advance ordered inputs atomically; publish only after every step succeeds."""

    if not isinstance(checkpoint, AdapterCheckpoint):
        raise TypeError("checkpoint must be AdapterCheckpoint")
    values = tuple(inputs)
    previous = checkpoint.computed_through
    effective: list[CompletedStrategyInput[InputT]] = []
    for index, item in enumerate(values):
        if not isinstance(item, CompletedStrategyInput):
            raise TypeError("inputs must contain CompletedStrategyInput")
        if previous is not None and item.bar_end < previous:
            raise ValueError("input is older than computed_through")
        if previous is not None and item.bar_end == previous:
            if index == 0 and item.fingerprint == checkpoint.last_fingerprint:
                continue
            raise ValueError("input conflicts with computed_through")
        if effective and item.bar_end <= effective[-1].bar_end:
            raise ValueError("inputs must be strictly ordered")
        effective.append(item)
        previous = item.bar_end
    if not effective:
        return checkpoint, ()

    working = deepcopy(checkpoint.strategy_state)
    outputs: list[OutputT] = []
    for item in effective:
        outputs.append(step(working, item))
    last = effective[-1]
    return (
        AdapterCheckpoint(
            strategy_state=working,
            computed_through=last.bar_end,
            last_fingerprint=last.fingerprint,
            physical_contract=last.physical_contract,
            owner_segment_id=last.owner_segment_id,
            calculation_segment_id=last.calculation_segment_id,
            stream=checkpoint.stream,
            reference_state=checkpoint.reference_state,
        ),
        tuple(outputs),
    )


class StrategyAdapter(Protocol[StrategyStateT, InputT, OutputT]):
    """Pure strategy state advance contract, deliberately without application DTOs."""

    stream: StreamIdentity

    def seed(self) -> AdapterCheckpoint[StrategyStateT]: ...

    def advance(
        self,
        state: AdapterCheckpoint[StrategyStateT],
        input_batch: tuple[CompletedStrategyInput[InputT], ...],
    ) -> tuple[AdapterCheckpoint[StrategyStateT], tuple[OutputT, ...], ReferenceTransition]: ...
