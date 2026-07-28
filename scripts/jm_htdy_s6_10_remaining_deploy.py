#!/usr/bin/env python3
"""Single schema-v6 deployment entry; all failures close signal delivery."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

from app.services.htdy_s6_10_remaining_deployment import (  # noqa: E402
    DeploymentStep,
    deployment_step_names,
    execute_deployment_steps,
    validate_source_context,
)
from app.services.htdy_s6_10_remaining_window import (  # noqa: E402
    build_activation_receipt,
    canonical_hash,
    verify_remaining_window_approval_times,
    verify_remaining_window_bindings,
    verify_activation_start_margin,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-deploy", action="store_true")
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--approval-hash", required=True)
    parser.add_argument("--approval-c2-receipt", type=Path, required=True)
    parser.add_argument("--approval-c2-hash", required=True)
    parser.add_argument("--approval-c2-signature", type=Path, required=True)
    parser.add_argument("--approved-signers", type=Path, required=True)
    parser.add_argument("--runtime-root", type=Path, required=True)
    parser.add_argument("--deployment-packet", type=Path, required=True)
    parser.add_argument("--deployment-receipt", type=Path, required=True)
    parser.add_argument("--s607-rebind-packet", type=Path, required=True)
    parser.add_argument("--s607-rebind-hash", required=True)
    parser.add_argument("--s607-rebind-receipt", type=Path, required=True)
    parser.add_argument("--s607-final-receipt", type=Path, required=True)
    parser.add_argument(
        "--database-recovery-receipt",
        type=Path,
        required=True,
    )
    parser.add_argument("--s607-enable-packet", type=Path, required=True)
    parser.add_argument("--s607-enable-hash", required=True)
    parser.add_argument("--activation-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.confirm_deploy:
        raise ValueError("--confirm-deploy required")
    context = _preflight(args)
    commands = _commands(args, context)

    def runner(step: DeploymentStep) -> None:
        action = commands[step.name]
        action()

    success = execute_deployment_steps(
        steps=tuple(DeploymentStep(name) for name in deployment_step_names()),
        rollback_steps=(
            DeploymentStep("rollback_stop_s610"),
            DeploymentStep("rollback_disable_s610"),
            DeploymentStep("rollback_runtime"),
            DeploymentStep("rollback_restore_after_market"),
        ),
        runner=runner,
        failure_recorder=lambda error: _write_failure(
            args,
            failed_step=str(
                getattr(error, "deployment_step", None) or "unknown"
            ),
            error=error,
        ),
    )
    if not success:
        failure_path = args.output_dir / "deployment_failed.json"
        failure_status = str(
            _load(failure_path).get("status") or "rollback_incomplete"
        )
        print(
            json.dumps(
                {
                    "status": failure_status,
                    "failure_receipt": str(failure_path),
                }
            )
        )
        return 1
    print(
        json.dumps(
            {
                "status": "activated",
                "parent_hash": args.approval_hash,
                "activation_receipt": str(args.activation_receipt),
            },
            sort_keys=True,
        )
    )
    return 0


def _preflight(args: argparse.Namespace) -> dict[str, Any]:
    parent = _load(args.parent)
    deployment = _load(args.deployment_packet)
    paths = dict((parent.get("bindings") or {}).get("artifact_paths") or {})
    source_root = Path(str(paths.get("source_root") or ""))
    validate_source_context(
        actual_source_root=ROOT,
        orchestrator_source_root=source_root,
    )
    deployment_receipt_path = Path(
        str(
            (deployment.get("output_scope") or {}).get(
                "deployment_receipt_path"
            )
            or ""
        )
    )
    runtime_values = _runtime_env_values()
    from app.services.rqdata_ingest.jm_historical_catchup import (
        canonical_packet_hash as s607_packet_hash,
    )
    rollback_eod_packet = Path(
        str(
            paths.get("pre_activation_s6_07_enable_packet") or ""
        )
    )
    rollback_eod_hash = str(
        parent["bindings"].get("pre_activation_s6_07_enable_hash")
        or ""
    )
    expected_paths = {
        args.deployment_packet: paths.get("deployment_packet"),
        args.s607_rebind_packet: paths.get("s6_07_rebind_packet"),
        args.s607_enable_packet: paths.get("s6_07_enable_packet"),
        args.activation_receipt: paths.get("activation_receipt"),
        args.deployment_receipt: paths.get("deployment_receipt"),
    }
    bound_failure_receipt = Path(
        str(paths.get("deployment_failure_receipt") or "")
    )
    rollback_tree = hashlib.sha256(
        _git(
            ROOT,
            "rev-parse",
            f"{parent['bindings'].get('rollback_runtime_commit')}^{{tree}}",
        ).encode("ascii")
    ).hexdigest()
    if _git(ROOT, "status", "--porcelain=v1") != "":
        raise ValueError("source_checkout_not_clean")
    if (
        _git(ROOT, "rev-parse", "HEAD")
        != parent["bindings"]["source_commit"]
        or parent.get("packet_hash") != args.approval_hash
        or canonical_hash(parent) != args.approval_hash
        or deployment.get("packet_type")
        != "s6_10_schema_v6_code_only_deployment"
        or _file_sha256(args.deployment_packet)
        != parent["bindings"]["deployment_packet_sha256"]
        or deployment.get("packet_hash") != canonical_hash(deployment)
        or args.runtime_root.resolve(strict=True)
        != Path(str(paths.get("runtime_root") or "")).resolve(strict=True)
        or args.deployment_receipt.resolve(strict=False)
        != deployment_receipt_path.resolve(strict=False)
        or args.output_dir.resolve(strict=True)
        != bound_failure_receipt.parent.resolve(strict=True)
        or any(
            supplied.resolve(strict=False)
            != Path(str(bound or "")).resolve(strict=False)
            for supplied, bound in expected_paths.items()
        )
        or _load(args.s607_rebind_packet).get("packet_hash")
        != args.s607_rebind_hash
        or canonical_hash(_load(args.s607_rebind_packet))
        != args.s607_rebind_hash
        or _load(args.s607_enable_packet).get("packet_hash")
        != args.s607_enable_hash
        or s607_packet_hash(_load(args.s607_enable_packet))
        != args.s607_enable_hash
        or _file_sha256(rollback_eod_packet)
        != parent["bindings"].get(
            "pre_activation_s6_07_enable_packet_sha256"
        )
        or _load(rollback_eod_packet).get("packet_hash")
        != rollback_eod_hash
        or s607_packet_hash(_load(rollback_eod_packet))
        != rollback_eod_hash
        or str(
            (
                (
                    _load(rollback_eod_packet).get("bound_facts")
                    or {}
                ).get("git")
                or {}
            ).get("commit")
            or ""
        )
        != parent["bindings"].get("rollback_runtime_commit")
        or runtime_values.get(
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET"
        )
        != str(rollback_eod_packet)
        or runtime_values.get(
            "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH"
        )
        != rollback_eod_hash
        or rollback_tree
        != parent["bindings"].get("rollback_runtime_tree")
    ):
        raise ValueError("deployment_preflight_drift")
    from jm_htdy_s6_10_remaining_window_gate import _verify_signed_c2

    receipt = _load(args.approval_c2_receipt)
    _verify_signed_c2(
        parent=parent,
        approval_hash=args.approval_hash,
        receipt=receipt,
        receipt_path=args.approval_c2_receipt,
        receipt_hash=args.approval_c2_hash,
        signature_path=args.approval_c2_signature,
        signers_path=args.approved_signers,
    )
    approved_at = datetime.fromisoformat(str(receipt["approved_at"]))
    if approved_at.tzinfo is None or approved_at >= datetime.now(
        approved_at.tzinfo
    ):
        raise ValueError("approval_c2_time_invalid")
    observed = _collect_bindings(args, parent)
    verify_remaining_window_bindings(
        expected=parent["bindings"],
        observed=observed,
        phase="pre_activation",
    )
    return {
        "parent": parent,
        "deployment": deployment,
        "approval": receipt,
        "rollback_runtime_commit": parent["bindings"][
            "rollback_runtime_commit"
        ],
        "rollback_eod_packet": rollback_eod_packet,
        "rollback_eod_hash": rollback_eod_hash,
        "pre_bindings": observed,
        "current_step": None,
    }


def _commands(
    args: argparse.Namespace,
    context: dict[str, Any],
) -> dict[str, Any]:
    parent = context["parent"]
    runtime = args.runtime_root
    environment = {
        **os.environ,
        "GUIYI_PROJECT_ROOT": str(runtime),
        "GUIYI_ALLOW_EXTERNAL_VOLUME_LAUNCHD": "1",
    }

    def command(name: str, values: list[str]) -> Any:
        def run() -> None:
            context["current_step"] = name
            _run(values, environment=environment)

        return run

    def pause_after_market() -> None:
        context["current_step"] = "pause_after_market"
        _run(
            [
                "bash",
                str(runtime / "scripts/install-after-market-scheduler.sh"),
                "--disable",
            ],
            environment=environment,
        )
        observed = _collect_bindings(args, parent)
        if observed["feature_flags"][
            "after_market_automation"
        ] is not False:
            raise ValueError("after_market_pause_failed")
        verify_remaining_window_bindings(
            expected=parent["bindings"],
            observed=observed,
            phase="pre_activation",
        )

    def write_deployment_receipt() -> None:
        context["current_step"] = "write_deployment_receipt"
        observed = context.get("runtime_switched")
        health = context.get("runtime_health")
        if not isinstance(observed, dict) or not isinstance(health, dict):
            raise ValueError("deployment_evidence_missing")
        receipt = {
            "schema_version": 1,
            "task_id": "JM-LIVE-STABILITY-S6-10",
            "receipt_type": "htdy_s6_10_schema_v6_code_only_deployment",
            "status": "completed",
            "approval_packet_hash": context["deployment"]["packet_hash"],
            "authorization_parent_hash": args.approval_hash,
            "target_commit": parent["bindings"]["runtime_commit"],
            "target_tree": parent["bindings"]["runtime_tree"],
            "database_unchanged": True,
            "flags_safe": True,
            "health_verified": True,
            "database_evidence_hash": canonical_hash(
                {
                    "database_revision": observed["database_revision"],
                    "profile_sha256": observed["profile_sha256"],
                    "baseline_counts": observed["baseline_counts"],
                    "baseline_hashes": observed["baseline_hashes"],
                    "baseline_max_ids": observed["baseline_max_ids"],
                }
            ),
            "feature_flags": observed["feature_flags"],
            "runtime_health": health,
            "rollback": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        _publish(args.deployment_receipt, receipt)

    def verify_ready() -> None:
        context["current_step"] = "verify_activation_ready"
        verify_remaining_window_bindings(
            expected=parent["bindings"],
            observed=_collect_bindings(args, parent),
            phase="activation_ready",
        )
        _verify_after_market(
            runtime,
            expected_packet=args.s607_enable_packet,
            expected_hash=args.s607_enable_hash,
        )

    def create_activation() -> None:
        context["current_step"] = "create_activation_receipt"
        activation = build_activation_receipt(
            parent_packet=parent,
            activated_at=datetime.now(UTC),
        )
        verify_remaining_window_approval_times(
            parent_packet=parent,
            activation_receipt=activation,
            approved_at=datetime.fromisoformat(
                str(context["approval"]["approved_at"])
            ),
        )
        _publish(args.activation_receipt, activation)

    def start_s610_services() -> None:
        context["current_step"] = "start_s610_services"
        _assert_activation_margin(args.activation_receipt)
        _run(
            [
                "bash",
                str(runtime / "scripts/install-htdy-s610-one-day-services.sh"),
                "--confirm-load",
            ],
            environment=environment,
        )
        for label in (
            "com.guiyi.quant-htdy-s610-one-day-observer",
            "com.guiyi.quant-htdy-s610-one-day-dispatcher",
        ):
            if not _launchd_running(label):
                raise RuntimeError("s610_service_not_running")
        _run(
            [
                "launchctl",
                "kickstart",
                "-k",
                (
                    f"gui/{os.getuid()}/"
                    "com.guiyi.quant-runtime-scheduler"
                ),
            ],
            environment=environment,
        )
        _wait_signal_runtime(
            expected_parent_hash=args.approval_hash,
        )
        verify_activation_start_margin(
            activation_receipt=_load(args.activation_receipt),
            now=datetime.now(UTC),
            minimum_seconds=0,
        )

    def rollback_stop_s610() -> None:
        context["current_step"] = "rollback_stop_s610"
        _run(
            [
                "bash",
                str(runtime / "scripts/install-htdy-s610-one-day-services.sh"),
                "--bootout",
            ],
            environment=environment,
        )
        for label in (
            "com.guiyi.quant-htdy-s610-one-day-observer",
            "com.guiyi.quant-htdy-s610-one-day-dispatcher",
        ):
            if _launchd_loaded(label):
                raise RuntimeError("s610_service_bootout_unverified")

    def rollback_disable_s610() -> None:
        context["current_step"] = "rollback_disable_s610"
        _run(
            [
                "bash",
                str(runtime / "scripts/configure-htdy-s610-one-day-runtime.sh"),
                "--disable",
            ],
            environment=environment,
        )
        values = _runtime_env_values()
        if (
            str(
                values.get("GUIYI_LIVE_SIGNAL_EVENTS_ENABLED")
                or ""
            ).lower()
            != "false"
            or str(
                values.get("GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED")
                or ""
            ).lower()
            != "false"
            or str(
                values.get("GUIYI_WECHAT_AUTOSEND_ENABLED") or ""
            ).lower()
            != "false"
        ):
            raise RuntimeError("s610_disable_unverified")

    def verify_post() -> None:
        context["current_step"] = "verify_post_activation"
        verify_remaining_window_bindings(
            expected=parent["bindings"],
            observed=_collect_bindings(args, parent),
            phase="post_activation",
        )
        _verify_runtime_health(runtime, environment)

    def switch_runtime() -> None:
        context["current_step"] = "switch_runtime"
        _run(
            [
                "git",
                "fetch",
                "--no-tags",
                str(ROOT),
                parent["bindings"]["runtime_commit"],
            ],
            cwd=runtime,
            environment=environment,
        )
        _run(
            [
                "git",
                "checkout",
                "--detach",
                parent["bindings"]["runtime_commit"],
            ],
            cwd=runtime,
            environment=environment,
        )

    def restart_core() -> None:
        context["current_step"] = "restart_core_runtime"
        _kickstart_core(environment)
        context["runtime_health"] = _verify_runtime_health(
            runtime,
            environment,
        )
        observed = _collect_bindings(args, parent)
        verify_remaining_window_bindings(
            expected=parent["bindings"],
            observed=observed,
            phase="runtime_switched",
        )
        context["runtime_switched"] = observed

    def restore_after_market(step_name: str) -> None:
        context["current_step"] = step_name
        if step_name == "rollback_restore_after_market":
            enable_packet = context["rollback_eod_packet"]
            enable_hash = context["rollback_eod_hash"]
        else:
            enable_packet = args.s607_enable_packet
            enable_hash = args.s607_enable_hash
        _run(
            [
                "bash",
                str(runtime / "scripts/configure-after-market-automation.sh"),
                "--enable",
                "--approval-packet",
                str(enable_packet),
                "--approval-hash",
                enable_hash,
            ],
            environment=environment,
        )
        _install_after_market_with_retry(
            runtime,
            environment=environment,
        )
        _verify_after_market(
            runtime,
            expected_packet=Path(enable_packet),
            expected_hash=str(enable_hash),
        )

    def rollback_runtime() -> None:
        context["current_step"] = "rollback_runtime"
        rollback_commit = context["rollback_runtime_commit"]
        _run(
            [
                "git",
                "fetch",
                "--no-tags",
                str(ROOT),
                rollback_commit,
            ],
            cwd=runtime,
            environment=environment,
        )
        _run(
            ["git", "checkout", "--detach", rollback_commit],
            cwd=runtime,
            environment=environment,
        )
        _kickstart_core(environment)
        _verify_runtime_health(runtime, environment)
        rollback_tree = hashlib.sha256(
            _git(runtime, "rev-parse", "HEAD^{tree}").encode("ascii")
        ).hexdigest()
        if (
            _git(runtime, "rev-parse", "HEAD") != rollback_commit
            or rollback_tree
            != parent["bindings"]["rollback_runtime_tree"]
            or _git(runtime, "status", "--porcelain=v1") != ""
        ):
            raise RuntimeError("rollback_runtime_identity_unverified")

    return {
        "stop_s610_services": command(
            "stop_s610_services",
            [
                "bash",
                str(runtime / "scripts/install-htdy-s610-one-day-services.sh"),
                "--bootout",
            ],
        ),
        "pause_after_market": pause_after_market,
        "switch_runtime": switch_runtime,
        "restart_core_runtime": restart_core,
        "write_deployment_receipt": write_deployment_receipt,
        "rebind_s607": command(
            "rebind_s607",
            [
                str(runtime / "services/quant-api/.venv/bin/python"),
                str(runtime / "scripts/jm_eod_automation_gate.py"),
                "--confirm-code-rebind",
                "--runtime-root",
                str(runtime),
                "--deployment-packet",
                str(args.deployment_packet),
                "--approval-packet",
                str(args.s607_rebind_packet),
                "--approval-hash",
                args.s607_rebind_hash,
                "--target-runtime-commit",
                parent["bindings"]["runtime_commit"],
                "--s6-07-final-receipt",
                str(args.s607_final_receipt),
                "--database-recovery-receipt",
                str(args.database_recovery_receipt),
                "--deployment-receipt",
                str(args.deployment_receipt),
                "--authorization-parent",
                str(args.parent),
                "--rebind-receipt-out",
                str(args.s607_rebind_receipt),
            ],
        ),
        "restore_after_market": lambda: restore_after_market(
            "restore_after_market"
        ),
        "verify_activation_ready": verify_ready,
        "create_activation_receipt": create_activation,
        "configure_s610": command(
            "configure_s610",
            [
                "bash",
                str(runtime / "scripts/configure-htdy-s610-one-day-runtime.sh"),
                "--enable",
                "--parent-packet",
                str(args.parent),
                "--approval-hash",
                args.approval_hash,
                "--approval-c2-receipt",
                str(args.approval_c2_receipt),
                "--approval-c2-hash",
                args.approval_c2_hash,
                "--approval-c2-signature",
                str(args.approval_c2_signature),
                "--approved-signers",
                str(args.approved_signers),
                "--output-dir",
                str(args.output_dir),
                "--activation-receipt",
                str(args.activation_receipt),
            ],
        ),
        "start_s610_services": start_s610_services,
        "verify_post_activation": verify_post,
        "rollback_stop_s610": rollback_stop_s610,
        "rollback_disable_s610": rollback_disable_s610,
        "rollback_runtime": rollback_runtime,
        "rollback_restore_after_market": lambda: restore_after_market(
            "rollback_restore_after_market"
        ),
    }


def _install_after_market_with_retry(
    runtime: Path,
    *,
    environment: dict[str, str],
    attempts: int = 3,
) -> None:
    """Bound the launchctl bootout/bootstrap race without hiding failure."""

    last_error: subprocess.CalledProcessError | None = None
    for attempt in range(attempts):
        try:
            _run(
                [
                    "bash",
                    str(
                        runtime
                        / "scripts/install-after-market-scheduler.sh"
                    ),
                    "--confirm-load",
                ],
                environment=environment,
            )
            return
        except subprocess.CalledProcessError as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("after_market_install_attempts_invalid")


def _kickstart_core(environment: dict[str, str]) -> None:
    for label in (
        "com.guiyi.quant-api",
        "com.guiyi.quant-runtime-scheduler",
    ):
        _run(
            [
                "launchctl",
                "kickstart",
                "-k",
                f"gui/{os.getuid()}/{label}",
            ],
            environment=environment,
        )


def _launchd_snapshot(label: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (
            "launchctl",
            "print",
            f"gui/{os.getuid()}/{label}",
        ),
        check=False,
        capture_output=True,
        text=True,
    )


def _launchd_loaded(label: str) -> bool:
    return _launchd_snapshot(label).returncode == 0


def _launchd_running(label: str) -> bool:
    snapshot = _launchd_snapshot(label)
    return (
        snapshot.returncode == 0
        and "state = running" in snapshot.stdout
        and re.search(
            r"(?m)^\s*pid\s*=\s*([1-9][0-9]*)\s*$",
            snapshot.stdout,
        )
        is not None
    )


def _wait_signal_runtime(*, expected_parent_hash: str) -> None:
    for _attempt in range(40):
        healthy = False
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/runtime/health",
                timeout=2,
            ) as response:
                payload = json.load(response)
            scheduler = (payload.get("components") or {}).get(
                "scheduler"
            )
            healthy = (
                isinstance(scheduler, dict)
                and scheduler.get("status") == "ok"
                and scheduler.get("signal_events_enabled") is True
                and scheduler.get("signal_event_gate_status")
                in {"authorized", "verified"}
                and scheduler.get("signal_event_authorization_hash")
                == expected_parent_hash
                and isinstance(
                    scheduler.get("heartbeat_age_seconds"),
                    int,
                )
                and 0 <= scheduler["heartbeat_age_seconds"] <= 180
            )
        except (OSError, TimeoutError, ValueError):
            healthy = False
        if healthy:
            return
        time.sleep(1)
    raise RuntimeError("signal_runtime_activation_unverified")


def _verify_runtime_health(
    runtime: Path,
    environment: dict[str, str],
) -> dict[str, str]:
    last_error: subprocess.CalledProcessError | None = None
    for _attempt in range(10):
        try:
            _run(
                [
                    "bash",
                    str(runtime / "scripts/engineering/runtime-health.sh"),
                    "--strict",
                ],
                environment=environment,
            )
            return {
                "status": "passed",
                "verified_at": datetime.now(UTC).isoformat(),
                "probe": "scripts/engineering/runtime-health.sh --strict",
            }
        except subprocess.CalledProcessError as exc:
            last_error = exc
            time.sleep(1)
    if last_error is not None:
        raise last_error
    raise RuntimeError("runtime_health_unavailable")


def _assert_activation_margin(activation_path: Path) -> None:
    verify_activation_start_margin(
        activation_receipt=_load(activation_path),
        now=datetime.now(UTC),
    )


def _verify_after_market(
    runtime: Path,
    *,
    expected_packet: Path,
    expected_hash: str,
) -> None:
    for _attempt in range(10):
        values = _runtime_env_values()
        env_matches = (
            values.get(
                "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET"
            )
            == str(expected_packet)
            and values.get(
                "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH"
            )
            == expected_hash
            and str(
                values.get("GUIYI_AFTER_MARKET_AUTOMATION_ENABLED")
                or ""
            ).lower()
            == "true"
        )
        launchd = subprocess.run(
            (
                "launchctl",
                "print",
                (
                    f"gui/{os.getuid()}/"
                    "com.guiyi.quant-after-market-scheduler"
                ),
            ),
            cwd=runtime,
            check=False,
            capture_output=True,
            text=True,
        )
        launchd_pid = re.search(
            r"(?m)^\s*pid\s*=\s*([1-9][0-9]*)\s*$",
            launchd.stdout,
        )
        launchd_running = (
            launchd.returncode == 0
            and "state = running" in launchd.stdout
            and launchd_pid is not None
        )
        healthy = False
        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8000/api/runtime/health",
                timeout=2,
            ) as response:
                payload = json.load(response)
            component = (payload.get("components") or {}).get(
                "after_market_scheduler"
            )
            heartbeat = (
                component.get("scheduler_heartbeat")
                if isinstance(component, dict)
                else None
            )
            healthy = (
                isinstance(component, dict)
                and component.get("enabled") is True
                and component.get("status") == "ok"
                and component.get("authorization_hash")
                == expected_hash
                and isinstance(heartbeat, dict)
                and heartbeat.get("health_status") == "ok"
                and isinstance(
                    heartbeat.get("heartbeat_age_seconds"),
                    int,
                )
                and 0
                <= heartbeat["heartbeat_age_seconds"]
                <= 180
            )
        except (OSError, TimeoutError, ValueError):
            healthy = False
        if env_matches and launchd_running and healthy:
            return
        time.sleep(1)
    raise RuntimeError("after_market_restore_unverified")


def _runtime_env_values() -> dict[str, str]:
    from dotenv import dotenv_values

    runtime_env_path = Path(
        str(
            os.environ.get("GUIYI_RUNTIME_ENV")
            or Path.home()
            / "Library/Application Support/GuiyiQuant/project.env"
        )
    )
    return {
        str(key): str(value)
        for key, value in dotenv_values(runtime_env_path).items()
        if value is not None
    }


def _collect_bindings(
    args: argparse.Namespace,
    parent: dict[str, Any],
) -> dict[str, Any]:
    runtime_values = _runtime_env_values()
    os.environ.update(runtime_values)
    from app.db.session import SessionLocal
    from app.services.htdy_s6_10_runtime_support import (
        collect_current_one_day_bindings,
    )

    with SessionLocal() as session:
        observed = collect_current_one_day_bindings(
            session,
            parent_packet=parent,
            parent_packet_path=args.parent,
            environ={**os.environ, **runtime_values},
        )
        session.rollback()
    return observed


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path | None = None,
) -> None:
    subprocess.run(
        command,
        cwd=cwd or ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )


def _write_failure(
    args: argparse.Namespace,
    *,
    failed_step: str,
    error: BaseException,
) -> None:
    rollback_failures = list(
        getattr(error, "rollback_failures", ()) or ()
    )
    failed_rollback_steps = {
        str(item.get("step") or "")
        for item in rollback_failures
        if isinstance(item, dict)
    }
    receipt = {
        "schema_version": 1,
        "receipt_type": "htdy_s6_10_schema_v6_deployment_failure",
        "status": (
            "rollback_incomplete"
            if rollback_failures
            else "failed_closed"
        ),
        "parent_packet_hash": args.approval_hash,
        "failed_step": failed_step,
        "error_type": type(error).__name__,
        "observer_dispatcher_unloaded": (
            "rollback_stop_s610" not in failed_rollback_steps
        ),
        "signal_and_dispatcher_authorization_disabled": (
            "rollback_disable_s610" not in failed_rollback_steps
        ),
        "runtime_restored": (
            "rollback_runtime" not in failed_rollback_steps
        ),
        "after_market_restored": (
            "rollback_restore_after_market"
            not in failed_rollback_steps
        ),
        "rollback_failures": rollback_failures,
        "audit_records_deleted": False,
        "failed_at": datetime.now(UTC).isoformat(),
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    path = args.output_dir / "deployment_failed.json"
    if not path.exists():
        _publish(path, receipt)


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


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ("git", "-c", "core.fsmonitor=false", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    os.umask(0o077)
    raise SystemExit(main())
