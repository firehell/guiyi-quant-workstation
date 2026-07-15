from __future__ import annotations

from pathlib import Path

from app.services.rqdata_ingest.daily_weekly_overlap_batch import (
    _is_batch_target,
    _resolve_product_paths,
    run_batch_overlap,
)


def test_is_batch_target_uses_covered_passed() -> None:
    coverage = [
        {"product": "a", "contract_role": "dominant_main", "period": "1d", "status": "covered_passed"},
        {"product": "a", "contract_role": "dominant_main", "period": "1w", "status": "metadata_gap"},
    ]
    assert _is_batch_target(coverage, product="a", period="1d") is True
    assert _is_batch_target(coverage, product="a", period="1w") is False


def test_resolve_product_paths_prefers_processed_summary() -> None:
    inventory = [
        {
            "product": "jm",
            "symbol_or_contract": "jm.MAIN",
            "contract_role": "dominant_main",
            "period": "1m",
            "physical_exists": "True",
            "physical_path": "/data/jm_v1.parquet",
            "evidence_source": "db_market_data_file",
            "quality_status": "passed",
            "end_date": "2026-07-06",
            "data_version": "v1",
        },
        {
            "product": "jm",
            "symbol_or_contract": "jm.MAIN",
            "contract_role": "dominant_main",
            "period": "1m",
            "physical_exists": "True",
            "physical_path": "/data/jm_v2.parquet",
            "evidence_source": "db_market_data_file,manifest,processed_summary",
            "quality_status": "passed",
            "end_date": "2026-07-10",
            "data_version": "v2",
        },
    ]
    resolved = _resolve_product_paths(inventory, product="jm", contract="jm.MAIN", contract_role="dominant_main")
    assert resolved["1m"] == Path("/data/jm_v2.parquet")


def test_run_batch_overlap_with_limit_products(tmp_path: Path) -> None:
    project_root = Path(__file__).resolve().parents[3]
    sealing_dir = project_root / "data/reports/data_sealing_audit_20260712_162941"
    if not sealing_dir.exists():
        return
    result = run_batch_overlap(
        sealing_dir=sealing_dir,
        output_dir=tmp_path / "batch",
        products=["a", "b"],
        max_workers=1,
        limit_products=1,
    )
    assert result["target_count"] >= 0
    assert (tmp_path / "batch" / "BATCH-OVERLAP-SUMMARY.md").exists()
