from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataProfile, MarketDataFile, ProfileActiveBinding
from app.services.data_profile_registry import DataProfileRegistry
from app.services.profile_active_switch import rollback_profile_active_binding
from app.services.profile_binding_rollout import (
    run_apply_mode,
    run_dry_run_mode,
    run_golden_query_mode,
    run_rollback_batch_mode,
    run_verify_mode,
)


def _session_factory() -> sessionmaker[Session]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def _seed(tmp_path: Path) -> tuple[sessionmaker[Session], Path]:
    SessionLocal = _session_factory()
    parquet_old = tmp_path / "old.parquet"
    parquet_new = tmp_path / "new.parquet"
    old_datetime = datetime(2023, 1, 3)
    new_datetime = datetime(2023, 1, 4)
    common = {
        "symbol": ["jm"],
        "contract": ["jm.MAIN"],
        "exchange": ["DCE"],
        "trading_day": [old_datetime.date()],
        "open": [100.0],
        "high": [101.0],
        "low": [99.0],
        "close": [100.5],
        "volume": [10.0],
        "open_interest": [20.0],
        "turnover": [1000.0],
        "period": ["1d"],
        "provider": ["rqdata"],
    }
    pd.DataFrame({**common, "datetime": [old_datetime], "data_version": ["old_v1"]}).to_parquet(
        parquet_old, index=False
    )
    pd.DataFrame(
        {
            **common,
            "datetime": [new_datetime],
            "trading_day": [new_datetime.date()],
            "data_version": ["new_v2"],
        }
    ).to_parquet(parquet_new, index=False)

    with SessionLocal() as session:
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research V1",
                description="test",
                contract_roles=["dominant_main"],
                periods=["1d"],
                quality_policy="passed_only",
                provider="rqdata",
            )
        )
        old_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            start_time=datetime(2023, 1, 3, tzinfo=UTC),
            end_time=datetime(2026, 7, 7, tzinfo=UTC),
            file_path=str(parquet_old),
            row_count=1,
            checksum=hashlib.sha256(parquet_old.read_bytes()).hexdigest(),
            data_version="old_v1",
            data_role="primary",
            quality_status="passed",
        )
        new_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="jm.MAIN",
            period="1d",
            start_time=datetime(2023, 1, 3, tzinfo=UTC),
            end_time=datetime(2026, 7, 10, tzinfo=UTC),
            file_path=str(parquet_new),
            row_count=1,
            checksum=hashlib.sha256(parquet_new.read_bytes()).hexdigest(),
            data_version="new_v2",
            data_role="primary",
            quality_status="passed",
        )
        session.add_all([old_file, new_file])
        session.flush()
        new_file_id = new_file.id
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="old_v1",
                market_data_file_id=old_file.id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

    candidates_path = tmp_path / "binding_candidates.csv"
    pd.DataFrame(
        [
            {
                "profile_id": "intraday_research_v1",
                "instrument_symbol": "jm",
                "contract_code": "jm.MAIN",
                "period": "1d",
                "contract_role": "dominant_main",
                "candidate_status": "current",
                "market_data_file_id": new_file_id,
                "data_version": "new_v2",
                "target_start": "2023-01-03",
                "target_end": "2026-07-10",
                "target_ranges": '[["2023-01-03","2026-07-10"]]',
                "coverage_start": "2023-01-03",
                "coverage_end": "2026-07-10",
                "covers_target": True,
                "checksum_status": "checksum_matched",
                "sealing_status": "verified",
                "lineage_status": "not_required",
            }
        ]
    ).to_csv(candidates_path, index=False)
    return SessionLocal, candidates_path


def _approval_args(session: Session, candidates_path: Path, tmp_path: Path) -> dict[str, object]:
    rows = pd.read_csv(candidates_path).to_dict("records")
    expected_rows: list[dict[str, object]] = []
    for row in rows:
        active = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == row["profile_id"],
                ProfileActiveBinding.instrument_symbol == row["instrument_symbol"],
                ProfileActiveBinding.contract_code == row["contract_code"],
                ProfileActiveBinding.period == row["period"],
                ProfileActiveBinding.binding_status == "active",
            )
        )
        expected_rows.append(
            {
                "profile_id": row["profile_id"],
                "instrument_symbol": row["instrument_symbol"],
                "contract_code": row["contract_code"],
                "period": row["period"],
                "previous_binding_id": active.id if active else "",
                "previous_market_data_file_id": active.market_data_file_id if active else "",
                "previous_data_version": active.data_version if active else "",
                "next_market_data_file_id": row["market_data_file_id"],
                "next_data_version": row["data_version"],
            }
        )
    expected_path = tmp_path / f"expected_before_{len(list(tmp_path.glob('expected_before_*.csv')))}.csv"
    pd.DataFrame(expected_rows).to_csv(expected_path, index=False)
    return {
        "expected_before_path": expected_path,
        "expected_before_sha256": hashlib.sha256(expected_path.read_bytes()).hexdigest(),
        "expected_candidates_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
        "expected_operation_count": len(rows),
    }


def _rollback_approval_args(candidates_path: Path) -> dict[str, object]:
    return {
        "expected_candidates_path": candidates_path,
        "expected_candidates_sha256": hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
        "expected_operation_count": len(pd.read_csv(candidates_path)),
    }


def test_run_dry_run_detects_change(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    with SessionLocal() as session:
        result = run_dry_run_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
    assert result["would_change"] == 1


def test_run_dry_run_rejects_legacy_candidate_without_target_coverage(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    frame = pd.read_csv(candidates_path)
    frame.drop(
        columns=["target_start", "target_end", "target_ranges", "coverage_start", "coverage_end", "covers_target"]
    ).to_csv(candidates_path, index=False)
    with SessionLocal() as session:
        result = run_dry_run_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
    assert result["candidate_count"] == 0
    assert result["rejected_schema_rows"] == 1


def test_run_apply_and_rollback_batch(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        apply_result = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="test_batch",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        assert apply_result["applied"] == 1
        apply_ledger = pd.read_csv(output_dir / "apply_ledger.csv")
        assert pd.notna(apply_ledger.iloc[0]["previous_binding_id"])

        verify_result = run_verify_mode(
            session,
            output_dir=output_dir,
            batch_id="test_batch",
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
        assert verify_result["passed"] is True

        rollback_result = run_rollback_batch_mode(
            session,
            output_dir=output_dir,
            batch_id="test_batch",
            commit=True,
            **_rollback_approval_args(candidates_path),
        )
        assert rollback_result["rolled_back"] == 1


def test_verify_fails_when_active_binding_does_not_point_to_candidate(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        result = run_verify_mode(
            session,
            output_dir=output_dir,
            batch_id=None,
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
    assert result["passed"] is False
    assert result["validator_errors"] == 1


def test_verify_named_batch_without_committed_ledger_fails_closed(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    with SessionLocal() as session:
        result = run_verify_mode(
            session,
            output_dir=tmp_path / "rollout",
            batch_id="missing_batch",
            candidates_path=candidates_path,
            project_root=tmp_path,
        )
    assert result["passed"] is False
    assert "no_committed_apply_rows" in result["ledger_errors"]
    assert "zero_candidates" in result["ledger_errors"]


def test_committed_apply_requires_frozen_scope_inputs(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    with SessionLocal() as session:
        result = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=tmp_path / "rollout",
            batch_id="unfrozen",
            project_root=tmp_path,
            commit=True,
        )
    assert result["committed"] is False
    assert result["errors"] >= 3


def test_apply_expected_before_state_drift_fails_before_any_write(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    expected_path = tmp_path / "expected_before.csv"
    pd.DataFrame(
        [
            {
                "profile_id": "intraday_research_v1",
                "instrument_symbol": "jm",
                "contract_code": "jm.MAIN",
                "period": "1d",
                "previous_binding_id": 999999,
                "previous_market_data_file_id": 999999,
                "previous_data_version": "wrong",
            }
        ]
    ).to_csv(expected_path, index=False)
    with SessionLocal() as session:
        original = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")[0]
        result = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="drift",
            project_root=tmp_path,
            expected_before_path=expected_path,
            expected_before_sha256=hashlib.sha256(expected_path.read_bytes()).hexdigest(),
            expected_candidates_sha256=hashlib.sha256(candidates_path.read_bytes()).hexdigest(),
            expected_operation_count=1,
            commit=True,
        )
        active = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")
    assert result["errors"] == 1
    assert result["transaction_rolled_back"] is True
    assert len(active) == 1
    assert active[0].id == original.id


def test_apply_validation_error_rolls_back_entire_batch(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    frame = pd.read_csv(candidates_path)
    invalid = frame.iloc[0].copy()
    invalid["instrument_symbol"] = "a"
    invalid["contract_code"] = "a.MAIN"
    invalid["market_data_file_id"] = 999999
    invalid["data_version"] = "missing"
    pd.concat([frame, invalid.to_frame().T], ignore_index=True).to_csv(candidates_path, index=False)
    with SessionLocal() as session:
        original = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")[0]
        result = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products=set(),
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="atomic_failure",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        active = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")
    assert result["errors"] == 1
    assert result["committed"] is False
    assert result["transaction_rolled_back"] is True
    assert len(active) == 1
    assert active[0].id == original.id


def test_rollback_new_identity_requires_explicit_absent_authorization_and_can_reapply(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        binding = session.scalar(select(ProfileActiveBinding))
        assert binding is not None
        session.delete(binding)
        session.commit()

        first_apply = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="new_identity",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        assert first_apply["applied"] == 1
        active = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")
        assert len(active) == 1

        rollback = run_rollback_batch_mode(
            session,
            output_dir=output_dir,
            batch_id="new_identity",
            commit=True,
            restore_absent=True,
            **_rollback_approval_args(candidates_path),
        )
        assert rollback["rolled_back"] == 1
        assert rollback["restored_absent"] == 1
        assert DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1") == []

        second_apply = run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="new_identity_reapply",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        assert second_apply["applied"] == 1
        assert len(DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")) == 1


def test_rollback_new_identity_without_authorization_keeps_active_binding(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        binding = session.scalar(select(ProfileActiveBinding))
        assert binding is not None
        session.delete(binding)
        session.commit()
        run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="new_identity",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        active = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")
        result = rollback_profile_active_binding(
            session,
            profile_id="intraday_research_v1",
            binding_id=active[0].id,
            dry_run=False,
            commit=True,
        )
        assert result["status"] == "no_previous_binding"
        assert len(DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")) == 1


def test_restore_absent_fails_closed_when_binding_id_drifts(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    with SessionLocal() as session:
        binding = session.scalar(select(ProfileActiveBinding))
        assert binding is not None
        session.delete(binding)
        session.commit()
        run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="new_identity",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        current = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")[0]
        current.binding_status = "superseded"
        current.superseded_at = datetime.now(UTC)
        session.add(
            ProfileActiveBinding(
                profile_id=current.profile_id,
                instrument_symbol=current.instrument_symbol,
                contract_code=current.contract_code,
                contract_role=current.contract_role,
                period=current.period,
                data_version="drift",
                market_data_file_id=current.market_data_file_id,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.commit()

        result = run_rollback_batch_mode(
            session,
            output_dir=output_dir,
            batch_id="new_identity",
            commit=True,
            restore_absent=True,
            **_rollback_approval_args(candidates_path),
        )
        assert result["errors"] == 1
        active = DataProfileRegistry(session, project_root=tmp_path).list_active_bindings("intraday_research_v1")
        assert len(active) == 1
        assert active[0].data_version == "drift"


def test_golden_query_uses_profile_binding_and_historical_reader(tmp_path: Path) -> None:
    SessionLocal, candidates_path = _seed(tmp_path)
    output_dir = tmp_path / "rollout"
    queries_path = tmp_path / "golden_queries.csv"
    pd.DataFrame(
        [
            {
                "query_id": "jm_daily",
                "profile_id": "intraday_research_v1",
                "instrument_symbol": "jm",
                "contract_code": "jm.MAIN",
                "period": "1d",
                "start": "2023-01-04T00:00:00",
                "end": "2023-01-04T23:59:59",
                "expected_first_datetime": "2023-01-04T00:00:00",
                "expected_last_datetime": "2023-01-04T00:00:00",
                "expected_first_trading_day": "2023-01-04",
                "expected_last_trading_day": "2023-01-04",
            }
        ]
    ).to_csv(queries_path, index=False)
    with SessionLocal() as session:
        run_apply_mode(
            session,
            profile_ids=["intraday_research_v1"],
            products={"jm"},
            candidates_path=candidates_path,
            output_dir=output_dir,
            batch_id="golden",
            project_root=tmp_path,
            **_approval_args(session, candidates_path, tmp_path),
            commit=True,
        )
        result = run_golden_query_mode(
            session,
            queries_path=queries_path,
            output_dir=output_dir,
            project_root=tmp_path,
        )
    assert result["passed"] is True
    assert result["query_count"] == 1
    assert result["results"][0]["historical_only"] is True
    assert result["results"][0]["row_count"] == 1

    incomplete = pd.read_csv(queries_path).drop(columns=["expected_last_trading_day"])
    incomplete.to_csv(queries_path, index=False)
    with SessionLocal() as session:
        missing_boundary = run_golden_query_mode(
            session,
            queries_path=queries_path,
            output_dir=output_dir,
            project_root=tmp_path,
        )
    assert missing_boundary["passed"] is False
    assert missing_boundary["results"][0]["boundary_schema_ok"] is False
