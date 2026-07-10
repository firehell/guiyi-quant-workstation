from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.services.rqdata_ingest.dominant_v2_parquet import _standard_path, build_dominant_v2_parquet_assets


class ExplodingClient:
    def __getattr__(self, name: str):
        raise AssertionError(f"RQData client must not be used for local aggregation: {name}")


def _source_frame() -> pd.DataFrame:
    stamps = pd.date_range("2026-07-10 09:01:00", periods=10, freq="min")
    return pd.DataFrame(
        {
            "symbol": ["jm"] * 10,
            "contract": ["jm.MAIN"] * 10,
            "exchange": ["DCE"] * 10,
            "vt_symbol": ["jm.MAIN.DCE"] * 10,
            "datetime": stamps,
            "trading_day": [date(2026, 7, 10)] * 10,
            "interval": ["1m"] * 10,
            "period": ["1m"] * 10,
            "open": [100.0 + index for index in range(10)],
            "high": [101.0 + index for index in range(10)],
            "low": [99.0 + index for index in range(10)],
            "close": [100.5 + index for index in range(10)],
            "volume": [10.0] * 10,
            "turnover": [1000.0] * 10,
            "open_interest": [500.0] * 10,
            "source": ["rqdata"] * 10,
            "provider": ["rqdata"] * 10,
            "data_role": ["primary"] * 10,
            "quality_status": ["passed"] * 10,
            "data_version": ["rqdata_jm_standard_1m_20260710_v2"] * 10,
            "source_contract": ["JM2609"] * 10,
            "created_at": [pd.Timestamp("2026-07-10")] * 10,
        }
    )


def test_build_aggregates_reads_passed_local_1m_without_rqdata(tmp_path) -> None:
    source_path = _standard_path(
        tmp_path,
        symbol="jm",
        exchange="DCE",
        contract="jm.MAIN",
        period="1m",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
    )
    source_path.parent.mkdir(parents=True, exist_ok=True)
    _source_frame().to_parquet(source_path, index=False)

    summary = build_dominant_v2_parquet_assets(
        client=ExplodingClient(),
        output_root=tmp_path,
        product="jm",
        exchange="DCE",
        start_date=date(2026, 7, 10),
        end_date=date(2026, 7, 10),
        periods=("5m", "1d"),
    )

    assert set(summary["periods"]) == {"5m", "1d"}
    assert summary["periods"]["5m"]["derivation_mode"] == "aggregated_from_1m"
    assert summary["periods"]["1d"]["derivation_mode"] == "aggregated_from_1m"
    assert summary["periods"]["1d"]["quality"]["details"]["source_interval"] == "1m"


def test_build_aggregates_rejects_missing_local_1m(tmp_path) -> None:
    with pytest.raises(FileNotFoundError, match="local 1m standard source not found"):
        build_dominant_v2_parquet_assets(
            client=ExplodingClient(),
            output_root=tmp_path,
            product="jm",
            exchange="DCE",
            start_date=date(2026, 7, 10),
            end_date=date(2026, 7, 10),
            periods=("5m",),
        )
