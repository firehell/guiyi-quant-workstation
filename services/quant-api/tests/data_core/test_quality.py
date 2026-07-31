from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.data_core.bar_schema import CanonicalBar
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.quality import (
    CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE,
    CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE,
    QualityValidationError,
    validate_provider_batch,
)
from app.data_core.rqdata_adapter import (
    ProviderBarBatch,
    ProviderBarRequest,
    TradingSessionCoverage,
)


START = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
FIRST = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
SECOND = datetime(2026, 7, 1, 1, 2, tzinfo=UTC)
TRADING_DAY = date(2026, 7, 1)


def _key(**overrides: object) -> DatasetKey:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    values.update(overrides)
    return DatasetKey(**values)


def _request(
    *,
    dataset: DatasetKey | None = None,
    expected: tuple[datetime, ...] = (FIRST, SECOND),
) -> ProviderBarRequest:
    return ProviderBarRequest(
        dataset=dataset or _key(),
        start=START,
        end=SECOND,
        sessions=(
            TradingSessionCoverage(
                trading_day=TRADING_DAY,
                start=START,
                end=SECOND,
                expected_bar_ends=expected,
            ),
        ),
    )


def _bar(
    bar_end: datetime = FIRST,
    **overrides: object,
) -> CanonicalBar:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "bar_end": bar_end,
        "trading_day": TRADING_DAY,
        "open": Decimal("100.000000000000000001"),
        "high": Decimal("102"),
        "low": Decimal("99"),
        "close": Decimal("101.125"),
        "volume": Decimal("12"),
        "turnover": Decimal("1213.50"),
        "open_interest": Decimal("99"),
        "adjustment": "none",
        "schema_version": "canonical-bar-v1",
    }
    values.update(overrides)
    return CanonicalBar(**values)


def _batch(
    bars: object = None,
    *,
    request: ProviderBarRequest | None = None,
    data_version: object = "provider-final-20260701",
) -> ProviderBarBatch:
    if bars is None:
        bars = (_bar(FIRST), _bar(SECOND, close=Decimal("101.25")))
    return ProviderBarBatch(
        request=request or _request(),
        bars=bars,  # type: ignore[arg-type]
        data_version=data_version,  # type: ignore[arg-type]
    )


def _assert_quality_code(batch: ProviderBarBatch, code: str) -> None:
    with pytest.raises(QualityValidationError) as error:
        validate_provider_batch(batch)
    assert error.value.code == code


def test_reorders_and_deduplicates_exact_rows_deterministically() -> None:
    first = _bar(FIRST)
    second = _bar(SECOND, close=Decimal("101.25"))

    validated = validate_provider_batch(_batch((second, first, first)))

    assert validated.bars == (first, second)
    assert validated.row_count == 2
    assert validated.coverage_start == START
    assert validated.coverage_end == SECOND


def test_empty_and_malformed_provider_batches_fail_visibly() -> None:
    _assert_quality_code(_batch(()), "CANONICAL_QUALITY_EMPTY_BATCH")
    _assert_quality_code(
        _batch(({"bar_end": FIRST},)),
        "CANONICAL_QUALITY_SCHEMA_MISMATCH",
    )
    _assert_quality_code(
        _batch(data_version=" ../escape "),
        "CANONICAL_QUALITY_IDENTITY_INVALID",
    )


@pytest.mark.parametrize(
    "bar",
    [
        _bar(symbol="i"),
        _bar(contract_or_series="I2609"),
        _bar(frequency=BarFrequency.M5),
        _bar(adjustment="pre"),
        _bar(schema_version="canonical-bar-v1"),
    ],
)
def test_bar_identity_must_exactly_match_requested_dataset(
    bar: CanonicalBar,
) -> None:
    if bar.schema_version == "canonical-bar-v1" and bar.symbol == "jm":
        bar = _bar(provider="rqdata", dataset_kind=DatasetKind.CONTINUOUS)
    _assert_quality_code(
        _batch((bar,), request=_request(expected=(FIRST,))),
        "CANONICAL_QUALITY_IDENTITY_MISMATCH",
    )


def test_same_key_value_conflict_fails_visibly() -> None:
    first = _bar(FIRST)
    conflict = replace(first, close=Decimal("100.5"))

    _assert_quality_code(
        _batch((first, conflict), request=_request(expected=(FIRST,))),
        "CANONICAL_QUALITY_SAME_KEY_CONFLICT",
    )


def test_missing_and_unexpected_bars_fail_exact_coverage() -> None:
    _assert_quality_code(
        _batch((_bar(FIRST),)),
        "CANONICAL_QUALITY_COVERAGE_MISMATCH",
    )
    unexpected = datetime(2026, 7, 1, 1, 3, tzinfo=UTC)
    _assert_quality_code(
        _batch(
            (_bar(FIRST), _bar(SECOND), _bar(unexpected)),
        ),
        "CANONICAL_QUALITY_COVERAGE_MISMATCH",
    )


def test_trading_day_and_session_assignment_are_validated() -> None:
    _assert_quality_code(
        _batch(
            (_bar(FIRST, trading_day=date(2026, 7, 2)),),
            request=_request(expected=(FIRST,)),
        ),
        "CANONICAL_QUALITY_TRADING_DAY_MISMATCH",
    )
    out_of_session = datetime(2026, 7, 1, 0, 59, tzinfo=UTC)
    _assert_quality_code(
        _batch(
            (_bar(out_of_session),),
            request=_request(expected=(out_of_session,)),
        ),
        "CANONICAL_QUALITY_SESSION_MISMATCH",
    )


def test_ohlc_and_quantities_are_rechecked_against_mutated_provider_objects() -> None:
    bad_ohlc = _bar(FIRST)
    object.__setattr__(bad_ohlc, "high", Decimal("98"))
    _assert_quality_code(
        _batch((bad_ohlc,), request=_request(expected=(FIRST,))),
        "CANONICAL_QUALITY_OHLC_INVALID",
    )

    bad_quantity = _bar(FIRST)
    object.__setattr__(bad_quantity, "volume", Decimal("-1"))
    _assert_quality_code(
        _batch((bad_quantity,), request=_request(expected=(FIRST,))),
        "CANONICAL_QUALITY_QUANTITY_INVALID",
    )


@pytest.mark.parametrize(
    "value",
    [
        Decimal("100000000000000000000"),
        Decimal("0.0000000000000000001"),
        Decimal("9" * 900),
    ],
)
def test_decimal_values_outside_decimal128_38_18_are_rejected(
    value: Decimal,
) -> None:
    bar = _bar(FIRST)
    object.__setattr__(bar, "volume", value)

    _assert_quality_code(
        _batch((bar,), request=_request(expected=(FIRST,))),
        CANONICAL_PARQUET_DECIMAL_OUT_OF_PROFILE,
    )


def test_largest_decimal128_38_18_value_is_accepted_exactly() -> None:
    maximum = Decimal("99999999999999999999.999999999999999999")
    bar = _bar(
        FIRST,
        open=maximum,
        high=maximum,
        low=maximum,
        close=maximum,
    )

    validated = validate_provider_batch(
        _batch((bar,), request=_request(expected=(FIRST,)))
    )

    assert validated.bars[0].open == maximum


class NanosecondDateTime(datetime):
    nanosecond = 1


def test_sub_microsecond_timestamp_is_rejected_without_truncation() -> None:
    precise = NanosecondDateTime(2026, 7, 1, 1, 1, tzinfo=UTC)
    bar = _bar(precise)

    _assert_quality_code(
        _batch((bar,), request=_request(expected=(FIRST,))),
        CANONICAL_PARQUET_TIMESTAMP_OUT_OF_PROFILE,
    )


def test_mutated_naive_timestamp_is_rejected_as_malformed_provider_data() -> None:
    bar = _bar(FIRST)
    object.__setattr__(bar, "bar_end", FIRST.replace(tzinfo=None))

    _assert_quality_code(
        _batch((bar,), request=_request(expected=(FIRST,))),
        "CANONICAL_QUALITY_TIMESTAMP_INVALID",
    )
