from datetime import UTC, date, datetime, time
import json
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.data_center import (
    DataProfile,
    Exchange,
    FuturesTradingParameter,
    MainContractMap,
    MarketDataFile,
    ProfileActiveBinding,
    TradingCalendar,
    TradingSession,
)
from app.services.rqdata_ingest.jm_historical_catchup_execution import (
    S603ExecutionError,
    apply_profile_binding_candidates,
    apply_reference_snapshot,
    build_execution_approval_packet,
    build_execution_artifact_plan,
    collect_active_binding_snapshot,
    collect_provider_reference_snapshot,
    expected_execution_paths,
    execute_approved_catchup,
    bind_single_trading_day_query,
    validate_execution_paths_create_only,
)
from app.services.rqdata_ingest.jm_historical_catchup import build_gap_plan


def _session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    session.add(Exchange(code="DCE", name="DCE", country="CN", timezone="Asia/Shanghai", is_active=True))
    session.add(
        TradingSession(
            exchange_code="DCE",
            instrument_symbol="jm",
            session_name="day",
            start_time=time(9),
            end_time=time(15),
            provider="rqdata",
        )
    )
    session.commit()
    return session


def _reference_snapshot() -> dict:
    return {
        "calendar": [
            {"trade_date": "2026-07-17", "is_trading_day": True},
            {"trade_date": "2026-07-18", "is_trading_day": False},
            {"trade_date": "2026-07-19", "is_trading_day": False},
            {"trade_date": "2026-07-20", "is_trading_day": True},
        ],
        "rank1_mapping": [
            {"trade_date": "2026-07-17", "contract_code": "JM2609"},
        ],
        "trading_parameters": [
            {
                "trade_date": "2026-07-17",
                "contract_code": "JM2609",
                "exchange_code": "DCE",
                "price_tick": "0.5",
                "contract_multiplier": 60,
                "long_margin_ratio": "0.12",
                "short_margin_ratio": "0.12",
                "open_commission": "1",
                "close_commission": "1",
                "close_today_commission": "1",
            }
        ],
    }


def test_single_trading_day_query_binds_weekend_night_rows_to_requested_day() -> None:
    frame = pd.DataFrame(
        {
            "datetime": pd.to_datetime(["2026-07-24 21:01:00", "2026-07-27 09:01:00"]),
            "trading_day": [date(2026, 7, 25), date(2026, 7, 27)],
        }
    )

    result = bind_single_trading_day_query(
        frame,
        request_start=date(2026, 7, 27),
        request_end=date(2026, 7, 27),
    )

    assert result["trading_day"].tolist() == [date(2026, 7, 27), date(2026, 7, 27)]


def test_reference_snapshot_is_versioned_and_fresh() -> None:
    with _session() as session:
        result = apply_reference_snapshot(
            session,
            snapshot=_reference_snapshot(),
            batch_id="s6_03_20260717_deadbeef",
            target=date(2026, 7, 17),
        )
        session.flush()

        mapping = session.scalar(select(MainContractMap).where(MainContractMap.trade_date == date(2026, 7, 17)))
        params = session.scalar(
            select(FuturesTradingParameter).where(FuturesTradingParameter.trade_date == date(2026, 7, 17))
        )

    assert result["status"] == "passed"
    assert result["latest_calendar_date"] == "2026-07-20"
    assert result["latest_mapping_date"] == "2026-07-17"
    assert result["latest_parameter_date"] == "2026-07-17"
    assert mapping is not None and mapping.contract_code == "JM2609"
    assert mapping.data_version == "s6_03_20260717_deadbeef_reference_v1"
    assert params is not None and params.data_version == "s6_03_20260717_deadbeef_reference_v1"


def test_reference_snapshot_blocks_missing_target_metadata() -> None:
    snapshot = _reference_snapshot()
    snapshot["rank1_mapping"] = []
    with _session() as session, pytest.raises(S603ExecutionError, match="rank1_mapping_target_missing"):
        apply_reference_snapshot(
            session,
            snapshot=snapshot,
            batch_id="s6_03_20260717_deadbeef",
            target=date(2026, 7, 17),
        )


def test_reference_refresh_preserves_existing_night_session_flag() -> None:
    with _session() as session:
        session.add(
            TradingCalendar(
                exchange_code="DCE",
                trade_date=date(2026, 7, 17),
                is_trading_day=True,
                has_night_session=True,
                provider="rqdata",
            )
        )
        session.flush()
        apply_reference_snapshot(
            session,
            snapshot=_reference_snapshot(),
            batch_id="s6_03_20260717_deadbeef",
            target=date(2026, 7, 17),
        )
        refreshed = session.scalar(
            select(TradingCalendar).where(TradingCalendar.trade_date == date(2026, 7, 17))
        )

    assert refreshed is not None and refreshed.has_night_session is True


def test_expected_paths_are_jm_only_and_create_only(tmp_path: Path) -> None:
    paths = expected_execution_paths(
        output_root=tmp_path,
        batch_id="s6_03_20260717_deadbeef",
        target=date(2026, 7, 17),
        continuous_start=date(2013, 3, 22),
        actual_contract="JM2609",
        actual_start=date(2026, 7, 13),
        weekly_target=date(2026, 7, 10),
    )
    validate_execution_paths_create_only(paths)
    all_paths = [Path(value) for value in paths["files"]]
    assert all(path.is_relative_to(tmp_path) for path in all_paths)
    assert all("jm" in str(path).lower() for path in all_paths)
    collision = all_paths[0]
    collision.parent.mkdir(parents=True)
    collision.write_bytes(b"existing")
    with pytest.raises(S603ExecutionError, match="output_already_exists"):
        validate_execution_paths_create_only(paths)


class _ReferenceClient:
    def trading_dates(self, start_date: date, end_date: date) -> list[date]:
        return [date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17), date(2026, 7, 20)]

    def dominant_contracts(self, product: str, start_date: date, end_date: date, rank: int) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "date": pd.date_range("2026-07-13", "2026-07-17", freq="B"),
                "dominant": ["JM2609"] * 5,
            }
        )

    def trading_parameters(self, contract: str, start_date: date, end_date: date) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "order_book_id": [contract] * 5,
                "trading_date": pd.date_range("2026-07-13", "2026-07-17", freq="B"),
                "long_margin_ratio": [0.12] * 5,
                "short_margin_ratio": [0.12] * 5,
                "open_commission": [0.0001] * 5,
                "close_commission": [0.0001] * 5,
                "close_commission_today": [0.0001] * 5,
            }
        )

    def price_tick(self, contract: str) -> float:
        return 0.5

    def contract_multiplier(self, contract: str) -> int:
        return 60


def test_provider_snapshot_proves_target_finality_and_contract() -> None:
    snapshot = collect_provider_reference_snapshot(
        _ReferenceClient(),
        calendar_start=date(2026, 7, 11),
        calendar_end=date(2026, 7, 20),
        mapping_start=date(2026, 7, 13),
        target=date(2026, 7, 17),
    )

    assert snapshot["provider_final_day"] == "2026-07-17"
    assert snapshot["actual_contract"] == "JM2609"
    assert snapshot["calendar"][-1] == {"trade_date": "2026-07-20", "is_trading_day": True}
    assert len(snapshot["trading_parameters"]) == 5
    assert snapshot["trading_parameters"][-1]["price_tick"] == 0.5


def test_artifact_plan_has_direct_and_local_derived_roles(tmp_path: Path) -> None:
    plan = build_execution_artifact_plan(
        output_root=tmp_path,
        batch_id="s6_03_20260717_deadbeef",
        target=date(2026, 7, 17),
        continuous_start=date(2013, 3, 22),
        actual_contract="JM2609",
        actual_start=date(2026, 7, 13),
        weekly_target=date(2026, 7, 10),
    )

    identities = {(row["contract"], row["period"], row["source_role"]) for row in plan["bars"]}
    assert ("jm.MAIN", "1w", "direct") in identities
    assert ("jm.MAIN", "1d", "derived_from_1m") in identities
    assert ("JM2609", "1d", "direct") in identities
    assert ("JM2609", "1w", "direct") not in identities
    weekly = next(row for row in plan["bars"] if row["contract"] == "jm.MAIN" and row["period"] == "1w")
    assert weekly["end"] == "2026-07-10"
    assert all(row["write_mode"] == "create_only" for row in plan["bars"])
    assert all(len(row["data_version"]) <= 64 for row in plan["bars"])


def test_active_binding_snapshot_is_deterministic() -> None:
    with _session() as session:
        session.add(
            ProfileActiveBinding(
                profile_id="intraday_research_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1m",
                data_version="v1",
                market_data_file_id=None,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.flush()
        first = collect_active_binding_snapshot(session)
        second = collect_active_binding_snapshot(session)

    assert first == second
    assert len(first["sha256"]) == 64
    assert first["bindings"][0]["data_version"] == "v1"


def _profile_candidate(session: Session, tmp_path: Path) -> tuple[MarketDataFile, dict, dict]:
    session.add(
        DataProfile(
            profile_id="long_horizon_daily_v1",
            label="Long Horizon Daily",
            contract_roles=["dominant_main"],
            periods=["1d"],
            quality_policy="passed_only",
            provider="rqdata",
        )
    )
    target_path = tmp_path / "target.parquet"
    pd.DataFrame({"datetime": [datetime(2026, 7, 17)]}).to_parquet(target_path, index=False)
    market_file = MarketDataFile(
        provider="rqdata",
        data_type="bars",
        instrument_symbol="jm",
        contract_code="jm.MAIN",
        period="1d",
        start_time=datetime(2026, 7, 17, tzinfo=UTC),
        end_time=datetime(2026, 7, 17, tzinfo=UTC),
        file_path=str(target_path),
        row_count=1,
        checksum="a" * 64,
        data_version="target_v1",
        data_role="primary",
        quality_status="passed",
    )
    session.add(market_file)
    session.flush()
    artifacts = {
        "bars": [
            {
                "contract": "jm.MAIN",
                "period": "1d",
                "source_role": "direct",
                "data_version": "target_v1",
                "canonical_path": str(target_path),
                "end": "2026-07-17",
            }
        ]
    }
    registration = {
        "by_version": {
            "target_v1": {
                "quality_status": "passed",
                "market_data_file_id": market_file.id,
            }
        }
    }
    return market_file, artifacts, registration


def test_profile_apply_blocks_snapshot_drift(tmp_path: Path) -> None:
    with _session() as session:
        _, artifacts, registration = _profile_candidate(session, tmp_path)
        stale = collect_active_binding_snapshot(session)
        session.add(
            ProfileActiveBinding(
                profile_id="long_horizon_daily_v1",
                instrument_symbol="jm",
                contract_code="jm.MAIN",
                contract_role="dominant_main",
                period="1d",
                data_version="drifted",
                market_data_file_id=None,
                binding_status="active",
                activated_at=datetime.now(UTC),
            )
        )
        session.flush()
        with pytest.raises(S603ExecutionError, match="active_binding_snapshot_drift"):
            apply_profile_binding_candidates(
                session,
                artifact_plan=artifacts,
                registration=registration,
                expected_snapshot=stale,
                project_root=tmp_path,
            )


def test_profile_apply_switches_registered_passed_candidate(tmp_path: Path) -> None:
    with _session() as session:
        _, artifacts, registration = _profile_candidate(session, tmp_path)
        snapshot = collect_active_binding_snapshot(session)
        result = apply_profile_binding_candidates(
            session,
            artifact_plan=artifacts,
            registration=registration,
            expected_snapshot=snapshot,
            project_root=tmp_path,
        )
        active = session.scalar(
            select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")
        )

    assert result["status"] == "passed"
    assert result["count"] == 1
    assert active is not None and active.data_version == "target_v1"


def test_execution_packet_binds_embedded_snapshots_and_all_paths(tmp_path: Path) -> None:
    gap = build_gap_plan(
        product="jm",
        trading_days=[date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 17)],
        target=date(2026, 7, 17),
        weekly_target=date(2026, 7, 17),
        active_ends={},
        rank1_mapping={
            date(2026, 7, 10): "JM2609",
            date(2026, 7, 13): "JM2609",
            date(2026, 7, 17): "JM2609",
        },
    )
    execution = build_execution_artifact_plan(
        output_root=tmp_path,
        batch_id="s6_03_20260717_deadbeef",
        target=date(2026, 7, 17),
        continuous_start=date(2013, 3, 22),
        actual_contract="JM2609",
        actual_start=date(2025, 9, 1),
        continuous_gap_start=date(2026, 7, 13),
        actual_gap_start=date(2026, 7, 13),
    )
    reference = {"product": "jm", "actual_contract": "JM2609", **_reference_snapshot()}
    bindings = {"product": "jm", "bindings": [], "sha256": "c" * 64}
    packet = build_execution_approval_packet(
        gap_plan=gap,
        execution_plan=execution,
        reference_snapshot=reference,
        binding_snapshot=bindings,
        git_commit="a" * 40,
        git_branch="feature/test",
        git_status_sha256="b" * 64,
        output_root=tmp_path,
        output_root_identity={"device": 1, "inode": 2},
        database_target="postgresql+psycopg://guiyi:***@127.0.0.1:5432/guiyi_quant",
        database_identity={"database": "guiyi_quant", "user": "guiyi"},
        metadata_snapshot_sha256="d" * 64,
        calendar_start=date(2026, 7, 11),
        calendar_end=date(2026, 7, 20),
    )

    assert packet["execution_plan"] == execution
    assert packet["binding_snapshot"] == bindings
    assert packet["bound_facts"]["expected_database_rows"]["market_data_files"] == 19
    assert any(path.endswith("completion_receipt.json") for path in packet["bound_facts"]["expected_outputs"])


def test_execute_requires_exact_user_approval_hash(tmp_path: Path) -> None:
    with _session() as session, pytest.raises(S603ExecutionError, match="approval_hash_mismatch"):
        execute_approved_catchup(
            session=session,
            client=object(),
            packet={"packet_hash": "a" * 64},
            approval_hash="b" * 64,
            current_facts={},
            output_root=tmp_path,
            project_root=tmp_path,
        )


def test_apply_cli_rejects_missing_write_flags_before_external_access(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps({"packet_hash": "a" * 64}), encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "jm_historical_catchup.py"

    result = subprocess.run(
        [sys.executable, str(script), "apply", "--packet", str(packet_path), "--approve-hash", "a" * 64],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "apply_requires_run_write_and_confirm_jm_only" in result.stderr
