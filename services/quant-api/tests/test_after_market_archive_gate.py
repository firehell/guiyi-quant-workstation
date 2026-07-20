from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataDownloadTask, DataProfile, LiveMinuteBar, MarketDataFile, ProfileActiveBinding
from app.services.after_market_archive_gate import (
    ArchiveGateError,
    _expected_minute_keys,
    _collect_stable_provider_final,
    _consumer_profile_smoke,
    _reconcile_provider_live_rows,
    _record_failure,
    _recover_committed_archive,
    _stage_json,
    _validate_stable_provider_frames,
    _verify_immutable_active_assets,
    build_approval_packet,
    build_archive_plan,
    reconcile_live_provider,
)
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
    profiles = build_profile_binding_plan(plan)
    assert ("long_horizon_daily_v1", "1d") in {(row["profile_id"], row["period"]) for row in profiles}
    assert ("long_horizon_daily_v1", "1w") in {(row["profile_id"], row["period"]) for row in profiles}


def test_archive_packet_hash_binds_plan_and_snapshots() -> None:
    packet = build_approval_packet(
        bound_facts={"actual_contract": "JM2609"},
        execution_plan={"product": "jm"},
        reference_snapshot={"actual_contract": "JM2609"},
        binding_snapshot={"sha256": "abc"},
    )

    assert packet["packet_hash"] == canonical_packet_hash(packet)
    packet["bound_facts"]["actual_contract"] = "JM2701"
    assert packet["packet_hash"] != canonical_packet_hash(packet)


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


def test_reconciliation_reports_duplicate_live_keys_without_collapsing_them() -> None:
    provider = pd.DataFrame([_bar("2026-07-17 09:01:00", 100)])
    live = [
        _live_row("2026-07-17 09:01:00", 100, revision=0),
        _live_row("2026-07-17 09:01:00", 100, revision=1),
    ]

    result = _reconcile_provider_live_rows(provider, live)

    assert result["status"] == "differences_observed"
    assert result["live_row_count"] == 2
    assert result["live_unique_bar_count"] == 1
    assert result["live_duplicate_count"] == 1
    assert result["revision_row_count"] == 1


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


def test_committed_archive_recovers_staged_receipt_without_repeating_writes(tmp_path: Path) -> None:
    canonical = tmp_path / "actual_1m.parquet"
    pd.DataFrame([_bar("2026-07-21 15:00:00", 100)]).to_parquet(canonical, index=False)
    checksum = sha256_file(canonical)
    audit_root = tmp_path / "audit"
    packet_hash = "a" * 64
    packet = {
        "packet_hash": packet_hash,
        "execution_plan": {
            "batch_id": "s606_20260721_deadbeef",
            "target": "2026-07-21",
            "audit_root": str(audit_root),
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


def test_reconciliation_reports_missing_and_revision_without_mutating_history(tmp_path: Path) -> None:
    path = tmp_path / "actual_1m.parquet"
    pd.DataFrame(
        [
            _bar("2026-07-17 09:01:00", 100),
            _bar("2026-07-17 09:02:00", 101),
        ]
    ).to_parquet(path, index=False)
    with _session() as session:
        session.add(
            LiveMinuteBar(
                provider="rqdata",
                instrument_symbol="jm",
                contract_code="JM2609",
                exchange_code="DCE",
                period="1m",
                bar_datetime=datetime(2026, 7, 17, 9, 1),
                trading_day=date(2026, 7, 17),
                open=100,
                high=101,
                low=99,
                close=100,
                volume=10,
                open_interest=20,
                bar_status="confirmed",
                quality_status="passed",
                revision=1,
            )
        )
        session.flush()

        result = reconcile_live_provider(
            session,
            actual_contract="JM2609",
            trading_day=date(2026, 7, 17),
            canonical_1m=path,
        )

    assert result["status"] == "differences_observed"
    assert result["live_reference_only"] is True
    assert result["exact_match_count"] == 1
    assert result["live_missing_count"] == 1
    assert result["revision_row_count"] == 1
    assert result["ohlcv_mismatch_count"] == 0


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


def _live_row(value: str, price: int, *, revision: int) -> SimpleNamespace:
    return SimpleNamespace(
        bar_datetime=datetime.fromisoformat(value),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=10,
        open_interest=20,
        revision=revision,
    )


def _counted_frame(client: SimpleNamespace, frame: pd.DataFrame) -> pd.DataFrame:
    client.calls += 1
    return frame.copy()
