#!/usr/bin/env python3
"""Prepare create-only schema-v5 artifacts; never deploy or send WeCom."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

from app.services.htdy_s6_10_one_day import (  # noqa: E402
    build_one_day_parent_packet,
    canonical_hash,
    finalize_one_day,
    git_tree_binding_sha256,
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

    prepare_deployment = subparsers.add_parser("prepare-deployment")
    prepare_deployment.add_argument(
        "--bindings-json", type=Path, required=True
    )
    prepare_deployment.add_argument("--output", type=Path, required=True)
    prepare_deployment.add_argument(
        "--schema-version",
        type=int,
        choices=(5, 6, 7),
        default=7,
    )

    refresh_bindings = subparsers.add_parser("refresh-bindings")
    refresh_bindings.add_argument("--bindings-json", type=Path, required=True)
    refresh_bindings.add_argument("--output", type=Path, required=True)

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
    sample.add_argument("--post-window-finalize", action="store_true")

    long_heartbeat = subparsers.add_parser("long-running-heartbeat")
    long_heartbeat.add_argument("--parent", type=Path, required=True)
    long_heartbeat.add_argument("--approval-hash", required=True)

    approval_d = subparsers.add_parser("prepare-approval-d")
    approval_d.add_argument("--parent", type=Path, required=True)
    approval_d.add_argument(
        "--acceptance-sample",
        type=Path,
        required=True,
    )
    approval_d.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare-approval-d":
        from app.services.htdy_s6_10_long_running import (
            build_approval_d_request,
        )

        request = build_approval_d_request(
            parent_packet=_load(args.parent),
            acceptance_sample=_load(args.acceptance_sample),
            generated_at=datetime.now(UTC),
        )
        _publish(args.output, request)
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "request_hash": request["request_hash"],
                    "output": str(args.output),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "long-running-heartbeat":
        from app.core.env import load_project_env

        load_project_env()
        from app.db.session import SessionLocal
        from app.queue import get_redis_connection
        from app.services.htdy_s6_10_long_running_runtime_gate import (
            build_runtime_gate,
        )
        from app.services.htdy_s6_10_service_heartbeat import (
            publish_s610_service_heartbeat,
        )

        gate = build_runtime_gate(
            approval_packet_path=args.parent,
            approval_hash=args.approval_hash,
            environ=os.environ,
        )
        with SessionLocal() as session:
            metadata = dict(gate(session, phase="daily_metadata"))
        if metadata.get("gate_status") == "waiting":
            print(
                json.dumps(
                    {
                        "status": "waiting",
                        "reason": "outside_confirmed_dce_session",
                    }
                )
            )
            return 0
        redis_connection = get_redis_connection()
        publish_s610_service_heartbeat(
            redis_connection,
            service="observer",
            authorization_hash=str(metadata["authorization_hash"]),
            target_trading_day=date.fromisoformat(
                str(metadata["target_trading_day"])
            ),
            details={
                "approval_d_hash": str(metadata["approval_d_hash"]),
                "expected_confirmed_15m_closes": len(
                    metadata["expected_bucket_ends"]
                ),
            },
        )
        print(
            json.dumps(
                {
                    "status": "observing",
                    "authorization_hash": metadata[
                        "authorization_hash"
                    ],
                    "trading_day": metadata["target_trading_day"],
                },
                sort_keys=True,
            )
        )
        return 0
    if args.command == "refresh-bindings":
        # This is intentionally a pre-approval, read-only operation.  It
        # prevents parent packets from inheriting a copied DB/profile baseline
        # from an older deployment directory.
        from sqlalchemy import text

        from app.core.env import load_project_env
        from app.services.htdy_s6_10_runtime_support import (
            refresh_one_day_preapproval_bindings,
        )

        bindings = _load(args.bindings_json)
        if _git_status(ROOT) != "":
            raise ValueError("source_checkout_not_clean")
        load_project_env()
        # SessionLocal constructs its engine from environment configuration at
        # import time; importing it before loading project.env loses the
        # password and must fail closed.
        from app.db.session import SessionLocal

        with SessionLocal() as session:
            session.execute(text("SET TRANSACTION READ ONLY"))
            refreshed = refresh_one_day_preapproval_bindings(
                session,
                bindings=bindings,
            )
            session.rollback()
        refreshed["runtime_tracked_clean"] = True
        _normalize_git_bindings(refreshed)
        _publish(args.output, refreshed)
        print(
            json.dumps(
                {
                    "status": "refreshed",
                    "output": str(args.output),
                }
            )
        )
        return 0
    if args.command == "prepare-deployment":
        bindings = _load(args.bindings_json)
        _normalize_git_bindings(bindings)
        bindings["approval_output_root"] = str(
            args.output.resolve(strict=False).parent
        )
        deployment = _build_deployment_packet(
            bindings,
            generated_at=datetime.now(UTC),
            schema_version=args.schema_version,
        )
        _publish(args.output, deployment)
        print(
            json.dumps(
                {
                    "status": "prepared",
                    "packet_hash": deployment["packet_hash"],
                }
            )
        )
        return 0
    if args.command == "prepare":
        bindings = _load(args.bindings_json)
        _normalize_git_bindings(bindings)
        generated_at = datetime.now(UTC)
        output = args.output_dir
        bindings["parent_packet_path"] = str(
            (output / "parent_packet.json").resolve(strict=False)
        )
        deployment_path = Path(
            str(
                ((bindings.get("artifact_paths") or {}).get(
                    "deployment_packet"
                ))
                or ""
            )
        )
        if deployment_path.is_file():
            bindings["approval_output_root"] = str(
                deployment_path.resolve(strict=True).parent
            )
            deployment = _load(deployment_path)
            expected_deployment = {
                key: value
                for key, value in deployment.items()
                if key not in {"generated_at", "packet_hash"}
            }
            if (
                expected_deployment
                != {
                    key: value
                    for key, value in _build_deployment_packet(
                        bindings,
                        generated_at=datetime.fromisoformat(
                            str(deployment.get("generated_at") or "")
                        ),
                    ).items()
                    if key not in {"generated_at", "packet_hash"}
                }
                or deployment.get("packet_hash")
                != canonical_hash(deployment)
            ):
                raise ValueError("deployment_packet_drift")
        else:
            bindings["approval_output_root"] = str(output.resolve())
            deployment = _build_deployment_packet(
                bindings,
                generated_at=generated_at,
            )
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
            "calendar_window.json": calendar,
            "observer_identity.json": observer,
            "dispatcher_identity.json": dispatcher,
        }
        augmented = dict(bindings)
        artifact_paths = dict(augmented.get("artifact_paths") or {})
        artifact_paths.update(
            {
                "deployment_packet": str(
                    (
                        deployment_path
                        if deployment_path.is_file()
                        else output / "deployment_packet.json"
                    ).resolve()
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
        if not deployment_path.is_file():
            artifacts["deployment_packet.json"] = deployment
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
        load_project_env()
        parent = _load(args.parent)
        trading_day = date.fromisoformat(parent["trading_days"][0])
        now = datetime.now(UTC)
        window_end = datetime.fromisoformat(str(parent["window_end"]))
        if (
            args.post_window_finalize
            and not window_end <= now <= window_end + timedelta(hours=3)
        ) or (not args.post_window_finalize and now >= window_end):
            raise ValueError("S610_SAMPLE_PHASE_INVALID")
        expected_bucket_ends = None
        activation_receipt_hash = None
        artifact_paths = dict(
            (parent.get("bindings") or {}).get("artifact_paths") or {}
        )
        eod_enable_packet = _load(
            Path(str(artifact_paths.get("s6_07_enable_packet") or ""))
        )
        expected_eod_authorization_hash = str(
            eod_enable_packet.get("packet_hash") or ""
        )
        if len(expected_eod_authorization_hash) != 64:
            raise ValueError("S610_EOD_AUTHORIZATION_BINDING_INVALID")
        if parent.get("schema_version") in {6, 7}:
            from app.services.htdy_s6_10_remaining_window_runtime_gate import (
                build_runtime_gate,
            )

            activation = _load(
                Path(
                    str(
                        os.environ.get(
                            "GUIYI_HTDY_S610_ACTIVATION_RECEIPT"
                        )
                        or ""
                    )
                )
            )
            expected_bucket_ends = list(
                activation["expected_bucket_ends"]
            )
            activation_receipt_hash = str(activation["receipt_hash"])
        else:
            from app.services.htdy_s6_10_one_day_runtime_gate import (
                build_runtime_gate,
            )

        gate = build_runtime_gate(
            parent_packet_path=args.parent,
            approval_hash=args.approval_hash,
            environ=os.environ,
        )
        redis_connection = get_redis_connection()
        if expected_bucket_ends is not None and not args.post_window_finalize:
            from app.services.htdy_s6_10_service_heartbeat import (
                publish_s610_service_heartbeat,
            )

            publish_s610_service_heartbeat(
                redis_connection,
                service="observer",
                authorization_hash=args.approval_hash,
                target_trading_day=trading_day,
            )
        with SessionLocal() as session:
            gate(session, phase="verify")
            sample_payload = collect_one_day_ledger_sample(
                session=session,
                redis=redis_connection,
                trading_day=trading_day,
                runtime_log=args.runtime_log,
                sampled_at=now,
                expected_bucket_ends=expected_bucket_ends,
                activation_receipt_hash=activation_receipt_hash,
                parent_packet_hash=args.approval_hash,
                terminal_seal_path=(
                    args.output_dir
                    / "remaining_window"
                    / "terminal_runtime_seal.json"
                ),
                expected_eod_authorization_hash=(
                    expected_eod_authorization_hash
                ),
            )
        sample_payload["parent_packet_hash"] = args.approval_hash
        sample_payload["sample_hash"] = canonical_hash(sample_payload)
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        window_name = (
            "remaining_window"
            if parent.get("schema_version") in {6, 7}
            else "one_day"
        )
        destination = (
            args.output_dir
            / window_name
            / "samples"
            / f"{timestamp}.json"
        )
        _publish(destination, sample_payload)
        if sample_payload.get("complete_trading_day_passed") is True:
            _publish(
                args.output_dir
                / "remaining_window"
                / "final_acceptance.json",
                sample_payload,
            )
        from app.services.htdy_s6_10_service_heartbeat import (
            publish_s610_service_heartbeat,
        )

        if not args.post_window_finalize:
            publish_s610_service_heartbeat(
                redis_connection,
                service="observer",
                authorization_hash=args.approval_hash,
                target_trading_day=trading_day,
                details={"sample_hash": sample_payload["sample_hash"]},
            )
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


def _build_deployment_packet(
    bindings: dict[str, Any],
    *,
    generated_at: datetime,
    schema_version: int = 5,
) -> dict[str, Any]:
    if generated_at.tzinfo is None:
        raise ValueError("deployment_generated_at_invalid")
    output_root = Path(str(bindings.get("approval_output_root") or ""))
    if (
        not output_root.is_absolute()
        or not output_root.is_dir()
        or output_root.is_symlink()
    ):
        raise ValueError("deployment_output_scope_invalid")
    deployment = {
        "schema_version": 1,
        "packet_type": (
            f"s6_10_schema_v{schema_version}_code_only_deployment"
        ),
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "source_commit": bindings["source_commit"],
        "source_tree": bindings["source_tree"],
        "target_runtime_commit": bindings["runtime_commit"],
        "target_runtime_tree": bindings["runtime_tree"],
        "database_migration_allowed": False,
        "runtime_activation_allowed": True,
        "activation_requires_signed_approval_c2": True,
        "output_scope": {
            "root": str(output_root.resolve(strict=True)),
            "root_device": output_root.stat().st_dev,
            "deployment_receipt_path": str(
                (output_root / "deployment_receipt.json").resolve(
                    strict=False
                )
            ),
        },
    }
    deployment["packet_hash"] = canonical_hash(deployment)
    return deployment


def _normalize_git_bindings(bindings: dict[str, Any]) -> None:
    for prefix in ("source", "runtime"):
        commit = str(bindings.get(f"{prefix}_commit") or "")
        result = subprocess.run(
            ("git", "rev-parse", f"{commit}^{{tree}}"),
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        bindings[f"{prefix}_tree"] = git_tree_binding_sha256(
            result.stdout.strip()
        )


def _git_status(root: Path) -> str:
    result = subprocess.run(
        ("git", "status", "--porcelain=v1"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


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
