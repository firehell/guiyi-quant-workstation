from datetime import UTC, date, datetime

from app.data_core.aggregation import AggregationSession
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.historical_sessions import build_provider_sessions


def _dataset(frequency: BarFrequency) -> DatasetKey:
    return DatasetKey(
        provider="rqdata",
        dataset_kind=DatasetKind.CONTINUOUS,
        symbol="jm",
        contract_or_series="JM.MAIN",
        frequency=frequency,
        adjustment="none",
        schema_version="canonical-bar-v1",
    )


def test_minute_provider_sessions_emit_only_exact_bar_ends() -> None:
    session = AggregationSession(
        trading_day=date(2026, 7, 1),
        name="night",
        start=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
        end=datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
    )

    result = build_provider_sessions(
        _dataset(BarFrequency.M1),
        start=datetime(2026, 6, 30, 13, 1, tzinfo=UTC),
        end=datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
        sessions=(session,),
    )

    assert result[0].expected_bar_ends == (
        datetime(2026, 6, 30, 13, 2, tzinfo=UTC),
        datetime(2026, 6, 30, 13, 3, tzinfo=UTC),
    )


def test_daily_and_weekly_provider_sessions_use_utc_trading_day_labels() -> None:
    sessions = tuple(
        AggregationSession(
            trading_day=trading_day,
            name="day",
            start=datetime(2026, 6, day, 1, 0, tzinfo=UTC),
            end=datetime(2026, 6, day, 7, 0, tzinfo=UTC),
        )
        for day, trading_day in (
            (29, date(2026, 6, 29)),
            (30, date(2026, 6, 30)),
        )
    ) + (
        AggregationSession(
            trading_day=date(2026, 7, 1),
            name="day",
            start=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
            end=datetime(2026, 7, 1, 7, 0, tzinfo=UTC),
        ),
    )
    start = datetime(2026, 6, 28, tzinfo=UTC)
    end = datetime(2026, 7, 1, tzinfo=UTC)

    daily = build_provider_sessions(
        _dataset(BarFrequency.D1),
        start=start,
        end=end,
        sessions=sessions,
    )
    weekly = build_provider_sessions(
        _dataset(BarFrequency.W1),
        start=start,
        end=end,
        sessions=sessions,
    )

    assert [item.expected_bar_ends[0] for item in daily] == [
        datetime(2026, 6, 29, tzinfo=UTC),
        datetime(2026, 6, 30, tzinfo=UTC),
        datetime(2026, 7, 1, tzinfo=UTC),
    ]
    assert [item.expected_bar_ends[0] for item in weekly] == [
        datetime(2026, 7, 1, tzinfo=UTC)
    ]
