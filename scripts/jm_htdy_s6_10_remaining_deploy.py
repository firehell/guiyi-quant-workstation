#!/usr/bin/env python3
"""Single schema-v6 deployment entry; all failures close signal delivery."""

from __future__ import annotations

import argparse
from datetime import UTC, date, datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Any, Callable
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "quant-api"))
sys.path.insert(0, str(ROOT / "packages" / "quant-core"))

AFTER_MARKET_RESTORE_WAIT_SECONDS = 300
AFTER_MARKET_LOCK_KEY = "guiyi:eod:jm:scheduler:singleton"
AFTER_MARKET_HEARTBEAT_KEY = "guiyi:eod:jm:scheduler:heartbeat"
SIGNAL_RUNTIME_ACTIVATION_ATTEMPTS = 90

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
    mapping_receipt = _prepare_c2_mapping(args)
    context = _preflight(args)
    context["mapping_receipt"] = mapping_receipt
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
        != "s6_10_schema_v7_code_only_deployment"
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
    observed = _collect_bindings(
        args,
        parent,
        require_activation_receipt=False,
    )
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
        observed = _collect_bindings(
            args,
            parent,
            require_activation_receipt=False,
        )
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
            "receipt_type": "htdy_s6_10_schema_v7_code_only_deployment",
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
            "mapping_receipt": context["mapping_receipt"],
            "rollback": False,
            "completed_at": datetime.now(UTC).isoformat(),
        }
        receipt["receipt_hash"] = canonical_hash(receipt)
        _publish(args.deployment_receipt, receipt)

    def verify_ready() -> None:
        context["current_step"] = "verify_activation_ready"
        verify_remaining_window_bindings(
            expected=parent["bindings"],
            observed=_collect_bindings(
                args,
                parent,
                require_activation_receipt=False,
            ),
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
        observed = _collect_bindings(
            args,
            parent,
            require_activation_receipt=False,
        )
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
        _restore_after_market_service(
            runtime,
            environment=environment,
            expected_packet=Path(enable_packet),
            expected_hash=str(enable_hash),
            diagnostic_path=(
                args.output_dir / f"{step_name}_diagnostic.json"
            ),
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
                "--arm",
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
        "activate_s610": command(
            "activate_s610",
            [
                "bash",
                str(runtime / "scripts/configure-htdy-s610-one-day-runtime.sh"),
                "--activate",
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
    deadline: float | None = None,
) -> None:
    """Bound the launchctl bootout/bootstrap race without hiding failure."""

    last_error: BaseException | None = None
    for attempt in range(attempts):
        try:
            timeout_seconds = (
                _remaining_seconds(
                    deadline,
                    error_type="after_market_restore_timeout",
                )
                if deadline is not None
                else None
            )
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
                timeout_seconds=timeout_seconds,
            )
            return
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                if deadline is None:
                    time.sleep(1)
                else:
                    remaining = _remaining_seconds(
                        deadline,
                        error_type="after_market_restore_timeout",
                    )
                    time.sleep(min(1, remaining))
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
    # A killed scheduler can leave its Redis singleton lease alive for up to
    # 60 seconds.  Wait beyond that lease so the replacement process can
    # acquire it and publish a heartbeat bound to the new authorization.
    for _attempt in range(SIGNAL_RUNTIME_ACTIVATION_ATTEMPTS):
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


def _after_market_redis_connection(
    environment: dict[str, str],
    *,
    timeout_seconds: float,
) -> Any:
    from redis import Redis

    io_timeout = min(2.0, timeout_seconds)
    redis_url = str(environment.get("REDIS_URL") or "").strip()
    redis_password = str(
        environment.get("REDIS_PASSWORD")
        or environment.get("POSTGRES_PASSWORD")
        or ""
    )
    if not redis_url or redis_url == "redis://127.0.0.1:6379/0":
        return Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            password=redis_password or None,
            socket_connect_timeout=io_timeout,
            socket_timeout=io_timeout,
        )
    return Redis.from_url(
        redis_url,
        socket_connect_timeout=io_timeout,
        socket_timeout=io_timeout,
    )


def _remaining_seconds(
    deadline: float,
    *,
    error_type: str,
) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise RuntimeError(error_type)
    return remaining


def _wait_after_market_lock_release(
    environment: dict[str, str],
    *,
    deadline: float,
    poll_interval_seconds: float = 1,
    redis_factory: Callable[..., Any] | None = None,
) -> None:
    """Wait for the prior scheduler lease; ownership is never overridden."""

    from redis.exceptions import RedisError

    selected_redis_factory = (
        redis_factory or _after_market_redis_connection
    )
    while True:
        remaining = _remaining_seconds(
            deadline,
            error_type="after_market_lock_release_timeout",
        )
        try:
            redis_connection = selected_redis_factory(
                environment,
                timeout_seconds=remaining,
            )
            if not bool(
                redis_connection.exists(AFTER_MARKET_LOCK_KEY)
            ):
                return
        except (OSError, TimeoutError, RedisError):
            pass
        remaining = _remaining_seconds(
            deadline,
            error_type="after_market_lock_release_timeout",
        )
        time.sleep(min(poll_interval_seconds, remaining))


def _read_after_market_heartbeat(
    redis_connection: Any,
) -> dict[str, Any]:
    raw = redis_connection.get(AFTER_MARKET_HEARTBEAT_KEY)
    if raw is None:
        raise ValueError("after_market_heartbeat_missing")
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    payload = json.loads(str(raw))
    if not isinstance(payload, dict):
        raise ValueError("after_market_heartbeat_invalid")
    return payload


def _restore_after_market_service(
    runtime: Path,
    *,
    environment: dict[str, str],
    expected_packet: Path,
    expected_hash: str,
    timeout_seconds: float = AFTER_MARKET_RESTORE_WAIT_SECONDS,
    diagnostic_path: Path | None = None,
) -> None:
    """Restore one authorized scheduler inside one bounded deadline."""

    deadline = time.monotonic() + timeout_seconds
    _run(
        [
            "bash",
            str(runtime / "scripts/install-after-market-scheduler.sh"),
            "--bootout",
        ],
        environment=environment,
        timeout_seconds=_remaining_seconds(
            deadline,
            error_type="after_market_restore_timeout",
        ),
    )
    _remaining_seconds(
        deadline,
        error_type="after_market_restore_timeout",
    )
    _wait_after_market_lock_release(
        environment,
        deadline=deadline,
    )
    configure_timeout = _remaining_seconds(
        deadline,
        error_type="after_market_restore_timeout",
    )
    _run(
        [
            "bash",
            str(runtime / "scripts/configure-after-market-automation.sh"),
            "--enable",
            "--approval-packet",
            str(expected_packet),
            "--approval-hash",
            expected_hash,
        ],
        environment=environment,
        timeout_seconds=configure_timeout,
    )
    _run(
        [
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/com.guiyi.quant-api",
        ],
        environment=environment,
        timeout_seconds=_remaining_seconds(
            deadline,
            error_type="after_market_restore_timeout",
        ),
    )
    minimum_heartbeat_at = datetime.now(UTC)
    _install_after_market_with_retry(
        runtime,
        environment=environment,
        deadline=deadline,
    )

    def direct_heartbeat_probe() -> dict[str, Any]:
        remaining = _remaining_seconds(
            deadline,
            error_type="after_market_restore_timeout",
        )
        return _read_after_market_heartbeat(
            _after_market_redis_connection(
                environment,
                timeout_seconds=remaining,
            )
        )

    _verify_after_market(
        runtime,
        expected_packet=expected_packet,
        expected_hash=expected_hash,
        deadline=deadline,
        heartbeat_probe=direct_heartbeat_probe,
        minimum_heartbeat_at=minimum_heartbeat_at,
        diagnostic_path=diagnostic_path,
    )


def _after_market_heartbeat_owner_is_valid(
    heartbeat: dict[str, Any],
    *,
    launchd_pid: int,
    now: datetime,
    minimum_heartbeat_at: datetime | None,
) -> bool:
    try:
        heartbeat_at = datetime.fromisoformat(
            str(heartbeat["generated_at"])
        )
    except (KeyError, TypeError, ValueError):
        return False
    pid = heartbeat.get("pid")
    if (
        heartbeat_at.tzinfo is None
        or heartbeat_at.utcoffset() is None
        or isinstance(pid, bool)
        or not isinstance(pid, int)
        or pid <= 0
        or pid != launchd_pid
        or heartbeat.get("status")
        not in {
            "running",
            "idle",
            "success",
            "retry_wait",
            "waiting_provider",
        }
        or heartbeat.get("lock_status") != "held"
    ):
        return False
    age_seconds = (now - heartbeat_at).total_seconds()
    return 0 <= age_seconds <= 180 and (
        minimum_heartbeat_at is None
        or heartbeat_at >= minimum_heartbeat_at
    )


def _publish_after_market_restore_diagnostic(
    path: Path,
    *,
    status: str,
    expected_packet: Path,
    expected_hash: str,
    minimum_heartbeat_at: datetime | None,
    observation: dict[str, Any],
) -> None:
    diagnostic = {
        "schema_version": 1,
        "receipt_type": "s6_10_after_market_restore_diagnostic",
        "status": status,
        "expected_packet": str(expected_packet),
        "expected_authorization_hash": expected_hash,
        "minimum_heartbeat_at": (
            minimum_heartbeat_at.isoformat()
            if minimum_heartbeat_at is not None
            else None
        ),
        **observation,
    }
    diagnostic["diagnostic_hash"] = canonical_hash(diagnostic)
    _publish(path, diagnostic)


def _normalized_diagnostic_token(
    value: Any,
    *,
    allowed: frozenset[str],
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and value in allowed:
        return value
    return "invalid"


def _normalized_diagnostic_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 64:
        return "invalid"
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "invalid"
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return "invalid"
    return parsed.isoformat()


def _verify_after_market(
    runtime: Path,
    *,
    expected_packet: Path,
    expected_hash: str,
    timeout_seconds: float = AFTER_MARKET_RESTORE_WAIT_SECONDS,
    poll_interval_seconds: float = 1,
    heartbeat_probe: Callable[[], dict[str, Any]] | None = None,
    minimum_heartbeat_at: datetime | None = None,
    deadline: float | None = None,
    diagnostic_path: Path | None = None,
) -> None:
    from redis.exceptions import RedisError

    if deadline is None:
        deadline = time.monotonic() + timeout_seconds
    if heartbeat_probe is None:
        redis_environment = {
            **os.environ,
            **_runtime_env_values(),
        }

        def direct_heartbeat_probe() -> dict[str, Any]:
            remaining = _remaining_seconds(
                deadline,
                error_type="after_market_restore_unverified",
            )
            return _read_after_market_heartbeat(
                _after_market_redis_connection(
                    redis_environment,
                    timeout_seconds=remaining,
                )
            )

        heartbeat_probe = direct_heartbeat_probe
    last_observation: dict[str, Any] = {}
    while True:
        if deadline - time.monotonic() <= 0:
            break
        values = _runtime_env_values()
        packet_matches = (
            values.get(
                "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_PACKET"
            )
            == str(expected_packet)
        )
        authorization_hash_matches = (
            values.get(
                "GUIYI_AFTER_MARKET_AUTOMATION_APPROVAL_HASH"
            )
            == expected_hash
        )
        enabled = (
            str(
                values.get("GUIYI_AFTER_MARKET_AUTOMATION_ENABLED")
                or ""
            ).lower()
            == "true"
        )
        env_matches = (
            packet_matches
            and authorization_hash_matches
            and enabled
        )
        last_observation = {
            "sampled_at": datetime.now(UTC).isoformat(),
            "environment": {
                "enabled": enabled,
                "packet_matches": packet_matches,
                "authorization_hash_matches": (
                    authorization_hash_matches
                ),
                "matches": env_matches,
            },
            "launchd": {
                "running": False,
                "pid": None,
                "returncode": None,
                "error_type": None,
            },
            "api": {
                "reachable": False,
                "enabled": None,
                "status": None,
                "authorization_hash_matches": False,
                "error_type": None,
            },
            "heartbeat": {
                "available": False,
                "status": None,
                "pid": None,
                "lock_status": None,
                "generated_at": None,
                "owner_valid": False,
                "error_type": None,
            },
            "healthy": False,
        }
        try:
            launchd_timeout = _remaining_seconds(
                deadline,
                error_type="after_market_restore_unverified",
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
                timeout=launchd_timeout,
            )
        except subprocess.TimeoutExpired:
            launchd = subprocess.CompletedProcess(
                args=(),
                returncode=1,
                stdout="",
                stderr="",
            )
            last_observation["launchd"][
                "error_type"
            ] = "TimeoutExpired"
        except RuntimeError as exc:
            last_observation["launchd"][
                "error_type"
            ] = type(exc).__name__
            if diagnostic_path is not None:
                _publish_after_market_restore_diagnostic(
                    diagnostic_path,
                    status="failed",
                    expected_packet=expected_packet,
                    expected_hash=expected_hash,
                    minimum_heartbeat_at=minimum_heartbeat_at,
                    observation=last_observation,
                )
                setattr(
                    exc,
                    "restore_diagnostic_path",
                    str(diagnostic_path),
                )
            raise
        launchd_pid = re.search(
            r"(?m)^\s*pid\s*=\s*([1-9][0-9]*)\s*$",
            launchd.stdout,
        )
        launchd_pid_value = (
            int(launchd_pid.group(1))
            if launchd_pid is not None
            else None
        )
        launchd_running = (
            launchd.returncode == 0
            and "state = running" in launchd.stdout
            and launchd_pid_value is not None
        )
        last_observation["launchd"].update(
            {
                "running": launchd_running,
                "pid": launchd_pid_value,
                "returncode": launchd.returncode,
            }
        )
        healthy = False
        if env_matches and launchd_running:
            try:
                remaining = _remaining_seconds(
                    deadline,
                    error_type="after_market_restore_unverified",
                )
                with urllib.request.urlopen(
                    "http://127.0.0.1:8000/api/runtime/health",
                    timeout=min(2.0, remaining),
                ) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise TypeError("runtime_health_not_object")
                components = payload.get("components")
                component = (
                    components.get("after_market_scheduler")
                    if isinstance(components, dict)
                    else None
                )
                component_enabled = (
                    component.get("enabled")
                    if isinstance(component, dict)
                    else None
                )
                component_status = (
                    component.get("status")
                    if isinstance(component, dict)
                    else None
                )
                component_authorization_hash = (
                    component.get("authorization_hash")
                    if isinstance(component, dict)
                    else None
                )
                last_observation["api"].update(
                    {
                        "reachable": True,
                        "enabled": (
                            component_enabled
                            if isinstance(component_enabled, bool)
                            else None
                        ),
                        "status": _normalized_diagnostic_token(
                            component_status,
                            allowed=frozenset(
                                {
                                    "ok",
                                    "degraded",
                                    "failed",
                                    "disabled",
                                    "unknown",
                                }
                            ),
                        ),
                        "authorization_hash_matches": (
                            component_authorization_hash
                            == expected_hash
                        ),
                    }
                )
            except (
                KeyError,
                OSError,
                TimeoutError,
                TypeError,
                ValueError,
            ) as exc:
                last_observation["api"][
                    "error_type"
                ] = type(exc).__name__
                healthy = False
            except RuntimeError as exc:
                last_observation["api"][
                    "error_type"
                ] = type(exc).__name__
                last_observation["healthy"] = False
                if diagnostic_path is not None:
                    _publish_after_market_restore_diagnostic(
                        diagnostic_path,
                        status="failed",
                        expected_packet=expected_packet,
                        expected_hash=expected_hash,
                        minimum_heartbeat_at=minimum_heartbeat_at,
                        observation=last_observation,
                    )
                    setattr(
                        exc,
                        "restore_diagnostic_path",
                        str(diagnostic_path),
                    )
                raise
            if last_observation["api"]["reachable"]:
                try:
                    heartbeat = heartbeat_probe()
                    if not isinstance(heartbeat, dict):
                        raise TypeError("heartbeat_not_object")
                    owner_valid = _after_market_heartbeat_owner_is_valid(
                        heartbeat,
                        launchd_pid=launchd_pid_value,
                        now=datetime.now(UTC),
                        minimum_heartbeat_at=minimum_heartbeat_at,
                    )
                    heartbeat_pid = heartbeat.get("pid")
                    last_observation["heartbeat"].update(
                        {
                            "available": True,
                            "status": _normalized_diagnostic_token(
                                heartbeat.get("status"),
                                allowed=frozenset(
                                    {
                                        "running",
                                        "idle",
                                        "success",
                                        "retry_wait",
                                        "waiting_provider",
                                    }
                                ),
                            ),
                            "pid": (
                                heartbeat_pid
                                if isinstance(heartbeat_pid, int)
                                and not isinstance(heartbeat_pid, bool)
                                and heartbeat_pid > 0
                                else None
                            ),
                            "lock_status": (
                                _normalized_diagnostic_token(
                                    heartbeat.get("lock_status"),
                                    allowed=frozenset({"held"}),
                                )
                            ),
                            "generated_at": (
                                _normalized_diagnostic_timestamp(
                                    heartbeat.get("generated_at")
                                )
                            ),
                            "owner_valid": owner_valid,
                        }
                    )
                    healthy = (
                        isinstance(component, dict)
                        and component_enabled is True
                        and component_status == "ok"
                        and component_authorization_hash == expected_hash
                        and owner_valid
                    )
                except (
                    OSError,
                    TimeoutError,
                    TypeError,
                    ValueError,
                    RedisError,
                ) as exc:
                    last_observation["heartbeat"][
                        "error_type"
                    ] = type(exc).__name__
                    healthy = False
                except RuntimeError as exc:
                    last_observation["heartbeat"][
                        "error_type"
                    ] = type(exc).__name__
                    last_observation["healthy"] = False
                    if diagnostic_path is not None:
                        _publish_after_market_restore_diagnostic(
                            diagnostic_path,
                            status="failed",
                            expected_packet=expected_packet,
                            expected_hash=expected_hash,
                            minimum_heartbeat_at=minimum_heartbeat_at,
                            observation=last_observation,
                        )
                        setattr(
                            exc,
                            "restore_diagnostic_path",
                            str(diagnostic_path),
                        )
                    raise
        last_observation["healthy"] = healthy
        if env_matches and launchd_running and healthy:
            if diagnostic_path is not None:
                _publish_after_market_restore_diagnostic(
                    diagnostic_path,
                    status="passed",
                    expected_packet=expected_packet,
                    expected_hash=expected_hash,
                    minimum_heartbeat_at=minimum_heartbeat_at,
                    observation=last_observation,
                )
            return
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(poll_interval_seconds, remaining))
    error = RuntimeError("after_market_restore_unverified")
    if diagnostic_path is not None:
        _publish_after_market_restore_diagnostic(
            diagnostic_path,
            status="failed",
            expected_packet=expected_packet,
            expected_hash=expected_hash,
            minimum_heartbeat_at=minimum_heartbeat_at,
            observation=last_observation,
        )
        setattr(
            error,
            "restore_diagnostic_path",
            str(diagnostic_path),
        )
    raise error


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
    *,
    require_activation_receipt: bool = True,
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
            require_activation_receipt=require_activation_receipt,
        )
        session.rollback()
    return observed


def _prepare_c2_mapping(
    args: argparse.Namespace,
) -> dict[str, str]:
    """Commit exact rank-1 mapping after signed C2, before full preflight."""

    parent = _load(args.parent)
    deployment = _load(args.deployment_packet)
    output = args.output_dir.resolve(strict=True)
    paths = dict((parent.get("bindings") or {}).get("artifact_paths") or {})
    source_head = _git(ROOT, "rev-parse", "HEAD")
    runtime_values = _runtime_env_values()
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
    deadline = datetime.fromisoformat(
        str(parent.get("activation_deadline") or "")
    )
    now = datetime.now(UTC)
    if (
        parent.get("schema_version") != 7
        or parent.get("window_mode") != "complete_trading_day"
        or parent.get("complete_trading_day_claim_allowed") is not True
        or parent.get("packet_hash") != args.approval_hash
        or canonical_hash(parent) != args.approval_hash
        or args.parent.resolve(strict=True).parent != output
        or _git(ROOT, "status", "--porcelain=v1") != ""
        or source_head != parent["bindings"].get("source_commit")
        or deployment.get("packet_type")
        != "s6_10_schema_v7_code_only_deployment"
        or deployment.get("source_commit") != source_head
        or deployment.get("target_runtime_commit")
        != parent["bindings"].get("runtime_commit")
        or deployment.get("packet_hash") != canonical_hash(deployment)
        or args.deployment_packet.resolve(strict=True)
        != Path(str(paths.get("deployment_packet") or "")).resolve(
            strict=True
        )
        or approved_at.tzinfo is None
        or not approved_at.astimezone(UTC) < now < deadline.astimezone(UTC)
        or str(
            runtime_values.get("GUIYI_LIVE_SIGNAL_EVENTS_ENABLED")
            or ""
        ).lower()
        != "false"
        or str(
            runtime_values.get("GUIYI_HTDY_S610_BOUNDED_WECOM_ENABLED")
            or ""
        ).lower()
        != "false"
        or str(
            runtime_values.get("GUIYI_WECHAT_AUTOSEND_ENABLED") or ""
        ).lower()
        != "false"
    ):
        raise ValueError("c2_mapping_authorization_drift")

    runtime_root = Path(str(paths.get("runtime_root") or ""))
    if (
        _git(runtime_root, "rev-parse", "HEAD")
        != parent["bindings"].get("pre_activation_runtime_commit")
        or _git(runtime_root, "status", "--porcelain=v1") != ""
    ):
        raise ValueError("c2_mapping_runtime_drift")

    trading_day = date.fromisoformat(str(parent["trading_days"][0]))
    mapping_root = output / "daily_mapping"
    if mapping_root.exists():
        if (
            mapping_root.is_symlink()
            or not mapping_root.is_dir()
            or mapping_root.resolve(strict=True).parent != output
        ):
            raise ValueError("c2_mapping_output_invalid")
    else:
        mapping_root.mkdir(mode=0o700)

    receipt_path = (
        mapping_root
        / trading_day.isoformat()
        / "mapping_receipt.json"
    )
    os.environ.update(runtime_values)
    from app.db.session import SessionLocal
    from app.services.htdy_s6_10_daily_mapping import (
        resolve_or_create_s610_c2_daily_mapping,
        verify_s610_c2_daily_mapping_receipt,
    )
    from app.services.htdy_s6_10_long_running_runtime_gate import (
        publish_daily_mapping_receipt_create_only,
    )

    with SessionLocal() as session:
        if receipt_path.exists():
            mapping_receipt = _load(receipt_path)
            result = verify_s610_c2_daily_mapping_receipt(
                session,
                receipt=mapping_receipt,
                trading_day=trading_day,
                approval_c2_parent_hash=args.approval_hash,
            )
            session.rollback()
        else:
            from app.services.rqdata_ingest.client import RqDataClient

            result = resolve_or_create_s610_c2_daily_mapping(
                session,
                trading_day=trading_day,
                approval_c2_parent_hash=args.approval_hash,
                client=RqDataClient(load_env_file=True),
                now=now,
            )
            session.commit()
            mapping_receipt = dict(result.receipt)
            publish_daily_mapping_receipt_create_only(
                mapping_receipt,
                root=mapping_root,
                trading_day=trading_day,
                create=True,
            )

    return {
        "path": str(receipt_path.resolve(strict=True)),
        "sha256": _file_sha256(receipt_path),
        "receipt_hash": str(mapping_receipt["receipt_hash"]),
        "mapping_sha256": str(result.mapping_sha256),
        "actual_contract": str(result.actual_contract),
    }


def _run(
    command: list[str],
    *,
    environment: dict[str, str],
    cwd: Path | None = None,
    timeout_seconds: float | None = None,
) -> None:
    subprocess.run(
        command,
        cwd=cwd or ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )


def _write_failure(
    args: argparse.Namespace,
    *,
    failed_step: str,
    error: BaseException,
) -> None:
    raw_rollback_failures = list(
        getattr(error, "rollback_failures", ()) or ()
    )
    rollback_failures: list[dict[str, Any]] = []
    for item in raw_rollback_failures:
        if not isinstance(item, dict):
            continue
        failure: dict[str, Any] = {
            "step": str(item.get("step") or ""),
            "error_type": str(item.get("error_type") or ""),
        }
        rollback_diagnostic = _restore_diagnostic_identity(
            args,
            str(item.get("restore_diagnostic_path") or ""),
        )
        if rollback_diagnostic is not None:
            failure["restore_diagnostic"] = rollback_diagnostic
        rollback_failures.append(failure)
    failed_rollback_steps = {
        str(item.get("step") or "")
        for item in rollback_failures
        if isinstance(item, dict)
    }
    diagnostic_identity = _restore_diagnostic_identity(
        args,
        str(getattr(error, "restore_diagnostic_path", "") or ""),
    )
    receipt = {
        "schema_version": 1,
        "receipt_type": "htdy_s6_10_schema_v7_deployment_failure",
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
        "restore_diagnostic": diagnostic_identity,
        "audit_records_deleted": False,
        "failed_at": datetime.now(UTC).isoformat(),
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    path = args.output_dir / "deployment_failed.json"
    if not path.exists():
        _publish(path, receipt)


def _restore_diagnostic_identity(
    args: argparse.Namespace,
    diagnostic_value: str,
) -> dict[str, str] | None:
    if not diagnostic_value:
        return None
    diagnostic_path = Path(diagnostic_value)
    if (
        diagnostic_path.is_file()
        and diagnostic_path.parent.resolve(strict=True)
        == args.output_dir.resolve(strict=True)
    ):
        return {
            "path": str(diagnostic_path.resolve(strict=True)),
            "sha256": _file_sha256(diagnostic_path),
        }
    return None


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
