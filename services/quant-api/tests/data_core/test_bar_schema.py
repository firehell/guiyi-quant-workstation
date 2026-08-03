from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal, localcontext

import pytest

from app.data_core.bar_schema import (
    CANONICAL_BAR_SCHEMA_VERSION,
    CanonicalBar,
    CanonicalBarConflictError,
    CanonicalBarError,
    normalize_decimal,
)
from app.data_core.contracts import BarFrequency, DatasetKind


BAR_END = datetime(2026, 7, 29, 13, 1, tzinfo=UTC)
TRADING_DAY = date(2026, 7, 30)


def _bar(**overrides: object) -> CanonicalBar:
    values: dict[str, object] = {
        "provider": "rqdata",
        "dataset_kind": DatasetKind.ACTUAL_DOMINANT,
        "symbol": "jm",
        "contract_or_series": "JM2609",
        "frequency": BarFrequency.M1,
        "bar_end": BAR_END,
        "trading_day": TRADING_DAY,
        "open": Decimal("100"),
        "high": Decimal("102"),
        "low": Decimal("99"),
        "close": Decimal("101"),
        "volume": Decimal("12"),
        "turnover": Decimal("1212.00"),
        "open_interest": Decimal("99"),
        "adjustment": "none",
        "schema_version": CANONICAL_BAR_SCHEMA_VERSION,
    }
    values.update(overrides)
    return CanonicalBar(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (Decimal("-0.000"), Decimal("0")),
        (0, Decimal("0")),
        ("100.2300", Decimal("100.23")),
        (Decimal("1000.000"), Decimal("1000")),
        ("1E+3", Decimal("1000")),
    ],
)
def test_decimal_normalization_is_exact_and_canonical(
    raw: Decimal | int | str,
    expected: Decimal,
) -> None:
    assert normalize_decimal(raw, field="price") == expected


def test_decimal_normalization_is_independent_of_global_context_precision() -> None:
    with localcontext() as context:
        context.prec = 6
        normalized = normalize_decimal(
            Decimal("123456.7800"),
            field="price",
        )

    assert normalized == Decimal("123456.78")
    assert normalized.as_tuple() == Decimal("123456.78").as_tuple()
    assert hash(normalized) == hash(Decimal("123456.78"))


def test_decimal_normalization_handles_arbitrarily_long_finite_values() -> None:
    significant = "123456789" * 100
    raw = Decimal(f"0.{significant}000000")

    with localcontext() as context:
        context.prec = 6
        normalized = normalize_decimal(raw, field="price")

    assert normalized == Decimal(f"0.{significant}")
    assert normalized.as_tuple().digits[-1] == 9
    assert len(normalized.as_tuple().digits) == len(significant)


@pytest.mark.parametrize(
    "raw",
    [
        True,
        False,
        1.5,
        "",
        " ",
        "NaN",
        "-Infinity",
        Decimal("Infinity"),
        None,
    ],
)
def test_decimal_normalization_rejects_lossy_or_nonfinite_values(
    raw: object,
) -> None:
    with pytest.raises(CanonicalBarError) as error:
        normalize_decimal(raw, field="price")  # type: ignore[arg-type]

    assert error.value.code == "CANONICAL_BAR_INVALID"
    assert error.value.facts["field"] == "price"


def test_canonical_bar_normalizes_identity_decimals_and_timezone() -> None:
    shanghai = timezone(timedelta(hours=8))
    bar = _bar(
        provider=" RQDATA ",
        dataset_kind="actual_dominant",
        symbol=" JM ",
        contract_or_series=" jm2609 ",
        frequency="1m",
        bar_end=datetime(2026, 7, 29, 21, 1, tzinfo=shanghai),
        open="100.000",
        high=102,
        low="99.00",
        close=Decimal("101.5000"),
        volume="12.000",
        turnover=None,
        open_interest="99.00",
        adjustment=" NONE ",
        schema_version=" canonical-bar-v1 ",
    )

    assert bar.provider == "rqdata"
    assert bar.dataset_kind is DatasetKind.ACTUAL_DOMINANT
    assert bar.symbol == "jm"
    assert bar.contract_or_series == "JM2609"
    assert bar.frequency is BarFrequency.M1
    assert bar.bar_end == BAR_END
    assert (bar.open, bar.high, bar.low, bar.close) == (
        Decimal("100"),
        Decimal("102"),
        Decimal("99"),
        Decimal("101.5"),
    )
    assert bar.volume == Decimal("12")
    assert bar.turnover is None
    assert bar.open_interest == Decimal("99")
    assert bar.adjustment == "none"
    assert bar.schema_version == CANONICAL_BAR_SCHEMA_VERSION
    with pytest.raises(FrozenInstanceError):
        bar.close = Decimal("100")  # type: ignore[misc]


def test_canonical_bar_identity_is_stable_and_excludes_values() -> None:
    original = _bar()
    changed_values = _bar(high="103", close="102")

    assert original.identity == changed_values.identity
    assert original != changed_values


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"provider": "local_parquet"}, "provider"),
        ({"symbol": ""}, "symbol"),
        ({"contract_or_series": " "}, "contract_or_series"),
        ({"bar_end": BAR_END.replace(tzinfo=None)}, "bar_end"),
        ({"trading_day": datetime(2026, 7, 30, tzinfo=UTC)}, "trading_day"),
        ({"schema_version": "canonical-bar-v2"}, "schema_version"),
        ({"low": "101", "open": "100"}, "ohlc"),
        ({"high": "100", "close": "101"}, "ohlc"),
        ({"volume": "-1"}, "volume"),
        ({"turnover": "-0.1"}, "turnover"),
        ({"open_interest": "-1"}, "open_interest"),
    ],
)
def test_canonical_bar_rejects_invalid_identity_or_market_values(
    overrides: dict[str, object],
    field: str,
) -> None:
    with pytest.raises(CanonicalBarError) as error:
        _bar(**overrides)

    assert error.value.code == "CANONICAL_BAR_INVALID"
    assert error.value.facts["field"] == field


def test_canonical_bar_conflict_error_is_fail_visible() -> None:
    error = CanonicalBarConflictError(
        facts={
            "symbol": "jm",
            "bar_end": BAR_END.isoformat(),
            "differing_fields": ("close",),
        }
    )

    assert error.code == "CANONICAL_BAR_CONFLICT"
    assert error.facts["differing_fields"] == ("close",)
    assert str(error) == "CANONICAL_BAR_CONFLICT"
