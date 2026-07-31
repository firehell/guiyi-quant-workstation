from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Protocol, Sequence, runtime_checkable

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import ContractValidationError, DatasetKey


def _utc_window(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    if (
        not isinstance(start, datetime)
        or not isinstance(end, datetime)
        or start.tzinfo is None
        or start.utcoffset() is None
        or end.tzinfo is None
        or end.utcoffset() is None
        or start >= end
    ):
        raise ContractValidationError(
            facts={"field": "window", "reason": "invalid"}
        )
    return start.astimezone(UTC), end.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class TradingSessionCoverage:
    trading_day: date
    start: datetime
    end: datetime
    expected_bar_ends: tuple[datetime, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.trading_day, date) or isinstance(
            self.trading_day,
            datetime,
        ):
            raise ContractValidationError(
                facts={"field": "trading_day", "reason": "invalid"}
            )
        start, end = _utc_window(self.start, self.end)
        try:
            expected = tuple(self.expected_bar_ends)
        except TypeError as exc:
            raise ContractValidationError(
                facts={"field": "expected_bar_ends", "reason": "not_iterable"}
            ) from exc
        normalized: list[datetime] = []
        for value in expected:
            if (
                not isinstance(value, datetime)
                or value.tzinfo is None
                or value.utcoffset() is None
            ):
                raise ContractValidationError(
                    facts={
                        "field": "expected_bar_ends",
                        "reason": "timezone_required",
                    }
                )
            normalized.append(value.astimezone(UTC))
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "expected_bar_ends", tuple(normalized))


@dataclass(frozen=True, slots=True)
class ProviderBarRequest:
    dataset: DatasetKey
    start: datetime
    end: datetime
    sessions: tuple[TradingSessionCoverage, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.dataset, DatasetKey):
            raise ContractValidationError(
                facts={"field": "dataset", "reason": "invalid"}
            )
        start, end = _utc_window(self.start, self.end)
        try:
            sessions = tuple(self.sessions)
        except TypeError as exc:
            raise ContractValidationError(
                facts={"field": "sessions", "reason": "not_iterable"}
            ) from exc
        if not sessions or not all(
            isinstance(item, TradingSessionCoverage) for item in sessions
        ):
            raise ContractValidationError(
                facts={"field": "sessions", "reason": "invalid"}
            )
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "sessions", sessions)


@dataclass(frozen=True, slots=True)
class ProviderBarBatch:
    request: ProviderBarRequest
    bars: Sequence[CanonicalBar]
    data_version: str


@dataclass(frozen=True, slots=True)
class MainMapRequest:
    symbol: str
    start_day: date
    end_day: date

    def __post_init__(self) -> None:
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ContractValidationError(
                facts={"field": "symbol", "reason": "invalid"}
            )
        if (
            not isinstance(self.start_day, date)
            or isinstance(self.start_day, datetime)
            or not isinstance(self.end_day, date)
            or isinstance(self.end_day, datetime)
            or self.start_day > self.end_day
        ):
            raise ContractValidationError(
                facts={"field": "date_window", "reason": "invalid"}
            )
        object.__setattr__(self, "symbol", self.symbol.strip().lower())


@dataclass(frozen=True, slots=True)
class MainMapRow:
    symbol: str
    trading_day: date
    actual_contract: str
    rank: int
    data_version: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.symbol, str)
            or not self.symbol.strip()
            or not isinstance(self.actual_contract, str)
            or not self.actual_contract.strip()
            or self.rank != 1
            or isinstance(self.rank, bool)
            or not isinstance(self.trading_day, date)
            or isinstance(self.trading_day, datetime)
            or not isinstance(self.data_version, str)
            or not self.data_version.strip()
        ):
            raise ContractValidationError(
                facts={"field": "main_map_row", "reason": "invalid"}
            )
        object.__setattr__(self, "symbol", self.symbol.strip().lower())
        object.__setattr__(
            self,
            "actual_contract",
            self.actual_contract.strip().upper(),
        )
        object.__setattr__(self, "data_version", self.data_version.strip())


@runtime_checkable
class RQDataBarAdapter(Protocol):
    def fetch_bars(self, request: ProviderBarRequest) -> ProviderBarBatch: ...

    def fetch_rank1_map(
        self,
        request: MainMapRequest,
    ) -> Sequence[MainMapRow]: ...
