from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import pytest

from app.data_core.aggregation import AggregationSession
from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind


DATASET = DatasetKey(
    provider="rqdata",
    dataset_kind=DatasetKind.CONTINUOUS,
    symbol="jm",
    contract_or_series="JM.MAIN",
    frequency=BarFrequency.M5,
    adjustment="none",
    schema_version="canonical-bar-v1",
)
SESSION_START = datetime(2026, 8, 3, 1, tzinfo=UTC)
SESSION_END = SESSION_START + timedelta(minutes=15)


def test_probe_uses_one_complete_bar_inside_a_calendar_partition() -> None:
    from app.services.data_operations.market_data_probe import (
        ProbePosition,
        SessionAlignedMarketDataProbe,
    )

    probe = SessionAlignedMarketDataProbe(
        session_provider=lambda *_args: (
            AggregationSession(
                trading_day=date(2026, 8, 3),
                name="night",
                start=SESSION_START,
                end=SESSION_END,
            ),
        )
    )

    result = probe.plan(
        DATASET,
        start=SESSION_START - timedelta(hours=1),
        end=SESSION_END + timedelta(hours=1),
        position=ProbePosition.FIRST,
    )

    assert result.start == SESSION_START + timedelta(minutes=5, microseconds=-1)
    assert result.end == SESSION_START + timedelta(minutes=5)


def test_probe_rejects_a_candidate_without_a_complete_session_bar() -> None:
    from app.services.data_operations.market_data_probe import (
        MarketDataProbeError,
        ProbePosition,
        SessionAlignedMarketDataProbe,
    )

    probe = SessionAlignedMarketDataProbe(session_provider=lambda *_args: ())

    with pytest.raises(MarketDataProbeError, match="MARKET_DATA_PROBE_UNAVAILABLE"):
        probe.plan(
            DATASET,
            start=SESSION_START,
            end=SESSION_END,
            position=ProbePosition.LAST,
        )
