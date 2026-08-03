from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pandas as pd

from app.data_core.contracts import BarFrequency, DatasetKey, DatasetKind
from app.data_core.rqdata_adapter import (
    MainMapRequest,
    ProviderBarRequest,
    TradingSessionCoverage,
)
from app.data_core.rqdata_provider import CanonicalRQDataAdapter


class FakeClient:
    @staticmethod
    def rqdatac_version() -> str:
        return "3.2.1"

    def contract_bars(
        self,
        contract: str,
        start_date: date,
        end_date: date,
        frequency: str,
    ) -> pd.DataFrame:
        assert (contract, start_date, end_date, frequency) == (
            "JM2609",
            date(2026, 7, 1),
            date(2026, 7, 1),
            "1m",
        )
        return pd.DataFrame(
            {
                "datetime": ["2026-07-01 09:01:00", "2026-07-01 09:02:00"],
                "trading_date": ["2026-07-01", "2026-07-01"],
                "open": ["100.1", "100.2"],
                "high": ["101.1", "101.2"],
                "low": ["99.1", "99.2"],
                "close": ["100.5", "100.6"],
                "volume": [12, 13],
                "total_turnover": ["1206.0", "1307.8"],
                "open_interest": [99, 101],
            }
        )

    def dominant_contracts(
        self,
        product: str,
        start_date: date,
        end_date: date,
        rank: int,
    ) -> pd.DataFrame:
        assert (product, start_date, end_date, rank) == (
            "jm",
            date(2026, 7, 1),
            date(2026, 7, 2),
            1,
        )
        return pd.DataFrame(
            {
                "date": ["2026-07-01", "2026-07-02"],
                "contract": ["JM2609", "JM2609"],
            }
        )


def _request() -> ProviderBarRequest:
    start = datetime(2026, 7, 1, 1, 0, tzinfo=UTC)
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
        start=start,
        end=second,
        sessions=(
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=start,
                end=second,
                expected_bar_ends=(first, second),
            ),
        ),
    )


def test_rqdata_adapter_normalizes_provider_rows_to_exact_canonical_bars() -> None:
    batch = CanonicalRQDataAdapter(FakeClient()).fetch_bars(_request())

    assert batch.data_version == "rqdata-3.2.1-1m-20260701-20260701"
    assert [bar.bar_end for bar in batch.bars] == [
        datetime(2026, 7, 1, 1, 1, tzinfo=UTC),
        datetime(2026, 7, 1, 1, 2, tzinfo=UTC),
    ]
    assert batch.bars[0].open == Decimal("100.1")
    assert batch.bars[0].turnover == Decimal("1206.0")
    assert batch.bars[1].open_interest == Decimal("101")


def test_rqdata_adapter_normalizes_rank_one_mapping_without_local_derivation() -> None:
    rows = CanonicalRQDataAdapter(FakeClient()).fetch_rank1_map(
        MainMapRequest(
            symbol="jm",
            start_day=date(2026, 7, 1),
            end_day=date(2026, 7, 2),
        )
    )

    assert [(row.trading_day, row.actual_contract, row.rank) for row in rows] == [
        (date(2026, 7, 1), "JM2609", 1),
        (date(2026, 7, 2), "JM2609", 1),
    ]
    assert {row.data_version for row in rows} == {
        "rqdata-3.2.1-rank1-20260701-20260702"
    }


def test_rqdata_adapter_accepts_native_dominant_series_frame_shape() -> None:
    class Client(FakeClient):
        def dominant_contracts(self, *_args) -> pd.DataFrame:
            return pd.Series(
                ["JM2609", "JM2609"],
                index=pd.to_datetime(["2026-07-01", "2026-07-02"]),
            ).reset_index()

    rows = CanonicalRQDataAdapter(Client()).fetch_rank1_map(
        MainMapRequest(
            symbol="jm",
            start_day=date(2026, 7, 1),
            end_day=date(2026, 7, 2),
        )
    )

    assert [(row.trading_day, row.actual_contract) for row in rows] == [
        (date(2026, 7, 1), "JM2609"),
        (date(2026, 7, 2), "JM2609"),
    ]


def test_rqdata_adapter_derives_missing_trading_day_from_exact_session() -> None:
    class Client(FakeClient):
        def contract_bars(self, *_args) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "datetime": ["2026-06-30 21:01:00"],
                    "open": ["100"],
                    "high": ["101"],
                    "low": ["99"],
                    "close": ["100.5"],
                    "volume": [12],
                }
            )

    request = ProviderBarRequest(
        dataset=_request().dataset,
        start=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
        end=datetime(2026, 6, 30, 13, 1, tzinfo=UTC),
        sessions=(
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=datetime(2026, 6, 30, 13, 0, tzinfo=UTC),
                end=datetime(2026, 6, 30, 13, 1, tzinfo=UTC),
                expected_bar_ends=(datetime(2026, 6, 30, 13, 1, tzinfo=UTC),),
            ),
        ),
    )

    batch = CanonicalRQDataAdapter(Client()).fetch_bars(request)

    assert batch.bars[0].trading_day == date(2026, 7, 1)


def test_unadjusted_continuous_identity_uses_rqdata_88_provider_series() -> None:
    observed = {}

    class Client(FakeClient):
        def contract_bars(
            self,
            contract: str,
            start_date: date,
            end_date: date,
            frequency: str,
        ) -> pd.DataFrame:
            observed["contract"] = contract
            return FakeClient().contract_bars(
                "JM2609",
                start_date,
                end_date,
                frequency,
            )

    request = _request()
    request = replace(
        request,
        dataset=replace(
            request.dataset,
            dataset_kind=DatasetKind.CONTINUOUS,
            contract_or_series="JM.MAIN",
        ),
    )

    batch = CanonicalRQDataAdapter(Client()).fetch_bars(request)

    assert observed["contract"] == "JM88"
    assert {bar.contract_or_series for bar in batch.bars} == {"JM.MAIN"}


def test_direct_daily_provider_date_is_a_utc_trading_day_label() -> None:
    class Client(FakeClient):
        def contract_bars(self, *_args) -> pd.DataFrame:
            return pd.DataFrame(
                {
                    "date": ["2026-07-01"],
                    "open": ["100"],
                    "high": ["101"],
                    "low": ["99"],
                    "close": ["100.5"],
                    "volume": [12],
                }
            )

    daily_end = datetime(2026, 7, 1, tzinfo=UTC)
    request = ProviderBarRequest(
        dataset=replace(_request().dataset, frequency=BarFrequency.D1),
        start=datetime(2026, 6, 30, tzinfo=UTC),
        end=daily_end,
        sessions=(
            TradingSessionCoverage(
                trading_day=date(2026, 7, 1),
                start=datetime(2026, 6, 30, 23, 59, 59, tzinfo=UTC),
                end=daily_end,
                expected_bar_ends=(daily_end,),
            ),
        ),
    )

    batch = CanonicalRQDataAdapter(Client()).fetch_bars(request)

    assert batch.bars[0].bar_end == daily_end
    assert batch.bars[0].trading_day == date(2026, 7, 1)
