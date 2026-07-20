from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.services.rqdata_ingest.jm_historical_catchup import (
    ApprovalPacketDriftError,
    CatchupBlockedError,
    TradingDayState,
    binding_quality_eligible,
    build_approval_packet,
    build_artifact_plan,
    build_gap_plan,
    build_profile_binding_plan,
    build_rqdata_request_plan,
    build_s6_03_approval_packet,
    canonical_packet_hash,
    latest_completed_week_end,
    resolve_latest_closed_trading_day,
    resolve_latest_completed_trading_day,
    validate_create_only_outputs,
    verify_approval_packet,
)


def _calendar() -> tuple[TradingDayState, ...]:
    return (
        TradingDayState(date(2026, 7, 10), True, datetime(2026, 7, 10, 15, 0)),
        TradingDayState(date(2026, 7, 11), False, None),
        TradingDayState(date(2026, 7, 12), False, None),
        TradingDayState(date(2026, 7, 13), True, datetime(2026, 7, 13, 15, 0)),
        TradingDayState(date(2026, 7, 14), True, datetime(2026, 7, 14, 15, 0)),
        TradingDayState(date(2026, 7, 15), True, datetime(2026, 7, 15, 15, 0)),
        TradingDayState(date(2026, 7, 16), True, datetime(2026, 7, 16, 15, 0)),
        TradingDayState(date(2026, 7, 17), True, datetime(2026, 7, 17, 15, 0)),
        TradingDayState(date(2026, 7, 18), False, None),
        TradingDayState(date(2026, 7, 19), False, None),
        TradingDayState(date(2026, 7, 20), True, datetime(2026, 7, 20, 15, 0)),
    )


def test_latest_completed_day_requires_calendar_covering_now() -> None:
    with pytest.raises(CatchupBlockedError, match="trading_calendar_stale"):
        resolve_latest_completed_trading_day(
            calendar=_calendar()[:-1],
            now=datetime(2026, 7, 20, 10, 0),
            provider_final_days={date(2026, 7, 17)},
        )


def test_latest_completed_day_uses_close_and_provider_finality() -> None:
    assert resolve_latest_completed_trading_day(
        calendar=_calendar(),
        now=datetime(2026, 7, 20, 10, 0),
        provider_final_days={date(2026, 7, 16), date(2026, 7, 17)},
    ) == date(2026, 7, 17)


def test_latest_closed_day_does_not_depend_on_delayed_provider_daybar() -> None:
    assert resolve_latest_closed_trading_day(
        calendar=_calendar(),
        now=datetime(2026, 7, 20, 15, 1),
    ) == date(2026, 7, 20)


def test_latest_completed_day_blocks_missing_session_close() -> None:
    broken = list(_calendar())
    broken[7] = TradingDayState(date(2026, 7, 17), True, None)
    with pytest.raises(CatchupBlockedError, match="trading_session_close_missing:2026-07-17"):
        resolve_latest_completed_trading_day(
            calendar=tuple(broken),
            now=datetime(2026, 7, 20, 10, 0),
            provider_final_days={date(2026, 7, 17)},
        )


def test_latest_completed_week_end_requires_complete_calendar_week() -> None:
    assert latest_completed_week_end(_calendar(), target=date(2026, 7, 17)) == date(2026, 7, 17)
    assert latest_completed_week_end(_calendar()[:8], target=date(2026, 7, 17)) == date(2026, 7, 10)


def test_gap_plan_separates_continuous_and_rank1_actual_roles() -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]
    plan = build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 17),
        weekly_target=date(2026, 7, 17),
        active_ends={
            ("jm.MAIN", "1m", "direct"): date(2026, 7, 10),
            ("jm.MAIN", "1d", "direct"): date(2026, 7, 10),
            ("jm.MAIN", "1w", "direct"): date(2026, 7, 10),
            ("JM2609", "1m", "direct"): date(2026, 7, 10),
            ("JM2609", "1d", "direct"): date(2026, 7, 10),
        },
        rank1_mapping={day: "JM2609" for day in trading_days},
    )

    identities = {(item.contract, item.period, item.source_role) for item in plan.items}
    assert ("jm.MAIN", "1m", "direct") in identities
    assert ("jm.MAIN", "1d", "derived_from_1m") in identities
    assert ("jm.MAIN", "1w", "direct") in identities
    assert ("JM2609", "1m", "direct") in identities
    assert ("JM2609", "60m", "derived_from_1m") in identities
    assert ("JM2609", "1w", "direct") not in identities
    starts = {(item.contract, item.period, item.source_role): item.start for item in plan.items}
    assert starts[("jm.MAIN", "1m", "direct")] == date(2026, 7, 13)
    assert starts[("jm.MAIN", "1d", "derived_from_1m")] == date(2026, 7, 10)
    assert starts[("JM2609", "60m", "derived_from_1m")] == date(2026, 7, 10)


def test_gap_plan_returns_up_to_date_and_rejects_mapping_gap() -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13)]
    active_ends = {
        (contract, period, role): date(2026, 7, 13)
        for contract, periods in {
            "jm.MAIN": (("1m", "direct"), ("1d", "direct"), ("1w", "direct"), ("5m", "derived_from_1m"), ("15m", "derived_from_1m"), ("30m", "derived_from_1m"), ("60m", "derived_from_1m"), ("1d", "derived_from_1m")),
            "JM2609": (("1m", "direct"), ("1d", "direct"), ("5m", "derived_from_1m"), ("15m", "derived_from_1m"), ("30m", "derived_from_1m"), ("60m", "derived_from_1m")),
        }.items()
        for period, role in periods
    }
    assert build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 13),
        weekly_target=date(2026, 7, 13),
        active_ends=active_ends,
        rank1_mapping={day: "JM2609" for day in trading_days},
    ).status == "up_to_date"

    with pytest.raises(CatchupBlockedError, match="rank1_mapping_missing:2026-07-13"):
        build_gap_plan(
            product="jm",
            trading_days=trading_days,
            target=date(2026, 7, 13),
            weekly_target=date(2026, 7, 13),
            active_ends={},
            rank1_mapping={date(2026, 7, 10): "JM2609"},
        )


def test_gap_plan_splits_actual_contracts_at_rank1_roll() -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14)]
    plan = build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 14),
        weekly_target=date(2026, 7, 10),
        active_ends={},
        rank1_mapping={
            date(2026, 7, 10): "JM2605",
            date(2026, 7, 13): "JM2609",
            date(2026, 7, 14): "JM2609",
        },
    )

    actual_1m = {
        item.contract: (item.start, item.end, item.mapping_start, item.mapping_end)
        for item in plan.items
        if item.period == "1m" and item.source_role == "direct" and item.contract != "jm.MAIN"
    }
    assert actual_1m == {
        "JM2605": (date(2026, 7, 10), date(2026, 7, 10), date(2026, 7, 10), date(2026, 7, 10)),
        "JM2609": (date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 13), date(2026, 7, 14)),
    }


def test_packet_hash_is_deterministic_and_bound_fact_drift_fails(tmp_path: Path) -> None:
    packet = build_approval_packet(
        git_commit="a" * 40,
        git_branch="feature/test",
        git_status_sha256="b" * 64,
        output_root=tmp_path,
        output_root_identity={"device": 1, "inode": 2},
        database_target="postgresql+psycopg://guiyi:***@127.0.0.1:5432/guiyi_quant",
        database_identity={"database": "guiyi_quant", "user": "guiyi"},
        binding_snapshot_sha256="c" * 64,
        metadata_snapshot_sha256="d" * 64,
        target=date(2026, 7, 17),
        request_plan={"calendar": ["2026-07-11", "2026-07-20"]},
        expected_outputs=[tmp_path / "candidate.parquet"],
        expected_versions=["s6_03_jm_20260717_v1"],
        expected_database_rows={"market_data_files": 1},
        rollback_plan={"binding": "restore_previous"},
    )
    assert packet["packet_hash"] == canonical_packet_hash(packet)
    assert packet == build_approval_packet(
        git_commit="a" * 40,
        git_branch="feature/test",
        git_status_sha256="b" * 64,
        output_root=tmp_path,
        output_root_identity={"device": 1, "inode": 2},
        database_target="postgresql+psycopg://guiyi:***@127.0.0.1:5432/guiyi_quant",
        database_identity={"database": "guiyi_quant", "user": "guiyi"},
        binding_snapshot_sha256="c" * 64,
        metadata_snapshot_sha256="d" * 64,
        target=date(2026, 7, 17),
        request_plan={"calendar": ["2026-07-11", "2026-07-20"]},
        expected_outputs=[tmp_path / "candidate.parquet"],
        expected_versions=["s6_03_jm_20260717_v1"],
        expected_database_rows={"market_data_files": 1},
        rollback_plan={"binding": "restore_previous"},
    )

    with pytest.raises(ApprovalPacketDriftError, match="metadata_snapshot_sha256"):
        verify_approval_packet(packet, current_facts={**packet["bound_facts"], "metadata_snapshot_sha256": "e" * 64})


def test_create_only_and_quality_gates(tmp_path: Path) -> None:
    output = tmp_path / "candidate.parquet"
    validate_create_only_outputs([output])
    output.write_bytes(b"existing")
    with pytest.raises(CatchupBlockedError, match="output_already_exists"):
        validate_create_only_outputs([output])

    assert binding_quality_eligible("passed") is True
    assert binding_quality_eligible("warning") is False
    assert binding_quality_eligible("failed") is False


def test_non_jm_scope_is_rejected() -> None:
    with pytest.raises(CatchupBlockedError, match="jm_only"):
        build_gap_plan(
            product="rb",
            trading_days=[date(2026, 7, 17)],
            target=date(2026, 7, 17),
            weekly_target=date(2026, 7, 17),
            active_ends={},
            rank1_mapping={date(2026, 7, 17): "RB2610"},
        )


def test_request_plan_downloads_direct_periods_only() -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13), date(2026, 7, 14), date(2026, 7, 15), date(2026, 7, 16), date(2026, 7, 17)]
    plan = build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 17),
        weekly_target=date(2026, 7, 17),
        active_ends={},
        rank1_mapping={day: "JM2609" for day in trading_days},
    )
    requests = build_rqdata_request_plan(
        plan,
        calendar_start=date(2026, 7, 11),
        calendar_end=date(2026, 7, 20),
    )

    assert requests["reference"]["calendar"] == ["2026-07-11", "2026-07-20"]
    assert requests["reference"]["rank1_mapping"] == ["2026-06-26", "2026-07-17"]
    bar_periods = {(row["contract"], row["period"]) for row in requests["bars"]}
    assert ("jm.MAIN", "1m") in bar_periods
    assert ("jm.MAIN", "1d") in bar_periods
    assert ("jm.MAIN", "1w") in bar_periods
    assert ("JM2609", "1m") in bar_periods
    assert ("JM2609", "1d") in bar_periods
    assert all(row["source_role"] == "direct" for row in requests["bars"])
    assert not any(row["period"] in {"5m", "15m", "30m", "60m"} for row in requests["bars"])


def test_artifact_and_profile_plans_are_versioned_and_role_specific(tmp_path: Path) -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13)]
    gap = build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 13),
        weekly_target=date(2026, 7, 10),
        active_ends={},
        rank1_mapping={day: "JM2609" for day in trading_days},
    )
    artifacts = build_artifact_plan(gap, output_root=tmp_path, batch_id="s6_03_20260713_deadbeef")

    versions = [row["data_version"] for row in artifacts["bars"]]
    paths = [row["canonical_path"] for row in artifacts["bars"]]
    assert len(versions) == len(set(versions))
    assert len(paths) == len(set(paths))
    assert any("derived_from_1m" in version for version in versions)
    assert any("direct" in version for version in versions)
    assert all("s6_03_20260713_deadbeef" in path for path in paths)
    assert all(Path(path).is_relative_to(tmp_path) for path in paths)

    bindings = build_profile_binding_plan(artifacts)
    identities = {(row["profile_id"], row["contract"], row["period"], row["source_role"]) for row in bindings}
    assert ("intraday_research_v1", "jm.MAIN", "1d", "derived_from_1m") in identities
    assert ("long_horizon_daily_v1", "jm.MAIN", "1d", "direct") in identities
    assert ("long_horizon_daily_v1", "JM2609", "1d", "direct") in identities
    assert not any(row["profile_id"] == "long_horizon_daily_v1" and row["period"] == "5m" for row in bindings)


def test_s6_03_packet_binds_all_planned_outputs_and_row_types(tmp_path: Path) -> None:
    trading_days = [date(2026, 7, 10), date(2026, 7, 13)]
    gap = build_gap_plan(
        product="jm",
        trading_days=trading_days,
        target=date(2026, 7, 13),
        weekly_target=date(2026, 7, 10),
        active_ends={},
        rank1_mapping={day: "JM2609" for day in trading_days},
    )
    packet = build_s6_03_approval_packet(
        plan=gap,
        batch_id="s6_03_20260713_deadbeef",
        git_commit="a" * 40,
        git_branch="feature/test",
        git_status_sha256="b" * 64,
        output_root=tmp_path,
        output_root_identity={"device": 1, "inode": 2},
        database_target="postgresql+psycopg://guiyi:***@127.0.0.1:5432/guiyi_quant",
        database_identity={"database": "guiyi_quant", "user": "guiyi"},
        binding_snapshot_sha256="c" * 64,
        metadata_snapshot_sha256="d" * 64,
        calendar_start=date(2026, 7, 11),
        calendar_end=date(2026, 7, 20),
    )

    facts = packet["bound_facts"]
    assert packet["writes_authorized"] is False
    assert facts["expected_database_rows"]["market_data_files"] == len(gap.items)
    assert facts["expected_database_rows"]["data_quality_reports"] == len(gap.items)
    assert facts["expected_database_rows"]["profile_binding_candidates"] > 0
    assert any(path.endswith(".parquet") for path in facts["expected_outputs"])
    assert facts["rollback_plan"]["existing_assets"] == "immutable"
    assert packet["packet_hash"] == canonical_packet_hash(packet)


def test_packet_cli_has_no_output_side_effects(tmp_path: Path) -> None:
    output_root = tmp_path / "must-not-be-created"
    snapshot = {
        "product": "jm",
        "trading_days": ["2026-07-10", "2026-07-13"],
        "latest_completed_trading_day": "2026-07-13",
        "latest_completed_week_end": "2026-07-10",
        "rank1_mapping": {"2026-07-10": "JM2609", "2026-07-13": "JM2609"},
        "active_ends": [],
        "batch_id": "s6_03_20260713_deadbeef",
        "git_commit": "a" * 40,
        "git_branch": "feature/test",
        "git_status_sha256": "b" * 64,
        "output_root": str(output_root),
        "output_root_identity": {"device": 1, "inode": 2},
        "database_target": "postgresql+psycopg://guiyi:***@127.0.0.1:5432/guiyi_quant",
        "database_identity": {"database": "guiyi_quant", "user": "guiyi"},
        "binding_snapshot_sha256": "c" * 64,
        "metadata_snapshot_sha256": "d" * 64,
        "calendar_start": "2026-07-11",
        "calendar_end": "2026-07-20",
    }
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(json.dumps(snapshot), encoding="utf-8")
    script = Path(__file__).parents[1] / "scripts" / "jm_historical_catchup.py"

    result = subprocess.run(
        [sys.executable, str(script), "packet", "--snapshot", str(snapshot_path)],
        check=True,
        capture_output=True,
        text=True,
    )

    packet = json.loads(result.stdout)
    assert packet["status"] == "approval_required"
    assert packet["writes_authorized"] is False
    assert not output_root.exists()
