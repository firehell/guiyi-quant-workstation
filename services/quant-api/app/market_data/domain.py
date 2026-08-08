from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Mapping


class ContractError(ValueError):
    """Bounded public contract error without provider or storage details."""

    code = "MARKET_DATA_CONTRACT_INVALID"

    def __init__(self, *, field: str, reason: str, value: object | None = None) -> None:
        facts: dict[str, object] = {"field": field, "reason": reason}
        if value is not None:
            facts["value"] = str(value)
        self.facts: Mapping[str, object] = MappingProxyType(facts)
        super().__init__(self.code)


class DatasetKind(StrEnum):
    CONTINUOUS = "continuous"
    CONTRACT = "contract"


class SeriesKind(StrEnum):
    CONTINUOUS = "continuous"
    ACTUAL_DOMINANT = "actual_dominant"
    CONTRACT = "contract"


class BarFrequency(StrEnum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "60m"
    D1 = "1d"
    W1 = "1w"


DIRECT_FREQUENCIES = frozenset({BarFrequency.M1, BarFrequency.D1, BarFrequency.W1})
DERIVED_FREQUENCIES = frozenset(
    {BarFrequency.M5, BarFrequency.M15, BarFrequency.M30, BarFrequency.H1}
)
ALL_FREQUENCIES = DIRECT_FREQUENCIES | DERIVED_FREQUENCIES
# RQData continuous/intraday history floor observed via get_dominant_price / A88.
RQDATA_INTRADAY_HISTORY_START = date(2010, 1, 4)
INTRADAY_FREQUENCIES = frozenset(
    {
        BarFrequency.M1,
        BarFrequency.M5,
        BarFrequency.M15,
        BarFrequency.M30,
        BarFrequency.H1,
    }
)
_SYMBOL = re.compile(r"[A-Z]+\Z")
_CONTRACT = re.compile(r"([A-Z]+)[0-9]{3,4}\Z")


def _enum(enum_type: type[StrEnum], value: object, *, field: str) -> Any:
    if not isinstance(value, str):
        raise ContractError(field=field, reason="unsupported", value=value)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ContractError(field=field, reason="unsupported", value=value) from exc


def _text(value: object, *, field: str, upper: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(field=field, reason="nonempty_text_required")
    normalized = value.strip()
    return normalized.upper() if upper else normalized.lower()


def _window(start: object, end: object) -> tuple[datetime, datetime]:
    if not isinstance(start, datetime) or start.tzinfo is None or start.utcoffset() is None:
        raise ContractError(field="start", reason="timezone_required")
    if not isinstance(end, datetime) or end.tzinfo is None or end.utcoffset() is None:
        raise ContractError(field="end", reason="timezone_required")
    start_utc = start.astimezone(UTC)
    end_utc = end.astimezone(UTC)
    if start_utc >= end_utc:
        raise ContractError(field="window", reason="start_must_precede_end")
    return start_utc, end_utc


@dataclass(frozen=True, slots=True)
class DatasetKey:
    kind: DatasetKind
    symbol: str
    series_or_contract: str
    frequency: BarFrequency

    def __post_init__(self) -> None:
        kind = _enum(DatasetKind, self.kind, field="kind")
        symbol = _text(self.symbol, field="symbol")
        if _SYMBOL.fullmatch(symbol.upper()) is None:
            raise ContractError(field="symbol", reason="invalid", value=symbol)
        series = _text(self.series_or_contract, field="series_or_contract", upper=True)
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        if kind is DatasetKind.CONTINUOUS:
            if series != "MAIN":
                raise ContractError(
                    field="series_or_contract",
                    reason="continuous_requires_main",
                    value=series,
                )
        else:
            match = _CONTRACT.fullmatch(series)
            if match is None:
                raise ContractError(
                    field="series_or_contract",
                    reason="concrete_contract_required",
                    value=series,
                )
            if match.group(1) != symbol.upper():
                raise ContractError(
                    field="series_or_contract",
                    reason="contract_symbol_mismatch",
                    value=series,
                )
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "series_or_contract", series)
        object.__setattr__(self, "frequency", frequency)

    def as_tuple(self) -> tuple[str, str, str, str]:
        return (self.kind.value, self.symbol, self.series_or_contract, self.frequency.value)

    @property
    def relative_root(self) -> PurePosixPath:
        return PurePosixPath(
            f"kind={self.kind.value}",
            f"symbol={self.symbol}",
            f"series={self.series_or_contract}",
            f"frequency={self.frequency.value}",
        )


@dataclass(frozen=True, slots=True)
class SeriesQuery:
    series_kind: SeriesKind
    symbol: str
    frequency: BarFrequency
    start: datetime
    end: datetime
    contract: str | None = None

    def __post_init__(self) -> None:
        kind = _enum(SeriesKind, self.series_kind, field="series_kind")
        symbol = _text(self.symbol, field="symbol")
        frequency = _enum(BarFrequency, self.frequency, field="frequency")
        start, end = _window(self.start, self.end)
        contract = self.contract
        if kind is SeriesKind.CONTRACT:
            if contract is None:
                raise ContractError(field="contract", reason="required_for_contract_series")
            contract = DatasetKey(
                kind=DatasetKind.CONTRACT,
                symbol=symbol,
                series_or_contract=contract,
                frequency=frequency,
            ).series_or_contract
        elif contract is not None:
            raise ContractError(field="contract", reason="forbidden_for_series_kind")
        object.__setattr__(self, "series_kind", kind)
        object.__setattr__(self, "symbol", symbol)
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)
        object.__setattr__(self, "contract", contract)

    @property
    def physical_key(self) -> DatasetKey | None:
        if self.series_kind is SeriesKind.ACTUAL_DOMINANT:
            return None
        if self.series_kind is SeriesKind.CONTINUOUS:
            return DatasetKey(
                kind=DatasetKind.CONTINUOUS,
                symbol=self.symbol,
                series_or_contract="MAIN",
                frequency=self.frequency,
            )
        assert self.contract is not None
        return DatasetKey(
            kind=DatasetKind.CONTRACT,
            symbol=self.symbol,
            series_or_contract=self.contract,
            frequency=self.frequency,
        )


def _decimal(value: Decimal | int | str | None, *, field: str, optional: bool = False) -> Decimal | None:
    if value is None:
        if optional:
            return None
        raise ContractError(field=field, reason="required")
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise ContractError(field=field, reason="decimal_required")
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError) as exc:
        raise ContractError(field=field, reason="decimal_required") from exc
    if not result.is_finite():
        raise ContractError(field=field, reason="finite_required")
    return result


@dataclass(frozen=True, slots=True)
class CanonicalBar:
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None

    def __post_init__(self) -> None:
        if not isinstance(self.bar_end, datetime) or self.bar_end.tzinfo is None or self.bar_end.utcoffset() is None:
            raise ContractError(field="bar_end", reason="timezone_required")
        if not isinstance(self.trading_day, date) or isinstance(self.trading_day, datetime):
            raise ContractError(field="trading_day", reason="date_required")
        values = {
            "open": _decimal(self.open, field="open"),
            "high": _decimal(self.high, field="high"),
            "low": _decimal(self.low, field="low"),
            "close": _decimal(self.close, field="close"),
            "volume": _decimal(self.volume, field="volume"),
            "turnover": _decimal(self.turnover, field="turnover", optional=True),
            "open_interest": _decimal(self.open_interest, field="open_interest", optional=True),
        }
        low = values["low"]
        high = values["high"]
        open_value = values["open"]
        close_value = values["close"]
        assert isinstance(low, Decimal) and isinstance(high, Decimal)
        assert isinstance(open_value, Decimal) and isinstance(close_value, Decimal)
        if low > high or any(
            not low <= value <= high for value in (open_value, close_value)
        ):
            raise ContractError(field="ohlc", reason="price_envelope_invalid")
        for field in ("volume", "turnover", "open_interest"):
            value = values[field]
            if value is not None and value < 0:
                raise ContractError(field=field, reason="nonnegative_required")
        object.__setattr__(self, "bar_end", self.bar_end.astimezone(UTC))
        for field, value in values.items():
            object.__setattr__(self, field, value)

    def as_record(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class TargetWindow:
    dataset: DatasetKey
    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        start, end = _window(self.start, self.end)
        object.__setattr__(self, "start", start)
        object.__setattr__(self, "end", end)


@dataclass(frozen=True, slots=True)
class PartitionDigest:
    dataset: DatasetKey
    year: int
    month: int
    checksum: str
    manifest_digest: str


@dataclass(frozen=True, slots=True)
class ResolvedContractSegment:
    contract: str
    start_trading_day: date
    end_trading_day: date


@dataclass(frozen=True, slots=True)
class MarketSeriesResult:
    request_identity: Mapping[str, object]
    bars: tuple[CanonicalBar, ...]
    coverage: tuple[datetime, datetime] | None
    partition_digests: tuple[PartitionDigest, ...]
    resolved_contract_segments: tuple[ResolvedContractSegment, ...]
    main_map_digest: str | None
