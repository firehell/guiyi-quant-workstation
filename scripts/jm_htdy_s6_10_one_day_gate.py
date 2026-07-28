#!/usr/bin/env python3
"""Prepare create-only schema-v5 artifacts; never deploy or send WeCom."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

from app.services.htdy_s6_10_one_day import (  # noqa: E402
    build_one_day_parent_packet,
    canonical_hash,
    finalize_one_day,
    verify_one_day_parent_packet,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--trading-day", type=date.fromisoformat, required=True)
    prepare.add_argument(
        "--night-session-date", type=date.fromisoformat, required=True
    )
    prepare.add_argument("--bindings-json", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)

    verify = subparsers.add_parser("verify")
    verify.add_argument("--parent", type=Path, required=True)
    verify.add_argument("--approval-hash", required=True)
    verify.add_argument("--bindings-json", type=Path, required=True)

    supersede = subparsers.add_parser("supersede-v4")
    supersede.add_argument("--old-parent", type=Path, required=True)
    supersede.add_argument("--output", type=Path, required=True)

    supersede_c2 = subparsers.add_parser("supersede-c2")
    supersede_c2.add_argument("--old-parent", type=Path, required=True)
    supersede_c2.add_argument("--approval-receipt", type=Path, required=True)
    supersede_c2.add_argument("--runtime-commit", required=True)
    supersede_c2.add_argument("--replacement-source-commit", required=True)
    supersede_c2.add_argument("--output", type=Path, required=True)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--metrics-json", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)

    sample = subparsers.add_parser("sample")
    sample.add_argument("--parent", type=Path, required=True)
    sample.add_argument("--approval-hash", required=True)
    sample.add_argument("--output-dir", type=Path, required=True)
    sample.add_argument("--runtime-log", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare":
        bindings = _load(args.bindings_json)
        generated_at = datetime.now(UTC)
        output = args.output_dir
        deployment = {
            "schema_version": 1,
            "packet_type": "s6_10_schema_v5_code_only_deployment",
            "generated_at": generated_at.isoformat(),
            "source_commit": bindings["source_commit"],
            "source_tree": bindings["source_tree"],
            "target_runtime_commit": bindings["runtime_commit"],
            "target_runtime_tree": bindings["runtime_tree"],
            "database_migration_allowed": False,
            "runtime_activation_allowed": True,
            "activation_requires_signed_approval_c2": True,
        }
        deployment["packet_hash"] = canonical_hash(deployment)
        calendar = {
            "schema_version": 1,
            "trading_days": [args.trading_day.isoformat()],
            "night_session_date": args.night_session_date.isoformat(),
            "expected_confirmed_15m_closes": 23,
        }
        observer = {
            "schema_version": 1,
            "identity": "s6_10_schema_v5_one_day_observer",
            "expected_confirmed_15m_closes": 23,
            "partial_evaluation_allowed": False,
            "launchd_label": "com.guiyi.quant-htdy-s610-one-day-observer",
            "template_path": str(
                (
                    ROOT
                    / "deploy/launchd/com.guiyi.quant-htdy-s610-one-day-observer.plist.template"
                ).resolve()
            ),
            "template_sha256": _file_hash(
                ROOT
                / "deploy/launchd/com.guiyi.quant-htdy-s610-one-day-observer.plist.template"
            ),
            "runner_path": str(
                (
                    ROOT / "scripts/run-htdy-s610-one-day-observer.sh"
                ).resolve()
            ),
            "runner_sha256": _file_hash(
                ROOT / "scripts/run-htdy-s610-one-day-observer.sh"
            ),
        }
        dispatcher = {
            "schema_version": 1,
            "identity": "s6_10_schema_v5_bounded_wecom_dispatcher",
            "global_autosend_required": False,
            "max_events": 23,
            "max_attempts_per_event": 3,
            "window_scoped": True,
            "launchd_label": "com.guiyi.quant-htdy-s610-one-day-dispatcher",
            "template_path": str(
                (
                    ROOT
                    / "deploy/launchd/com.guiyi.quant-htdy-s610-one-day-dispatcher.plist.template"
                ).resolve()
            ),
            "template_sha256": _file_hash(
                ROOT
                / "deploy/launchd/com.guiyi.quant-htdy-s610-one-day-dispatcher.plist.template"
            ),
            "runner_path": str(
                (
                    ROOT / "scripts/run-htdy-s610-one-day-dispatcher.sh"
                ).resolve()
            ),
            "runner_sha256": _file_hash(
                ROOT / "scripts/run-htdy-s610-one-day-dispatcher.sh"
            ),
        }
        artifacts = {
            "deployment_packet.json": deployment,
            "calendar_window.json": calendar,
            "observer_identity.json": observer,
            "dispatcher_identity.json": dispatcher,
        }
        augmented = dict(bindings)
        artifact_paths = dict(augmented.get("artifact_paths") or {})
        artifact_paths.update(
            {
                "deployment_packet": str(
                    (output / "deployment_packet.json").resolve()
                ),
                "calendar_window": str(
                    (output / "calendar_window.json").resolve()
                ),
                "observer_identity": str(
                    (output / "observer_identity.json").resolve()
                ),
                "delivery_identity": str(
                    (output / "dispatcher_identity.json").resolve()
                ),
            }
        )
        augmented.update(
            {
                "deployment_packet_sha256": _payload_file_hash(deployment),
                "calendar_sha256": _payload_file_hash(calendar),
                "observer_launchd_sha256": _payload_file_hash(observer),
                "delivery_launchd_sha256": _payload_file_hash(dispatcher),
                "artifact_paths": artifact_paths,
            }
        )
        parent = build_one_day_parent_packet(
            trading_day=args.trading_day,
            night_session_date=args.night_session_date,
            generated_at=generated_at,
            bindings=augmented,
        )
        request = {
            "schema_version": 1,
            "request_type": "htdy_s6_10_approval_c2_request",
            "decision": "pending",
            "parent_packet_hash": parent["packet_hash"],
            "trading_day": args.trading_day.isoformat(),
            "max_wecom_notifications": 23,
            "max_attempts_per_event": 3,
            "global_wechat_autosend": False,
            "scope": "one complete DCE trading day",
            "approval_receipt_required_fields": [
                "approved_at",
                "trading_day",
                "max_wecom_notifications",
                "max_attempts_per_event",
                "global_wechat_autosend",
            ],
            "signature_namespace": "guiyi-htdy-s610",
            "signature_principal": "guiyi-owner",
        }
        request["request_hash"] = canonical_hash(request)
        artifacts["parent_packet.json"] = parent
        artifacts["bound_current_bindings.json"] = augmented
        artifacts["approval_c2_request.json"] = request
        for name, payload in artifacts.items():
            _publish(output / name, payload)
        print(json.dumps({"status": "prepared", "parent_hash": parent["packet_hash"]}))
        return 0
    if args.command == "verify":
        parent = _load(args.parent)
        verify_one_day_parent_packet(
            parent,
            approval_hash=args.approval_hash,
            current_bindings=_load(args.bindings_json),
            now=datetime.now(UTC),
        )
        print(json.dumps({"status": "verified", "parent_hash": args.approval_hash}))
        return 0
    if args.command == "sample":
        from app.core.env import load_project_env
        from app.db.session import SessionLocal
        from app.queue import get_redis_connection
        from app.services.htdy_s6_10_one_day_ledger import (
            collect_one_day_ledger_sample,
        )
        from app.services.htdy_s6_10_one_day_runtime_gate import (
            build_runtime_gate,
        )

        load_project_env()
        parent = _load(args.parent)
        trading_day = date.fromisoformat(parent["trading_days"][0])
        gate = build_runtime_gate(
            parent_packet_path=args.parent,
            approval_hash=args.approval_hash,
            environ=os.environ,
        )
        with SessionLocal() as session:
            gate(session, phase="verify")
            sample_payload = collect_one_day_ledger_sample(
                session=session,
                redis=get_redis_connection(),
                trading_day=trading_day,
                runtime_log=args.runtime_log,
                sampled_at=datetime.now(UTC),
            )
        sample_payload["parent_packet_hash"] = args.approval_hash
        sample_payload["sample_hash"] = canonical_hash(sample_payload)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        destination = args.output_dir / "one_day" / "samples" / f"{timestamp}.json"
        _publish(destination, sample_payload)
        print(
            json.dumps(
                {
                    "status": "sampled",
                    "path": str(destination),
                    "sample_hash": sample_payload["sample_hash"],
                }
            )
        )
        return 0
    if args.command == "supersede-v4":
        old = _load(args.old_parent)
        receipt = {
            "schema_version": 1,
            "receipt_type": "htdy_s6_10_schema_v4_superseded",
            "created_at": datetime.now(UTC).isoformat(),
            "old_parent_packet_hash": old.get("packet_hash"),
            "old_schema_version": old.get("schema_version"),
            "status": "superseded",
            "replacement": "schema-v5 Approval C2 pending",
            "old_evidence_preserved": True,
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        _publish(args.output, receipt)
        print(json.dumps({"status": "superseded", "receipt_hash": receipt["receipt_hash"]}))
        return 0
    if args.command == "supersede-c2":
        old = _load(args.old_parent)
        approval = _load(args.approval_receipt)
        target_commit = str(
            ((old.get("bindings") or {}).get("runtime_commit") or "")
        )
        if (
            old.get("schema_version") != 5
            or old.get("authorization_consumed") is not False
            or approval.get("decision") != "approved"
            or approval.get("parent_packet_hash") != old.get("packet_hash")
            or args.runtime_commit == target_commit
            or len(args.runtime_commit) != 40
            or len(args.replacement_source_commit) != 40
        ):
            raise ValueError("S610_C2_SUPERSEDE_PRECONDITION_FAILED")
        receipt = {
            "schema_version": 1,
            "receipt_type": "htdy_s6_10_approval_c2_superseded",
            "created_at": datetime.now(UTC).isoformat(),
            "status": "superseded_before_activation",
            "old_parent_packet_hash": old["packet_hash"],
            "old_approval_receipt_hash": approval.get("receipt_hash"),
            "old_target_runtime_commit": target_commit,
            "observed_runtime_commit": args.runtime_commit,
            "replacement_source_commit": args.replacement_source_commit,
            "authorization_consumed": False,
            "runtime_deployed": False,
            "signal_events_written": False,
            "wecom_requests_sent": False,
            "old_evidence_preserved": True,
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        _publish(args.output, receipt)
        print(
            json.dumps(
                {
                    "status": receipt["status"],
                    "receipt_hash": receipt["receipt_hash"],
                }
            )
        )
        return 0
    result = finalize_one_day(**_load(args.metrics_json))
    result["sealed_at"] = datetime.now(UTC).isoformat()
    result["seal_hash"] = canonical_hash(result)
    _publish(args.output, result)
    print(json.dumps(result))
    return 0


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON object required")
    return value


def _publish(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _payload_file_hash(payload: dict[str, Any]) -> str:
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
