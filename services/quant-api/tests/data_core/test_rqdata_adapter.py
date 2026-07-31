from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Sequence

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    MainMapRow,
    ProviderBarBatch,
    ProviderBarRequest,
    RQDataBarAdapter,
    TradingSessionCoverage,
)


def _request() -> ProviderBarRequest:
    first = datetime(2026, 7, 1, 1, 1, tzinfo=UTC)
    second = datetime(2026, 7, 1, 1, 2, tzinfo=UTC)
    return ProviderBarRequest(
        dataset=DatasetKey(
            provider="rqdata",
            dataset_kind=DatasetKind.ACTUAL_DOMINANT,
            symbol="jm",
            contract_or_series="JM2609",
            frequency=BarFrequency.M1,
            adjustment="none",
            schema_version="canonical-bar-v1",
        ),
        start=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
        end=second,
        sessions=(
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=datetime(2026, 7, 1, 1, 0, tzinfo=UTC),
                end=second,
                expected_bar_ends=(first, second),
            ),
        ),
    )


class FakeAdapter:
    def fetch_bars(self, request: ProviderBarRequest) -> ProviderBarBatch:
        return ProviderBarBatch(
            request=request,
            bars=(),
            data_version="provider-final-20260701",
        )

    def fetch_rank1_map(
        self,
        request: MainMapRequest,
    ) -> Sequence[MainMapRow]:
        return (
            MainMapRow(
                symbol=request.symbol,
                trading_day=request.start_day,
                actual_contract="JM2609",
                rank=1,
                data_version="rank1-20260701",
            ),
        )


def test_fake_adapter_satisfies_protocol_without_importing_real_rqdata() -> None:
    adapter = FakeAdapter()
    request = _request()

    batch = adapter.fetch_bars(request)
    rows = adapter.fetch_rank1_map(
        MainMapRequest(
            symbol="jm",
            start_day=date(2026, 7, 1),
            end_day=date(2026, 7, 1),
        )
    )

    assert isinstance(adapter, RQDataBarAdapter)
    assert batch.request == request
    assert batch.data_version == "provider-final-20260701"
    assert rows == (
        MainMapRow(
            symbol="jm",
            trading_day=date(2026, 7, 1),
            actual_contract="JM2609",
            rank=1,
            data_version="rank1-20260701",
        ),
    )
