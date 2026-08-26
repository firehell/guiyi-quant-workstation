from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.market_data.domain import (
    ActualDominantRecentBarsQuery,
    BASE_PROVIDER_FREQUENCIES,
    BarFrequency,
    CanonicalBar,
    ContractError,
    DatasetKey,
    DatasetKind,
    DERIVED_FREQUENCIES,
    PROVIDER_FETCH_FREQUENCIES,
    SeriesKind,
    SeriesPageQuery,
    SeriesQuery,
    normalize_contract_for_symbol,
    parse_rfc3339_instant,
)


def test_frequency_lineage_keeps_weekly_out_of_provider_base_but_fetchable() -> None:
    assert BASE_PROVIDER_FREQUENCIES == {BarFrequency.M1, BarFrequency.D1}
    assert BarFrequency.W1 in DERIVED_FREQUENCIES
    assert BarFrequency.W1 in PROVIDER_FETCH_FREQUENCIES


def test_contract_normalizer_accepts_only_the_requested_symbol_and_real_month() -> None:
    assert normalize_contract_for_symbol("jm", " jm2609 ") == "JM2609"
    assert normalize_contract_for_symbol("jm", "RB2610") is None
    assert normalize_contract_for_symbol("jm", "JM2613") is None
    assert normalize_contract_for_symbol("jm", None) is None


def test_rfc3339_parser_requires_timezone_and_normalizes_utc() -> None:
    assert parse_rfc3339_instant("2025-01-02T15:00:00+08:00", field="after") == datetime(
        2025, 1, 2, 7, tzinfo=UTC
    )
    with pytest.raises(ContractError) as exc:
        parse_rfc3339_instant("2025-01-02T15:00:00", field="after")
    assert exc.value.facts == {"field": "after", "reason": "timezone_required"}


def test_dataset_key_normalizes_four_field_identity_and_path() -> None:
    continuous = DatasetKey(
        kind=DatasetKind.CONTINUOUS,
        symbol=" Jm ",
        series_or_contract=" main ",
        frequency=BarFrequency.M15,
    )
    contract = DatasetKey(
        kind="contract",
        symbol="jm",
        series_or_contract=" jm2509 ",
        frequency="1m",
    )

    assert continuous.as_tuple() == ("continuous", "jm", "MAIN", "15m")
    assert continuous.relative_root.as_posix() == (
        "kind=continuous/symbol=jm/series=MAIN/frequency=15m"
    )
    assert contract.as_tuple() == ("contract", "jm", "JM2509", "1m")


@pytest.mark.parametrize(
    ("kind", "symbol", "series"),
    [
        ("actual_dominant", "jm", "JM2509"),
        ("continuous", "jm", "JM.MAIN"),
        ("continuous", "jm", "JM2509"),
        ("contract", "jm", "RB2510"),
        ("contract", "jm", "MAIN"),
    ],
)
def test_dataset_key_rejects_non_physical_or_mismatched_identity(
    kind: str,
    symbol: str,
    series: str,
) -> None:
    with pytest.raises(ContractError):
        DatasetKey(
            kind=kind,
            symbol=symbol,
            series_or_contract=series,
            frequency="1m",
        )


def test_series_query_requires_contract_only_for_contract_mode() -> None:
    window = {
        "symbol": "jm",
        "frequency": "1d",
        "start": datetime(2025, 1, 1, tzinfo=UTC),
        "end": datetime(2025, 2, 1, tzinfo=UTC),
    }

    actual = SeriesQuery(series_kind=SeriesKind.ACTUAL_DOMINANT, **window)
    contract = SeriesQuery(
        series_kind=SeriesKind.CONTRACT,
        contract="JM2509",
        **window,
    )

    assert actual.physical_key is None
    assert contract.physical_key == DatasetKey(
        kind="contract",
        symbol="jm",
        series_or_contract="JM2509",
        frequency="1d",
    )
    with pytest.raises(ContractError):
        SeriesQuery(series_kind="contract", **window)
    with pytest.raises(ContractError):
        SeriesQuery(
            series_kind="continuous",
            contract="JM2509",
            **window,
        )


def test_series_page_query_normalizes_cursor_and_defaults_limit() -> None:
    request = SeriesPageQuery(
        series_kind="actual_dominant",
        symbol=" JM ",
        frequency="15m",
        before=datetime(2025, 1, 3, 7, tzinfo=UTC),
    )

    assert request.symbol == "jm"
    assert request.frequency is BarFrequency.M15
    assert request.before == datetime(2025, 1, 3, 7, tzinfo=UTC)
    assert request.limit == 1200
    assert request.physical_key is None


@pytest.mark.parametrize("limit", (0, 2001, True))
def test_series_page_query_rejects_invalid_limit(limit: int) -> None:
    with pytest.raises(ContractError):
        SeriesPageQuery(
            series_kind="continuous",
            symbol="jm",
            frequency="1d",
            limit=limit,
        )


def test_series_page_query_requires_aware_cursor_and_contract_only_for_contract() -> None:
    request = SeriesPageQuery(
        series_kind="contract",
        symbol="jm",
        contract=" jm2509 ",
        frequency="1d",
    )

    assert request.contract == "JM2509"
    assert request.physical_key == DatasetKey("contract", "jm", "JM2509", "1d")
    with pytest.raises(ContractError):
        SeriesPageQuery(
            series_kind="contract",
            symbol="jm",
            frequency="1d",
        )
    with pytest.raises(ContractError):
        SeriesPageQuery(
            series_kind="continuous",
            symbol="jm",
            frequency="1d",
            before=datetime(2025, 1, 3, 7),
        )


def test_actual_dominant_recent_bars_query_normalizes_identity() -> None:
    query = ActualDominantRecentBarsQuery(
        symbol="RB",
        frequency="1d",
        through=date(2026, 8, 25),
        limit=30,
    )

    assert query.symbol == "rb"
    assert query.frequency is BarFrequency.D1
    assert query.through == date(2026, 8, 25)
    assert query.limit == 30


@pytest.mark.parametrize("limit", [True, 0, -1, 2001, 1.5])
def test_actual_dominant_recent_bars_query_rejects_invalid_limit(limit: object) -> None:
    with pytest.raises(ContractError):
        ActualDominantRecentBarsQuery("rb", BarFrequency.D1, date(2026, 8, 25), limit)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "changes",
    [
        {"symbol": "rb1"},
        {"frequency": "unsupported"},
        {"through": datetime(2026, 8, 25, tzinfo=UTC)},
    ],
)
def test_actual_dominant_recent_bars_query_rejects_invalid_identity_or_through(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "symbol": "rb",
        "frequency": BarFrequency.D1,
        "through": date(2026, 8, 25),
        "limit": 30,
    }
    values.update(changes)

    with pytest.raises(ContractError):
        ActualDominantRecentBarsQuery(**values)  # type: ignore[arg-type]


def test_canonical_bar_contains_only_bar_values_and_normalizes_utc_decimal() -> None:
    bar = CanonicalBar(
        bar_end=datetime.fromisoformat("2025-01-02T15:00:00+08:00"),
        trading_day=date(2025, 1, 2),
        open="100.0",
        high=Decimal("102"),
        low="99",
        close="101.50",
        volume="10",
        turnover=None,
        open_interest="20",
    )

    assert bar.bar_end == datetime(2025, 1, 2, 7, 0, tzinfo=UTC)
    assert bar.close == Decimal("101.50")
    assert tuple(bar.as_record()) == (
        "bar_end",
        "trading_day",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "turnover",
        "open_interest",
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"high": "98"},
        {"volume": "-1"},
        {"bar_end": datetime(2025, 1, 2, 15, 0)},
    ],
)
def test_canonical_bar_rejects_invalid_ohlcv_or_naive_time(
    changes: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "bar_end": datetime(2025, 1, 2, 7, 0, tzinfo=UTC),
        "trading_day": date(2025, 1, 2),
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": "10",
        "turnover": None,
        "open_interest": "20",
    }
    values.update(changes)
    with pytest.raises(ContractError):
        CanonicalBar(**values)  # type: ignore[arg-type]
