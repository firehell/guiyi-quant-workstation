from __future__ import annotations

from pathlib import Path

import pandas as pd

from app.services.rqdata_ingest.data_stage_closure import (
    ALLOWED_DOCUMENT_ACTIONS,
    build_data_stage_closure_package,
)


def test_build_data_stage_closure_package_outputs_required_files(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_input_tables(input_dir)
    _write_docs(tmp_path)

    output_dir = tmp_path / "out"
    paths = build_data_stage_closure_package(input_dir=input_dir, output_dir=output_dir, project_root=tmp_path)

    expected = {
        "asset_inventory",
        "product_period_coverage",
        "contract_role_matrix",
        "manifest_db_consistency",
        "duplicate_or_conflicting_assets",
        "document_inventory",
        "data_stage_closure_summary",
    }
    assert expected.issubset(paths)
    for key in expected:
        assert paths[key].exists()

    summary = paths["data_stage_closure_summary"].read_text(encoding="utf-8")
    assert "DATA_LAYER_PARTIAL" in summary
    assert "writes_database=False" in summary
    assert "不能宣称“全品种周线从上市以来完整”" in summary


def test_document_inventory_uses_allowed_actions(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_input_tables(input_dir)
    _write_docs(tmp_path)

    paths = build_data_stage_closure_package(input_dir=input_dir, output_dir=tmp_path / "out", project_root=tmp_path)
    inventory = pd.read_csv(paths["document_inventory"])

    assert set(inventory["action"]).issubset(ALLOWED_DOCUMENT_ACTIONS)
    data_center = inventory[inventory["path"] == "docs/DATA_CENTER.md"].iloc[0]
    assert data_center["action"] == "update"
    closure = inventory[inventory["path"] == "docs/tasks/DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md"].iloc[0]
    assert closure["action"] == "merge"


def test_canonical_docs_exclude_removed_state_sources() -> None:
    from app.services.rqdata_ingest.data_stage_closure import CANONICAL_DOCS

    removed = {
        "tasks/current.md",
        "docs/CODEX_HANDOFF.md",
        "docs/gpt/CURRENT_STATE.md",
        "docs/gpt/NEXT_STEPS.md",
        "docs/gpt/PROJECT_SNAPSHOT.md",
    }
    assert removed.isdisjoint(CANONICAL_DOCS)
    assert "STATUS.md" in CANONICAL_DOCS
    assert "AGENTS.md" in CANONICAL_DOCS
    assert "docs/DEVELOPMENT.md" in CANONICAL_DOCS
    assert "docs/INDICATOR_KERNEL.md" in CANONICAL_DOCS


def test_asset_inventory_preserves_warning_boundary(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_input_tables(input_dir)
    _write_docs(tmp_path)

    paths = build_data_stage_closure_package(input_dir=input_dir, output_dir=tmp_path / "out", project_root=tmp_path)
    inventory = pd.read_csv(paths["asset_inventory"])

    warning = inventory[inventory["quality_status"] == "warning"].iloc[0]
    assert warning["active_status"] == "warning"
    coverage = pd.read_csv(paths["product_period_coverage"])
    assert int(coverage["covered_warning"].sum()) == 1


def _write_input_tables(input_dir: Path) -> None:
    pd.DataFrame(
        [
            {
                "product": "jm",
                "contract_role": "dominant_main",
                "symbol_or_contract": "jm.MAIN",
                "period": "1w",
                "year": "2020",
                "status": "covered_warning",
                "issue_type": "quality_warning",
                "expected_start": "2020-01-02",
                "expected_end": "2020-12-31",
                "target_reason": "dominant_2020_plus",
                "evidence_source": "db_market_data_file,manifest",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "warning",
                "start_date": "2020-01-02",
                "end_date": "2026-07-10",
                "row_count": "10",
                "db_market_data_file_id": "1",
                "standard_path": "/tmp/jm.parquet",
                "recommended_next_task": "",
            },
            {
                "product": "rb",
                "contract_role": "dominant_main",
                "symbol_or_contract": "rb.MAIN",
                "period": "1w",
                "year": "2019",
                "status": "metadata_gap",
                "issue_type": "data_role_superseded",
                "expected_start": "2019-01-01",
                "expected_end": "2019-12-31",
                "target_reason": "pre2020_weekly",
                "evidence_source": "manifest",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "start_date": "",
                "end_date": "",
                "row_count": "",
                "db_market_data_file_id": "",
                "standard_path": "/tmp/rb-old.parquet",
                "recommended_next_task": "manifest_db_align",
            },
        ]
    ).to_csv(input_dir / "target_coverage_matrix.csv", index=False)
    pd.DataFrame(
        [
            {
                "product": "jm",
                "contract_role": "dominant_main",
                "symbol_or_contract": "jm.MAIN",
                "period": "1w",
                "start_date": "2020-01-02",
                "end_date": "2026-07-10",
                "evidence_source": "db_market_data_file",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "warning",
                "manifest_status": "matched",
                "manifest_or_db_row_count": "10",
                "db_market_data_file_id": "1",
                "data_quality_report_status": "warning",
                "physical_path": "/tmp/jm.parquet",
                "physical_exists": "True",
                "duckdb_row_count": "10",
                "duckdb_min_datetime": "2020-01-02",
                "duckdb_max_datetime": "2026-07-10",
                "duckdb_error": "",
                "checksum_status": "matched",
                "row_count_status": "matched",
            }
        ]
    ).to_csv(input_dir / "asset_physical_inventory.csv", index=False)
    pd.DataFrame(
        [
            {
                "product": "jm",
                "year": "2020",
                "dataset": "main_contract_map_rank1",
                "status": "covered_passed",
                "issue_type": "",
                "db_available": "True",
                "recommended_next_task": "",
            },
            {
                "product": "rb",
                "year": "2019",
                "dataset": "main_contract_map_rank1",
                "status": "metadata_gap",
                "issue_type": "missing_mapping",
                "db_available": "True",
                "recommended_next_task": "mapping_reconcile",
            },
        ]
    ).to_csv(input_dir / "metadata_consistency_matrix.csv", index=False)
    pd.DataFrame(
        [
            {
                "product": "jm",
                "listed_date": "2011-04-15",
                "pre_2020_applicable": "True",
                "pre_2020_status": "missing_pre2020",
                "post_2020_passed_years": "6",
                "post_2020_expected_years": "7",
                "direct_1w_present": "True",
                "direct_1w_row_count": "10",
                "duckdb_row_count": "10",
                "min_datetime": "2020-01-02",
                "max_datetime": "2026-07-10",
                "incomplete_week_excluded": "False",
                "seam_2020_status": "gap",
                "issue_class": "partial",
            }
        ]
    ).to_csv(input_dir / "weekly_history_audit.csv", index=False)
    (input_dir / "duplicate_active_assets.csv").write_text("", encoding="utf-8")


def _write_docs(root: Path) -> None:
    (root / "docs" / "tasks").mkdir(parents=True)
    (root / "docs" / "DATA_CENTER.md").write_text("# DATA_CENTER.md\n更新时间：2026-07-12\n", encoding="utf-8")
    (root / "STATUS.md").write_text("# STATUS\nDATA_LAYER_PARTIAL\n", encoding="utf-8")
    (root / "docs" / "tasks" / "DATA-PART-TARGET-CLOSURE-ACCEPTANCE.md").write_text(
        "# DATA-PART-TARGET-CLOSURE 总验收报告\n状态：`DELIVERY_READY_DATA_PART_TARGET_CLOSURE`\n",
        encoding="utf-8",
    )
