#!/usr/bin/env python3
"""Prepare, verify, or execute the exact HTDY S6-09 single-send Gate."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
for root in (
    PROJECT_ROOT / "services" / "quant-api",
    PROJECT_ROOT / "packages" / "quant-core",
):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="HTDY S6-09 exact one-event Enterprise WeChat Gate"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--prepare", action="store_true")
    mode.add_argument("--verify", action="store_true")
    mode.add_argument("--execute", action="store_true")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--s6-08-final-receipt", type=Path, required=True)
    parser.add_argument("--s6-08-accepted-event", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--env-file", type=Path, required=True)
    parser.add_argument("--event-id", type=int, default=4)
    parser.add_argument("--approval-hash")
    parser.add_argument("--output-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return _run(args)
    except Exception as exc:  # noqa: BLE001 - CLI must fail closed.
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": exc.__class__.__name__,
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 1


def _run(args: argparse.Namespace) -> int:
    from dotenv import dotenv_values
    from sqlalchemy import text

    environ = {
        key: str(value)
        for key, value in dotenv_values(args.env_file).items()
        if value is not None
    }
    for name, value in environ.items():
        os.environ[name] = value

    from app.db.session import SessionLocal
    from app.models.signal import SignalEvent
    from app.signal.stage9_gate import evaluate_stage9_signal_event_gate
    from app.signal.stage9_wechat import (
        build_stage9_wechat_payload_from_basis,
    )
    from app.signal.stage9_wechat_delivery import (
        Stage9WechatDeliveryService,
    )
    from app.services.htdy_s6_08_approval_artifacts import (
        write_json_create_only,
    )
    from app.services.htdy_s6_09_wecom_gate import (
        HtDyS609Authorization,
        build_authorization_packet,
        canonical_hash,
        canonical_packet_hash,
        collect_current_facts,
        load_json_mapping,
        sha256_file,
        verify_authorization_packet,
        verify_final_facts,
        verify_retry_facts,
    )

    health = _collect_health()
    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        facts = collect_current_facts(
            session,
            source_root=PROJECT_ROOT,
            runtime_root=args.runtime_root,
            environ=environ,
            health=health,
            event_id=args.event_id,
        )
        event = session.get(SignalEvent, args.event_id)
        if event is None:
            raise RuntimeError("event_missing")
        gate = evaluate_stage9_signal_event_gate(event)
        if (
            gate["allowed"] is not True
            or gate["delivery_allowed"] is not False
            or gate["delivery_blocked_reasons"]
            != ["htdy_observation_delivery_requires_separate_gate"]
        ):
            raise RuntimeError("htdy_stage9_contract_invalid")
        message = build_stage9_wechat_payload_from_basis(
            gate["payload_basis"]
        )
        message_sha256 = canonical_hash(message)

    if args.prepare:
        if args.packet.exists():
            raise RuntimeError("packet_already_exists")
        packet = build_authorization_packet(
            current_facts=facts,
            s6_08_receipt=load_json_mapping(
                args.s6_08_final_receipt
            ),
            s6_08_receipt_file_sha256=sha256_file(
                args.s6_08_final_receipt
            ),
            accepted_event=load_json_mapping(
                args.s6_08_accepted_event
            ),
            accepted_event_file_sha256=sha256_file(
                args.s6_08_accepted_event
            ),
            rendered_message_sha256=message_sha256,
            generated_at=datetime.now(UTC),
        )
        write_json_create_only(args.packet, packet)
        return _print_result(
            {
                "status": "prepared",
                "event_id": args.event_id,
                "packet_hash": packet["packet_hash"],
                "real_send_executed": False,
            }
        )

    packet = load_json_mapping(args.packet)
    approval_hash = str(args.approval_hash or packet.get("packet_hash") or "")
    if args.verify:
        verify_authorization_packet(
            packet,
            approval_hash=approval_hash,
            current_facts=facts,
            now=datetime.now(UTC),
        )
        return _print_result(
            {
                "status": "verified",
                "event_id": args.event_id,
                "packet_hash": packet["packet_hash"],
                "real_send_executed": False,
            }
        )

    if not args.approval_hash or args.output_dir is None:
        raise RuntimeError("execute_requires_approval_hash_and_output_dir")
    if canonical_packet_hash(packet) != approval_hash:
        raise RuntimeError("approval_hash_mismatch")
    state_path = args.output_dir / "execution_started.json"
    now = datetime.now(UTC)
    if state_path.exists():
        state = load_json_mapping(state_path)
        started_at = datetime.fromisoformat(str(state["started_at"]))
        notification_status = (
            (facts.get("event_notification") or {}).get("status")
        )
        if facts["event_notification_count"] == 0:
            verify_authorization_packet(
                packet,
                approval_hash=approval_hash,
                current_facts=facts,
                now=now,
                execution_started_at=started_at,
            )
        elif notification_status == "sent":
            verify_final_facts(packet, facts)
        else:
            verify_retry_facts(packet, facts)
        scope = packet["scope"]
        authorization = HtDyS609Authorization(
            event_id=int(scope["event_id"]),
            signal_id=int(scope["signal_id"]),
            event_sha256=str(scope["event_sha256"]),
            packet_hash=approval_hash,
            dedupe_key=str(scope["dedupe_key"]),
            max_attempts=int(scope["max_attempts"]),
            retry_deadline=started_at + timedelta(
                seconds=int(scope["retry_window_seconds"])
            ),
            rendered_message_sha256=str(
                scope["rendered_message_sha256"]
            ),
        )
    else:
        authorization = verify_authorization_packet(
            packet,
            approval_hash=approval_hash,
            current_facts=facts,
            now=now,
            execution_started_at=now,
        )
        write_json_create_only(
            state_path,
            {
                "schema_version": 1,
                "task_id": "JM-LIVE-WECOM-SINGLE-S6-09",
                "event_id": args.event_id,
                "packet_hash": approval_hash,
                "started_at": now.isoformat(),
                "retry_deadline": authorization.retry_deadline.isoformat(),
            },
        )
    if now > authorization.retry_deadline:
        raise RuntimeError("authorization_retry_window_expired")

    with SessionLocal() as session:
        result = Stage9WechatDeliveryService(
            session,
            environ=environ,
            now=now,
            max_attempts=authorization.max_attempts,
        ).send_event(args.event_id, authorization=authorization)
        public = result.to_public_dict()
    before_attempt_count = int(
        (facts.get("event_notification") or {}).get("attempt_count") or 0
    )
    if int(public["attempt_count"]) > before_attempt_count:
        attempt_no = int(public["attempt_count"])
        write_json_create_only(
            args.output_dir / f"attempt_{attempt_no}.json",
            {
                "schema_version": 1,
                "task_id": "JM-LIVE-WECOM-SINGLE-S6-09",
                "packet_hash": approval_hash,
                "recorded_at": datetime.now(UTC).isoformat(),
                "delivery": public,
            },
        )
    if public["status"] == "sent":
        with SessionLocal() as session:
            after_facts = collect_current_facts(
                session,
                source_root=PROJECT_ROOT,
                runtime_root=args.runtime_root,
                environ=environ,
                health=_collect_health(),
                event_id=args.event_id,
            )
        verify_final_facts(packet, after_facts)
        receipt = {
            "schema_version": 1,
            "task_id": "JM-LIVE-WECOM-SINGLE-S6-09",
            "status": "completed",
            "gate": "LIVE_WECOM_SINGLE_SEND_PASSED",
            "event_id": args.event_id,
            "signal_id": packet["scope"]["signal_id"],
            "packet_hash": approval_hash,
            "notification_id": public["notification_id"],
            "attempt_count": public["attempt_count"],
            "sent_at": datetime.now(UTC).isoformat(),
            "final_facts_sha256": canonical_hash(after_facts),
            "autosend_enabled": False,
            "notification_ready": False,
            "trading_ready": False,
            "long_running_ready": False,
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        receipt_path = args.output_dir / "final_receipt.json"
        if receipt_path.exists():
            existing = load_json_mapping(receipt_path)
            existing_hash = str(existing.get("receipt_hash") or "")
            if canonical_hash(
                {
                    key: value
                    for key, value in existing.items()
                    if key != "receipt_hash"
                }
            ) != existing_hash:
                raise RuntimeError("final_receipt_invalid")
        else:
            write_json_create_only(receipt_path, receipt)
    return _print_result(
        {
            "status": public["status"],
            "event_id": args.event_id,
            "notification_id": public["notification_id"],
            "attempt_count": public["attempt_count"],
            "packet_hash": approval_hash,
        }
    )


def _collect_health() -> dict[str, str]:
    result = subprocess.run(
        (
            "bash",
            "scripts/engineering/runtime-health.sh",
            "--json",
            "--strict",
        ),
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    if (
        not isinstance(payload, dict)
        or (payload.get("summary") or {}).get("failed") != 0
        or (payload.get("summary") or {}).get("warn") != 0
    ):
        raise RuntimeError("runtime_health_invalid")
    return {"runtime": "ok", "live": "ok", "after_market": "ok"}


def _print_result(value: dict[str, Any]) -> int:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
