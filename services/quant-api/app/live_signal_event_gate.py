from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
import json
import os
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.core.env import PROJECT_ROOT, load_project_env
from app.services.live_signal_event_gate import (
    LiveSignalEventGateError,
    build_live_strategy_eligibility,
    build_final_verification,
    build_service_approval_packet,
    collect_bound_facts,
    collect_new_event_rows,
    collect_new_signal_rows,
    load_json,
    publish_final_receipt,
    validate_s6_final_receipt,
    verify_foundation_receipt,
    verify_service_approval_packet,
    write_json_create_only,
)
from app.services.review_lineage import resolve_review_source_lineage


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="S6-08 JM live-confirmed SignalEvent approval and acceptance Gate")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--check-strategy-eligibility", action="store_true")
    mode.add_argument("--prepare-packet", action="store_true")
    mode.add_argument("--verify-packet", action="store_true")
    mode.add_argument("--verify-final", action="store_true")
    mode.add_argument("--publish-final", action="store_true")
    parser.add_argument("--s6-final-receipt", type=Path)
    parser.add_argument("--s6-final-receipt-sha256")
    parser.add_argument("--target-trading-day")
    parser.add_argument("--approval-packet", type=Path)
    parser.add_argument("--approval-hash")
    parser.add_argument("--packet-out", type=Path)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--runtime-health-json", type=Path)
    parser.add_argument("--execution-health-json", type=Path)
    parser.add_argument("--eligibility-out", type=Path)
    parser.add_argument("--verification-json", type=Path)
    parser.add_argument("--verification-out", type=Path)
    parser.add_argument("--receipt-out", type=Path)
    parser.add_argument("--execution-phase", action="store_true")
    parser.add_argument("--confirm-final-gate", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> int:
    args = parse_args(argv)
    if args.dry_run:
        print(
            json.dumps(
                {
                    "status": "dry-run",
                    "task_id": "JM-LIVE-SIGNAL-EVENT-S6-08",
                    "would_open_database": False,
                    "would_connect_redis": False,
                    "would_construct_rqdata_client": False,
                    "would_write_live_tables": False,
                    "would_write_signal_event": False,
                    "would_send_notification": False,
                    "would_publish_receipt": False,
                    "auto_order": False,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.check_strategy_eligibility:
        try:
            eligibility = build_live_strategy_eligibility(PROJECT_ROOT)
            if args.eligibility_out:
                write_json_create_only(args.eligibility_out, eligibility)
            print(json.dumps(eligibility, ensure_ascii=False))
            return 0 if eligibility.get("status") == "eligible" else 2
        except Exception as exc:  # noqa: BLE001 - CLI emits a bounded, redacted failure.
            print(json.dumps({"status": "blocked", "error_type": type(exc).__name__}, ensure_ascii=False))
            return 2
    source_env = environ
    if source_env is None:
        load_project_env()
        source_env = os.environ
    try:
        if args.prepare_packet:
            return _prepare(args, source_env, session_factory)
        if args.verify_packet:
            return _verify(args, source_env, session_factory)
        if args.verify_final:
            return _verify_final(args, source_env, session_factory)
        return _publish_final(args, source_env, session_factory)
    except Exception as exc:  # noqa: BLE001 - CLI must emit a bounded, redacted failure.
        print(
            json.dumps(
                {"status": "blocked", "error_type": type(exc).__name__},
                ensure_ascii=False,
            )
        )
        return 2


def _prepare(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
) -> int:
    if (
        not args.s6_final_receipt
        or not args.target_trading_day
        or not args.packet_out
        or not args.output_root
        or not args.runtime_root
    ):
        raise LiveSignalEventGateError("prepare_arguments_required")
    if not _is_lower_sha256(args.s6_final_receipt_sha256):
        raise LiveSignalEventGateError("prepare_s6_final_receipt_sha256_required")
    foundation = validate_s6_final_receipt(
        args.s6_final_receipt,
        expected_sha256=args.s6_final_receipt_sha256,
    )
    factory = session_factory or _default_session_factory()
    with factory() as session:
        _set_read_only(session)
        facts = collect_bound_facts(
            session,
            project_root=args.runtime_root,
            output_root=args.output_root,
            environ=environ,
        )
        session.rollback()
    packet = build_service_approval_packet(
        target_trading_day=args.target_trading_day,
        bound_facts=facts,
        s6_final_receipt=foundation,
    )
    write_json_create_only(args.packet_out, packet)
    print(
        json.dumps(
            {
                "status": "approval_required",
                "packet_hash": packet["packet_hash"],
                "target_trading_day": packet["target_trading_day"],
                "writes_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0


def _verify(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
) -> int:
    if not args.approval_packet or not args.approval_hash or not args.output_root or not args.runtime_root:
        raise LiveSignalEventGateError("verify_arguments_required")
    packet = load_json(args.approval_packet)
    verify_foundation_receipt(packet)
    factory = session_factory or _default_session_factory()
    with factory() as session:
        _set_read_only(session)
        facts = collect_bound_facts(
            session,
            project_root=args.runtime_root,
            output_root=args.output_root,
            environ=environ,
        )
        verify_service_approval_packet(
            packet,
            approval_hash=args.approval_hash,
            current_facts=facts,
            current_trading_day=str(packet.get("target_trading_day") or ""),
            execution_phase=args.execution_phase,
        )
        session.rollback()
    print(json.dumps({"status": "verified", "packet_hash": packet["packet_hash"]}, ensure_ascii=False))
    return 0


def _verify_final(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
) -> int:
    if (
        not args.approval_packet
        or not args.approval_hash
        or not args.output_root
        or not args.execution_health_json
        or not args.runtime_health_json
        or not args.verification_out
        or not args.runtime_root
    ):
        raise LiveSignalEventGateError("verify_final_arguments_required")
    *_, verification = _collect_final_evidence(args, environ, session_factory)
    write_json_create_only(args.verification_out, verification)
    print(json.dumps({"status": verification["status"], "gate": verification["gate"]}, ensure_ascii=False))
    return 0 if verification["status"] in {"passed", "pending"} else 2


def _publish_final(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
) -> int:
    if (
        not args.approval_packet
        or not args.approval_hash
        or not args.output_root
        or not args.execution_health_json
        or not args.runtime_health_json
        or not args.receipt_out
        or not args.runtime_root
    ):
        raise LiveSignalEventGateError("publish_final_arguments_required")
    packet, facts, signals, events, flags, execution_health, health, review_lineages, _ = (
        _collect_final_evidence(args, environ, session_factory)
    )
    receipt = publish_final_receipt(
        args.receipt_out,
        packet=packet,
        approval_hash=args.approval_hash,
        current_facts=facts,
        new_signal_rows=signals,
        new_event_rows=events,
        restored_flags=flags,
        execution_runtime_health=execution_health,
        runtime_health=health,
        review_lineages=review_lineages,
        confirm_final_gate=args.confirm_final_gate,
    )
    print(json.dumps({"status": "completed", "gate": receipt["gate"]}, ensure_ascii=False))
    return 0


def _collect_final_evidence(
    args: argparse.Namespace,
    environ: Mapping[str, str],
    session_factory: Callable[[], Any] | None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    dict[str, bool],
    dict[str, Any],
    dict[str, Any],
    list[dict[str, Any]],
    dict[str, Any],
]:
    packet = load_json(args.approval_packet)
    verify_foundation_receipt(packet)
    health = load_json(args.runtime_health_json)
    execution_health = load_json(args.execution_health_json)
    factory = session_factory or _default_session_factory()
    with factory() as session:
        _set_read_only(session)
        facts = collect_bound_facts(
            session,
            project_root=args.runtime_root,
            output_root=args.output_root,
            environ=environ,
        )
        verify_service_approval_packet(
            packet,
            approval_hash=args.approval_hash,
            current_facts=facts,
            current_trading_day=str(packet.get("target_trading_day") or ""),
            execution_phase=False,
        )
        signals = collect_new_signal_rows(session, packet)
        events = collect_new_event_rows(session, packet)
        review_lineages = [
            resolve_review_source_lineage(
                session,
                source_type="signal_event",
                source_id=int(event["id"]),
            )
            for event in events
        ]
        flags = {
            name: _enabled(environ, name)
            for name in (
                "GUIYI_LIVE_RUNTIME_ENABLED",
                "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED",
                "GUIYI_WECHAT_AUTOSEND_ENABLED",
                "GUIYI_AFTER_MARKET_ARCHIVE_ENABLED",
                "GUIYI_AFTER_MARKET_AUTOMATION_ENABLED",
            )
        }
        verification = build_final_verification(
            packet=packet,
            current_facts=facts,
            new_signal_rows=signals,
            new_event_rows=events,
            restored_flags=flags,
            execution_runtime_health=execution_health,
            runtime_health=health,
            review_lineages=review_lineages,
        )
        session.rollback()
    return packet, facts, signals, events, flags, execution_health, health, review_lineages, verification


def _default_session_factory() -> Callable[[], Any]:
    from app.db.session import SessionLocal

    return SessionLocal


def _set_read_only(session: Any) -> None:
    if session.get_bind().dialect.name == "postgresql":
        session.execute(text("SET TRANSACTION READ ONLY"))


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {"1", "true", "yes", "on"}


def _is_lower_sha256(value: str | None) -> bool:
    return value is not None and len(value) == 64 and all(character in "0123456789abcdef" for character in value)


if __name__ == "__main__":
    raise SystemExit(main())
