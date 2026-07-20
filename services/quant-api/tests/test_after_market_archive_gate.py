from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.models.data_center import DataDownloadTask, LiveMinuteBar
from app.services.after_market_archive_gate import (
    _record_failure,
    build_approval_packet,
    build_archive_plan,
    reconcile_live_provider,
)
from app.services.rqdata_ingest.jm_historical_catchup import build_profile_binding_plan, canonical_packet_hash


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
