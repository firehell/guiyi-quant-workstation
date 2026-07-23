"""JM 盘后归档受控入口（hash-bound approval packet）。

模式：
- 默认 / 无 ``--run-write``：dry-run，不建 client、不写库/文件
- ``--prepare-packet``：根据 T3 receipt 生成批准包
- ``--run-write`` + 环境开关 + ``--confirm-after-market-archive`` + packet/hash/receipt：真实归档

核心逻辑在 ``app.services.after_market_*``；禁止绕过 approval。
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Controlled JM after-market archive")
    parser.add_argument("--trading-day", type=date.fromisoformat, required=True)
    parser.add_argument("--product", default="jm", choices=("jm",))
    parser.add_argument("--output-root", type=Path, default=PROJECT_ROOT / "data")
    parser.add_argument("--run-write", action="store_true")
    parser.add_argument("--confirm-after-market-archive", action="store_true")
    parser.add_argument("--prepare-packet", action="store_true")
    parser.add_argument("--packet-out", type=Path)
    parser.add_argument("--t3-receipt", type=Path)
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--wait-provider-ready", action="store_true")
    parser.add_argument("--provider-ready-poll-seconds", type=float, default=60)
    parser.add_argument("--provider-ready-timeout-seconds", type=float, default=14400)
    parser.add_argument("--provider-stability-checks", type=int, default=2)
    parser.add_argument("--provider-stability-interval-seconds", type=float, default=30)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None, *, environ: Mapping[str, str] | None = None) -> int:
    """盘后归档主流程：prepare-packet / dry-run / 受控真实写入三选一。"""
    args = parse_args(argv)
    source_env = environ if environ is not None else os.environ
    enabled = str(source_env.get("GUIYI_AFTER_MARKET_ARCHIVE_ENABLED") or "").lower() in {"1", "true", "yes", "on"}
    if args.prepare_packet:
        if args.packet_out is None or args.t3_receipt is None:
            print(json.dumps({"status": "blocked", "reason": "packet_out_and_t3_receipt_required"}, ensure_ascii=False))
            return 2
        try:
            return _prepare_packet(args)
        except Exception as exc:  # noqa: BLE001 - prepare must fail without leaking credentials.
            payload, exit_code = _prepare_failure_result(exc)
            print(json.dumps(payload, ensure_ascii=False))
            return exit_code
    if not args.run_write:
        print(
            json.dumps(
                {
                    "mode": "dry-run",
                    "product": args.product,
                    "trading_day": args.trading_day.isoformat(),
                    "output_root": str(args.output_root),
                    "enabled": enabled,
                    "would_construct_rqdata_client": False,
                    "would_open_database": False,
                    "would_write_database": False,
                    "would_write_parquet": False,
                    "would_register_primary": False,
                    "would_send_notification": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if not enabled or not args.confirm_after_market_archive or args.approval_packet is None or not args.approval_hash or args.t3_receipt is None:
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "enabled": enabled,
                    "confirmation": args.confirm_after_market_archive,
                    "approval_present": args.approval_packet is not None and bool(args.approval_hash),
                    "t3_receipt_present": args.t3_receipt is not None,
                },
                ensure_ascii=False,
            )
        )
        return 2

    try:
        from app.db.session import SessionLocal
        from app.services.after_market_archive_gate import (
            _recover_committed_archive,
            collect_archive_packet,
            execute_archive,
            validate_approval_packet,
        )
        from app.services.rqdata_ingest.client import RqDataClient
        from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

        approved = _read_object(args.approval_packet)
        packet_hash = str(approved.get("packet_hash") or "")
        if args.approval_hash != packet_hash:
            raise RuntimeError("approval_hash_mismatch")
        if canonical_packet_hash(approved) != packet_hash:
            raise RuntimeError("packet_hash_invalid")
        validate_approval_packet(approved, output_root=args.output_root)
        execution = approved.get("execution_plan") or {}
        receipt_path = Path(str(execution.get("audit_root") or "")) / "completion_receipt.json"
        if receipt_path.is_file():
            receipt = _read_object(receipt_path)
            if receipt.get("packet_hash") != approved.get("packet_hash"):
                raise RuntimeError("completion_receipt_mismatch")
            print(json.dumps({"status": "already_archived", "writes_performed": False, "receipt_path": str(receipt_path)}, ensure_ascii=False, indent=2))
            return 0
        with SessionLocal() as session:
            recovered = _recover_committed_archive(session, packet=approved, project_root=PROJECT_ROOT)
            if recovered is not None:
                print(json.dumps(recovered, ensure_ascii=False, indent=2, default=str))
                return 0
            client = RqDataClient(load_env_file=True)
            current = collect_archive_packet(
                session=session,
                client=client,
                output_root=args.output_root,
                trading_day=args.trading_day,
                now=datetime.now(UTC),
                git_identity=_git_identity(),
                database_identity=_database_identity(session),
                t3_receipt=_read_object(args.t3_receipt),
                readiness_poll_seconds=args.provider_ready_poll_seconds,
                provider_stability_checks=args.provider_stability_checks,
                provider_stability_interval_seconds=args.provider_stability_interval_seconds,
            )
            result = execute_archive(
                session,
                client=client,
                packet=approved,
                approval_hash=args.approval_hash,
                current_packet=current,
                output_root=args.output_root,
                project_root=PROJECT_ROOT,
            )
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0 if result["status"] in {"success", "already_archived"} else 1
    except Exception as exc:  # noqa: BLE001 - CLI must return a bounded failure.
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}, ensure_ascii=False))
        return 1


def _prepare_packet(args: argparse.Namespace) -> int:
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.after_market_archive_gate import collect_archive_packet
    from app.services.rqdata_ingest.client import RqDataClient

    assert args.packet_out is not None and args.t3_receipt is not None
    client = RqDataClient(load_env_file=True)
    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        packet = collect_archive_packet(
            session,
            client=client,
            output_root=args.output_root,
            trading_day=args.trading_day,
            now=datetime.now(UTC),
            git_identity=_git_identity(),
            database_identity=_database_identity(session),
            t3_receipt=_read_object(args.t3_receipt),
            readiness_timeout_seconds=(args.provider_ready_timeout_seconds if args.wait_provider_ready else 0),
            readiness_poll_seconds=args.provider_ready_poll_seconds,
            provider_stability_checks=args.provider_stability_checks,
            provider_stability_interval_seconds=args.provider_stability_interval_seconds,
        )
        session.rollback()
    output = args.packet_out.resolve(strict=False)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite approval packet: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(packet, ensure_ascii=False, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps({"status": "approval_required", "packet": str(output), "packet_hash": packet["packet_hash"]}, ensure_ascii=False))
    return 0


def _read_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"json object required: {path}")
    return payload


def _prepare_failure_result(exc: Exception) -> tuple[dict[str, str], int]:
    from app.services.after_market_archive_gate import ArchiveGateError
    from app.services.provider_readiness import ProviderReadinessError

    reason = str(exc).split(":", 1)[0]
    if isinstance(exc, ArchiveGateError) and reason == "trading_day_not_closed":
        return {"status": "TRADING_DAY_NOT_CLOSED", "reason": reason}, 3
    if isinstance(exc, ProviderReadinessError) and reason in {
        "provider_data_pending",
        "provider_data_stale",
        "provider_readiness_timeout",
    }:
        return {"status": "PROVIDER_FINAL_PENDING", "reason": reason}, 3
    return {"status": "failed", "error_type": type(exc).__name__}, 1


def _git_identity() -> dict[str, str]:
    def value(*args: str) -> str:
        return subprocess.run(("git", *args), cwd=PROJECT_ROOT, check=True, capture_output=True, text=True).stdout.strip()

    status = value("status", "--porcelain=v1", "--untracked-files=no")
    return {
        "commit": value("rev-parse", "HEAD"),
        "branch": value("branch", "--show-current"),
        "tracked_status_sha256": hashlib.sha256(status.encode()).hexdigest(),
    }


def _database_identity(session) -> dict:
    url = session.get_bind().url
    return {"driver": url.drivername, "host": url.host, "port": url.port, "database": url.database}


if __name__ == "__main__":
    raise SystemExit(main())
