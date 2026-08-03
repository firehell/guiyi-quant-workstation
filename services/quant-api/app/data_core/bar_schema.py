from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from app.data_core.contracts import (
    BarFrequency,
    DataCoreError,
    DatasetKind,
)


CANONICAL_BAR_SCHEMA_VERSION = "canonical-bar-v1"


class CanonicalBarError(DataCoreError):
    error_code = "CANONICAL_BAR_INVALID"


class CanonicalBarConflictError(DataCoreError):
    error_code = "CANONICAL_BAR_CONFLICT"


@dataclass(frozen=True, slots=True)
class CanonicalBar:
    provider: str
    dataset_kind: DatasetKind
    symbol: str
    contract_or_series: str
    frequency: BarFrequency
    bar_end: datetime
    trading_day: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    turnover: Decimal | None
    open_interest: Decimal | None
    adjustment: str
    schema_version: str

    def __post_init__(self) -> None:
        provider = _normalize_identity(
            self.provider,
            field="provider",
            lower=True,
        )
        if provider != "rqdata":
            raise CanonicalBarError(
                facts={"field": "provider", "value": provider}
            )
        try:
            dataset_kind = DatasetKind(self.dataset_kind)
        except (TypeError, ValueError) as exc:
            raise CanonicalBarError(
                facts={"field": "dataset_kind", "value": str(self.dataset_kind)}
            ) from exc
        try:
            frequency = BarFrequency(self.frequency)
        except (TypeError, ValueError) as exc:
            raise CanonicalBarError(
                facts={"field": "frequency", "value": str(self.frequency)}
            ) from exc
        if not _is_aware_datetime(self.bar_end):
            raise CanonicalBarError(
                facts={"field": "bar_end", "reason": "timezone_required"}
            )
        if not isinstance(self.trading_day, date) or isinstance(
            self.trading_day,
            datetime,
        ):
            raise CanonicalBarError(
                facts={
                    "field": "trading_day",
                    "value_type": type(self.trading_day).__name__,
                }
            )
        schema_version = _normalize_identity(
            self.schema_version,
            field="schema_version",
        )
        if schema_version != CANONICAL_BAR_SCHEMA_VERSION:
            raise CanonicalBarError(
                facts={"field": "schema_version", "value": schema_version}
            )

        open_value = normalize_decimal(self.open, field="open")
        high_value = normalize_decimal(self.high, field="high")
        low_value = normalize_decimal(self.low, field="low")
        close_value = normalize_decimal(self.close, field="close")
        volume = normalize_decimal(self.volume, field="volume")
        turnover = _normalize_optional_decimal(self.turnover, field="turnover")
        open_interest = _normalize_optional_decimal(
            self.open_interest,
            field="open_interest",
        )
        if not (
            low_value <= open_value <= high_value
            and low_value <= close_value <= high_value
        ):
            raise CanonicalBarError(
                facts={"field": "ohlc", "reason": "price_envelope_invalid"}
            )
        for field_name, value in (
            ("volume", volume),
            ("turnover", turnover),
            ("open_interest", open_interest),
        ):
            if value is not None and value < 0:
                raise CanonicalBarError(
                    facts={"field": field_name, "reason": "must_be_nonnegative"}
                )

        object.__setattr__(self, "provider", provider)
        object.__setattr__(self, "dataset_kind", dataset_kind)
        object.__setattr__(
            self,
            "symbol",
            _normalize_identity(self.symbol, field="symbol", lower=True),
        )
        object.__setattr__(
            self,
            "contract_or_series",
            _normalize_identity(
                self.contract_or_series,
                field="contract_or_series",
                upper=True,
            ),
        )
        object.__setattr__(self, "frequency", frequency)
        object.__setattr__(self, "bar_end", self.bar_end.astimezone(UTC))
        object.__setattr__(self, "open", open_value)
        object.__setattr__(self, "high", high_value)
        object.__setattr__(self, "low", low_value)
        object.__setattr__(self, "close", close_value)
        object.__setattr__(self, "volume", volume)
        object.__setattr__(self, "turnover", turnover)
        object.__setattr__(self, "open_interest", open_interest)
        object.__setattr__(
            self,
            "adjustment",
            _normalize_identity(
                self.adjustment,
                field="adjustment",
                lower=True,
            ),
        )
        object.__setattr__(self, "schema_version", schema_version)

    @property
    def identity(self) -> tuple[object, ...]:
        return (
            self.provider,
            self.dataset_kind,
            self.symbol,
            self.contract_or_series,
            self.frequency,
            self.trading_day,
            self.bar_end,
            self.adjustment,
            self.schema_version,
        )


def normalize_decimal(
    value: Decimal | int | str,
    *,
    field: str,
) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, str)):
        raise CanonicalBarError(
            facts={"field": field, "value_type": type(value).__name__}
        )
    if isinstance(value, str):
        value = value.strip()
        if not value:
            raise CanonicalBarError(
                facts={"field": field, "reason": "empty_decimal"}
            )
    try:
        normalized = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise CanonicalBarError(
            facts={"field": field, "reason": "invalid_decimal"}
        ) from exc
    if not normalized.is_finite():
        raise CanonicalBarError(
            facts={"field": field, "reason": "nonfinite_decimal"}
        )
    if normalized == 0:
        return Decimal(0)
    decimal_tuple = normalized.as_tuple()
    digits = decimal_tuple.digits
    exponent = decimal_tuple.exponent
    while digits[-1] == 0:
        digits = digits[:-1]
        exponent += 1
    return Decimal((decimal_tuple.sign, digits, exponent))


def _normalize_optional_decimal(
    value: Decimal | int | str | None,
    *,
    field: str,
) -> Decimal | None:
    if value is None:
        return None
    return normalize_decimal(value, field=field)


def _normalize_identity(
    value: object,
    *,
    field: str,
    lower: bool = False,
    upper: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise CanonicalBarError(
            facts={"field": field, "value_type": type(value).__name__}
        )
    normalized = value.strip()
    if lower:
        normalized = normalized.lower()
    if upper:
        normalized = normalized.upper()
    return normalized


def _is_aware_datetime(value: object) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and value.utcoffset() is not None
    )
