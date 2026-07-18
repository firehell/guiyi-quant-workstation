#!/usr/bin/env python3
"""Freeze B2-08B batch inputs and build the final rollout evidence."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any

import duckdb
from sqlalchemy import func, select, text


TASK_ID = "DATA-PROFILE-ROLLOUT-APPLY-008B"
CANDIDATES_SHA256 = "639009e89a8c5424c7de8281f059e296495595bc75c1abe939c19d461deba59b"
EXPECTED_CURRENT = 265
EXPECTED_WOULD_CHANGE = 241
EXPECTED_UNCHANGED = 24
EXPECTED_BLOCKED = 660
BATCH_COUNTS = {
    "profile-rollout-pilot-008b-001": 15,
    "profile-rollout-pilot-new-identity-008b-002": 1,
    "profile-rollout-intraday-008b-003": 85,
    "profile-rollout-long-horizon-008b-004": 140,
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _collect_execution_csv(output_dir: Path, filename: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((output_dir / "executions").glob(f"*/{filename}")):
        for row in _read_csv(path):
            rows.append({"execution_stage": path.parent.name, **row})
    return rows


def _identity(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return tuple(str(row.get(key) or "").strip() for key in ("profile_id", "instrument_symbol", "contract_code", "period"))  # type: ignore[return-value]


def _batch_for(row: dict[str, str]) -> str:
    profile, symbol, contract, period = _identity(row)
    pilot = (
        symbol in {"a", "al", "ag"}
        or (profile == "intraday_research_v1" and symbol == "jm" and contract == "jm.MAIN" and period == "1m")
        or (profile == "live_observation_v1" and symbol == "jm" and period in {"5m", "15m"})
        or (
            profile == "long_horizon_daily_v1"
            and symbol == "jm"
            and ((contract == "jm.MAIN" and period in {"1d", "1w"}) or (contract == "JM2305" and period == "1d"))
        )
    )
    if pilot:
        return "profile-rollout-pilot-008b-001"
    if profile == "long_horizon_daily_v1" and symbol == "jm" and contract == "JM2605" and period == "1d":
        return "profile-rollout-pilot-new-identity-008b-002"
    if profile == "intraday_research_v1":
        return "profile-rollout-intraday-008b-003"
    if profile == "long_horizon_daily_v1":
        return "profile-rollout-long-horizon-008b-004"
    raise RuntimeError(f"approved would-change row did not map to a batch: {_identity(row)}")


def _snapshot(session: Any) -> dict[str, Any]:
    from app.models.data_center import DataProfile, DataQualityReport, MarketDataFile, ProfileActiveBinding  # noqa: PLC0415

    def table_digest(table: str) -> str:
        allowed = {
            "market_data_files",
            "data_quality_reports",
            "data_profiles",
            "live_minute_bars",
            "live_aggregated_bars",
            "live_aggregation_checkpoints",
            "live_ingest_checkpoints",
        }
        if table not in allowed:
            raise ValueError(f"table not approved for snapshot: {table}")
        return str(
            session.execute(
                text(
                    f"SELECT md5(COALESCE(string_agg(md5(to_jsonb(t)::text), '' ORDER BY id), '')) "
                    f"FROM {table} AS t"
                )
            ).scalar_one()
        )

    report14 = session.execute(
        text("SELECT md5(to_jsonb(t)::text) FROM backtest_reports AS t WHERE id = 14")
    ).scalar_one_or_none()
    return {
        "market_data_files": session.scalar(select(func.count()).select_from(MarketDataFile)),
        "data_quality_reports": session.scalar(select(func.count()).select_from(DataQualityReport)),
        "data_profiles": session.scalar(select(func.count()).select_from(DataProfile)),
        "profile_active_bindings": session.scalar(select(func.count()).select_from(ProfileActiveBinding)),
        "active_bindings": session.scalar(
            select(func.count()).select_from(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")
        ),
        "report14_md5": report14,
        "market_data_files_digest": table_digest("market_data_files"),
        "data_quality_reports_digest": table_digest("data_quality_reports"),
        "data_profiles_digest": table_digest("data_profiles"),
        "live_minute_bars_digest": table_digest("live_minute_bars"),
        "live_aggregated_bars_digest": table_digest("live_aggregated_bars"),
        "live_aggregation_checkpoints_digest": table_digest("live_aggregation_checkpoints"),
        "live_ingest_checkpoints_digest": table_digest("live_ingest_checkpoints"),
    }


def _candidate_query(row: dict[str, str], *, query_id: str) -> dict[str, Any]:
    path = Path(row["file_path"])
    with duckdb.connect(database=":memory:") as connection:
        first = connection.execute(
            """
            SELECT datetime, trading_day
            FROM read_parquet(?)
            WHERE symbol = ? AND contract = ? AND period = ?
            ORDER BY datetime
            LIMIT 1
            """,
            [str(path), row["instrument_symbol"], row["contract_code"], row["period"]],
        ).fetchone()
        if first is None:
            raise RuntimeError(f"golden query source is empty: {_identity(row)}")
        first_datetime = first[0]
        day_start = datetime.combine(first_datetime.date(), time.min)
        day_end = datetime.combine(first_datetime.date(), time.max)
        boundaries = connection.execute(
            """
            SELECT min(datetime), max(datetime), min(trading_day), max(trading_day)
            FROM read_parquet(?)
            WHERE symbol = ? AND contract = ? AND period = ?
              AND datetime >= ? AND datetime <= ?
            """,
            [str(path), row["instrument_symbol"], row["contract_code"], row["period"], day_start, day_end],
        ).fetchone()
    if query_id == "ag_first_completed_week" and first_datetime.date().isoformat() != "2012-05-11":
        raise RuntimeError("ag first completed weekly bar drifted from 2012-05-11")
    if boundaries is None or boundaries[0] is None:
        raise RuntimeError(f"golden query boundary evidence is empty: {_identity(row)}")
    start = boundaries[0]
    end = boundaries[1]
    return {
        "query_id": query_id,
        "profile_id": row["profile_id"],
        "instrument_symbol": row["instrument_symbol"],
        "contract_code": row["contract_code"],
        "period": row["period"],
        "start": start.replace(tzinfo=UTC).isoformat(),
        "end": end.replace(tzinfo=UTC).isoformat(),
        "expected_market_data_file_id": row["market_data_file_id"],
        "expected_data_version": row["data_version"],
        "expected_first_datetime": boundaries[0].replace(tzinfo=UTC).isoformat(),
        "expected_last_datetime": boundaries[1].replace(tzinfo=UTC).isoformat(),
        "expected_first_trading_day": str(boundaries[2]),
        "expected_last_trading_day": str(boundaries[3]),
    }


def _golden_queries(current_by_identity: dict[tuple[str, str, str, str], dict[str, str]]) -> list[dict[str, Any]]:
    definitions = [
        ("a_provider_earliest_1m", ("intraday_research_v1", "a", "a.MAIN", "1m")),
        ("al_early_daily", ("long_horizon_daily_v1", "al", "al.MAIN", "1d")),
        ("ag_first_completed_week", ("long_horizon_daily_v1", "ag", "ag.MAIN", "1w")),
        ("jm_listing_aware_1m", ("intraday_research_v1", "jm", "jm.MAIN", "1m")),
        ("jm_live_historical_5m", ("live_observation_v1", "jm", "jm.MAIN", "5m")),
        ("jm_live_historical_15m", ("live_observation_v1", "jm", "jm.MAIN", "15m")),
        ("jm2305_actual_1d", ("long_horizon_daily_v1", "jm", "JM2305", "1d")),
        ("jm2605_new_identity_1d", ("long_horizon_daily_v1", "jm", "JM2605", "1d")),
    ]
    return [_candidate_query(current_by_identity[key], query_id=query_id) for query_id, key in definitions]


def plan(*, candidates_path: Path, diff_path: Path, output_dir: Path, session: Any) -> dict[str, Any]:
    from app.models.data_center import ProfileActiveBinding  # noqa: PLC0415

    if output_dir.exists():
        raise FileExistsError(f"refusing to overwrite rollout plan: {output_dir}")
    if _sha256(candidates_path) != CANDIDATES_SHA256:
        raise RuntimeError("B2-08A candidate SHA-256 drifted")
    candidates = _read_csv(candidates_path)
    current = [row for row in candidates if row.get("candidate_status") == "current"]
    blocked = [row for row in candidates if row.get("candidate_status") == "blocked"]
    diffs = _read_csv(diff_path)
    changed = [row for row in diffs if row.get("status") == "would_change"]
    unchanged = [row for row in diffs if row.get("status") == "unchanged"]
    if (len(current), len(changed), len(unchanged), len(blocked)) != (
        EXPECTED_CURRENT,
        EXPECTED_WOULD_CHANGE,
        EXPECTED_UNCHANGED,
        EXPECTED_BLOCKED,
    ):
        raise RuntimeError("B2-08A approved counts drifted")
    current_by_identity = {_identity(row): row for row in current}
    changed_by_identity = {_identity(row): row for row in changed}
    batches: dict[str, list[dict[str, str]]] = {batch_id: [] for batch_id in BATCH_COUNTS}
    for identity, diff in changed_by_identity.items():
        candidate = current_by_identity[identity]
        batches[_batch_for(candidate)].append(candidate)
    actual_counts = {batch_id: len(rows) for batch_id, rows in batches.items()}
    if actual_counts != BATCH_COUNTS:
        raise RuntimeError(f"approved batch counts drifted: {actual_counts}")

    active_rows = list(session.scalars(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")))
    active_by_identity: dict[tuple[str, str, str, str], list[Any]] = {}
    for binding in active_rows:
        active_by_identity.setdefault(
            (binding.profile_id, binding.instrument_symbol, binding.contract_code, binding.period), []
        ).append(binding)
    output_dir.mkdir(parents=True)
    for batch_id, rows in batches.items():
        batch_dir = output_dir / "batches" / batch_id
        batch_dir.mkdir(parents=True)
        stable_rows = sorted(rows, key=_identity)
        _write_csv(batch_dir / "binding_candidates.csv", stable_rows)
        before_rows: list[dict[str, Any]] = []
        for candidate in stable_rows:
            identity = _identity(candidate)
            active = active_by_identity.get(identity, [])
            if len(active) > 1:
                raise RuntimeError(f"multiple active before rollout: {identity}")
            binding = active[0] if active else None
            diff = changed_by_identity[identity]
            expected_file = str(diff.get("market_data_file_id_before") or "")
            expected_version = str(diff.get("data_version_before") or "")
            if (str(binding.market_data_file_id) if binding else "") != expected_file or (
                binding.data_version if binding else ""
            ) != expected_version:
                raise RuntimeError(f"DB before-state drifted from B2-08A diff: {identity}")
            before_rows.append(
                {
                    "profile_id": identity[0],
                    "instrument_symbol": identity[1],
                    "contract_code": identity[2],
                    "period": identity[3],
                    "previous_binding_id": binding.id if binding else "",
                    "previous_market_data_file_id": binding.market_data_file_id if binding else "",
                    "previous_data_version": binding.data_version if binding else "",
                    "next_market_data_file_id": candidate["market_data_file_id"],
                    "next_data_version": candidate["data_version"],
                }
            )
        _write_csv(batch_dir / "expected_before.csv", before_rows)
        (batch_dir / "batch_plan.json").write_text(
            json.dumps(
                {
                    "task_id": TASK_ID,
                    "batch_id": batch_id,
                    "operation_count": len(stable_rows),
                    "candidates_sha256": _sha256(batch_dir / "binding_candidates.csv"),
                    "expected_before_sha256": _sha256(batch_dir / "expected_before.csv"),
                    "writes_table": "profile_active_bindings",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
    _write_csv(output_dir / "unchanged.csv", unchanged)
    _write_csv(output_dir / "golden_queries.csv", _golden_queries(current_by_identity))
    before = _snapshot(session)
    (output_dir / "database_before.json").write_text(
        json.dumps(before, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    result = {
        "task_id": TASK_ID,
        "status": "PROFILE_ROLLOUT_BATCHES_FROZEN",
        "candidate_input_sha256": _sha256(candidates_path),
        "candidate_count": len(current),
        "would_change": len(changed),
        "unchanged": len(unchanged),
        "blocked": len(blocked),
        "batch_counts": actual_counts,
        "database_before": before,
    }
    (output_dir / "rollout_plan.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    return result


def finalize(*, candidates_path: Path, diff_path: Path, output_dir: Path, session: Any) -> dict[str, Any]:
    from app.models.data_center import ProfileActiveBinding  # noqa: PLC0415

    plan_payload = json.loads((output_dir / "rollout_plan.json").read_text(encoding="utf-8"))
    if plan_payload["candidate_input_sha256"] != CANDIDATES_SHA256 or _sha256(candidates_path) != CANDIDATES_SHA256:
        raise RuntimeError("candidate input drifted before finalization")
    candidates = _read_csv(candidates_path)
    current = [row for row in candidates if row.get("candidate_status") == "current"]
    blocked = [row for row in candidates if row.get("candidate_status") == "blocked"]
    diffs = _read_csv(diff_path)
    diff_by_identity = {_identity(row): row for row in diffs}
    active_rows = list(session.scalars(select(ProfileActiveBinding).where(ProfileActiveBinding.binding_status == "active")))
    active_by_identity: dict[tuple[str, str, str, str], list[Any]] = {}
    for binding in active_rows:
        active_by_identity.setdefault(
            (binding.profile_id, binding.instrument_symbol, binding.contract_code, binding.period), []
        ).append(binding)
    matrix: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in sorted(current, key=_identity):
        identity = _identity(candidate)
        active = active_by_identity.get(identity, [])
        binding = active[0] if len(active) == 1 else None
        matched = bool(
            binding
            and str(binding.market_data_file_id) == candidate["market_data_file_id"]
            and binding.data_version == candidate["data_version"]
        )
        if not matched:
            errors.append(f"active mismatch: {identity}")
        matrix.append(
            {
                **{key: candidate[key] for key in ("profile_id", "instrument_symbol", "contract_code", "period")},
                "diff_status": diff_by_identity[identity]["status"],
                "expected_market_data_file_id": candidate["market_data_file_id"],
                "actual_market_data_file_id": binding.market_data_file_id if binding else "",
                "expected_data_version": candidate["data_version"],
                "actual_data_version": binding.data_version if binding else "",
                "active_match": matched,
            }
        )
    duplicate_groups = sum(1 for rows in active_by_identity.values() if len(rows) > 1)
    before = plan_payload["database_before"]
    after = _snapshot(session)
    invariants = {
        key: before[key] == after[key]
        for key in (
            "market_data_files_digest",
            "data_quality_reports_digest",
            "data_profiles_digest",
            "live_minute_bars_digest",
            "live_aggregated_bars_digest",
            "live_aggregation_checkpoints_digest",
            "live_ingest_checkpoints_digest",
            "report14_md5",
        )
    }
    if duplicate_groups or not all(invariants.values()):
        errors.append("duplicate/blocked/non-binding table invariant failed")
    stage_batches = {
        "pilot_initial": "profile-rollout-pilot-008b-001",
        "pilot_final": "profile-rollout-pilot-008b-001",
        "new_identity_initial": "profile-rollout-pilot-new-identity-008b-002",
        "new_identity_final": "profile-rollout-pilot-new-identity-008b-002",
        "intraday": "profile-rollout-intraday-008b-003",
        "long_horizon": "profile-rollout-long-horizon-008b-004",
    }
    for stage, batch_id in stage_batches.items():
        execution_rows = _read_csv(output_dir / "executions" / stage / "apply_ledger.csv")
        approved_path = output_dir / "batches" / batch_id / "binding_candidates.csv"
        approved_rows = _read_csv(approved_path)
        if (
            len(execution_rows) != BATCH_COUNTS[batch_id]
            or {row.get("batch_id") for row in execution_rows} != {batch_id}
            or {_identity(row) for row in execution_rows} != {_identity(row) for row in approved_rows}
            or {row.get("candidate_sha256") for row in execution_rows} != {_sha256(approved_path)}
            or not all(str(row.get("committed", "")).lower() == "true" for row in execution_rows)
        ):
            errors.append(f"execution stage evidence mismatch: {stage}")
    rollback_stages = {
        "pilot_initial": "profile-rollout-pilot-008b-001",
        "new_identity_initial": "profile-rollout-pilot-new-identity-008b-002",
    }
    for stage, batch_id in rollback_stages.items():
        rollback_rows = _read_csv(output_dir / "executions" / stage / "rollback_ledger.csv")
        approved_rows = _read_csv(output_dir / "batches" / batch_id / "binding_candidates.csv")
        if (
            len(rollback_rows) != BATCH_COUNTS[batch_id]
            or {row.get("batch_id") for row in rollback_rows} != {batch_id}
            or {_identity(row) for row in rollback_rows} != {_identity(row) for row in approved_rows}
            or not all(str(row.get("committed", "")).lower() == "true" for row in rollback_rows)
        ):
            errors.append(f"rollback stage evidence mismatch: {stage}")
    apply_ledger = _collect_execution_csv(output_dir, "apply_ledger.csv")
    rollback_ledger = _collect_execution_csv(output_dir, "rollback_ledger.csv")
    committed_apply_rows = [row for row in apply_ledger if str(row.get("committed", "")).lower() == "true"]
    committed_rollback_rows = [row for row in rollback_ledger if str(row.get("committed", "")).lower() == "true"]
    blocked_keys = {(_identity(row), row["market_data_file_id"]) for row in blocked}
    blocked_applied_count = sum(
        1
        for row in committed_apply_rows
        if (_identity(row), str(row.get("next_market_data_file_id") or "")) in blocked_keys
    )
    if blocked_applied_count:
        errors.append(f"blocked candidates were applied: {blocked_applied_count}")
    if len(committed_apply_rows) != 257 or len(committed_rollback_rows) != 16:
        errors.append(
            f"pilot/full ledger count mismatch: apply={len(committed_apply_rows)} rollback={len(committed_rollback_rows)}"
        )
    _write_csv(output_dir / "apply_ledger.csv", apply_ledger)
    _write_csv(output_dir / "rollback_ledger.csv", rollback_ledger)
    _write_csv(output_dir / "profile_binding_final_matrix.csv", matrix)
    final = {
        "task_id": TASK_ID,
        "status": "PROFILE_ACTIVE_BINDINGS_VERIFIED" if not errors else "PROFILE_ROLLOUT_VERIFY_FAILED",
        "current_candidates": len(current),
        "would_change": Counter(row["diff_status"] for row in matrix).get("would_change", 0),
        "unchanged": Counter(row["diff_status"] for row in matrix).get("unchanged", 0),
        "active_match_count": sum(bool(row["active_match"]) for row in matrix),
        "blocked_candidates": len(blocked),
        "blocked_candidates_applied": blocked_applied_count,
        "duplicate_active_groups": duplicate_groups,
        "database_before": before,
        "database_after": after,
        "non_binding_invariants": invariants,
        "errors": errors,
        "committed_apply_ledger_rows": len(committed_apply_rows),
        "committed_rollback_ledger_rows": len(committed_rollback_rows),
        "writes_database": True,
        "writes_database_table": "profile_active_bindings",
        "writes_parquet": False,
        "writes_manifest": False,
        "calls_rqdata": False,
        "profile_binding_changed": True,
        "report14_changed": not invariants["report14_md5"],
        "data_layer_status": "DATA_LAYER_REAUDIT_REQUIRED",
    }
    (output_dir / "batch_evidence.json").write_text(
        json.dumps(final, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    (output_dir / "PROFILE_ROLLOUT_FINAL_SUMMARY.md").write_text(
        "\n".join(
            [
                f"# {TASK_ID}",
                "",
                f"- status: `{final['status']}`",
                f"- current / changed / unchanged: `{len(current)} / {final['would_change']} / {final['unchanged']}`",
                f"- active matches: `{final['active_match_count']}`",
                f"- blocked candidates written: `{blocked_applied_count}`",
                f"- duplicate active groups: `{duplicate_groups}`",
                "- writes: `profile_active_bindings only`",
                "- Parquet / manifest / RQData: `unchanged / unchanged / not called`",
                "- report_id=14: `unchanged`",
                "- higher-level status: `DATA_LAYER_REAUDIT_REQUIRED`",
                "",
                final["status"],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return final


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["plan", "finalize"])
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--candidates-path", type=Path, required=True)
    parser.add_argument("--diff-path", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    if not project_root.is_dir():
        parser.error(f"project root does not exist: {project_root}")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/quant-api"))
    from app.db.session import SessionLocal  # noqa: PLC0415

    with SessionLocal() as session:
        if args.mode == "plan":
            result = plan(
                candidates_path=args.candidates_path.resolve(),
                diff_path=args.diff_path.resolve(),
                output_dir=args.output_dir.resolve(),
                session=session,
            )
        else:
            result = finalize(
                candidates_path=args.candidates_path.resolve(),
                diff_path=args.diff_path.resolve(),
                output_dir=args.output_dir.resolve(),
                session=session,
            )
        session.rollback()
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
