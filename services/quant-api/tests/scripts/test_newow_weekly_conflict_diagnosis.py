from datetime import UTC, date, datetime
from decimal import Decimal

from app.market_data.domain import CanonicalBar
from scripts.newow_weekly_conflict_diagnosis import diagnosis_status, field_differences


def _bar(**overrides):
    values = {
        "bar_end": datetime(2026, 9, 4, 7, tzinfo=UTC),
        "trading_day": date(2026, 9, 4),
        "open": Decimal("100.0"),
        "high": Decimal("110.0"),
        "low": Decimal("90.0"),
        "close": Decimal("105.0"),
        "volume": Decimal("12"),
        "turnover": Decimal("1234.50"),
        "open_interest": Decimal("30"),
    }
    values.update(overrides)
    return CanonicalBar(**values)


def test_field_differences_preserve_decimal_precision_and_all_seven_fields():
    stored = _bar()
    aggregate = _bar(
        close=Decimal("105.00"),
        volume=Decimal("13"),
        turnover=None,
        open_interest=Decimal("31.0"),
    )

    result = field_differences(stored, aggregate)

    assert list(result) == [
        "open", "high", "low", "close", "volume", "turnover", "open_interest"
    ]
    assert result["close"] == {
        "stored": "105.0",
        "d1_aggregate": "105.00",
        "stored_exponent": -1,
        "d1_aggregate_exponent": -2,
        "numeric_equal": True,
        "precision_equal": False,
    }
    assert result["volume"]["numeric_equal"] is False
    assert result["turnover"]["stored"] == "1234.50"
    assert result["turnover"]["d1_aggregate"] is None
    assert result["open_interest"]["precision_equal"] is False


def test_diagnosis_status_fails_closed_on_blocked_contract_or_catalog_drift():
    diagnosed = [{"classification": "SOURCE_VERIFICATION_REQUIRED"}] * 20

    assert diagnosis_status(diagnosed, catalog_revision_stable=True) == "diagnosed"
    assert diagnosis_status(
        [*diagnosed[:-1], {"classification": "DIAGNOSIS_BLOCKED"}],
        catalog_revision_stable=True,
    ) == "blocked"
    assert diagnosis_status(diagnosed, catalog_revision_stable=False) == "blocked"
