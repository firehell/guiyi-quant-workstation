#!/usr/bin/env python3
"""Create-only schema-v7 remainder/full-day artifacts and activation receipt."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
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

from app.services.htdy_s6_10_remaining_window import (  # noqa: E402
    build_activation_receipt,
    build_complete_day_parent_packet,
    build_remaining_window_parent_packet,
    canonical_hash,
    finalize_remaining_window,
    verify_remaining_window_approval_times,
)
from app.services.htdy_s6_10_one_day import (  # noqa: E402
    git_tree_binding_sha256,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare")
    prepare.add_argument("--trading-day", type=date.fromisoformat, required=True)
    prepare.add_argument(
        "--night-session-date",
        type=date.fromisoformat,
        required=True,
    )
    prepare.add_argument(
        "--activation-deadline",
        type=datetime.fromisoformat,
        required=True,
    )
    prepare.add_argument("--bindings-json", type=Path, required=True)
    prepare.add_argument("--output-dir", type=Path, required=True)
    prepare.add_argument(
        "--complete-day",
        action="store_true",
        help="require activation before night session and all 23 closes",
    )

    activate = commands.add_parser("activate")
    activate.add_argument("--parent", type=Path, required=True)
    activate.add_argument("--approval-hash", required=True)
    activate.add_argument("--approval-c2-receipt", type=Path, required=True)
    activate.add_argument("--approval-c2-hash", required=True)
    activate.add_argument("--approval-c2-signature", type=Path, required=True)
    activate.add_argument("--approved-signers", type=Path, required=True)
    activate.add_argument("--output", type=Path, required=True)

    finalize = commands.add_parser("finalize")
    finalize.add_argument("--metrics-json", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "prepare":
        return _prepare(args)
    if args.command == "activate":
        return _activate(args)
    result = finalize_remaining_window(**_load(args.metrics_json))
    result["sealed_at"] = datetime.now(UTC).isoformat()
    result["seal_hash"] = canonical_hash(result)
    _publish(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _prepare(args: argparse.Namespace) -> int:
    if _git_status(ROOT):
        raise ValueError("source_checkout_not_clean")
    output = args.output_dir.resolve(strict=True)
    bindings = _refresh_bindings(_load(args.bindings_json))
    _normalize_git_bindings(bindings)
    source_head = _git(ROOT, "rev-parse", "HEAD")
    if (
        bindings.get("source_commit") != source_head
        or bindings.get("runtime_commit") != source_head
    ):
        raise ValueError("target_commit_must_match_source_head")
    bindings["parent_packet_path"] = str(output / "parent_packet.json")
    paths = dict(bindings.get("artifact_paths") or {})
    deployment_path = Path(str(paths.get("deployment_packet") or ""))
    if not deployment_path.is_file():
        raise ValueError("deployment_packet_missing")
    deployment = _load(deployment_path)
    if (
        deployment.get("packet_type")
        != "s6_10_schema_v7_code_only_deployment"
        or deployment.get("source_commit") != bindings["source_commit"]
        or deployment.get("target_runtime_commit")
        != bindings["runtime_commit"]
        or deployment.get("packet_hash") != canonical_hash(deployment)
    ):
        raise ValueError("deployment_packet_drift")

    complete_day = bool(args.complete_day)
    calendar = {
        "schema_version": 1,
        "window_mode": (
            "complete_trading_day"
            if complete_day
            else "remaining_trading_day"
        ),
        "trading_days": [args.trading_day.isoformat()],
        "night_session_date": args.night_session_date.isoformat(),
        "activation_policy": (
            "before_first_full_15m_bucket"
            if complete_day
            else "next_full_15m_bucket"
        ),
        "activation_deadline": args.activation_deadline.isoformat(),
        "maximum_confirmed_15m_closes": 23,
    }
    observer = _service_identity("observer")
    dispatcher = _service_identity("dispatcher")
    artifacts = {
        "calendar_window.json": calendar,
        "observer_identity.json": observer,
        "dispatcher_identity.json": dispatcher,
    }
    paths.update(
        {
            "calendar_window": str(output / "calendar_window.json"),
            "observer_identity": str(output / "observer_identity.json"),
            "delivery_identity": str(output / "dispatcher_identity.json"),
            "activation_receipt": str(
                output / "activation_receipt.json"
            ),
            "deployment_receipt": str(
                output / "deployment_receipt.json"
            ),
            "deployment_failure_receipt": str(
                output / "deployment_failed.json"
            ),
        }
    )
    bindings.update(
        {
            "calendar_sha256": _payload_file_hash(calendar),
            "observer_launchd_sha256": _payload_file_hash(observer),
            "delivery_launchd_sha256": _payload_file_hash(dispatcher),
            "deployment_packet_sha256": _file_hash(deployment_path),
            "artifact_paths": paths,
        }
    )
    parent_builder = (
        build_complete_day_parent_packet
        if complete_day
        else build_remaining_window_parent_packet
    )
    parent = parent_builder(
        trading_day=args.trading_day,
        night_session_date=args.night_session_date,
        generated_at=datetime.now(UTC),
        activation_deadline=args.activation_deadline,
        bindings=bindings,
    )
    request = {
        "schema_version": 1,
        "request_type": (
            "htdy_s6_10_complete_day_approval_c2_request"
            if complete_day
            else "htdy_s6_10_remaining_window_approval_c2_request"
        ),
        "decision": "pending",
        "parent_packet_hash": parent["packet_hash"],
        "trading_day": args.trading_day.isoformat(),
        "activation_deadline": args.activation_deadline.isoformat(),
        "max_wecom_notifications": 23,
        "max_attempts_per_event": 3,
        "global_wechat_autosend": False,
        "scope": (
            "one complete DCE trading day with 23 confirmed closes"
            if complete_day
            else "activation-bound remainder of one DCE trading day"
        ),
        "complete_trading_day_claim_allowed": complete_day,
        "signature_namespace": "guiyi-htdy-s610",
        "signature_principal": "guiyi-owner",
    }
    request["request_hash"] = canonical_hash(request)
    artifacts.update(
        {
            "parent_packet.json": parent,
            "bound_current_bindings.json": bindings,
            "approval_c2_request.json": request,
        }
    )
    for name, payload in artifacts.items():
        _publish(output / name, payload)
    print(
        json.dumps(
            {
                "status": "prepared",
                "parent_hash": parent["packet_hash"],
                "activation_deadline": parent["activation_deadline"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _activate(args: argparse.Namespace) -> int:
    parent = _load(args.parent)
    receipt = _load(args.approval_c2_receipt)
    now = datetime.now(UTC)
    _verify_signed_c2(
        parent=parent,
        approval_hash=args.approval_hash,
        receipt=receipt,
        receipt_path=args.approval_c2_receipt,
        receipt_hash=args.approval_c2_hash,
        signature_path=args.approval_c2_signature,
        signers_path=args.approved_signers,
    )
    approval_time = datetime.fromisoformat(str(receipt["approved_at"]))
    provisional = build_activation_receipt(
        parent_packet=parent,
        activated_at=now,
    )
    verify_remaining_window_approval_times(
        parent_packet=parent,
        activation_receipt=provisional,
        approved_at=approval_time,
    )
    _publish(args.output, provisional)
    print(
        json.dumps(
            {
                "status": "activated",
                "activation_receipt_hash": provisional["receipt_hash"],
                "first_expected_bucket_end": provisional[
                    "first_expected_bucket_end"
                ],
                "expected_confirmed_15m_closes": provisional[
                    "expected_confirmed_15m_closes"
                ],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _verify_signed_c2(
    *,
    parent: dict[str, Any],
    approval_hash: str,
    receipt: dict[str, Any],
    receipt_path: Path,
    receipt_hash: str,
    signature_path: Path,
    signers_path: Path,
) -> None:
    from app.services.htdy_s6_10_stability import (
        _file_sha256,
        _verify_approved_signers_trust_root,
        _verify_ssh_signature,
    )

    if (
        parent.get("packet_hash") != approval_hash
        or canonical_hash(parent) != approval_hash
        or receipt.get("schema_version") != 1
        or receipt.get("approval") != "Approval C2"
        or receipt.get("decision") != "approved"
        or receipt.get("parent_packet_hash") != approval_hash
        or receipt.get("trading_day") != parent["trading_days"][0]
        or receipt.get("max_wecom_notifications") != 23
        or receipt.get("max_attempts_per_event") != 3
        or receipt.get("global_wechat_autosend") is not False
        or receipt.get("receipt_hash") != receipt_hash
        or canonical_hash(receipt) != receipt_hash
        or _file_sha256(signers_path)
        != parent["bindings"]["approval_c2_approved_signers_sha256"]
        or not _verify_approved_signers_trust_root(signers_path)
        or not _verify_ssh_signature(
            receipt_path.read_bytes(),
            signature_path,
            signers_path,
        )
    ):
        raise ValueError("approval_c2_receipt_invalid")


def _service_identity(service: str) -> dict[str, Any]:
    template = (
        ROOT
        / "deploy"
        / "launchd"
        / f"com.guiyi.quant-htdy-s610-one-day-{service}.plist.template"
    )
    runner = ROOT / "scripts" / f"run-htdy-s610-one-day-{service}.sh"
    return {
        "schema_version": 1,
        "identity": f"s6_10_schema_v7_decision_close_{service}",
        "launchd_label": (
            f"com.guiyi.quant-htdy-s610-one-day-{service}"
        ),
        "activation_receipt_required": True,
        "maximum_events": 23,
        "max_attempts_per_event": 3,
        "global_autosend_required": False,
        "template_path": str(template.resolve()),
        "template_sha256": _file_hash(template),
        "runner_path": str(runner.resolve()),
        "runner_sha256": _file_hash(runner),
    }


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


def _refresh_bindings(bindings: dict[str, Any]) -> dict[str, Any]:
    from dotenv import dotenv_values
    from sqlalchemy import text

    runtime_root = Path(
        str((bindings.get("artifact_paths") or {}).get("runtime_root") or "")
    )
    if not runtime_root.is_dir():
        raise ValueError("runtime_root_missing")
    pre_commit = _git(runtime_root, "rev-parse", "HEAD")
    pre_tree = git_tree_binding_sha256(
        _git(runtime_root, "rev-parse", "HEAD^{tree}")
    )
    runtime_env = Path(
        str(
            os.environ.get("GUIYI_RUNTIME_ENV")
            or Path.home()
            / "Library/Application Support/GuiyiQuant/project.env"
        )
    )
    values = {
        str(key): str(value)
        for key, value in dotenv_values(runtime_env).items()
        if value is not None
    }
    os.environ.update(values)
    old_enable_path = Path(
        str(
            values.get(
                "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET"
            )
            or ""
        )
    )
    old_enable_hash = str(
        values.get("GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH") or ""
    )
    if not old_enable_path.is_file():
        raise ValueError("pre_activation_s607_enable_packet_missing")
    old_enable = _load(old_enable_path)
    from app.services.rqdata_ingest.jm_historical_catchup import (
        canonical_packet_hash as s607_packet_hash,
    )

    if (
        old_enable.get("packet_hash") != old_enable_hash
        or s607_packet_hash(old_enable) != old_enable_hash
    ):
        raise ValueError("pre_activation_s607_enable_packet_invalid")
    rollback_runtime_commit = str(
        ((old_enable.get("bound_facts") or {}).get("git") or {}).get(
            "commit"
        )
        or ""
    )
    rollback_runtime_tree = git_tree_binding_sha256(
        _git(ROOT, "rev-parse", f"{rollback_runtime_commit}^{{tree}}")
    )
    from app.db.session import SessionLocal
    from app.services.htdy_s6_10_runtime_support import (
        refresh_one_day_preapproval_bindings,
    )

    with SessionLocal() as session:
        session.execute(text("SET TRANSACTION READ ONLY"))
        refreshed = refresh_one_day_preapproval_bindings(
            session,
            bindings=bindings,
        )
        session.rollback()
    refreshed["pre_activation_runtime_commit"] = pre_commit
    refreshed["pre_activation_runtime_tree"] = pre_tree
    refreshed["rollback_runtime_commit"] = rollback_runtime_commit
    refreshed["rollback_runtime_tree"] = rollback_runtime_tree
    artifact_paths = dict(refreshed.get("artifact_paths") or {})
    artifact_paths["pre_activation_s6_07_enable_packet"] = str(
        old_enable_path.resolve(strict=True)
    )
    refreshed["artifact_paths"] = artifact_paths
    refreshed["pre_activation_s6_07_enable_packet_sha256"] = _file_hash(
        old_enable_path
    )
    refreshed["pre_activation_s6_07_enable_hash"] = old_enable_hash
    return refreshed


def _git_status(root: Path) -> str:
    return subprocess.run(
        ("git", "-c", "core.fsmonitor=false", "status", "--porcelain=v1"),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _git(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-c", "core.fsmonitor=false", *arguments),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


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
    return hashlib.sha256(
        (
            json.dumps(
                payload,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    ).hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
