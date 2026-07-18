#!/usr/bin/env python3
"""Fail-closed Stage C Profile binding reconciliation.

Only ``profile_active_bindings`` may be changed. The script never downloads or
rewrites market data and never touches historical consumer records.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import select, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from app.db.session import SessionLocal  # noqa: E402
from app.models.data_center import MarketDataFile, ProfileActiveBinding  # noqa: E402
from app.services.data_profile_registry import DataProfileRegistry  # noqa: E402
from app.services.profile_lineage import resolve_source_interval  # noqa: E402
from app.services.rqdata_ingest.parquet import sha256_file  # noqa: E402

TASK_ID = "CONSUMER-CONTRACT-FINAL-CLOSEOUT-006"
EXPECTED_ALEMBIC = "20260718_0024"
PROFILES = ("intraday_research_v1", "live_observation_v1", "long_horizon_daily_v1")
ALLOWED_PROVIDERS = {"rqdata", "local_parquet"}
LIVE_TABLES_ONLY_PERIODS = {"30m", "60m", "1d", "1w"}
ACTUAL_FILE_ID = 103923
ACTUAL_PROFILES = ("intraday_research_v1", "live_observation_v1")
EVIDENCE_DIR = PROJECT_ROOT / "data/reports/consumer_contract_final_closeout_006"
LOCK_KEY = 2026071806


class CloseoutError(RuntimeError):
    pass


def plan_digest(operations: list[dict[str, Any]]) -> str:
    payload = json.dumps(operations, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def select_replacement(*, current: dict[str, Any], candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    start = datetime.fromisoformat(str(current["start_time"]).replace("Z", "+00:00"))
    end = datetime.fromisoformat(str(current["end_time"]).replace("Z", "+00:00"))
    eligible = []
    for candidate in candidates:
        candidate_start = datetime.fromisoformat(str(candidate["start_time"]).replace("Z", "+00:00"))
        candidate_end = datetime.fromisoformat(str(candidate["end_time"]).replace("Z", "+00:00"))
        if (
            candidate.get("provider") in (None, *ALLOWED_PROVIDERS)
            and candidate.get("data_role") == "primary"
            and candidate.get("quality_status") == "passed"
            and candidate.get("physical_ok") is True
            and candidate.get("source_interval")
            and candidate_start <= start
            and candidate_end >= end
        ):
            eligible.append(candidate)
    if not eligible:
        return None
    return sorted(
        eligible,
        key=lambda item: (
            datetime.fromisoformat(str(item["start_time"]).replace("Z", "+00:00")),
            -datetime.fromisoformat(str(item["end_time"]).replace("Z", "+00:00")).timestamp(),
            -int(item["id"]),
        ),
    )[0]


def action_for_invalid_binding(*, profile_id: str, period: str, replacement: dict[str, Any] | None) -> str:
    if profile_id == "live_observation_v1" and period in LIVE_TABLES_ONLY_PERIODS:
        return "deactivate"
    return "replace" if replacement is not None else "deactivate"


def _path(market_file: MarketDataFile) -> Path:
    raw = Path(market_file.file_path)
    return raw if raw.is_absolute() else PROJECT_ROOT / raw


def _file_evidence(session: Any, market_file: MarketDataFile, cache: dict[int, dict[str, Any]]) -> dict[str, Any]:
    if market_file.id in cache:
        return cache[market_file.id]
    path = _path(market_file)
    exists = path.is_file()
    checksum_actual = sha256_file(path) if exists else None
    source_interval, source_interval_basis = resolve_source_interval(session, market_file, project_root=PROJECT_ROOT)
    row = {
        "id": int(market_file.id),
        "provider": market_file.provider,
        "data_role": market_file.data_role,
        "quality_status": market_file.quality_status,
        "start_time": market_file.start_time.isoformat(),
        "end_time": market_file.end_time.isoformat(),
        "data_version": market_file.data_version,
        "checksum": market_file.checksum,
        "checksum_actual": checksum_actual,
        "physical_ok": bool(exists and market_file.checksum and checksum_actual == market_file.checksum),
        "source_interval": source_interval,
        "source_interval_basis": source_interval_basis,
    }
    cache[market_file.id] = row
    return row


def _binding_snapshot(binding: ProfileActiveBinding) -> dict[str, Any]:
    return {
        "id": int(binding.id),
        "profile_id": binding.profile_id,
        "instrument_symbol": binding.instrument_symbol,
        "contract_code": binding.contract_code,
        "contract_role": binding.contract_role,
        "period": binding.period,
        "data_version": binding.data_version,
        "market_data_file_id": binding.market_data_file_id,
        "binding_status": binding.binding_status,
        "activated_at": binding.activated_at.isoformat() if binding.activated_at else None,
        "superseded_at": binding.superseded_at.isoformat() if binding.superseded_at else None,
    }


def _candidate_rows(session: Any, binding: ProfileActiveBinding, cache: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    files = session.scalars(
        select(MarketDataFile).where(
            MarketDataFile.instrument_symbol == binding.instrument_symbol,
            MarketDataFile.contract_code == binding.contract_code,
            MarketDataFile.period == binding.period,
            MarketDataFile.provider.in_(sorted(ALLOWED_PROVIDERS)),
            MarketDataFile.data_role == "primary",
            MarketDataFile.quality_status == "passed",
        )
    )
    return [_file_evidence(session, item, cache) for item in files]


def _invalid_reason(file_row: dict[str, Any] | None) -> str | None:
    if file_row is None:
        return "market_data_file_missing"
    if file_row["provider"] not in ALLOWED_PROVIDERS:
        return "provider_blocked"
    if file_row["data_role"] != "primary":
        return f"data_role={file_row['data_role']}"
    if file_row["quality_status"] != "passed":
        return f"quality_status={file_row['quality_status']}"
    if not file_row["physical_ok"]:
        return "physical_or_checksum_invalid"
    if not file_row["source_interval"]:
        return "source_interval_unresolved"
    return None


def build_plan(session: Any) -> dict[str, Any]:
    revisions = [row[0] for row in session.execute(text("select version_num from alembic_version order by version_num"))]
    if revisions != [EXPECTED_ALEMBIC]:
        raise CloseoutError(f"unexpected alembic revision: {revisions}")
    cache: dict[int, dict[str, Any]] = {}
    active = list(
        session.scalars(
            select(ProfileActiveBinding)
            .where(
                ProfileActiveBinding.profile_id.in_(PROFILES),
                ProfileActiveBinding.binding_status == "active",
            )
            .order_by(
                ProfileActiveBinding.profile_id,
                ProfileActiveBinding.instrument_symbol,
                ProfileActiveBinding.contract_code,
                ProfileActiveBinding.period,
                ProfileActiveBinding.id,
            )
        )
    )
    operations: list[dict[str, Any]] = []
    for binding in active:
        market_file = session.get(MarketDataFile, binding.market_data_file_id) if binding.market_data_file_id else None
        file_row = _file_evidence(session, market_file, cache) if market_file is not None else None
        reason = _invalid_reason(file_row)
        if reason is None:
            continue
        replacement = select_replacement(
            current=file_row or {"start_time": "0001-01-01T00:00:00", "end_time": "9999-12-31T00:00:00"},
            candidates=_candidate_rows(session, binding, cache),
        )
        action = action_for_invalid_binding(
            profile_id=binding.profile_id,
            period=binding.period,
            replacement=replacement,
        )
        operations.append(
            {
                "action": action,
                "reason": reason,
                "profile_id": binding.profile_id,
                "instrument_symbol": binding.instrument_symbol,
                "contract_code": binding.contract_code,
                "contract_role": binding.contract_role,
                "period": binding.period,
                "binding_id": int(binding.id),
                "current_file_id": binding.market_data_file_id,
                "target_file_id": int(replacement["id"]) if action == "replace" and replacement else None,
                "target_data_version": replacement["data_version"] if action == "replace" and replacement else None,
                "before": _binding_snapshot(binding),
            }
        )

    actual = session.get(MarketDataFile, ACTUAL_FILE_ID)
    if actual is None:
        raise CloseoutError(f"JM2609 actual 1m file {ACTUAL_FILE_ID} is missing")
    actual_row = _file_evidence(session, actual, cache)
    if (
        actual.instrument_symbol != "jm"
        or actual.contract_code != "JM2609"
        or actual.period != "1m"
        or _invalid_reason(actual_row) is not None
    ):
        raise CloseoutError(f"JM2609 actual 1m asset is ineligible: {actual_row}")
    for profile_id in ACTUAL_PROFILES:
        existing = session.scalar(
            select(ProfileActiveBinding).where(
                ProfileActiveBinding.profile_id == profile_id,
                ProfileActiveBinding.instrument_symbol == "jm",
                ProfileActiveBinding.contract_code == "JM2609",
                ProfileActiveBinding.period == "1m",
                ProfileActiveBinding.binding_status == "active",
            )
        )
        if existing is None:
            operations.append(
                {
                    "action": "add",
                    "reason": "formal_actual_1m_binding_missing",
                    "profile_id": profile_id,
                    "instrument_symbol": "jm",
                    "contract_code": "JM2609",
                    "contract_role": "actual_contract",
                    "period": "1m",
                    "binding_id": None,
                    "current_file_id": None,
                    "target_file_id": ACTUAL_FILE_ID,
                    "target_data_version": actual.data_version,
                    "before": None,
                }
            )
        elif existing.market_data_file_id != ACTUAL_FILE_ID:
            raise CloseoutError(f"unexpected active actual 1m binding for {profile_id}: {existing.market_data_file_id}")

    operations.sort(key=lambda row: (row["profile_id"], row["instrument_symbol"], row["contract_code"], row["period"], row["action"]))
    return {
        "task_id": TASK_ID,
        "alembic_revision": revisions[0],
        "operation_count": len(operations),
        "plan_sha256": plan_digest(operations),
        "operations": operations,
        "writes": ["profile_active_bindings"],
        "writes_parquet": False,
        "writes_quality_reports": False,
        "calls_rqdata": False,
    }


def snapshot_no_touch(session: Any) -> dict[str, Any]:
    return dict(
        session.execute(
            text(
                """
                select
                  (select count(*) from market_data_files) as market_data_files,
                  (select count(*) from data_quality_reports) as data_quality_reports,
                  (select count(*) from backtest_reports) as backtest_reports,
                  (select count(*) from signal_scan_tasks) as signal_scan_tasks,
                  (select count(*) from strategy_signals) as strategy_signals,
                  (select count(*) from signal_events) as signal_events,
                  (select count(*) from review_notes) as review_notes,
                  (select count(*) from live_minute_bars) as live_minute_bars,
                  (select count(*) from live_aggregated_bars) as live_aggregated_bars,
                  (select md5(to_jsonb(t)::text) from backtest_reports t where id=14) as report14_md5
                """
            )
        ).mappings().one()
    )


def compare_no_touch(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    diffs = {key: {"before": before[key], "after": after[key]} for key in sorted(before) if before[key] != after[key]}
    return {"status": "passed" if not diffs else "failed", "diffs": diffs}


def apply_plan(session: Any, plan: dict[str, Any]) -> list[dict[str, Any]]:
    registry = DataProfileRegistry(session)
    ledger: list[dict[str, Any]] = []
    for operation in plan["operations"]:
        action = operation["action"]
        old = session.get(ProfileActiveBinding, operation["binding_id"]) if operation["binding_id"] else None
        if action == "deactivate":
            if old is None or old.binding_status != "active":
                raise CloseoutError(f"binding drift before deactivate: {operation['binding_id']}")
            old.binding_status = "superseded"
            old.superseded_at = datetime.now().astimezone()
            new_id = None
        else:
            target = session.get(MarketDataFile, operation["target_file_id"])
            if target is None or target.data_version != operation["target_data_version"]:
                raise CloseoutError(f"target file drift: {operation['target_file_id']}")
            if action == "replace" and (old is None or old.binding_status != "active"):
                raise CloseoutError(f"binding drift before replace: {operation['binding_id']}")
            new = registry.switch_active_binding(
                profile_id=operation["profile_id"],
                instrument_symbol=operation["instrument_symbol"],
                contract_code=operation["contract_code"],
                contract_role=operation["contract_role"],
                period=operation["period"],
                data_version=operation["target_data_version"],
                market_data_file_id=operation["target_file_id"],
            )
            new_id = int(new.id)
        ledger.append({**operation, "new_binding_id": new_id})
    session.flush()
    return ledger


def duplicate_active_groups(session: Any) -> int:
    return int(
        session.execute(
            text(
                """
                select count(*) from (
                  select profile_id, instrument_symbol, contract_code, period
                  from profile_active_bindings where binding_status='active'
                  group by 1,2,3,4 having count(*) > 1
                ) duplicates
                """
            )
        ).scalar_one()
    )


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [key for row in rows for key in row if key != "before"]
    fields = list(dict.fromkeys(fields))
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def execute_plan(*, expected_sha: str, expected_count: int) -> dict[str, Any]:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as session:
        session.execute(text("select pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        before = snapshot_no_touch(session)
        plan = build_plan(session)
        if plan["plan_sha256"] != expected_sha or plan["operation_count"] != expected_count:
            raise CloseoutError("frozen plan hash/count drifted; refusing apply")
        ledger = apply_plan(session, plan)
        remaining = build_plan(session)
        if remaining["operation_count"] != 0:
            raise CloseoutError(f"post-apply reconcile still has {remaining['operation_count']} operations")
        if duplicate_active_groups(session) != 0:
            raise CloseoutError("duplicate active bindings detected")
        after = snapshot_no_touch(session)
        no_touch = compare_no_touch(before, after)
        if no_touch["status"] != "passed":
            raise CloseoutError(f"protected historical state changed: {no_touch['diffs']}")
        rollback = {"task_id": TASK_ID, "plan_sha256": expected_sha, "ledger": ledger}
        write_json(EVIDENCE_DIR / "rollback_evidence.json", rollback)
        session.commit()
    result = {
        "status": "applied",
        "plan_sha256": expected_sha,
        "operation_count": expected_count,
        "duplicate_active_groups": 0,
        "no_touch": no_touch,
    }
    write_json(EVIDENCE_DIR / "apply_verify.json", result)
    return result


def verify_current() -> dict[str, Any]:
    with SessionLocal() as session:
        plan = build_plan(session)
        result = {
            "status": "passed" if plan["operation_count"] == 0 and duplicate_active_groups(session) == 0 else "failed",
            "remaining_operation_count": plan["operation_count"],
            "duplicate_active_groups": duplicate_active_groups(session),
            "report14_md5": snapshot_no_touch(session)["report14_md5"],
        }
        session.rollback()
    write_json(EVIDENCE_DIR / "verify.json", result)
    return result


def rollback(*, expected_sha: str) -> dict[str, Any]:
    evidence = json.loads((EVIDENCE_DIR / "rollback_evidence.json").read_text(encoding="utf-8"))
    if evidence.get("plan_sha256") != expected_sha:
        raise CloseoutError("rollback plan SHA mismatch")
    with SessionLocal() as session:
        session.execute(text("select pg_advisory_xact_lock(:key)"), {"key": LOCK_KEY})
        for row in reversed(evidence["ledger"]):
            if row.get("new_binding_id"):
                new = session.get(ProfileActiveBinding, row["new_binding_id"])
                if new is not None:
                    session.delete(new)
            before = row.get("before")
            if before:
                old = session.get(ProfileActiveBinding, before["id"])
                if old is None:
                    raise CloseoutError(f"rollback binding missing: {before['id']}")
                old.binding_status = before["binding_status"]
                old.superseded_at = datetime.fromisoformat(before["superseded_at"]) if before["superseded_at"] else None
        session.flush()
        if duplicate_active_groups(session) != 0:
            raise CloseoutError("rollback would create duplicate active bindings")
        session.commit()
    result = {"status": "rolled_back", "plan_sha256": expected_sha}
    write_json(EVIDENCE_DIR / "rollback_verify.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply", "verify", "rollback"))
    parser.add_argument("--expected-plan-sha")
    parser.add_argument("--expected-operation-count", type=int)
    args = parser.parse_args(argv)
    if args.mode == "plan":
        with SessionLocal() as session:
            session.execute(text("set transaction read only"))
            result = build_plan(session)
            result["no_touch_before"] = snapshot_no_touch(session)
            session.rollback()
        EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
        write_json(EVIDENCE_DIR / "binding_reconcile_plan.json", result)
        write_csv(EVIDENCE_DIR / "binding_reconcile_plan.csv", result["operations"])
    elif args.mode == "apply":
        if not args.expected_plan_sha or args.expected_operation_count is None:
            parser.error("apply requires --expected-plan-sha and --expected-operation-count")
        result = execute_plan(expected_sha=args.expected_plan_sha, expected_count=args.expected_operation_count)
    elif args.mode == "rollback":
        if not args.expected_plan_sha:
            parser.error("rollback requires --expected-plan-sha")
        result = rollback(expected_sha=args.expected_plan_sha)
    else:
        result = verify_current()
    console_result = result
    if args.mode == "plan":
        console_result = {key: value for key, value in result.items() if key != "operations"}
    print(json.dumps(console_result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("status") not in {"failed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
