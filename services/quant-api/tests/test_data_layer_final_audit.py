from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataDownloadTask, MarketDataFile, TradingCalendar, TradingSession
from app.services.rqdata_ingest.data_layer_final_audit import (
    build_actual_consumer_matrix,
    build_claim_verdicts,
    build_duplicate_active_assets,
    build_one_day_lineage_samples,
    build_partial_revision_policy,
    build_quality_issue_register,
    build_stale_metrics_verdict,
    run_extended_final_audit,
    write_final_audit_reports,
)
from app.services.rqdata_ingest.target_coverage_audit import ProductWindow


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_build_duplicate_active_assets_detects_multiple_primary_rows() -> None:
    rows = [
        _market_file(product="rb", period="1d", version="v1"),
        _market_file(product="rb", period="1d", version="v2"),
    ]
    result = build_duplicate_active_assets(rows)
    assert len(result) == 2
    assert all(item["duplicate_group_size"] == 2 for item in result)


def test_build_quality_issue_register_marks_warning_not_upgradable() -> None:
    rows = build_quality_issue_register([{"product": "bb", "issue_type": "quality_warning", "status": "covered_warning"}])
    assert rows[0]["issue_class"] == "quality_warning"
    assert rows[0]["upgrade_to_passed_allowed"] == "false"


def test_build_stale_metrics_verdict_counts_stage8_6_rows() -> None:
    result = build_stale_metrics_verdict(
        stage8_6_1d_result={
            "matrix": [
                {"gate_status": "active_passed"},
                {"gate_status": "audit_pending"},
            ],
            "product_summary": [
                {"product_status": "active_passed"},
                {"product_status": "active_partial"},
            ],
        }
    )
    assert result["stage8_6_asset_active_passed"] == 1
    assert result["stage8_6_asset_audit_pending"] == 1
    assert result["stage8_6_product_active_passed"] == 1
    assert result["stage8_6_product_active_partial"] == 1


def test_write_final_audit_reports_outputs_required_files(tmp_path) -> None:
    target = {
        "target_asset_catalog": [{"product": "rb"}],
        "asset_physical_inventory": [{"product": "rb"}],
        "target_coverage_matrix": [{"product": "rb", "coverage_status": "covered_passed"}],
        "metadata_consistency_matrix": [{"product": "rb", "status": "covered_passed"}],
        "issue_register": [],
        "coverage_summary": "# summary",
    }
    extended = run_extended_final_audit(
        session=None,
        project_root=tmp_path,
        products=["rb"],
        product_windows={
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="test",
            )
        },
        audit_end=date(2026, 7, 10),
        target_coverage_result=target,
        stage8_6_1d_result={"matrix": [], "product_summary": []},
        jm_six_period_result={"matrix": [], "product_summary": []},
        git_commit="test",
        db_snapshot_time="now",
    )
    paths = write_final_audit_reports(output_dir=tmp_path / "out", target_coverage_result=target, extended_result=extended)
    assert (tmp_path / "out" / "DATA_LAYER_FINAL_AUDIT.md").exists()
    assert (tmp_path / "out" / "audit_evidence.json").exists()
    assert (tmp_path / "out" / "weekly_history_audit.csv").exists()
    assert paths["target_asset_catalog"].exists()


def test_build_claim_verdicts_includes_architecture_and_user_claims() -> None:
    coverage = [
        {
            "product": "rb",
            "period": "1m",
            "contract_role": "dominant_main",
            "year": 2023,
            "target_status": "expected",
            "coverage_status": "covered_passed",
        }
    ]
    weekly = [
        {
            "product": "rb",
            "pre_2020_applicable": True,
            "pre_2020_status": "missing_pre2020",
            "post_2020_passed_years": 0,
            "post_2020_expected_years": 1,
            "direct_1w_present": False,
        }
    ]
    claims = build_claim_verdicts(
        products=["rb"],
        product_windows={
            "rb": ProductWindow(
                product="rb",
                window_start=date(2020, 1, 2),
                listed_date=date(2009, 3, 27),
                effective_1d_start=date(2020, 1, 2),
                note="test",
            )
        },
        coverage_matrix=coverage,
        weekly_history=weekly,
        stage8_6_1d_result={"matrix": [], "product_summary": []},
        audit_end=date(2026, 7, 10),
    )
    claim_ids = {item["claim_id"] for item in claims}
    assert "claim_1" in claim_ids
    assert "claim_1_arch" in claim_ids
    assert "claim_4" in claim_ids


def test_actual_consumer_matrix_requires_actual_1m_for_minute_consumers() -> None:
    rows = build_actual_consumer_matrix(
        rank1_ranges=[{"product": "jm", "contract_code": "JM2609", "start_date": date(2026, 7, 1), "end_date": date(2026, 7, 10)}]
    )
    by_consumer = {(row["consumer"], row["period"]): row for row in rows}

    assert by_consumer[("Backtest", "1m")]["actual_requirement"] == "required"
    assert by_consumer[("Signal", "1m")]["actual_requirement"] == "required"
    assert by_consumer[("trigger price", "1m")]["actual_requirement"] == "required"
    assert by_consumer[("live evaluator", "1m")]["actual_requirement"] == "required"
    assert by_consumer[("archive", "1m")]["actual_requirement"] == "required"
    assert by_consumer[("archive", "1w")]["actual_requirement"] == "not_applicable"
    assert by_consumer[("archive", "1m")]["rank1_effective_start"] == "2026-07-01"


def test_partial_revision_policy_confirms_completed_friday_after_archive() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_calendar_week(session, start=date(2026, 7, 6))
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="day",
                start_time=time(9, 0),
                end_time=time(15, 0),
                provider="rqdata",
            )
        )
        session.add(
            DataDownloadTask(
                task_no="archive-jm-20260710",
                provider="rqdata",
                data_type="after_market_archive",
                instrument_symbol="jm",
                contract_code="JM2609",
                period="1m",
                start_time=datetime(2026, 7, 10, tzinfo=UTC),
                end_time=datetime(2026, 7, 10, tzinfo=UTC),
                status="success",
                progress=100,
                result={"trading_day": "2026-07-10", "quality_status": "passed"},
            )
        )
        session.commit()

        result = build_partial_revision_policy(
            session=session,
            product="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            audit_end=date(2026, 7, 10),
            now=datetime(2026, 7, 10, 16, 30, tzinfo=UTC),
        )

    assert result["last_completed_trading_day"] == "2026-07-10"
    assert result["last_completed_week"] == "2026-07-10"
    assert result["archive_completion"] == "success"
    assert result["confirmed"] is True
    assert result["partial"] is False
    assert result["latest_accepted_revision"] is None
    assert result["live_revision_status"] == "retired"


def test_partial_revision_policy_keeps_unfinished_week_partial() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_calendar_week(session, start=date(2026, 7, 6))
        session.add(
            TradingSession(
                exchange_code="DCE",
                instrument_symbol="jm",
                session_name="day",
                start_time=time(9, 0),
                end_time=time(15, 0),
                provider="rqdata",
            )
        )
        session.commit()

        result = build_partial_revision_policy(
            session=session,
            product="jm",
            contract_code="JM2609",
            exchange_code="DCE",
            audit_end=date(2026, 7, 10),
            now=datetime(2026, 7, 10, 14, 30, tzinfo=UTC),
        )

    assert result["confirmed"] is False
    assert result["partial"] is True
    assert result["last_completed_week"] == ""


def test_one_day_lineage_samples_are_traceable(tmp_path) -> None:
    parquet_path = tmp_path / "data/parquet/canonical/bars/provider=rqdata/period=1d/exchange=DCE/symbol=jm/contract=jm.MAIN/jm_MAIN_1d.parquet"
    parquet_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        {
            "symbol": ["jm", "jm", "jm"],
            "contract": ["jm.MAIN", "jm.MAIN", "jm.MAIN"],
            "datetime": pd.to_datetime(["2020-01-02", "2021-01-04", "2022-01-04"]),
            "trading_day": [date(2020, 1, 2), date(2021, 1, 4), date(2022, 1, 4)],
            "open": [1, 2, 3],
            "high": [1, 2, 3],
            "low": [1, 2, 3],
            "close": [1, 2, 3],
            "volume": [1, 2, 3],
            "open_interest": [1, 2, 3],
            "source_interval": ["1m", "1m", "1m"],
            "data_version": ["dv_2020", "dv_2021", "dv_2022"],
            "quality_status": ["passed", "passed", "passed"],
        }
    ).to_parquet(parquet_path, index=False)
    manifest = tmp_path / "data/manifests/rqdata_jm_v2_history_20200102_20260710.csv"
    manifest.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(
        [
            {
                "period": "1d",
                "provider": "rqdata",
                "data_role": "primary",
                "quality_status": "passed",
                "row_count": 3,
                "min_datetime": "2020-01-02T00:00:00",
                "max_datetime": "2022-01-04T00:00:00",
                "standard_path": str(parquet_path),
                "raw_path": "/raw/frequency=1d/jm.parquet",
                "status": "success",
                "data_version": "jm_1d_v2",
            }
        ]
    ).to_csv(manifest, index=False)
    market_files = [
        _market_file(product="jm", period="1d", version="jm_1d_v2"),
    ]
    market_files[0].file_path = str(parquet_path)

    result = build_one_day_lineage_samples(project_root=tmp_path, products=["jm"], market_files=market_files, sample_years=(2020, 2021, 2022))

    assert {row["year"] for row in result} == {2020, 2021, 2022}
    assert all(row["source_interval"] == "1m" for row in result)
    assert all(row["db_registration_evidence"] for row in result)
    assert {row["lineage_decision"] for row in result} == {"review_required_manifest_raw_frequency_conflict"}


def _market_file(*, product: str, period: str, version: str) -> MarketDataFile:
    return MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol=product,
        contract_code=f"{product}.MAIN",
        period=period,
        start_time=datetime(2020, 1, 2, tzinfo=UTC),
        end_time=datetime(2026, 7, 10, tzinfo=UTC),
        file_path=f"/tmp/{product}_{period}_{version}.parquet",
        row_count=10,
        data_version=version,
        data_role="primary",
        quality_status="passed",
    )


def _add_calendar_week(session: Session, *, start: date) -> None:
    for offset in range(5):
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=start + timedelta(days=offset),
                is_trading_day=True,
                has_night_session=True,
                provider="rqdata",
            )
        )
