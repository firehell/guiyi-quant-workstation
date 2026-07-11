from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.dominant_v2_backfill import (
    _merge_raw_frames,
    plan_dominant_period_backfill,
    resolve_dominant_coverage,
    run_dominant_period_backfill,
)


def _write_existing_asset(tmp_path: Path, *, product: str, period: str, start: date, end: date) -> None:
    exchange = "DCE"
    standard_path = (
        tmp_path
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / f"period={period}"
        / f"exchange={exchange}"
        / f"symbol={product}"
        / f"contract={product}.MAIN"
        / f"{product}_MAIN_{period}_{start:%Y%m%d}_{end:%Y%m%d}_v2.parquet"
    )
    standard_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "open": [1.0, 2.0],
            "high": [1.5, 2.5],
            "low": [0.5, 1.5],
            "close": [1.2, 2.2],
            "volume": [10.0, 11.0],
            "turnover": [100.0, 110.0],
            "open_interest": [1000.0, 1001.0],
            "symbol": [product, product],
            "contract": [f"{product}.MAIN", f"{product}.MAIN"],
            "exchange": [exchange, exchange],
            "vt_symbol": [f"{product}.MAIN", f"{product}.MAIN"],
            "trading_day": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "source": ["rqdata", "rqdata"],
            "provider": ["rqdata", "rqdata"],
            "data_role": ["primary", "primary"],
            "created_at": pd.to_datetime(["2023-01-03", "2023-01-04"]),
            "source_symbol": ["JM2305", "JM2305"],
            "quality_status": ["passed", "passed"],
            "data_version": ["test", "test"],
        }
    )
    frame.to_parquet(standard_path, index=False)

    raw_path = (
        tmp_path
        / "raw"
        / "rqdata"
        / "dominant_contract_bars"
        / f"product={product}"
        / f"frequency={period}"
        / "version=v2"
        / f"{product}_{period}_dominant_raw_{start:%Y%m%d}_{end:%Y%m%d}_v2.parquet"
    )
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw = frame.copy()
    raw["rqdata_product"] = "JM"
    raw["rqdata_order_book_id"] = "JM2305"
    raw["project_contract"] = "jm2305"
    raw["frequency"] = period
    raw.to_parquet(raw_path, index=False)


class FakeClient:
    def underlying_symbol(self, product: str) -> str:
        return product.upper()

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int = 1) -> pd.DataFrame:
        return pd.DataFrame({"date": [start_date], "dominant": ["JM2305"]})

    def contract_bars(self, contract: str, start_date: date, end_date: date, frequency: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "datetime": pd.to_datetime(["2020-01-02", "2020-01-03"]),
                "open": [10.0, 11.0],
                "high": [10.5, 11.5],
                "low": [9.5, 10.5],
                "close": [10.2, 11.2],
                "volume": [20.0, 21.0],
                "turnover": [200.0, 210.0],
                "open_interest": [2000.0, 2001.0],
            }
        )


def test_resolve_dominant_coverage_reads_existing_asset(tmp_path: Path) -> None:
    _write_existing_asset(tmp_path, product="jm", period="1d", start=date(2023, 1, 3), end=date(2026, 7, 10))
    coverage = resolve_dominant_coverage(output_root=tmp_path, product="jm", period="1d")
    assert coverage is not None
    assert coverage.file_start == date(2023, 1, 3)
    assert coverage.min_datetime.date() == date(2023, 1, 3)


def test_plan_skip_when_already_covered(tmp_path: Path) -> None:
    _write_existing_asset(tmp_path, product="jm", period="1d", start=date(2023, 1, 3), end=date(2026, 7, 10))
    plan = plan_dominant_period_backfill(
        output_root=tmp_path,
        product="jm",
        period="1d",
        target_start=date(2020, 1, 2),
    )
    assert plan.mode == "prepend"
    assert plan.gap_start == date(2020, 1, 2)
    assert plan.gap_end == date(2023, 1, 2)


def test_plan_skip_when_target_after_existing_min(tmp_path: Path) -> None:
    _write_existing_asset(tmp_path, product="jm", period="1d", start=date(2023, 1, 3), end=date(2026, 7, 10))
    plan = plan_dominant_period_backfill(
        output_root=tmp_path,
        product="jm",
        period="1d",
        target_start=date(2023, 1, 3),
    )
    assert plan.mode == "skip"


def test_plan_full_missing_without_existing_asset(tmp_path: Path) -> None:
    plan = plan_dominant_period_backfill(
        output_root=tmp_path,
        product="jm",
        period="1w",
        target_start=date(2020, 1, 2),
        global_end=date(2026, 7, 10),
    )
    assert plan.mode == "full_missing"
    assert plan.gap_start == date(2020, 1, 2)
    assert plan.gap_end == date(2026, 7, 10)


def test_merge_raw_frames_deduplicates_datetime() -> None:
    gap = pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02"]), "close": [1.0]})
    existing = pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02", "2023-01-03"]), "close": [9.0, 2.0]})
    merged = _merge_raw_frames(gap, existing)
    assert len(merged) == 2
    assert float(merged.loc[merged["datetime"] == pd.Timestamp("2020-01-02"), "close"].iloc[0]) == 9.0


def test_plan_reuses_tail_when_extended_file_is_incomplete(tmp_path: Path) -> None:
    _write_existing_asset(tmp_path, product="jm", period="1d", start=date(2023, 1, 3), end=date(2026, 7, 10))
    bad_standard = (
        tmp_path
        / "parquet"
        / "canonical"
        / "bars"
        / "provider=rqdata"
        / "period=1d"
        / "exchange=DCE"
        / "symbol=jm"
        / "contract=jm.MAIN"
        / "jm_MAIN_1d_20200102_20260710_v2.parquet"
    )
    bad_standard.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame({"datetime": pd.to_datetime(["2020-01-02", "2020-01-03"]), "close": [1.0, 2.0]}).to_parquet(
        bad_standard,
        index=False,
    )
    plan = plan_dominant_period_backfill(
        output_root=tmp_path,
        product="jm",
        period="1d",
        target_start=date(2020, 1, 2),
    )
    assert plan.mode == "prepend"
    assert plan.coverage is not None
    assert plan.coverage.file_start == date(2023, 1, 3)


def test_run_dominant_period_backfill_writes_extended_paths_and_keeps_old_files(tmp_path: Path) -> None:
    _write_existing_asset(tmp_path, product="jm", period="1d", start=date(2023, 1, 3), end=date(2026, 7, 10))
    plan = plan_dominant_period_backfill(
        output_root=tmp_path,
        product="jm",
        period="1d",
        target_start=date(2020, 1, 2),
    )
    old_standard = plan.coverage.standard_path if plan.coverage else None
    result = run_dominant_period_backfill(client=FakeClient(), output_root=tmp_path, plan=plan)
    new_standard = Path(result["standard"]["path"])
    assert new_standard.exists()
    assert old_standard is not None and old_standard.exists()
    assert result["output_start"] == "2020-01-02"
    frame = pd.read_parquet(new_standard)
    assert frame["datetime"].min().date() <= date(2020, 1, 2)
    assert frame["datetime"].max().date() >= date(2023, 1, 4)
