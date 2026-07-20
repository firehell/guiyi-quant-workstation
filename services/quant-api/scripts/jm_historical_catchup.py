"""Preflight, verify, and apply the JM-only S6-03 historical catch-up."""

from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import text


REPO_ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]
QUANT_CORE_ROOT = REPO_ROOT / "packages/quant-core"
for import_root in (SERVICE_ROOT, QUANT_CORE_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

from app.db.session import SessionLocal  # noqa: E402
from app.services.rqdata_ingest.client import RqDataClient  # noqa: E402
from app.services.rqdata_ingest.jm_historical_catchup import (  # noqa: E402
    TradingDayState,
    build_gap_plan,
    build_s6_03_approval_packet,
    latest_completed_week_end,
    resolve_latest_completed_trading_day,
)
from app.services.rqdata_ingest.jm_historical_catchup_execution import (  # noqa: E402
    ACTUAL_DIRECT_PERIODS,
    CONTINUOUS_DIRECT_PERIODS,
    S603ExecutionError,
    active_baseline_start,
    active_end_map,
    build_execution_approval_packet,
    build_execution_artifact_plan,
    collect_database_state,
    collect_provider_reference_snapshot,
    execute_approved_catchup,
    validate_execution_paths_create_only,
)
from app.services.trading_session_clock import TradingSessionClock  # noqa: E402


TASK_ID = "JM-HISTORICAL-CATCHUP-S6-03"
DEFAULT_OUTPUT_ROOT = Path("/Volumes/扩展盘/guiyi-quant-workstation/data")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    packet = subparsers.add_parser("packet", help="Build a no-I/O foundation packet from a frozen snapshot.")
    packet.add_argument("--snapshot", type=Path, required=True)
    for name in ("preflight", "verify"):
        command = subparsers.add_parser(name)
        command.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
        command.add_argument("--packet", type=Path, required=name == "verify")
        if name == "preflight":
            command.add_argument("--packet-out", type=Path, required=True)
    apply = subparsers.add_parser("apply")
    apply.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    apply.add_argument("--packet", type=Path, required=True)
    apply.add_argument("--approve-hash", required=True)
    apply.add_argument("--run-write", action="store_true")
    apply.add_argument("--confirm-jm-only", action="store_true")
    return parser


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise S603ExecutionError(f"json_object_required:{path.name}")
    return payload


def _write_object_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise S603ExecutionError(f"output_already_exists:{path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def _day(value: Any) -> date:
    return date.fromisoformat(str(value))


def _gap_from_snapshot(snapshot: Mapping[str, Any]) -> Any:
    active_ends = {
        (str(row["contract"]), str(row["period"]), str(row["source_role"])): _day(row["end"])
        for row in snapshot.get("active_ends", [])
    }
    rank1_mapping = {_day(day): str(contract) for day, contract in dict(snapshot["rank1_mapping"]).items()}
    return build_gap_plan(
        product=str(snapshot.get("product", "jm")),
        trading_days=[_day(day) for day in snapshot["trading_days"]],
        target=_day(snapshot["latest_completed_trading_day"]),
        weekly_target=_day(snapshot["latest_completed_week_end"]),
        active_ends=active_ends,
        rank1_mapping=rank1_mapping,
    )


def _packet_from_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    database_target = str(snapshot["database_target"])
    credential = urlsplit(database_target).password
    if credential and credential != "***":
        raise S603ExecutionError("database_target_must_be_redacted")
    return build_s6_03_approval_packet(
        plan=_gap_from_snapshot(snapshot),
        batch_id=str(snapshot["batch_id"]),
        git_commit=str(snapshot["git_commit"]),
        git_branch=str(snapshot["git_branch"]),
        git_status_sha256=str(snapshot["git_status_sha256"]),
        output_root=Path(str(snapshot["output_root"])),
        output_root_identity=dict(snapshot["output_root_identity"]),
        database_target=database_target,
        database_identity=dict(snapshot["database_identity"]),
        binding_snapshot_sha256=str(snapshot["binding_snapshot_sha256"]),
        metadata_snapshot_sha256=str(snapshot["metadata_snapshot_sha256"]),
        calendar_start=_day(snapshot["calendar_start"]),
        calendar_end=_day(snapshot["calendar_end"]),
    )


def _git_value(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _git_facts() -> dict[str, str]:
    status = _git_value("status", "--porcelain=v1", "--untracked-files=all")
    return {
        "git_commit": _git_value("rev-parse", "HEAD"),
        "git_branch": _git_value("branch", "--show-current"),
        "git_status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
    }


def _database_target() -> str:
    value = os.getenv("DATABASE_URL", "postgresql+psycopg://guiyi@127.0.0.1:5432/guiyi_quant")
    parsed = urlsplit(value)
    hostname = parsed.hostname or ""
    port = f":{parsed.port}" if parsed.port else ""
    username = parsed.username or ""
    auth = f"{username}:***@" if parsed.password else (f"{username}@" if username else "")
    return urlunsplit((parsed.scheme, f"{auth}{hostname}{port}", parsed.path, parsed.query, ""))


def _database_identity(session: Any) -> dict[str, Any]:
    row = session.execute(
        text("select current_database(), current_user, inet_server_addr()::text, inet_server_port()")
    ).one()
    return {"database": row[0], "user": row[1], "server": row[2], "port": row[3]}


def _output_root_identity(root: Path) -> dict[str, Any]:
    resolved = root.resolve(strict=True)
    stat = resolved.stat()
    return {"device": stat.st_dev, "inode": stat.st_ino, "path": str(resolved)}


def _frame_dates(frame: pd.DataFrame) -> set[date]:
    if frame is None or frame.empty:
        return set()
    for column in ("trading_date", "trade_date", "date", "datetime", "index"):
        if column not in frame.columns:
            continue
        values = pd.to_datetime(frame[column], errors="coerce").dropna()
        if not values.empty:
            return {value.date() for value in values}
    return set()


def _build_current_packet(*, session: Any, client: RqDataClient, output_root: Path) -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Shanghai")).replace(tzinfo=None)
    calendar_start = now.date() - timedelta(days=35)
    calendar_end = now.date() + timedelta(days=7)
    provider_trading_days = sorted(set(client.trading_dates(calendar_start, calendar_end)))
    provider_final_days = _frame_dates(client.main_price("jm", calendar_start, now.date(), "1d"))
    clock = TradingSessionClock(session)
    trading_set = set(provider_trading_days)
    calendar: list[TradingDayState] = []
    current = calendar_start
    while current <= calendar_end:
        calendar.append(
            TradingDayState(
                day=current,
                is_trading_day=current in trading_set,
                final_close_at=clock.final_close_at(current, product="jm", exchange="DCE") if current in trading_set else None,
            )
        )
        current += timedelta(days=1)
    target = resolve_latest_completed_trading_day(calendar=calendar, now=now, provider_final_days=provider_final_days)
    weekly_target = latest_completed_week_end(calendar, target=target)
    mapping_start = min(day for day in provider_trading_days if day >= calendar_start and day <= target)
    preliminary = collect_provider_reference_snapshot(
        client,
        calendar_start=calendar_start,
        calendar_end=calendar_end,
        mapping_start=mapping_start,
        target=target,
    )
    actual_contract = str(preliminary["actual_contract"])
    database_state = collect_database_state(session, actual_contract=actual_contract)
    relevant_days = [day for day in provider_trading_days if mapping_start <= day <= target]
    rank1_mapping = {
        date.fromisoformat(row["trade_date"]): str(row["contract_code"])
        for row in preliminary["rank1_mapping"]
    }
    gap = build_gap_plan(
        product="jm",
        trading_days=relevant_days,
        target=target,
        weekly_target=weekly_target,
        active_ends=active_end_map(database_state),
        rank1_mapping=rank1_mapping,
    )
    if gap.status == "up_to_date":
        raise S603ExecutionError("up_to_date")
    if any(item.contract not in {"jm.MAIN", actual_contract} for item in gap.items):
        raise S603ExecutionError("multiple_actual_contract_segments_not_supported")
    continuous_gap = min(item.start for item in gap.items if item.contract == "jm.MAIN")
    actual_gap = min(item.start for item in gap.items if item.contract == actual_contract)
    continuous_start = active_baseline_start(session, contract="jm.MAIN", periods=CONTINUOUS_DIRECT_PERIODS)
    actual_start = active_baseline_start(session, contract=actual_contract, periods=ACTUAL_DIRECT_PERIODS)
    git = _git_facts()
    batch_id = f"s6_03_{target:%Y%m%d}_{git['git_commit'][:8]}"
    execution = build_execution_artifact_plan(
        output_root=output_root,
        batch_id=batch_id,
        target=target,
        continuous_start=continuous_start,
        actual_contract=actual_contract,
        actual_start=actual_start,
        continuous_gap_start=continuous_gap,
        actual_gap_start=actual_gap,
        weekly_target=weekly_target,
    )
    validate_execution_paths_create_only(
        {
            "product": "jm",
            "files": [
                *[row["canonical_path"] for row in execution["bars"]],
                *[row["raw_path"] for row in execution["bars"] if row["raw_path"]],
                execution["manifest_path"],
                str(Path(execution["audit_root"]) / "quality_gate.json"),
                str(Path(execution["audit_root"]) / "final_audit.json"),
                str(Path(execution["audit_root"]) / "completion_receipt.json"),
            ],
        }
    )
    return build_execution_approval_packet(
        gap_plan=gap,
        execution_plan=execution,
        reference_snapshot=preliminary,
        binding_snapshot=database_state["binding_snapshot"],
        git_commit=git["git_commit"],
        git_branch=git["git_branch"],
        git_status_sha256=git["git_status_sha256"],
        output_root=output_root,
        output_root_identity=_output_root_identity(output_root),
        database_target=_database_target(),
        database_identity=_database_identity(session),
        metadata_snapshot_sha256=database_state["metadata_sha256"],
        calendar_start=calendar_start,
        calendar_end=calendar_end,
    )


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "packet":
        print(json.dumps(_packet_from_snapshot(_read_object(args.snapshot)), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "apply" and (not args.run_write or not args.confirm_jm_only):
        raise S603ExecutionError("apply_requires_run_write_and_confirm_jm_only")
    approved = _read_object(args.packet) if args.command in {"verify", "apply"} else None
    if approved is not None:
        audit_root = Path(str(approved.get("execution_plan", {}).get("audit_root", "")))
        receipt_path = audit_root / "completion_receipt.json"
        if audit_root != Path(".") and receipt_path.is_file():
            receipt = _read_object(receipt_path)
            if receipt.get("packet_hash") != approved.get("packet_hash") or receipt.get("status") != "completed":
                raise S603ExecutionError("completion_receipt_mismatch")
            print(
                json.dumps(
                    {
                        "status": "already_completed",
                        "writes_performed": False,
                        "packet_hash": approved["packet_hash"],
                        "receipt_path": str(receipt_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
    output_root = args.output_root.resolve(strict=True)
    client = RqDataClient(load_env_file=False)
    with SessionLocal() as session:
        current_packet = _build_current_packet(session=session, client=client, output_root=output_root)
        if args.command == "preflight":
            _write_object_create_only(args.packet_out, current_packet)
            payload = {
                "status": "approval_required",
                "writes_performed": False,
                "packet_path": str(args.packet_out),
                "packet_hash": current_packet["packet_hash"],
                "bound_facts": current_packet["bound_facts"],
            }
        else:
            assert approved is not None
            if args.command == "verify":
                from app.services.rqdata_ingest.jm_historical_catchup import verify_approval_packet

                verify_approval_packet(approved, current_facts=current_packet["bound_facts"])
                payload = {"status": "verified", "writes_performed": False, "packet_hash": approved["packet_hash"]}
            else:
                payload = execute_approved_catchup(
                    session=session,
                    client=client,
                    packet=approved,
                    approval_hash=args.approve_hash,
                    current_facts=current_packet["bound_facts"],
                    output_root=output_root,
                    project_root=REPO_ROOT,
                )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
