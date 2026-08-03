from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import re
from typing import Iterable

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import DataCoreError, DatasetKey
from app.data_core.rqdata_adapter import ProviderBarBatch, ProviderBarRequest


CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE = (
    "CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE"
)
CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE = (
    "CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE"
)
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_DECIMAL_FIELDS = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "turnover",
    "open_interest",
)


class QualityValidationError(DataCoreError):
    error_code = "CANONICAL_QUALITY_INVALID"

    def __init__(self, code: str, *, facts: dict[str, object] | None = None) -> None:
        self.error_code = code
        super().__init__(facts=facts)


@dataclass(frozen=True, slots=True)
class ValidatedProviderBatch:
    dataset: DatasetKey
    bars: tuple[CanonicalBar, ...]
    coverage_start: datetime
    coverage_end: datetime
    row_count: int
    data_version: str


def validate_provider_batch(batch: ProviderBarBatch) -> ValidatedProviderBatch:
    if not isinstance(batch, ProviderBarBatch) or not isinstance(
        batch.request,
        ProviderBarRequest,
    ):
        _fail("CANONICAL_QUALITY_SCHEMA_MISMATCH", field="batch")
    request = batch.request
    _require_safe_dataset(request.dataset)
    data_version = _require_safe_component(
        batch.data_version,
        field="data_version",
    )
    try:
        rows = tuple(batch.bars)
    except TypeError:
        _fail("CANONICAL_QUALITY_SCHEMA_MISMATCH", field="bars")
    if not rows:
        _fail("CANONICAL_QUALITY_EMPTY_BATCH")
    if not all(isinstance(row, CanonicalBar) for row in rows):
        _fail("CANONICAL_QUALITY_SCHEMA_MISMATCH", field="bars")

    for row in rows:
        _validate_physical_profile(row)
        _validate_identity(row, request.dataset)
        _validate_ohlcv(row)

    deduplicated = _deduplicate(rows)
    expected_to_day = _expected_bar_days(request)
    actual = {row.bar_end for row in deduplicated}
    expected = set(expected_to_day)
    if actual != expected:
        _fail(
            "CANONICAL_QUALITY_COVERAGE_MISMATCH",
            missing=sorted(item.isoformat() for item in expected - actual),
            unexpected=sorted(item.isoformat() for item in actual - expected),
        )
    for row in deduplicated:
        expected_day = expected_to_day[row.bar_end]
        if row.trading_day != expected_day:
            _fail(
                "CANONICAL_QUALITY_TRADING_DAY_MISMATCH",
                bar_end=row.bar_end.isoformat(),
            )
    return ValidatedProviderBatch(
        dataset=request.dataset,
        bars=deduplicated,
        coverage_start=request.start,
        coverage_end=request.end,
        row_count=len(deduplicated),
        data_version=data_version,
    )


def require_safe_component(value: object, *, field: str) -> str:
    return _require_safe_component(value, field=field)


def decimal_profile_reason(value: Decimal) -> str | None:
    if not isinstance(value, Decimal) or not value.is_finite():
        return "invalid_decimal"
    decimal_tuple = value.as_tuple()
    coefficient_digits = len(decimal_tuple.digits)
    exponent = decimal_tuple.exponent
    if not isinstance(exponent, int):
        return "invalid_decimal"
    if exponent < -18:
        return "excess_scale"
    scaled_digits = coefficient_digits + exponent + 18
    if scaled_digits > 38:
        return "excess_precision"
    return None


def _validate_physical_profile(row: CanonicalBar) -> None:
    if (
        not isinstance(row.bar_end, datetime)
        or row.bar_end.tzinfo is None
        or row.bar_end.utcoffset() is None
        or row.bar_end.utcoffset().total_seconds() != 0
    ):
        _fail("CANONICAL_QUALITY_TIMESTAMP_INVALID", field="bar_end")
    if getattr(row.bar_end, "nanosecond", 0):
        _fail(
            CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE,
            field="bar_end",
        )
    for field in _DECIMAL_FIELDS:
        value = getattr(row, field)
        if value is None:
            continue
        reason = decimal_profile_reason(value)
        if reason is not None:
            _fail(
                CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE,
                field=field,
                reason=reason,
            )


def _validate_identity(row: CanonicalBar, dataset: DatasetKey) -> None:
    actual = (
        row.provider,
        row.dataset_kind,
        row.symbol,
        row.contract_or_series,
        row.frequency,
        row.adjustment,
        row.schema_version,
    )
    expected = (
        dataset.provider,
        dataset.dataset_kind,
        dataset.symbol,
        dataset.contract_or_series,
        dataset.frequency,
        dataset.adjustment,
        dataset.schema_version,
    )
    if actual != expected:
        _fail("CANONICAL_QUALITY_IDENTITY_MISMATCH")


def _validate_ohlcv(row: CanonicalBar) -> None:
    decimal_values = tuple(getattr(row, field) for field in _DECIMAL_FIELDS)
    if any(
        value is not None
        and (not isinstance(value, Decimal) or not value.is_finite())
        for value in decimal_values
    ):
        _fail("CANONICAL_QUALITY_SCHEMA_MISMATCH", field="decimal")
    if not (
        row.low <= row.open <= row.high
        and row.low <= row.close <= row.high
    ):
        _fail("CANONICAL_QUALITY_OHLC_INVALID")
    if any(
        value is not None and value < 0
        for value in (row.volume, row.turnover, row.open_interest)
    ):
        _fail("CANONICAL_QUALITY_QUANTITY_INVALID")


def _deduplicate(rows: Iterable[CanonicalBar]) -> tuple[CanonicalBar, ...]:
    by_identity: dict[tuple[object, ...], CanonicalBar] = {}
    for row in rows:
        existing = by_identity.get(row.identity)
        if existing is None:
            by_identity[row.identity] = row
        elif existing != row:
            _fail(
                "CANONICAL_QUALITY_SAME_KEY_CONFLICT",
                bar_end=row.bar_end.isoformat(),
            )
    return tuple(
        sorted(
            by_identity.values(),
            key=lambda row: (
                row.bar_end,
                row.trading_day,
                row.contract_or_series,
            ),
        )
    )


def _expected_bar_days(request: ProviderBarRequest) -> dict[datetime, object]:
    expected: dict[datetime, object] = {}
    for session in request.sessions:
        if (
            session.start < request.start
            or session.end > request.end
            or session.start >= session.end
        ):
            _fail("CANONICAL_QUALITY_SESSION_MISMATCH")
        for bar_end in session.expected_bar_ends:
            if (
                not session.start < bar_end <= session.end
                or not request.start < bar_end <= request.end
            ):
                _fail(
                    "CANONICAL_QUALITY_SESSION_MISMATCH",
                    bar_end=bar_end.isoformat(),
                )
            previous = expected.get(bar_end)
            if previous is not None and previous != session.trading_day:
                _fail(
                    "CANONICAL_QUALITY_SESSION_MISMATCH",
                    bar_end=bar_end.isoformat(),
                )
            expected[bar_end] = session.trading_day
    if not expected:
        _fail("CANONICAL_QUALITY_SESSION_MISMATCH")
    return expected


def _require_safe_dataset(dataset: DatasetKey) -> None:
    for field in (
        "provider",
        "symbol",
        "contract_or_series",
        "adjustment",
        "schema_version",
    ):
        _require_safe_component(getattr(dataset, field), field=field)
    _require_safe_component(dataset.dataset_kind.value, field="dataset_kind")
    _require_safe_component(dataset.frequency.value, field="frequency")


def _require_safe_component(value: object, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not _SAFE_COMPONENT.fullmatch(value)
        or value in {".", ".."}
    ):
        _fail("CANONICAL_QUALITY_IDENTITY_INVALID", field=field)
    return value


def _fail(code: str, **facts: object) -> None:
    raise QualityValidationError(code, facts=dict(facts))
