from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import (
    DataDownloadTask,
    DataProfile,
    DataQualityReport,
    MarketDataFile,
    ProfileActiveBinding,
)
from app.services.after_market_archive_gate import (
    ArchiveGateError,
    _expected_minute_keys,
    _collect_stable_provider_final,
    _consumer_profile_smoke,
    _registered_asset_smoke,
    _record_failure,
    _recover_committed_archive,
    _stage_json,
    _validate_stable_provider_frames,
    _verify_immutable_active_assets,
    build_approval_packet,
    build_archive_plan,
    execute_archive,
    reconcile_live_provider,
    validate_approval_packet,
    validate_execution_contract,
)
from app.services import after_market_archive_gate as archive_gate
from app.services.trading_session_clock import SessionWindow
from app.services.rqdata_ingest.jm_historical_catchup import build_profile_binding_plan, canonical_packet_hash
from app.services.rqdata_ingest.jm_historical_catchup_execution import collect_active_binding_snapshot
from app.services.rqdata_ingest.parquet import sha256_file


def _session():
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    Base.metadata.create_all(bind=engine)
    return SessionLocal()


def test_archive_plan_is_actual_only_and_week_is_conditional(tmp_path: Path) -> None:
    plan = build_archive_plan(
        output_root=tmp_path,
        batch_id="s606_20260717_12345678",
        trading_day=date(2026, 7, 17),
        actual_contract="JM2609",
        baseline_start=date(2026, 4, 1),
        expected_source_rows=345,
        provider_final_1m_hash="a" * 64,
        include_week=True,
    )

    assert {row["contract"] for row in plan["bars"]} == {"JM2609"}
    assert {(row["period"], row["source_role"]) for row in plan["bars"]} == {
        ("1m", "direct"),
        ("5m", "derived_from_1m"),
        ("15m", "derived_from_1m"),
        ("30m", "derived_from_1m"),
        ("60m", "derived_from_1m"),
        ("1d", "derived_from_1m"),
        ("1w", "derived_from_1m"),
    }
    assert all(len(row["data_version"]) <= 64 for row in plan["bars"])
    assert {row["output_start"] for row in plan["bars"]} == {"2026-04-01"}
    direct_1m = next(row for row in plan["bars"] if row["period"] == "1m")
    assert direct_1m["request_start"] == "2026-07-17"
    profiles = build_profile_binding_plan(plan)
    assert ("long_horizon_daily_v1", "1d") in {(row["profile_id"], row["period"]) for row in profiles}
    assert ("long_horizon_daily_v1", "1w") in {(row["profile_id"], row["period"]) for row in profiles}


def test_archive_contract_supports_s607_daily_identity_without_changing_s606_defaults(tmp_path: Path) -> None:
    identity = archive_gate.ArchiveGateIdentity(
        task_id="JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DAY",
        batch_prefix="s607",
        success_gate="JM_EOD_ARCHIVE_DAY_PASSED",
        audit_namespace="jm_eod_incremental_s6_07",
    )
    plan = build_archive_plan(
        output_root=tmp_path,
        batch_id="s607_20260722_12345678",
        trading_day=date(2026, 7, 22),
        actual_contract="JM2609",
        baseline_start=date(2026, 4, 1),
        expected_source_rows=345,
        provider_final_1m_hash="b" * 64,
        include_week=False,
        identity=identity,
    )
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan=plan,
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "abc"},
        output_root=tmp_path,
        identity=identity,
    )

    assert plan["task_id"] == identity.task_id
    assert plan["audit_root"].endswith("reports/jm_eod_incremental_s6_07/s607_20260722_12345678")
    assert packet["task_id"] == identity.task_id
    assert validate_approval_packet(packet, output_root=tmp_path, identity=identity)["status"] == "passed"


def test_execution_contract_rejects_missing_materializer_field_before_packet_publish(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    del plan["bars"][0]["output_start"]

    with pytest.raises(ArchiveGateError, match="execution_contract_bar_field_missing:output_start"):
        validate_execution_contract(plan, output_root=tmp_path)


def test_execution_contract_freezes_six_assets_and_seven_profile_candidates(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)

    contract = validate_execution_contract(plan, output_root=tmp_path)

    assert contract["asset_count"] == 6
    assert {row["period"] for row in contract["asset_identities"]} == {"1m", "5m", "15m", "30m", "60m", "1d"}
    assert contract["profile_candidate_count"] == 7
    assert {row["period"] for row in contract["profile_candidate_identities"]} == {"1m", "5m", "15m", "1d"}


def test_execution_contract_rejects_path_outside_approved_output_root(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    plan["bars"][0]["canonical_path"] = str(tmp_path.parent / "outside.parquet")

    with pytest.raises(ArchiveGateError, match="execution_contract_path_outside_output_root"):
        validate_execution_contract(plan, output_root=tmp_path)


def test_archive_packet_hash_binds_plan_and_snapshots(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan=plan,
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "abc"},
        output_root=tmp_path,
    )

    assert packet["schema_version"] == 2
    assert packet["execution_contract"]["asset_count"] == 6
    assert packet["execution_contract"]["profile_candidate_count"] == 7
    assert packet["packet_hash"] == canonical_packet_hash(packet)
    packet["bound_facts"]["actual_contract"] = "JM2701"
    assert packet["packet_hash"] != canonical_packet_hash(packet)


def test_legacy_archive_packet_schema_is_permanently_rejected(tmp_path: Path) -> None:
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan=_archive_plan(tmp_path),
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "abc"},
        output_root=tmp_path,
    )
    packet["schema_version"] = 1
    packet["packet_hash"] = canonical_packet_hash(packet)

    with pytest.raises(ArchiveGateError, match="approval_packet_schema_version_invalid"):
        validate_approval_packet(packet, output_root=tmp_path)


def test_archive_packet_rejects_bound_fact_contract_mismatch(tmp_path: Path) -> None:
    with pytest.raises(ArchiveGateError, match="approval_packet_bound_actual_contract_mismatch"):
        build_approval_packet(
            bound_facts={"actual_contract": "JM2701"},
            execution_plan=_archive_plan(tmp_path),
            reference_snapshot={"actual_contract": "JM2609"},
            binding_snapshot={"sha256": "abc"},
            output_root=tmp_path,
        )


def test_provider_final_requires_exact_expected_minute_keys() -> None:
    clock = SimpleNamespace(
        windows_for_trading_day=lambda *_args, **_kwargs: [
            SessionWindow(
                trading_day=date(2026, 7, 21),
                name="day",
                start=datetime(2026, 7, 21, 9, 0),
                end=datetime(2026, 7, 21, 9, 3),
            )
        ]
    )
    expected = _expected_minute_keys(clock, date(2026, 7, 21), product="jm", exchange="DCE")
    frame = pd.DataFrame(
        [
            _bar_for_day("2026-07-21 09:01:00", 100, date(2026, 7, 21)),
            _bar_for_day("2026-07-21 09:02:00", 101, date(2026, 7, 21)),
            _bar_for_day("2026-07-21 09:04:00", 102, date(2026, 7, 21)),
        ]
    )

    with pytest.raises(ArchiveGateError, match="provider_final_minute_key_mismatch"):
        _validate_stable_provider_frames([frame, frame.copy()], expected_keys=expected)


def test_provider_final_requires_two_stable_hashes() -> None:
    expected = tuple(pd.to_datetime(["2026-07-21 09:01:00", "2026-07-21 09:02:00"]).to_pydatetime())
    first = pd.DataFrame(
        [
            _bar_for_day("2026-07-21 09:01:00", 100, date(2026, 7, 21)),
            _bar_for_day("2026-07-21 09:02:00", 101, date(2026, 7, 21)),
        ]
    )
    second = first.copy()
    second.loc[1, "close"] = 999

    with pytest.raises(ArchiveGateError, match="provider_final_unstable"):
        _validate_stable_provider_frames([first, second], expected_keys=expected)


def test_provider_final_evidence_records_stable_observations() -> None:
    expected = tuple(pd.to_datetime(["2026-07-21 09:01:00", "2026-07-21 09:02:00"]).to_pydatetime())
    frame = pd.DataFrame(
        [
            _bar_for_day("2026-07-21 09:01:00", 100, date(2026, 7, 21)),
            _bar_for_day("2026-07-21 09:02:00", 101, date(2026, 7, 21)),
        ]
    )

    selected, evidence = _validate_stable_provider_frames([frame, frame.copy()], expected_keys=expected)

    assert len(selected) == 2
    assert evidence["check_count"] == 2
    assert evidence["stable"] is True
    assert len(set(evidence["hashes"])) == 1
    assert evidence["expected_minute_count"] == 2


def test_provider_final_collection_downloads_twice_with_bounded_interval() -> None:
    expected = tuple(pd.to_datetime(["2026-07-21 09:01:00", "2026-07-21 09:02:00"]).to_pydatetime())
    frame = pd.DataFrame(
        [
            _bar_for_day("2026-07-21 09:01:00", 100, date(2026, 7, 21)),
            _bar_for_day("2026-07-21 09:02:00", 101, date(2026, 7, 21)),
        ]
    )
    client = SimpleNamespace(
        calls=0,
        contract_bars=lambda *_args: _counted_frame(client, frame),
    )
    sleeps: list[float] = []

    selected, evidence = _collect_stable_provider_final(
        client,
        actual_contract="JM2609",
        trading_day=date(2026, 7, 21),
        expected_keys=expected,
        stability_checks=2,
        stability_interval_seconds=0.25,
        sleep=sleeps.append,
    )

    assert len(selected) == 2
    assert client.calls == 2
    assert sleeps == [0.25]
    assert evidence["stable"] is True


def test_provider_final_collection_assigns_query_trading_day_across_weekend_night_session() -> None:
    trading_day = date(2026, 7, 27)
    expected = tuple(
        pd.to_datetime(
            [
                "2026-07-24 21:01:00",
                "2026-07-27 09:01:00",
            ]
        ).to_pydatetime()
    )
    frame = pd.DataFrame(
        [
            _bar_for_day("2026-07-24 21:01:00", 100, date(2026, 7, 25)),
            _bar_for_day("2026-07-27 09:01:00", 101, trading_day),
        ]
    )
    client = SimpleNamespace(
        contract_bars=lambda *_args: frame.copy(),
    )

    selected, evidence = _collect_stable_provider_final(
        client,
        actual_contract="JM2609",
        trading_day=trading_day,
        expected_keys=expected,
        stability_checks=2,
        stability_interval_seconds=0,
    )

    assert list(selected["datetime"]) == list(expected)
    assert set(selected["trading_day"]) == {trading_day}
    assert evidence["expected_minute_count"] == 2


def test_immutable_active_asset_verification_detects_physical_file_drift(tmp_path: Path) -> None:
    path = tmp_path / "baseline.parquet"
    pd.DataFrame([_bar("2026-07-17 09:01:00", 100)]).to_parquet(path, index=False)
    with _session() as session:
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m",
            start_time=datetime(2026, 7, 17, 9, 1),
            end_time=datetime(2026, 7, 17, 9, 1),
            file_path=str(path),
            row_count=1,
            checksum=sha256_file(path),
            data_version="baseline_v1",
            data_role="primary",
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="JM2609",
                contract_role="actual_dominant",
                period="1m",
                data_version="baseline_v1",
                market_data_file_id=market_file.id,
                binding_status="active",
            )
        )
        session.flush()
        snapshot = collect_active_binding_snapshot(session)

        result = _verify_immutable_active_assets(session, snapshot=snapshot, project_root=tmp_path)
        assert result["verified_file_count"] == 1

        pd.DataFrame([_bar("2026-07-17 09:01:00", 999)]).to_parquet(path, index=False)
        with pytest.raises(ArchiveGateError, match="immutable_active_file_checksum_drift"):
            _verify_immutable_active_assets(session, snapshot=snapshot, project_root=tmp_path)


def test_consumer_profile_smoke_requires_new_passed_binding(tmp_path: Path) -> None:
    path = tmp_path / "actual_1m.parquet"
    pd.DataFrame([_bar("2026-07-21 15:00:00", 100)]).to_parquet(path, index=False)
    with _session() as session:
        session.add(
            DataProfile(
                profile_id="live_observation_v1",
                label="Live Observation",
                contract_roles=["actual_dominant"],
                periods=["1m"],
                quality_policy="passed_only",
                provider="rqdata",
            )
        )
        session.add(
            DataProfile(
                profile_id="intraday_research_v1",
                label="Intraday Research",
                contract_roles=["actual_dominant"],
                periods=["1m"],
                quality_policy="passed_only",
                provider="rqdata",
            )
        )
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m",
            start_time=datetime(2026, 7, 1),
            end_time=datetime(2026, 7, 21, 15, 0),
            file_path=str(path),
            row_count=1,
            checksum=sha256_file(path),
            data_version="archive_1m_v1",
            data_role="primary",
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
        session.add(
            ProfileActiveBinding(
                profile_id="live_observation_v1",
                instrument_symbol="jm",
                contract_code="JM2609",
                contract_role="actual_dominant",
                period="1m",
                data_version="archive_1m_v1",
                market_data_file_id=market_file.id,
                binding_status="active",
            )
        )
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="JM2609",
                contract_role="actual_dominant",
                period="1m",
                data_version="archive_1m_v1",
                market_data_file_id=market_file.id,
                binding_status="active",
            )
        )
        session.flush()
        plan = {
            "bars": [
                {
                    "contract": "JM2609",
                    "period": "1m",
                    "source_role": "direct",
                    "data_version": "archive_1m_v1",
                    "canonical_path": str(path),
                    "end": "2026-07-21",
                }
            ]
        }
        registration = {
            "by_version": {
                "archive_1m_v1": {
                    "quality_status": "passed",
                    "market_data_file_id": market_file.id,
                }
            }
        }

        result = _consumer_profile_smoke(
            session,
            artifact_plan=plan,
            registration=registration,
            actual_contract="JM2609",
            trading_day=date(2026, 7, 21),
            project_root=tmp_path,
        )

    assert result["status"] == "passed"
    assert result["verified_periods"] == ["1m"]
    assert result["rows"][0]["market_data_file_id"] == market_file.id


def test_consumer_profile_smoke_verifies_candidate_identities_not_all_asset_periods(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        _seed_archive_profile_bindings(session, plan, registration)

        result = _consumer_profile_smoke(
            session,
            artifact_plan=plan,
            registration=registration,
            actual_contract="JM2609",
            trading_day=date(2026, 7, 21),
            project_root=tmp_path,
        )

    assert result["status"] == "passed"
    assert result["verified_candidate_count"] == 7
    assert result["verified_periods"] == ["15m", "1d", "1m", "5m"]
    assert len(result["verified_candidate_identities"]) == 7


def test_registered_asset_smoke_verifies_six_assets_manifest_files_and_database(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    with _session() as session:
        registration = _seed_registered_archive(session, plan)

        result = _registered_asset_smoke(
            session,
            artifact_plan=plan,
            registration=registration,
            project_root=tmp_path,
        )

    assert result["status"] == "passed"
    assert result["verified_asset_count"] == 6
    assert result["verified_periods"] == ["15m", "1d", "1m", "30m", "5m", "60m"]


def test_registered_asset_smoke_rejects_missing_registration(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        registration["rows"] = registration["rows"][:-1]
        registration["by_version"].pop(plan["bars"][-1]["data_version"])

        with pytest.raises(ArchiveGateError, match="registered_asset_identity_mismatch"):
            _registered_asset_smoke(
                session,
                artifact_plan=plan,
                registration=registration,
                project_root=tmp_path,
            )


def test_registered_asset_smoke_rejects_manifest_checksum_drift(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        manifest = pd.read_csv(registration["manifest_path"], dtype=str, keep_default_na=False)
        manifest.loc[0, "checksum"] = "0" * 64
        manifest.to_csv(registration["manifest_path"], index=False)

        with pytest.raises(ArchiveGateError, match="registered_asset_manifest_mismatch"):
            _registered_asset_smoke(
                session,
                artifact_plan=plan,
                registration=registration,
                project_root=tmp_path,
            )


def test_registered_asset_smoke_rejects_quality_report_drift(tmp_path: Path) -> None:
    plan = _archive_plan(tmp_path)
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        report_id = registration["rows"][0]["data_quality_report_id"]
        session.get(DataQualityReport, report_id).status = "warning"
        session.flush()

        with pytest.raises(ArchiveGateError, match="registered_asset_quality_report_not_passed"):
            _registered_asset_smoke(
                session,
                artifact_plan=plan,
                registration=registration,
                project_root=tmp_path,
            )


def test_execute_archive_completes_and_identical_rerun_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    plan = _archive_plan(tmp_path)
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan=plan,
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "empty", "bindings": []},
        output_root=tmp_path,
    )
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        _seed_archive_profile_bindings(session, plan, registration)
        session.commit()
        _stub_successful_archive_dependencies(monkeypatch, registration)

        result = execute_archive(
            session,
            client=SimpleNamespace(),
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_packet=packet,
            output_root=tmp_path,
            project_root=tmp_path,
        )
        counts_after_first = (
            session.query(MarketDataFile).count(),
            session.query(ProfileActiveBinding).count(),
            session.query(DataDownloadTask).count(),
        )
        rerun = execute_archive(
            session,
            client=SimpleNamespace(),
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_packet=packet,
            output_root=tmp_path,
            project_root=tmp_path,
        )
        counts_after_rerun = (
            session.query(MarketDataFile).count(),
            session.query(ProfileActiveBinding).count(),
            session.query(DataDownloadTask).count(),
        )

    assert result["status"] == "success"
    assert result["registered_asset_smoke"]["verified_asset_count"] == 6
    assert result["consumer_profile_smoke"]["verified_candidate_count"] == 7
    assert rerun["status"] == "already_archived"
    assert rerun["writes_performed"] is False
    assert counts_after_rerun == counts_after_first
    receipt = Path(plan["audit_root"]) / "completion_receipt.json"
    assert receipt.is_file()
    assert not receipt.with_name(f"{receipt.name}.staged").exists()


def test_execute_archive_publishes_s607_daily_gate_for_delegated_identity(tmp_path: Path, monkeypatch) -> None:
    identity = archive_gate.ArchiveGateIdentity(
        task_id="JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DAY",
        batch_prefix="s607",
        success_gate="JM_EOD_ARCHIVE_DAY_PASSED",
        audit_namespace="jm_eod_incremental_s6_07",
    )
    plan = build_archive_plan(
        output_root=tmp_path,
        batch_id="s607_20260717_12345678",
        trading_day=date(2026, 7, 17),
        actual_contract="JM2609",
        baseline_start=date(2026, 4, 1),
        expected_source_rows=345,
        provider_final_1m_hash="b" * 64,
        include_week=False,
        identity=identity,
    )
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609", "parent_automation_approval_hash": "c" * 64},
        execution_plan=plan,
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "empty", "bindings": []},
        output_root=tmp_path,
        identity=identity,
    )
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        _seed_archive_profile_bindings(session, plan, registration)
        session.commit()
        _stub_successful_archive_dependencies(monkeypatch, registration)

        result = execute_archive(
            session,
            client=SimpleNamespace(),
            packet=packet,
            approval_hash=packet["packet_hash"],
            current_packet=packet,
            output_root=tmp_path,
            project_root=tmp_path,
            identity=identity,
        )

    receipt = json.loads((Path(plan["audit_root"]) / "completion_receipt.json").read_text(encoding="utf-8"))
    assert result["gate"] == "JM_EOD_ARCHIVE_DAY_PASSED"
    assert receipt["gate"] == "JM_EOD_ARCHIVE_DAY_PASSED"


def test_execute_archive_rolls_back_before_profile_switch_when_asset_gate_fails(tmp_path: Path, monkeypatch) -> None:
    plan = _archive_plan(tmp_path)
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan=plan,
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "empty", "bindings": []},
        output_root=tmp_path,
    )
    with _session() as session:
        registration = _seed_registered_archive(session, plan)
        incomplete = {
            **registration,
            "rows": registration["rows"][:-1],
            "by_version": {
                key: value
                for key, value in registration["by_version"].items()
                if key != plan["bars"][-1]["data_version"]
            },
        }
        switched = {"called": False}
        _stub_successful_archive_dependencies(monkeypatch, incomplete, switched=switched)
        session.commit()

        with pytest.raises(ArchiveGateError, match="registered_asset_identity_mismatch"):
            execute_archive(
                session,
                client=SimpleNamespace(),
                packet=packet,
                approval_hash=packet["packet_hash"],
                current_packet=packet,
                output_root=tmp_path,
                project_root=tmp_path,
            )
        failure = session.scalar(
            select(DataDownloadTask).where(DataDownloadTask.data_type == "after_market_archive")
        )

    assert switched["called"] is False
    assert failure is not None
    assert failure.result["packet_hash"] == packet["packet_hash"]
    assert failure.result["active_binding_changed"] is False
    assert not (Path(plan["audit_root"]) / "quality_gate.json").exists()


def test_committed_archive_recovers_staged_receipt_without_repeating_writes(tmp_path: Path) -> None:
    canonical = tmp_path / "actual_1m.parquet"
    recovery_frame = pd.DataFrame([_bar("2026-07-21 15:00:00", 100)])
    recovery_frame["source_interval"] = "1m"
    recovery_frame.to_parquet(canonical, index=False)
    checksum = sha256_file(canonical)
    audit_root = tmp_path / "audit"
    manifest_path = tmp_path / "manifest.csv"
    packet_hash = "a" * 64
    packet = {
        "packet_hash": packet_hash,
        "execution_plan": {
            "batch_id": "s606_20260721_deadbeef",
            "target": "2026-07-21",
            "audit_root": str(audit_root),
            "manifest_path": str(manifest_path),
            "bars": [
                {
                    "contract": "JM2609",
                    "period": "1m",
                    "source_role": "direct",
                    "data_version": "archive_1m_v1",
                    "canonical_path": str(canonical),
                    "end": "2026-07-21",
                }
            ],
        },
    }
    with _session() as session:
        for profile_id in ("live_observation_v1", "intraday_research_v1"):
            session.add(
                DataProfile(
                    profile_id=profile_id,
                    label=profile_id,
                    contract_roles=["actual_dominant"],
                    periods=["1m"],
                    quality_policy="passed_only",
                    provider="rqdata",
                )
            )
        task = DataDownloadTask(
            task_no="archive-recovery-test",
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m",
            start_time=datetime(2026, 7, 1),
            end_time=datetime(2026, 7, 21, 15, 0),
            status="success",
            progress=100,
            result={
                "packet_hash": packet_hash,
                "batch_id": "s606_20260721_deadbeef",
                "data_version": "archive_1m_v1",
                "canonical_path": str(canonical),
                "checksum": checksum,
            },
        )
        session.add(task)
        session.flush()
        market_file = MarketDataFile(
            task_id=task.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m",
            start_time=datetime(2026, 7, 1),
            end_time=datetime(2026, 7, 21, 15, 0),
            file_path=str(canonical),
            row_count=1,
            checksum=checksum,
            data_version="archive_1m_v1",
            data_role="primary",
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
        quality_report = DataQualityReport(
            file_id=market_file.id,
            task_id=task.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m",
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status="passed",
            details={"packet_hash": packet_hash},
        )
        session.add(quality_report)
        session.flush()
        for profile_id in ("live_observation_v1", "intraday_research_v1"):
            session.add(
                ProfileActiveBinding(
                    profile_id=profile_id,
                    instrument_symbol="jm",
                    contract_code="JM2609",
                    contract_role="actual_dominant",
                    period="1m",
                    data_version="archive_1m_v1",
                    market_data_file_id=market_file.id,
                    binding_status="active",
                )
            )
        session.commit()
        pd.DataFrame(
            [
                {
                    "contract": "JM2609",
                    "period": "1m",
                    "source_role": "direct",
                    "data_version": "archive_1m_v1",
                    "canonical_path": str(canonical),
                    "raw_path": "",
                    "row_count": 1,
                    "min_datetime": "2026-07-01T00:00:00",
                    "max_datetime": "2026-07-21T15:00:00",
                    "checksum": checksum,
                    "quality_status": "passed",
                    "market_data_file_id": market_file.id,
                    "data_quality_report_id": quality_report.id,
                }
            ]
        ).to_csv(manifest_path, index=False)
        _stage_json(audit_root / "final_audit.json", {"gate": "JM_ARCHIVE_PASSED", "packet_hash": packet_hash})
        _stage_json(
            audit_root / "completion_receipt.json",
            {"gate": "JM_ARCHIVE_PASSED", "packet_hash": packet_hash},
        )

        result = _recover_committed_archive(session, packet=packet, project_root=tmp_path)

    assert result["status"] == "already_archived"
    assert result["writes_performed"] is False
    assert result["receipt_recovered"] is True
    assert (audit_root / "completion_receipt.json").is_file()
    assert not (audit_root / "completion_receipt.json.staged").exists()


def test_reconciliation_reports_live_bars_as_retired(tmp_path: Path) -> None:
    path = tmp_path / "actual_1m.parquet"
    pd.DataFrame(
        [
            _bar("2026-07-17 09:01:00", 100),
            _bar("2026-07-17 09:02:00", 101),
        ]
    ).to_parquet(path, index=False)
    with _session() as session:
        result = reconcile_live_provider(
            session,
            actual_contract="JM2609",
            trading_day=date(2026, 7, 17),
            canonical_1m=path,
        )

    assert result["status"] == "retired"
    assert result["live_reference_only"] is True
    assert result["live_row_count"] == 0
    assert result["provider_row_count"] == 2
    assert result["mismatches"] == []


def test_archive_failure_evidence_commits_without_claiming_binding_change() -> None:
    with _session() as session:
        _record_failure(
            session,
            trading_day=date(2026, 7, 17),
            actual_contract="JM2609",
            packet_hash="a" * 64,
            exc=RuntimeError("quality failed"),
        )
        task = session.query(DataDownloadTask).one()

    assert task.status == "failed"
    assert task.error_message == "quality failed"
    assert task.result["active_binding_changed"] is False
    assert len(task.result["attempts"]) == 1


def test_archive_failure_evidence_is_per_packet_and_append_only() -> None:
    legacy_task_no = "archive:s606:jm:JM2609:2026-07-17"
    with _session() as session:
        legacy = DataDownloadTask(
            task_no=legacy_task_no,
            provider="rqdata",
            data_type="after_market_archive",
            instrument_symbol="jm",
            contract_code="JM2609",
            period="1m_bundle",
            start_time=datetime(2026, 7, 17),
            end_time=datetime(2026, 7, 17, 23, 59),
            status="failed",
            progress=0,
            error_message="output_start",
            result={"packet_hash": "legacy"},
        )
        session.add(legacy)
        session.commit()

        _record_failure(
            session,
            trading_day=date(2026, 7, 17),
            actual_contract="JM2609",
            packet_hash="a" * 64,
            exc=RuntimeError("first failure"),
        )
        _record_failure(
            session,
            trading_day=date(2026, 7, 17),
            actual_contract="JM2609",
            packet_hash="a" * 64,
            exc=RuntimeError("second failure"),
        )
        _record_failure(
            session,
            trading_day=date(2026, 7, 17),
            actual_contract="JM2609",
            packet_hash="b" * 64,
            exc=RuntimeError("third failure"),
        )
        rows = session.query(DataDownloadTask).order_by(DataDownloadTask.id).all()

    assert len(rows) == 3
    assert rows[0].task_no == legacy_task_no
    assert rows[0].error_message == "output_start"
    assert rows[0].result == {"packet_hash": "legacy"}
    assert rows[1].result["packet_hash"] == "a" * 64
    assert [row["error_message"] for row in rows[1].result["attempts"]] == ["first failure", "second failure"]
    assert rows[2].result["packet_hash"] == "b" * 64
    assert len(rows[2].result["attempts"]) == 1


def _archive_plan(tmp_path: Path) -> dict:
    return build_archive_plan(
        output_root=tmp_path,
        batch_id="s606_20260721_deadbeef",
        trading_day=date(2026, 7, 21),
        actual_contract="JM2609",
        baseline_start=date(2026, 7, 1),
        expected_source_rows=345,
        provider_final_1m_hash="a" * 64,
        include_week=False,
    )


def _seed_registered_archive(session, plan: dict) -> dict:
    rows = []
    by_version = {}
    for index, planned in enumerate(plan["bars"], start=1):
        path = Path(planned["canonical_path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        frame = pd.DataFrame([_bar_for_day("2026-07-21 15:00:00", 100 + index, date(2026, 7, 21))])
        frame["source_interval"] = "1m"
        frame.to_parquet(path, index=False)
        checksum = sha256_file(path)
        market_file = MarketDataFile(
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code=planned["contract"],
            period=planned["period"],
            start_time=datetime(2026, 7, 21, 15, 0),
            end_time=datetime(2026, 7, 21, 15, 0),
            file_path=str(path),
            row_count=1,
            checksum=checksum,
            data_version=planned["data_version"],
            data_role="primary",
            quality_status="passed",
        )
        session.add(market_file)
        session.flush()
        quality_report = DataQualityReport(
            file_id=market_file.id,
            provider="rqdata",
            data_type="bars",
            instrument_symbol="jm",
            contract_code=planned["contract"],
            period=planned["period"],
            start_time=market_file.start_time,
            end_time=market_file.end_time,
            status="passed",
            details={"data_version": planned["data_version"]},
        )
        session.add(quality_report)
        session.flush()
        row = {
            "contract": planned["contract"],
            "period": planned["period"],
            "source_role": planned["source_role"],
            "data_version": planned["data_version"],
            "canonical_path": str(path),
            "raw_path": planned.get("raw_path"),
            "row_count": 1,
            "min_datetime": "2026-07-21T15:00:00",
            "max_datetime": "2026-07-21T15:00:00",
            "checksum": checksum,
            "quality_status": "passed",
            "market_data_file_id": market_file.id,
            "data_quality_report_id": quality_report.id,
        }
        rows.append(row)
        by_version[planned["data_version"]] = row
    manifest_path = Path(plan["manifest_path"])
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).sort_values(["contract", "period", "source_role"]).to_csv(manifest_path, index=False)
    session.flush()
    return {"status": "passed", "rows": rows, "by_version": by_version, "manifest_path": str(manifest_path)}


def _seed_archive_profile_bindings(session, plan: dict, registration: dict) -> None:
    for profile_id in ("intraday_research_v1", "live_observation_v1", "long_horizon_daily_v1"):
        session.add(
            DataProfile(
                profile_id=profile_id,
                label=profile_id,
                contract_roles=["actual_dominant"],
                periods=["1m", "5m", "15m", "1d"],
                quality_policy="passed_only",
                provider="rqdata",
            )
        )
    for candidate in build_profile_binding_plan(plan):
        target = registration["by_version"][candidate["data_version"]]
        session.add(
            ProfileActiveBinding(
                profile_id=candidate["profile_id"],
                instrument_symbol="jm",
                contract_code=candidate["contract"],
                contract_role="actual_dominant",
                period=candidate["period"],
                data_version=candidate["data_version"],
                market_data_file_id=target["market_data_file_id"],
                binding_status="active",
            )
        )
    session.flush()


def _stub_successful_archive_dependencies(monkeypatch, registration: dict, *, switched: dict | None = None) -> None:
    import app.services.after_market_archive_gate as gate

    monkeypatch.setattr(gate, "apply_reference_snapshot", lambda *_args, **_kwargs: {"status": "passed"})
    monkeypatch.setattr(
        gate,
        "materialize_execution_assets",
        lambda *_args, **_kwargs: {"actual_contract": "JM2609", "status": "passed"},
    )
    monkeypatch.setattr(gate, "register_execution_assets", lambda *_args, **_kwargs: registration)

    def apply_bindings(*_args, **_kwargs):
        if switched is not None:
            switched["called"] = True
        return {"status": "passed", "switches": [{"profile_id": "test"}] * 7}

    monkeypatch.setattr(gate, "apply_profile_binding_candidates", apply_bindings)
    monkeypatch.setattr(
        gate,
        "reconcile_live_provider",
        lambda *_args, **_kwargs: {"status": "retired", "live_reference_only": True, "live_row_count": 0, "mismatches": []},
    )
    monkeypatch.setattr(
        gate,
        "_resolve_consumer_target",
        lambda *_args, **_kwargs: {"status": "ready", "actual_contract": "JM2609", "readiness_status": "ready"},
    )


def _bar(value: str, price: int) -> dict:
    return {
        "datetime": pd.Timestamp(value),
        "trading_day": date(2026, 7, 17),
        "open": price,
        "high": price + 1,
        "low": price - 1,
        "close": price,
        "volume": 10,
        "open_interest": 20,
    }


def _bar_for_day(value: str, price: int, trading_day: date) -> dict:
    return {**_bar(value, price), "trading_day": trading_day}


def _counted_frame(client: SimpleNamespace, frame: pd.DataFrame) -> pd.DataFrame:
    client.calls += 1
    return frame.copy()
