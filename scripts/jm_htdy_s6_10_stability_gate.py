#!/usr/bin/env python3
"""Prepare and operate the hash-bound HTDY S6-10 stability Gate.

No command in this CLI sends WeCom messages or creates orders/trades.  The
write-capable modes require both the exact parent hash and the separately
approved aggregate Approval C bundle hash.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import subprocess
import sys
from typing import Any, Mapping
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_ROOT = PROJECT_ROOT / "services" / "quant-api"
CORE_ROOT = PROJECT_ROOT / "packages" / "quant-core"
for root in (API_ROOT, CORE_ROOT, PROJECT_ROOT):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from app.services.htdy_s6_10_stability import (  # noqa: E402
    HtDyS610Error,
    HtDyS610Ledger,
    HtDyS610Observer,
    build_parent_packet,
    canonical_hash,
    publish_json_create_only,
    verify_ledger,
    verify_approval_c_bundle,
    verify_parent_packet,
)


BACKUP_ROOT = Path("/Volumes/扩展盘/GuiyiBackup")
HIGH_RISK_MODES = {
    "calendar-apply",
    "start",
    "inject-fault",
    "finalize",
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HTDY S6-10 five-day Gate")
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in (
        "prepare",
        "verify",
        "calendar-apply",
        "start",
        "sample",
        "seal-day",
        "inject-fault",
        "finalize",
        "stop",
    ):
        sub = subparsers.add_parser(mode)
        _common_arguments(sub)
    return parser.parse_args(argv)


def _common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--parent-packet", type=Path, required=True)
    parser.add_argument("--approval-hash")
    parser.add_argument("--approval-c-bundle", type=Path)
    parser.add_argument("--approval-c-hash")
    parser.add_argument("--approval-c-receipt", type=Path)
    parser.add_argument("--approval-c-signature", type=Path)
    parser.add_argument("--approval-c-approved-signers", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--source-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--backup-receipt", type=Path)
    parser.add_argument("--restore-receipt", type=Path)
    parser.add_argument("--s6-07-receipt", type=Path)
    parser.add_argument("--s6-08-receipt", type=Path)
    parser.add_argument("--s6-09-receipt", type=Path)
    parser.add_argument("--runtime-launchd", type=Path)
    parser.add_argument("--observer-launchd", type=Path)
    parser.add_argument("--deployment-packet", type=Path)
    parser.add_argument("--s6-07-rebind-packet", type=Path)
    parser.add_argument("--s6-07-enable-packet", type=Path)
    parser.add_argument("--fault-schedule-json", type=Path)
    parser.add_argument("--trading-days", nargs=5)
    parser.add_argument("--trading-day")
    parser.add_argument("--fault")
    parser.add_argument("--fault-duration-seconds", type=int, default=60)
    parser.add_argument("--status", choices=("passed", "failed"))


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.mode in HIGH_RISK_MODES:
            if not args.approval_hash:
                raise HtDyS610Error("approval_hash_required")
            _verify_approval_c(args)
        if args.mode == "prepare":
            result = _prepare(args)
        elif args.mode == "verify":
            result = _verify(args)
        elif args.mode == "calendar-apply":
            result = _calendar_apply(args)
        elif args.mode == "start":
            result = _start(args)
        elif args.mode == "sample":
            result = _sample(args)
        elif args.mode == "seal-day":
            result = _seal_day(args)
        elif args.mode == "inject-fault":
            result = _inject_fault(args)
        elif args.mode == "finalize":
            result = _finalize(args)
        else:
            result = _stop(args)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:  # noqa: BLE001 - bounded fail-closed CLI.
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "reason": _safe_reason(exc),
                    "writes_authorized": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2


def _filesystem_mount(path: Path) -> Path:
    current = path.resolve(strict=True)
    while not os.path.ismount(current):
        if current.parent == current:
            raise HtDyS610Error("backup_filesystem_mount_invalid")
        current = current.parent
    return current


def collect_backup_root_facts(path: Path) -> dict[str, Any]:
    """Require the explicit S6-10 same-volume snapshot root."""

    if not path.is_dir() or path.is_symlink():
        raise HtDyS610Error("backup_root_missing")
    resolved = path.resolve(strict=True)
    if resolved != BACKUP_ROOT.resolve(strict=True):
        raise HtDyS610Error("backup_root_identity_invalid")
    filesystem_mount = _filesystem_mount(resolved)
    if filesystem_mount == Path(filesystem_mount.anchor):
        raise HtDyS610Error("backup_filesystem_mount_invalid")
    source_device = PROJECT_ROOT.stat().st_dev
    backup_device = resolved.stat().st_dev
    if source_device != backup_device:
        raise HtDyS610Error("backup_root_not_same_device")
    free_bytes = shutil.disk_usage(path).free
    if free_bytes < 10 * 1024**3:
        raise HtDyS610Error("backup_root_space_insufficient")
    return {
        "path": str(resolved),
        "filesystem_mount": str(filesystem_mount),
        "device": backup_device,
        "source_device": source_device,
        "free_bytes": free_bytes,
        "storage_scope": "same_device_snapshot",
        "same_device_snapshot": True,
        "independent_device_backup": False,
        "disaster_recovery_ready": False,
    }


def _prepare(args: argparse.Namespace) -> dict[str, Any]:
    mount = collect_backup_root_facts(BACKUP_ROOT)
    required_paths = {
        "backup_receipt": args.backup_receipt,
        "restore_receipt": args.restore_receipt,
        "s6_07_receipt": args.s6_07_receipt,
        "s6_08_receipt": args.s6_08_receipt,
        "s6_09_receipt": args.s6_09_receipt,
        "runtime_launchd": args.runtime_launchd,
        "observer_launchd": args.observer_launchd,
        "deployment_packet": args.deployment_packet,
        "s6_07_rebind_packet": args.s6_07_rebind_packet,
        "s6_07_enable_packet": args.s6_07_enable_packet,
        "fault_schedule_json": args.fault_schedule_json,
        "approval_c_approved_signers": args.approval_c_approved_signers,
    }
    if args.runtime_root is None:
        raise HtDyS610Error("runtime_root_required")
    for key, path in required_paths.items():
        if path is None or not path.is_file():
            raise HtDyS610Error(f"{key}_missing")
    restore_audit_receipt = validate_backup_restore_receipts(
        args.backup_receipt,
        args.restore_receipt,
    )
    required_paths["restore_audit_receipt"] = restore_audit_receipt
    source_root = args.source_root.resolve(strict=True)
    if _git(source_root, "status", "--porcelain=v1") != "":
        raise HtDyS610Error("source_worktree_not_clean")
    runtime_root = args.runtime_root.resolve(strict=True)
    if _git(
        runtime_root,
        "status",
        "--porcelain=v1",
    ) != "":
        raise HtDyS610Error("runtime_worktree_not_clean")
    generated_at = datetime.now(UTC)
    days = (
        tuple(date.fromisoformat(value) for value in args.trading_days)
        if args.trading_days
        else _next_rqdata_days(generated_at)
    )
    calendar_rows = [
        {
            "trade_date": day.isoformat(),
            "is_trading_day": True,
            "has_night_session": True,
            "provider": "rqdata",
            "night_session_date": _previous_rqdata_trading_day(day).isoformat(),
        }
        for day in days
    ]
    artifact_paths = {
        "runtime_root": str(runtime_root),
        "source_root": str(source_root),
        **{
            key: str(path.resolve(strict=True))
            for key, path in required_paths.items()
        },
    }
    bindings = _collect_prepare_bindings(
        args,
        days=days,
        calendar_rows=calendar_rows,
        artifact_paths=artifact_paths,
    )
    fault_schedule = _load_json(args.fault_schedule_json)
    packet = build_parent_packet(
        trading_days=days,
        generated_at=generated_at,
        bindings=bindings,
        calendar_rows=calendar_rows,
        fault_schedule=fault_schedule,
    )
    if args.parent_packet.resolve(strict=False).parent != (
        args.output_dir.resolve(strict=False)
    ):
        raise HtDyS610Error("parent_packet_output_root_mismatch")
    publish_json_create_only(args.parent_packet, packet)
    bundle = {
        "schema_version": 1,
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "status": "approval_c_required",
        "parent_packet_path": str(args.parent_packet.resolve(strict=False)),
        "parent_packet_hash": packet["packet_hash"],
        "deployment_packet": _packet_identity(
            args.deployment_packet,
        ),
        "s6_07_rebind_packet": _packet_identity(
            args.s6_07_rebind_packet,
        ),
        "s6_07_enable_packet": _packet_identity(
            args.s6_07_enable_packet,
        ),
        "observer_launchd": {
            "path": str(args.observer_launchd.resolve(strict=True)),
            "sha256": _file_hash(args.observer_launchd),
        },
        "fault_schedule": {
            "path": str(args.fault_schedule_json.resolve(strict=True)),
            "sha256": _file_hash(args.fault_schedule_json),
        },
        "approval_challenge": secrets.token_hex(32),
        "backup_mount": mount,
        "deployment_authorized": False,
        "calendar_write_authorized": False,
        "fault_injection_authorized": False,
        "notification_authorized": False,
        "trading_authorized": False,
    }
    bundle["bundle_hash"] = canonical_hash(bundle)
    publish_json_create_only(args.output_dir / "approval_c_bundle.json", bundle)
    return {
        "status": "approval_c_required",
        "HTDY_S6_10_PARENT_PACKET_HASH": packet["packet_hash"],
        "HTDY_S6_10_APPROVAL_BUNDLE_HASH": bundle["bundle_hash"],
        "writes_authorized": False,
    }


def _verify_approval_c(args: argparse.Namespace) -> None:
    if (
        args.approval_c_bundle is None
        or not args.approval_c_hash
        or args.approval_c_receipt is None
        or args.approval_c_signature is None
        or args.approval_c_approved_signers is None
    ):
        raise HtDyS610Error("approval_c_signed_receipt_required")
    packet = _load_json(args.parent_packet)
    verify_approval_c_bundle(
        args.approval_c_bundle,
        approval_c_hash=str(args.approval_c_hash),
        parent_packet=packet,
        parent_packet_path=args.parent_packet,
        approval_receipt_path=args.approval_c_receipt,
        approval_signature_path=args.approval_c_signature,
        approved_signers_path=args.approval_c_approved_signers,
    )


def _verify(args: argparse.Namespace) -> dict[str, Any]:
    packet = _load_json(args.parent_packet)
    approval_hash = args.approval_hash or str(packet.get("packet_hash") or "")
    bindings = _collect_runtime_bindings(args, packet)
    verify_parent_packet(
        packet,
        approval_hash=approval_hash,
        current_bindings=bindings,
        now=datetime.now(UTC),
        allow_started=True,
    )
    verify_ledger(args.output_dir, parent_packet_hash=approval_hash)
    return {
        "status": "verified",
        "parent_packet_hash": approval_hash,
        "writes_authorized": False,
    }


def _calendar_apply(args: argparse.Namespace) -> dict[str, Any]:
    packet = _calendar_preverify(args)
    from sqlalchemy import select

    from app.db.session import SessionLocal
    from app.models.data_center import TradingCalendar

    changes: list[dict[str, Any]] = []
    with SessionLocal() as session:
        for row in packet["calendar_rows"]:
            day = date.fromisoformat(row["trade_date"])
            current = session.scalar(
                select(TradingCalendar).where(
                    TradingCalendar.exchange_code == "DCE",
                    TradingCalendar.trade_date == day,
                )
            )
            old = (
                None
                if current is None
                else {
                    "is_trading_day": current.is_trading_day,
                    "has_night_session": current.has_night_session,
                    "provider": current.provider,
                }
            )
            if current is None:
                current = TradingCalendar(
                    exchange_code="DCE",
                    trade_date=day,
                    is_trading_day=True,
                    has_night_session=True,
                    provider="rqdata",
                    remark="HTDY S6-10 Approval C bounded window",
                )
                session.add(current)
            else:
                current.is_trading_day = True
                current.has_night_session = True
                current.provider = "rqdata"
            changes.append(
                {
                    "trade_date": day.isoformat(),
                    "old": old,
                    "new": {
                        "is_trading_day": True,
                        "has_night_session": True,
                        "provider": "rqdata",
                    },
                }
            )
        session.commit()
    receipt = {
        "schema_version": 1,
        "status": "calendar_window_applied",
        "parent_packet_hash": packet["packet_hash"],
        "changes": changes,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    publish_json_create_only(
        args.output_dir / "calendar_apply_receipt.json",
        receipt,
    )
    return {"status": "calendar_window_applied", "rows": len(changes)}


def _start(args: argparse.Namespace) -> dict[str, Any]:
    packet = _activation_preverify(args)
    paths = dict(packet["bindings"]["artifact_paths"])
    runtime_root = Path(paths["runtime_root"])
    eod_packet = Path(paths["s6_07_enable_packet"])
    eod_payload = _load_json(eod_packet)
    eod_hash = str(eod_payload.get("packet_hash") or "")
    environment = {
        **os.environ,
        "GUIYI_PROJECT_ROOT": str(runtime_root),
        "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
    }
    configured = False
    try:
        _run_checked(
            [
                "bash",
                str(runtime_root / "scripts/configure-htdy-s610-runtime.sh"),
                "--enable",
                "--parent-packet",
                str(args.parent_packet.resolve(strict=True)),
                "--approval-hash",
                str(args.approval_hash),
                "--approval-c-bundle",
                str(args.approval_c_bundle.resolve(strict=True)),
                "--approval-c-hash",
                str(args.approval_c_hash),
                "--approval-c-receipt",
                str(args.approval_c_receipt.resolve(strict=True)),
                "--approval-c-signature",
                str(args.approval_c_signature.resolve(strict=True)),
                "--approval-c-approved-signers",
                str(args.approval_c_approved_signers.resolve(strict=True)),
                "--output-dir",
                str(args.output_dir.resolve(strict=True)),
                "--eod-packet",
                str(eod_packet.resolve(strict=True)),
                "--eod-hash",
                eod_hash,
            ],
            environ=environment,
        )
        configured = True
        _run_checked(
            [
                "bash",
                str(runtime_root / "scripts/install-after-market-scheduler.sh"),
                "--confirm-load",
            ],
            environ=environment,
        )
        _run_checked(
            [
                "bash",
                str(runtime_root / "scripts/install-htdy-s610-observer.sh"),
                "--confirm-load",
            ],
            environ=environment,
        )
        _run_checked(
            [
                "launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/com.guiyi.quant-runtime-scheduler",
            ],
            environ=environment,
        )
        current = _collect_runtime_bindings(
            args,
            packet,
            environ=_runtime_env_values(runtime_root),
        )
        verify_parent_packet(
            packet,
            approval_hash=str(args.approval_hash),
            current_bindings=current,
            now=datetime.now(UTC),
            allow_started=False,
        )
    except Exception:
        _activation_rollback(
            runtime_root=runtime_root,
            environment=environment,
            configured=configured,
        )
        rollback = _collect_runtime_bindings(
            args,
            packet,
            environ=_runtime_env_values(runtime_root),
        )
        if dict(rollback.get("feature_flags") or {}) != {
            "live_runtime": True,
            "signal_events": False,
            "wechat_autosend": False,
            "after_market_automation": False,
        }:
            raise HtDyS610Error("activation_rollback_verification_failed")
        rollback_receipt = {
            "schema_version": 1,
            "status": "activation_rolled_back",
            "parent_packet_hash": packet["packet_hash"],
            "feature_flags": rollback["feature_flags"],
            "rolled_back_at": datetime.now(UTC).isoformat(),
        }
        rollback_receipt["receipt_hash"] = canonical_hash(rollback_receipt)
        publish_json_create_only(
            args.output_dir / "activation_rollback_receipt.json",
            rollback_receipt,
        )
        raise
    marker = {
        "schema_version": 1,
        "status": "observer_start_authorized",
        "parent_packet_hash": packet["packet_hash"],
        "started_at": datetime.now(UTC).isoformat(),
        "wechat_autosend": False,
    }
    publish_json_create_only(args.output_dir / "observer_started.json", marker)
    return {
        "status": "observer_start_authorized",
        "runtime_configuration_changed": True,
    }


def _sample(args: argparse.Namespace) -> dict[str, Any]:
    packet = _verified_packet(args, allow_started=True)
    trading_day = _required_day(args, packet)
    observer = HtDyS610Observer(
        collector=lambda: _collect_observer_facts(packet, trading_day),
        baseline_counts=packet["bindings"]["baseline_counts"],
        baseline_hashes=packet["bindings"]["baseline_hashes"],
        max_event_count=int(packet["max_event_count"]),
    )
    sample = observer.sample()
    facts = dict(sample.get("facts") or {})
    sampled_at = datetime.fromisoformat(str(facts.get("observed_at") or ""))
    if (
        sampled_at.tzinfo is None
        or abs((datetime.now(UTC) - sampled_at.astimezone(UTC)).total_seconds())
        > 5
    ):
        raise HtDyS610Error("observer_sample_time_invalid")
    ledger = HtDyS610Ledger(
        root=args.output_dir,
        parent_packet_hash=str(packet["packet_hash"]),
        night_session_dates=_night_session_dates(packet),
    )
    record = ledger.append_sample(
        trading_day=trading_day,
        sampled_at=sampled_at,
        payload=sample,
    )
    return {
        "status": "sampled",
        "trading_day": trading_day.isoformat(),
        "sequence": record["sequence"],
        "sample_hash": record["sample_hash"],
    }


def _seal_day(args: argparse.Namespace) -> dict[str, Any]:
    packet = _verified_packet(args, allow_started=True)
    trading_day = _required_day(args, packet)
    if args.status is None:
        raise HtDyS610Error("daily_status_required")
    ledger = HtDyS610Ledger(
        root=args.output_dir,
        parent_packet_hash=str(packet["packet_hash"]),
        night_session_dates=_night_session_dates(packet),
    )
    seal = ledger.seal_day(
        trading_day=trading_day,
        status=args.status,
        summary={"verified_at": datetime.now(UTC).isoformat()},
    )
    return {
        "status": "sealed",
        "trading_day": trading_day.isoformat(),
        "seal_hash": seal["seal_hash"],
    }


def _inject_fault(args: argparse.Namespace) -> dict[str, Any]:
    packet = _verified_packet(args, allow_started=True)
    if args.fault is None:
        raise HtDyS610Error("fault_required")
    if not 1 <= args.fault_duration_seconds <= 60:
        raise HtDyS610Error("fault_duration_invalid")
    entries = [
        dict(item)
        for values in packet["fault_schedule"].values()
        for item in values
        if isinstance(item, Mapping) and item.get("fault") == args.fault
    ]
    if len(entries) != 1:
        raise HtDyS610Error("fault_not_authorized")
    entry = entries[0]
    now = datetime.now(UTC)
    slot_start = datetime.fromisoformat(str(entry["slot_start"]))
    slot_end = datetime.fromisoformat(str(entry["slot_end"]))
    if not slot_start <= now <= slot_end:
        raise HtDyS610Error("fault_outside_authorized_slot")
    if args.fault_duration_seconds > int(entry["max_duration_seconds"]):
        raise HtDyS610Error("fault_duration_exceeds_packet")
    from app.services.htdy_s6_10_faults import default_fault_executor

    return default_fault_executor(
        evidence_root=args.output_dir,
        parent_packet_hash=str(packet["packet_hash"]),
    ).execute(
        fault=args.fault,
        duration_seconds=args.fault_duration_seconds,
        target_ip=entry.get("target_ip"),
    )


def _finalize(args: argparse.Namespace) -> dict[str, Any]:
    packet = _verified_packet(args, allow_started=True)
    from app.services.htdy_s6_10_faults import verify_fault_receipts

    verify_ledger(
        args.output_dir,
        parent_packet_hash=str(packet["packet_hash"]),
        expected_trading_days=tuple(
            date.fromisoformat(value) for value in packet["trading_days"]
        ),
        require_passed_seals=True,
        night_session_dates=_night_session_dates(packet),
    )
    seals = sorted((args.output_dir / "daily").glob("*/daily_seal.json"))
    if len(seals) != 5:
        raise HtDyS610Error("five_daily_seals_required")
    loaded = [_load_json(path) for path in seals]
    if any(item.get("status") != "passed" for item in loaded):
        raise HtDyS610Error("daily_seal_not_passed")
    verified_faults = verify_fault_receipts(
        args.output_dir,
        parent_packet_hash=str(packet["packet_hash"]),
    )
    _verify_final_sample(args.output_dir)
    receipt = {
        "schema_version": 1,
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "status": "passed",
        "gate": "HTDY_S6_10_FIVE_DAY_LEDGER_PASSED",
        "parent_packet_hash": packet["packet_hash"],
        "daily_seal_hashes": [item["seal_hash"] for item in loaded],
        "faults": sorted(verified_faults),
        "wechat_autosend": False,
        "notification_ready": False,
        "trading_ready": False,
        "strategy_validated": False,
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    publish_json_create_only(args.output_dir / "final_receipt.json", receipt)
    return {
        "status": "passed",
        "gate": receipt["gate"],
        "receipt_hash": receipt["receipt_hash"],
    }


def _stop(args: argparse.Namespace) -> dict[str, Any]:
    packet = _load_json(args.parent_packet)
    if args.approval_hash and packet.get("packet_hash") != args.approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    paths = dict((packet.get("bindings") or {}).get("artifact_paths") or {})
    runtime_root = Path(str(paths.get("runtime_root") or ""))
    if not runtime_root.is_dir():
        raise HtDyS610Error("runtime_root_unavailable")
    environment = {
        **os.environ,
        "GUIYI_PROJECT_ROOT": str(runtime_root),
        "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
    }
    _run_checked(
        [
            "bash",
            str(runtime_root / "scripts/install-htdy-s610-observer.sh"),
            "--bootout",
        ],
        environ=environment,
    )
    _run_checked(
        [
            "bash",
            str(runtime_root / "scripts/configure-htdy-s610-runtime.sh"),
            "--disable",
        ],
        environ=environment,
    )
    _run_checked(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/com.guiyi.quant-runtime-scheduler",
        ],
        environ=environment,
    )
    marker = {
        "schema_version": 1,
        "status": "observer_stop_requested",
        "parent_packet_hash": packet.get("packet_hash"),
        "stopped_at": datetime.now(UTC).isoformat(),
        "signal_event_disable_required": True,
        "wechat_autosend": False,
    }
    publish_json_create_only(args.output_dir / "observer_stopped.json", marker)
    return marker


def _activation_preverify(args: argparse.Namespace) -> dict[str, Any]:
    packet = _load_json(args.parent_packet)
    if packet.get("packet_hash") != args.approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    current = _collect_runtime_bindings(args, packet)
    flags = dict(current.get("feature_flags") or {})
    if flags != {
        "live_runtime": True,
        "signal_events": False,
        "wechat_autosend": False,
        "after_market_automation": False,
    }:
        raise HtDyS610Error("activation_pre_flags_invalid")
    normalized = dict(current)
    normalized["feature_flags"] = deepcopy(
        packet["bindings"]["feature_flags"]
    )
    verify_parent_packet(
        packet,
        approval_hash=str(args.approval_hash),
        current_bindings=normalized,
        now=datetime.now(UTC),
        allow_started=False,
    )
    return packet


def _calendar_preverify(args: argparse.Namespace) -> dict[str, Any]:
    packet = _load_json(args.parent_packet)
    if packet.get("packet_hash") != args.approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    collector_packet = dict(packet)
    collector_packet["_prepare_allow_missing_calendar"] = True
    current = _collect_runtime_bindings(args, collector_packet)
    flags = dict(current.get("feature_flags") or {})
    if flags != {
        "live_runtime": True,
        "signal_events": False,
        "wechat_autosend": False,
        "after_market_automation": False,
    }:
        raise HtDyS610Error("calendar_pre_flags_invalid")
    current["feature_flags"] = deepcopy(packet["bindings"]["feature_flags"])
    verify_parent_packet(
        packet,
        approval_hash=str(args.approval_hash),
        current_bindings=current,
        now=datetime.now(UTC),
        allow_started=False,
    )
    return packet


def _activation_rollback(
    *,
    runtime_root: Path,
    environment: Mapping[str, str],
    configured: bool,
) -> Path:
    commands = [
        [
            "bash",
            str(runtime_root / "scripts/install-htdy-s610-observer.sh"),
            "--bootout",
        ],
    ]
    if configured:
        commands.extend(
            [
                [
                    "bash",
                    str(runtime_root / "scripts/configure-htdy-s610-runtime.sh"),
                    "--disable",
                ],
                [
                    "bash",
                    str(runtime_root / "scripts/install-after-market-scheduler.sh"),
                    "--disable",
                ],
            ]
        )
    errors = 0
    for command in commands:
        try:
            _run_checked(command, environ=environment)
        except HtDyS610Error:
            errors += 1
    if errors:
        raise HtDyS610Error("activation_rollback_command_failed")


def _run_checked(
    command: list[str],
    *,
    environ: Mapping[str, str],
) -> None:
    try:
        subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
            env=dict(environ),
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HtDyS610Error("runtime_operation_failed") from exc


def _verify_final_sample(output_dir: Path) -> None:
    samples = sorted((output_dir / "daily").glob("*/samples/*.json"))
    if not samples:
        raise HtDyS610Error("final_sample_missing")
    record = _load_json(samples[-1])
    payload = dict(record.get("payload") or {})
    facts = dict(payload.get("facts") or {})
    counts = dict(facts.get("counts") or {})
    htdy = dict(facts.get("htdy") or {})
    if counts.get("signal_notifications") != 2:
        raise HtDyS610Error("final_notification_count_invalid")
    if htdy.get("changed") != 0:
        raise HtDyS610Error("final_signal_changed_invalid")


def _verified_packet(
    args: argparse.Namespace,
    *,
    allow_started: bool,
) -> dict[str, Any]:
    packet = _load_json(args.parent_packet)
    if packet.get("packet_hash") != args.approval_hash:
        raise HtDyS610Error("approval_hash_invalid")
    bindings = _collect_runtime_bindings(args, packet)
    verify_parent_packet(
        packet,
        approval_hash=str(args.approval_hash),
        current_bindings=bindings,
        now=datetime.now(UTC),
        allow_started=allow_started,
    )
    return packet


def _collect_prepare_bindings(
    args: argparse.Namespace,
    *,
    days: tuple[date, ...],
    calendar_rows: list[dict[str, Any]],
    artifact_paths: dict[str, str],
) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.htdy_s6_10_runtime_support import (
        collect_current_bindings,
    )

    target_commit = _git(args.source_root, "rev-parse", "HEAD")
    target_tree = _tree_hash(args.source_root)
    skeleton = {
        "trading_days": [day.isoformat() for day in days],
        "calendar_rows": calendar_rows,
        "_prepare_allow_missing_calendar": True,
        "bindings": {"artifact_paths": artifact_paths},
    }
    with SessionLocal() as session:
        facts = collect_current_bindings(
            session,
            parent_packet=skeleton,
            parent_packet_path=args.parent_packet,
            environ={
                "GUIYI_LIVE_RUNTIME_ENABLED": "true",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": "true",
                "GUIYI_WECHAT_AUTOSEND_ENABLED": "false",
                "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED": "true",
            },
        )
        session.rollback()
    facts["runtime_commit"] = target_commit
    facts["runtime_tree"] = target_tree
    facts["source_commit"] = target_commit
    facts["source_tree"] = target_tree
    facts["runtime_tracked_clean"] = True
    return facts


def _collect_runtime_bindings(
    args: argparse.Namespace,
    packet: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    from app.db.session import SessionLocal
    from app.services.htdy_s6_10_runtime_support import (
        collect_current_bindings,
    )

    with SessionLocal() as session:
        facts = collect_current_bindings(
            session,
            parent_packet=packet,
            parent_packet_path=args.parent_packet,
            environ=environ or os.environ,
        )
        session.rollback()
    return facts


def _runtime_env_values(runtime_root: Path) -> dict[str, str]:
    from dotenv import dotenv_values

    path = Path(
        os.environ.get(
            "GUIYI_RUNTIME_ENV",
            str(
                Path.home()
                / "Library"
                / "Application Support"
                / "GuiyiQuant"
                / "project.env"
            ),
        )
    )
    if not path.is_file():
        raise HtDyS610Error("runtime_env_missing")
    values = dotenv_values(path)
    return {
        str(key): str(value or "")
        for key, value in values.items()
        if key.startswith("GUIYI_")
    }


def _collect_observer_facts(
    packet: Mapping[str, Any],
    trading_day: date,
) -> dict[str, Any]:
    from sqlalchemy import desc, select

    from app.after_market_scheduler import (
        HEARTBEAT_KEY as AFTER_MARKET_HEARTBEAT_KEY,
    )
    from app.core.env import PROJECT_ROOT as API_PROJECT_ROOT
    from app.db.session import SessionLocal
    from app.models.data_center import AfterMarketSchedulerCheckpoint
    from app.models.signal import SignalEvent
    from app.queue import get_redis_connection
    from app.runtime_scheduler import SCHEDULER_HEARTBEAT_KEY
    from app.services.htdy_realtime_evaluator import (
        HtDyRealtimeCandidateEvaluator,
    )
    from app.services.htdy_realtime_snapshot import (
        HtDyRealtimeSnapshotResolver,
    )
    from app.services.htdy_s6_10_runtime_support import (
        _event_fact,
        collect_current_daily_state,
    )

    detected_at = datetime.now(UTC)
    redis_connection = get_redis_connection()
    runtime_heartbeat = _redis_json(
        redis_connection,
        SCHEDULER_HEARTBEAT_KEY,
    )
    eod_heartbeat = _redis_json(
        redis_connection,
        AFTER_MARKET_HEARTBEAT_KEY,
    )
    with SessionLocal() as session:
        state = collect_current_daily_state(
            session,
            parent_packet=packet,
            trading_day=trading_day,
            environ=os.environ,
        )
        snapshot = HtDyRealtimeSnapshotResolver(
            session,
            project_root=API_PROJECT_ROOT,
        ).resolve(trading_day=trading_day, detected_at=detected_at)
        evaluation = HtDyRealtimeCandidateEvaluator().evaluate(
            snapshot,
            detected_at=detected_at,
        )
        latest_event = session.scalar(
            select(SignalEvent)
            .where(
                SignalEvent.source_mode == "live_realtime_repainting",
                SignalEvent.strategy_name
                == "htdy_original_realtime_first_seen",
                SignalEvent.strategy_version == "v1.0",
                SignalEvent.product == "jm",
                SignalEvent.period == "15m",
            )
            .order_by(desc(SignalEvent.id))
            .limit(1)
        )
        new_events = list(
            session.scalars(
                select(SignalEvent)
                .where(
                    SignalEvent.id
                    > int(
                        packet["bindings"]["baseline_max_ids"][
                            "signal_events"
                        ]
                    )
                )
                .order_by(SignalEvent.id)
            )
        )
        new_event_facts = [_event_fact(event) for event in new_events]
        eod_checkpoint = session.scalar(
            select(AfterMarketSchedulerCheckpoint).where(
                AfterMarketSchedulerCheckpoint.product == "jm"
            )
        )
        latest_event_id = (
            latest_event.id if latest_event is not None else None
        )
        eod_state = {
            "heartbeat": eod_heartbeat,
            "status": (
                eod_checkpoint.status
                if eod_checkpoint is not None
                else "missing"
            ),
            "last_successful_trading_day": (
                eod_checkpoint.last_successful_trading_day.isoformat()
                if eod_checkpoint is not None
                and eod_checkpoint.last_successful_trading_day
                else None
            ),
            "receipt_path_set": bool(
                eod_checkpoint is not None
                and eod_checkpoint.last_receipt_path
            ),
        }
        session.rollback()
    runtime_result = dict(
        runtime_heartbeat.get("signal_event_result") or {}
    )
    return {
        "observed_at": detected_at.isoformat(),
        "trading_day": trading_day.isoformat(),
        "runtime": {
            "heartbeat": runtime_heartbeat,
            "health": runtime_heartbeat.get("status"),
        },
        "mapping": {
            "actual_contract": state["actual_contract"],
            "mapping_sha256": state["mapping_sha256"],
        },
        "live": {
            "minute_count": len(snapshot.source_minutes),
            "bucket_count": len(snapshot.buckets),
            "snapshot_sha256": snapshot.snapshot_sha256,
        },
        "htdy": {
            "candidate_count": len(evaluation.candidates),
            "blocked_count": len(evaluation.blocked),
            "created": int(runtime_result.get("created") or 0),
            "unchanged": int(runtime_result.get("unchanged") or 0),
            "changed": int(runtime_result.get("changed") or 0),
            "blocked": int(
                runtime_result.get("blocked")
                if runtime_result.get("blocked") is not None
                else len(evaluation.blocked)
            ),
            "latest_event_id": latest_event_id,
        },
        "eod": eod_state,
        "counts": state["counts"],
        "hashes": state["hashes"],
        "indicator_source_sha256": packet["bindings"][
            "indicator_source_sha256"
        ],
        "policy_sha256": packet["bindings"]["policy_sha256"],
        "new_events": new_event_facts,
    }


def _redis_json(connection: Any, key: str) -> dict[str, Any]:
    raw = connection.get(key)
    if raw is None:
        raise HtDyS610Error("runtime_heartbeat_missing")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="strict")
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError, UnicodeError) as exc:
        raise HtDyS610Error("runtime_heartbeat_invalid") from exc
    if not isinstance(value, dict):
        raise HtDyS610Error("runtime_heartbeat_invalid")
    return value


def _next_rqdata_days(generated_at: datetime) -> tuple[date, ...]:
    from app.services.rqdata_ingest.client import RqDataClient

    local = generated_at.astimezone(ZoneInfo("Asia/Shanghai"))
    start = local.date()
    provider_days = RqDataClient(load_env_file=True).trading_dates(
        start - timedelta(days=20),
        start + timedelta(days=30),
    )
    eligible: list[date] = []
    for index, day in enumerate(provider_days):
        if index == 0 or day <= date(2026, 7, 28):
            continue
        night_start = datetime.combine(
            provider_days[index - 1],
            time(21),
            tzinfo=ZoneInfo("Asia/Shanghai"),
        )
        if night_start > local:
            eligible.append(day)
    if len(eligible) < 5:
        raise HtDyS610Error("rqdata_calendar_window_incomplete")
    return tuple(eligible[:5])


def _previous_rqdata_trading_day(trading_day: date) -> date:
    from app.services.rqdata_ingest.client import RqDataClient

    values = RqDataClient(load_env_file=True).trading_dates(
        trading_day - timedelta(days=20),
        trading_day - timedelta(days=1),
    )
    eligible = [item for item in values if item < trading_day]
    if not eligible:
        raise HtDyS610Error("rqdata_previous_trading_day_missing")
    return eligible[-1]


def _required_day(
    args: argparse.Namespace,
    packet: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> date:
    if args.trading_day:
        day = date.fromisoformat(args.trading_day)
    else:
        local = (now or datetime.now(UTC)).astimezone(
            ZoneInfo("Asia/Shanghai")
        )
        authorized = [
            date.fromisoformat(value) for value in packet["trading_days"]
        ]
        active = [
            item
            for item in authorized
            if datetime.combine(
                _night_session_dates(packet)[item],
                datetime.min.time().replace(hour=21),
                tzinfo=ZoneInfo("Asia/Shanghai"),
            )
            <= local
        ]
        if not active:
            raise HtDyS610Error("trading_day_not_started")
        day = active[-1]
    if day.isoformat() not in packet["trading_days"]:
        raise HtDyS610Error("trading_day_outside_window")
    return day


def _night_session_dates(
    packet: Mapping[str, Any],
) -> dict[date, date]:
    result: dict[date, date] = {}
    for row in packet.get("calendar_rows", ()):
        if not isinstance(row, Mapping):
            raise HtDyS610Error("calendar_window_invalid")
        trading_day = date.fromisoformat(str(row.get("trade_date")))
        night_day = date.fromisoformat(str(row.get("night_session_date")))
        if night_day >= trading_day or trading_day in result:
            raise HtDyS610Error("calendar_night_session_invalid")
        result[trading_day] = night_day
    expected = {
        date.fromisoformat(str(item))
        for item in packet.get("trading_days", ())
    }
    if set(result) != expected:
        raise HtDyS610Error("calendar_night_session_invalid")
    return result


def _tree_hash(root: Path) -> str:
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return hashlib.sha256(tree.encode("utf-8")).hexdigest()


def validate_backup_restore_receipts(
    backup_path: Path,
    restore_path: Path,
    *,
    backup_mount: Path = BACKUP_ROOT,
    restore_parent: Path = Path("/private/tmp"),
    artifact_verifier: Any | None = None,
    restore_executor: Any | None = None,
) -> None:
    from scripts.backup.artifact import ArtifactError, verify_backup_artifact

    resolved_backup = backup_path.resolve(strict=True)
    try:
        backup_root = resolved_backup.parent
        backup_root.relative_to(backup_mount.resolve(strict=True))
    except (OSError, ValueError) as exc:
        raise HtDyS610Error("backup_not_on_approved_same_volume_root") from exc
    if (
        resolved_backup.name != "backup_manifest.json"
        or backup_root.parent != backup_mount.resolve(strict=True)
        or not backup_root.name.startswith("guiyi-v1-full-s610-")
        or backup_root.stat().st_dev != backup_mount.stat().st_dev
    ):
        raise HtDyS610Error("backup_artifact_path_invalid")
    try:
        artifact = (artifact_verifier or verify_backup_artifact)(backup_root)
    except ArtifactError as exc:
        raise HtDyS610Error(f"backup_artifact_invalid:{exc}") from exc
    if artifact.manifest_sha256 != _file_hash(resolved_backup):
        raise HtDyS610Error("backup_manifest_hash_invalid")
    backup = artifact.manifest
    if (
        backup.get("schema_version") != "guiyi_local_backup_v1"
        or backup.get("status") != "completed"
        or backup.get("mode") != "full"
        or backup.get("retention_class") != "milestone"
        or "data/raw" not in backup.get("excluded_categories", ())
    ):
        raise HtDyS610Error("backup_manifest_invalid")
    database = dict(backup.get("database") or {})
    if (
        database.get("included") is not True
        or database.get("alembic_revision") != "20260721_0025"
        or (database.get("report14") or {}).get("md5")
        != "ae807ef77f7d9a4ce3067996558b57e8"
    ):
        raise HtDyS610Error("backup_database_evidence_invalid")
    inventory = dict(backup.get("inventory") or {})
    if (
        type(inventory.get("file_count")) is not int
        or inventory["file_count"] < 1
        or not _sha256(inventory.get("sha256"))
    ):
        raise HtDyS610Error("backup_inventory_invalid")
    backup_boundaries = dict(backup.get("boundaries") or {})
    if (
        backup_boundaries.get("secrets_included") is not False
        or backup_boundaries.get("production_restore_authorized") is not False
        or backup_boundaries.get("storage_scope")
        != "same_device_snapshot"
        or backup_boundaries.get("same_device_snapshot") is not True
        or backup_boundaries.get("independent_device_backup") is not False
        or backup_boundaries.get("disaster_recovery_ready") is not False
    ):
        raise HtDyS610Error("backup_boundary_invalid")

    resolved_restore = restore_path.resolve(strict=True)
    restore_root = resolved_restore.parent
    if (
        resolved_restore.name != "isolated_restore_receipt.json"
        or restore_root.parent != restore_parent.resolve(strict=True)
        or not restore_root.name.startswith("guiyi-restore-s610-")
    ):
        raise HtDyS610Error("restore_receipt_path_invalid")
    sidecar = restore_root / "isolated_restore_receipt.sha256"
    if (
        not sidecar.is_file()
        or sidecar.read_text(encoding="utf-8").strip()
        != _file_hash(resolved_restore)
    ):
        raise HtDyS610Error("restore_receipt_checksum_invalid")
    restore = _load_json(resolved_restore)
    if (
        restore.get("schema_version") != "guiyi_isolated_restore_v1"
        or restore.get("status") != "passed"
        or (restore.get("backup") or {}).get("manifest_sha256")
        != artifact.manifest_sha256
    ):
        raise HtDyS610Error("restore_receipt_invalid")
    verification = dict(restore.get("artifact_verification") or {})
    if (
        verification.get("all_declared_files_verified") is not True
        or verification.get("profile_verified") is not True
    ):
        raise HtDyS610Error("restore_artifact_verification_invalid")
    restored_database = dict(restore.get("database") or {})
    if (
        restored_database.get("alembic_revision") != "20260721_0025"
        or (restored_database.get("report14") or {}).get("md5")
        != "ae807ef77f7d9a4ce3067996558b57e8"
    ):
        raise HtDyS610Error("restore_database_evidence_invalid")
    smoke = restore.get("consumer_smoke")
    expected_consumers = {
        "market",
        "backtest",
        "signal_latest",
        "signal_events",
        "review",
    }
    if (
        not isinstance(smoke, list)
        or len(smoke) != 5
        or any(not isinstance(item, Mapping) for item in smoke)
        or {str(item.get("consumer")) for item in smoke} != expected_consumers
        or any(
            item.get("method") != "GET" or item.get("status") != "passed"
            for item in smoke
        )
    ):
        raise HtDyS610Error("restore_consumer_smoke_invalid")
    tool = dict(restore.get("tool") or {})
    isolated = dict(restore.get("isolated") or {})
    target_database = str(isolated.get("target_database") or "")
    target_root = Path(str(isolated.get("target_data_root") or "")).resolve(
        strict=False
    )
    if (
        tool.get("postgres_image") != "postgres:16"
        or not target_database.startswith("guiyi_restore_s610_")
        or target_root != restore_root
        or isolated.get("container_removed") is not True
        or isolated.get("volume_removed") is not True
    ):
        raise HtDyS610Error("restore_isolation_invalid")
    boundaries = dict(restore.get("boundaries") or {})
    required_boundaries = {
        "transaction_read_only": True,
        "database_unchanged": True,
        "production_database_touched": False,
        "production_data_touched": False,
        "wechat_called": False,
    }
    if any(
        boundaries.get(key) is not value
        for key, value in required_boundaries.items()
    ):
        raise HtDyS610Error("restore_boundary_invalid")
    executor = restore_executor or _execute_independent_restore_audit
    audit_path = Path(
        executor(
            backup_root,
            restore_parent,
            artifact.manifest_sha256,
        )
    ).resolve(strict=True)
    if audit_path == resolved_restore:
        raise HtDyS610Error("restore_audit_not_independent")
    _validate_independent_restore_receipt(
        audit_path,
        restore_parent=restore_parent,
        artifact_sha256=artifact.manifest_sha256,
    )
    return audit_path


def _execute_independent_restore_audit(
    backup_root: Path,
    restore_parent: Path,
    artifact_sha256: str,
) -> Path:
    from scripts.restore.core import execute_isolated_restore
    from scripts.restore.isolated import default_dependencies

    token = secrets.token_hex(4)
    target = restore_parent / f"guiyi-restore-s610-audit-{artifact_sha256[:8]}-{token}"
    result = execute_isolated_restore(
        backup_root=backup_root,
        target_database=f"guiyi_restore_s610_audit_{token}",
        target_data_root=target,
        isolated=True,
        confirm_isolated_restore=True,
        dependencies=default_dependencies(),
    )
    receipt = result.get("receipt")
    if not isinstance(receipt, str):
        raise HtDyS610Error("restore_audit_failed")
    return Path(receipt)


def _validate_independent_restore_receipt(
    path: Path,
    *,
    restore_parent: Path,
    artifact_sha256: str,
) -> None:
    root = path.parent
    sidecar = root / "isolated_restore_receipt.sha256"
    if (
        path.name != "isolated_restore_receipt.json"
        or root.parent != restore_parent.resolve(strict=True)
        or not root.name.startswith("guiyi-restore-s610-audit-")
        or not sidecar.is_file()
        or sidecar.read_text(encoding="utf-8").strip() != _file_hash(path)
    ):
        raise HtDyS610Error("restore_audit_receipt_invalid")
    payload = _load_json(path)
    isolated = dict(payload.get("isolated") or {})
    consumers = payload.get("consumer_smoke")
    if (
        payload.get("status") != "passed"
        or (payload.get("backup") or {}).get("manifest_sha256")
        != artifact_sha256
        or (payload.get("database") or {}).get("alembic_revision")
        != "20260721_0025"
        or (payload.get("database") or {}).get("report14", {}).get("md5")
        != "ae807ef77f7d9a4ce3067996558b57e8"
        or (payload.get("artifact_verification") or {}).get(
            "all_declared_files_verified"
        )
        is not True
        or not isinstance(consumers, list)
        or {item.get("consumer") for item in consumers if isinstance(item, Mapping)}
        != {"market", "backtest", "signal_latest", "signal_events", "review"}
        or any(
            not isinstance(item, Mapping)
            or item.get("method") != "GET"
            or item.get("status") != "passed"
            for item in consumers
        )
        or not str(isolated.get("target_database") or "").startswith(
            "guiyi_restore_s610_audit_"
        )
        or Path(str(isolated.get("target_data_root") or "")).resolve(
            strict=False
        )
        != root
        or isolated.get("container_removed") is not True
        or isolated.get("volume_removed") is not True
        or any(
            (payload.get("boundaries") or {}).get(key) is not value
            for key, value in {
                "transaction_read_only": True,
                "database_unchanged": True,
                "production_database_touched": False,
                "production_data_touched": False,
                "wechat_called": False,
            }.items()
        )
    ):
        raise HtDyS610Error("restore_audit_receipt_invalid")


def _file_hash(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise HtDyS610Error("artifact_unavailable") from exc


def _packet_identity(path: Path) -> dict[str, str]:
    payload = _load_json(path)
    packet_hash = payload.get("packet_hash")
    if not _sha256(packet_hash):
        raise HtDyS610Error("bound_packet_hash_invalid")
    return {
        "path": str(path.resolve(strict=True)),
        "packet_hash": str(packet_hash),
        "file_sha256": _file_hash(path),
    }


def _sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _git(root: Path, *args: str) -> str:
    import subprocess

    try:
        result = subprocess.run(
            ("git", *args),
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise HtDyS610Error("git_identity_invalid") from exc
    return result.stdout.strip()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610Error("json_artifact_invalid") from exc
    if not isinstance(value, dict):
        raise HtDyS610Error("json_artifact_invalid")
    return value


def _safe_reason(exc: Exception) -> str:
    value = str(exc).strip()
    if not value:
        return "operation_failed"
    lowered = value.lower()
    if any(
        token in lowered
        for token in ("password", "secret", "token", "webhook", "cookie")
    ):
        return "sensitive_error_redacted"
    return value[:160]


if __name__ == "__main__":
    raise SystemExit(main())
