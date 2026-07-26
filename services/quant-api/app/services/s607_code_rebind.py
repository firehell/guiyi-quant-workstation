"""Execute the approved S6-07 code-only rebind without archive writes."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import time
from typing import Any
import urllib.request


LAUNCHD_LABEL = "com.guiyi.quant-after-market-scheduler"
DISABLED_HEALTH = {"status": "disabled", "enabled": False}
DATABASE_COUNT_KEYS = {
    "strategy_signals",
    "signal_events",
    "signal_notifications",
    "signal_scan_tasks",
    "orders",
    "trades",
    "review_notes",
    "backtest_tasks",
    "profile_bindings",
    "canonical_assets",
}
DATABASE_HASH_KEYS = {
    "backtest_state_sha256",
    "profile_bindings_sha256",
    "canonical_assets_sha256",
    "forbidden_tables_sha256",
}


def execute_confirmed_code_rebind(
    *,
    packet: Mapping[str, Any],
    deployment_receipt: Mapping[str, Any],
    runtime_root: Path,
    receipt_out: Path,
    runtime_probe: Callable[[Path], Mapping[str, Any]]
    | None = None,
    launchd_probe: Callable[[Path], Mapping[str, Any]]
    | None = None,
    state_probe: Callable[[], Mapping[str, Any]] | None = None,
    health_probe: Callable[[], Mapping[str, Any]] | None = None,
    restart_scheduler: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    from app.services.htdy_s6_08_approval_artifacts import (
        canonical_hash,
    )

    validate_deployment_receipt(packet, deployment_receipt)
    validate_receipt_destination(packet, receipt_out)
    runtime_probe = runtime_probe or collect_runtime_identity
    launchd_probe = launchd_probe or collect_launchd_identity
    state_probe = state_probe or collect_database_state
    health_probe = health_probe or collect_after_market_health
    restart_scheduler = (
        restart_scheduler or restart_after_market_scheduler
    )
    target_commit = str(packet.get("target_runtime_commit") or "")
    runtime_before = dict(runtime_probe(runtime_root))
    if (
        runtime_before.get("commit") != target_commit
        or runtime_before.get("tracked_clean") is not True
    ):
        raise RuntimeError("s6_07_rebind_runtime_drift")
    bound_launchd = packet.get("after_market_launchd")
    launchd_before = dict(launchd_probe(runtime_root))
    if not isinstance(bound_launchd, Mapping) or (
        launchd_binding(launchd_before) != dict(bound_launchd)
    ):
        raise RuntimeError("s6_07_rebind_launchd_drift")
    bound_health = packet.get("after_market_health")
    state_before = dict(state_probe())
    health_before = dict(health_probe())
    require_disabled_health(health_before)
    if health_before != bound_health:
        raise RuntimeError("s6_07_rebind_health_drift")
    loaded_before = bool(launchd_before.get("loaded"))
    previous_pid = launchd_before.get("pid")
    if loaded_before:
        if (
            not isinstance(previous_pid, int)
            or isinstance(previous_pid, bool)
            or previous_pid <= 0
        ):
            raise RuntimeError("s6_07_rebind_launchd_drift")
        restart_scheduler(str(packet["launchd_label"]))
        launchd_after = _wait_for_restarted_launchd(
            launchd_probe=launchd_probe,
            runtime_root=runtime_root,
            bound_launchd=dict(bound_launchd),
            previous_pid=previous_pid,
        )
    else:
        launchd_after = dict(launchd_probe(runtime_root))
        if launchd_binding(launchd_after) != dict(bound_launchd):
            raise RuntimeError("s6_07_rebind_launchd_drift")
    new_pid = launchd_after.get("pid")
    if loaded_before and (
        not isinstance(new_pid, int)
        or new_pid <= 0
        or new_pid == previous_pid
    ):
        raise RuntimeError("s6_07_rebind_restart_failed")
    if not loaded_before and launchd_after.get("loaded") is not False:
        raise RuntimeError("s6_07_rebind_unexpected_enable")
    runtime_after = dict(runtime_probe(runtime_root))
    state_after = dict(state_probe())
    health_after = dict(health_probe())
    require_disabled_health(health_after)
    if health_after != bound_health:
        raise RuntimeError("s6_07_rebind_health_drift")
    if runtime_after != runtime_before:
        raise RuntimeError("s6_07_rebind_runtime_drift")
    if state_after != state_before:
        raise RuntimeError("s6_07_rebind_state_drift")
    receipt: dict[str, Any] = {
        "schema_version": 1,
        "task_id": packet["task_id"],
        "status": "completed",
        "gate": "JM_EOD_AUTOMATION_CODE_REBIND_PASSED",
        "approval_packet_hash": packet["packet_hash"],
        "deployment_packet_hash": packet[
            "deployment_packet_sha256"
        ],
        "deployment_receipt_hash": canonical_hash(
            deployment_receipt
        ),
        "runtime_commit": target_commit,
        "scheduler_restart": {
            "label": packet["launchd_label"],
            "loaded_before": loaded_before,
            "loaded_after": bool(launchd_after.get("loaded")),
            "restart_performed": loaded_before,
            "previous_pid": previous_pid,
            "new_pid": new_pid,
        },
        "database_state": state_after,
        "database_unchanged": True,
        "health": health_after,
        "archive_rerun": False,
        "historical_receipt_modified": False,
        "watermark_modified": False,
        "asset_or_profile_modified": False,
        "completed_at": datetime.now(UTC).isoformat(),
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    write_create_only(receipt_out, receipt)
    return receipt


def validate_receipt_destination(
    packet: Mapping[str, Any],
    receipt_out: Path,
) -> None:
    binding = packet.get("rebind_receipt")
    if not isinstance(binding, Mapping):
        raise RuntimeError("s6_07_rebind_receipt_drift")
    resolved = receipt_out.resolve(strict=False)
    parent = resolved.parent
    bound_device = binding.get("parent_device")
    bound_inode = binding.get("parent_inode")
    try:
        parent_stat = parent.stat()
    except OSError as exc:
        raise RuntimeError("s6_07_rebind_receipt_drift") from exc
    if (
        resolved != Path(str(binding.get("path") or ""))
        or resolved.name != "s6_07_rebind_receipt.json"
        or resolved.exists()
        or parent.is_symlink()
        or isinstance(bound_device, bool)
        or not isinstance(bound_device, int)
        or isinstance(bound_inode, bool)
        or not isinstance(bound_inode, int)
        or int(parent_stat.st_dev) != bound_device
        or int(parent_stat.st_ino) != bound_inode
    ):
        raise RuntimeError("s6_07_rebind_receipt_drift")


def _wait_for_restarted_launchd(
    *,
    launchd_probe: Callable[[Path], Mapping[str, Any]],
    runtime_root: Path,
    bound_launchd: Mapping[str, Any],
    previous_pid: int,
    attempts: int = 30,
) -> dict[str, Any]:
    for attempt in range(attempts):
        current = dict(launchd_probe(runtime_root))
        binding = launchd_binding(current)
        if not _same_launchd_definition(binding, bound_launchd):
            raise RuntimeError("s6_07_rebind_launchd_drift")
        current_pid = current.get("pid")
        if (
            binding.get("loaded") is True
            and isinstance(current_pid, int)
            and not isinstance(current_pid, bool)
            and current_pid > 0
            and current_pid != previous_pid
        ):
            return current
        if attempt + 1 < attempts:
            time.sleep(0.2)
    raise RuntimeError("s6_07_rebind_restart_failed")


def _same_launchd_definition(
    actual: Mapping[str, Any],
    expected: Mapping[str, Any],
) -> bool:
    return all(
        actual.get(field) == expected.get(field)
        for field in (
            "label",
            "plist_path",
            "plist_sha256",
            "runner_path",
            "runner_sha256",
            "project_root",
        )
    )


def validate_deployment_receipt(
    packet: Mapping[str, Any],
    receipt: Mapping[str, Any],
) -> None:
    if (
        receipt.get("schema_version") != 1
        or receipt.get("task_id")
        != "JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY"
        or receipt.get("status") != "completed"
        or receipt.get("approval_packet_hash")
        != packet.get("deployment_packet_sha256")
        or receipt.get("target_commit")
        != packet.get("target_runtime_commit")
        or receipt.get("database_unchanged") is not True
        or receipt.get("flags_safe") is not True
        or receipt.get("health_verified") is not True
        or receipt.get("rollback") is not False
    ):
        raise RuntimeError("deployment_receipt_invalid")


def verify_code_rebind_receipt(
    receipt: Mapping[str, Any],
    *,
    packet: Mapping[str, Any],
    deployment_receipt: Mapping[str, Any],
) -> None:
    from app.services.htdy_s6_08_approval_artifacts import (
        canonical_hash,
    )

    validate_deployment_receipt(packet, deployment_receipt)
    payload = {
        str(key): value
        for key, value in receipt.items()
        if key != "receipt_hash"
    }
    scheduler = receipt.get("scheduler_restart")
    database_state = receipt.get("database_state")
    if (
        receipt.get("schema_version") != 1
        or receipt.get("task_id") != packet.get("task_id")
        or receipt.get("status") != "completed"
        or receipt.get("gate")
        != "JM_EOD_AUTOMATION_CODE_REBIND_PASSED"
        or receipt.get("approval_packet_hash")
        != packet.get("packet_hash")
        or receipt.get("deployment_packet_hash")
        != packet.get("deployment_packet_sha256")
        or receipt.get("deployment_receipt_hash")
        != canonical_hash(deployment_receipt)
        or receipt.get("runtime_commit")
        != packet.get("target_runtime_commit")
        or receipt.get("receipt_hash") != canonical_hash(payload)
        or not isinstance(scheduler, Mapping)
        or not isinstance(database_state, Mapping)
        or not _valid_database_state(database_state)
        or receipt.get("database_unchanged") is not True
        or receipt.get("health") != DISABLED_HEALTH
        or receipt.get("archive_rerun") is not False
        or receipt.get("historical_receipt_modified") is not False
        or receipt.get("watermark_modified") is not False
        or receipt.get("asset_or_profile_modified") is not False
        or not _valid_scheduler_result(scheduler)
        or not _aware_datetime(receipt.get("completed_at"))
    ):
        raise RuntimeError("s6_07_rebind_receipt_invalid")


def _valid_database_state(value: Mapping[str, Any]) -> bool:
    counts = value.get("counts")
    hashes = value.get("hashes")
    checkpoint_count = value.get("checkpoint_count")
    return (
        set(value)
        == {
            "database_revision",
            "counts",
            "hashes",
            "checkpoint_count",
            "checkpoint_sha256",
        }
        and value.get("database_revision") == "20260721_0025"
        and isinstance(counts, Mapping)
        and set(counts) == DATABASE_COUNT_KEYS
        and all(
            isinstance(item, int)
            and not isinstance(item, bool)
            and item >= 0
            for item in counts.values()
        )
        and isinstance(hashes, Mapping)
        and set(hashes) == DATABASE_HASH_KEYS
        and all(_valid_sha256(item) for item in hashes.values())
        and isinstance(checkpoint_count, int)
        and not isinstance(checkpoint_count, bool)
        and checkpoint_count >= 0
        and _valid_sha256(value.get("checkpoint_sha256"))
    )


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.lower()
        and all(character in "0123456789abcdef" for character in value)
    )


def _valid_scheduler_result(value: Mapping[str, Any]) -> bool:
    if (
        value.get("label") != LAUNCHD_LABEL
        or not isinstance(value.get("loaded_before"), bool)
        or not isinstance(value.get("loaded_after"), bool)
        or not isinstance(value.get("restart_performed"), bool)
    ):
        return False
    if value["restart_performed"] is False:
        return (
            value["loaded_before"] is False
            and value["loaded_after"] is False
            and value.get("previous_pid") is None
            and value.get("new_pid") is None
        )
    previous = value.get("previous_pid")
    current = value.get("new_pid")
    return (
        value["loaded_before"] is True
        and value["loaded_after"] is True
        and isinstance(previous, int)
        and not isinstance(previous, bool)
        and previous > 0
        and isinstance(current, int)
        and not isinstance(current, bool)
        and current > 0
        and current != previous
    )


def _aware_datetime(value: Any) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def collect_runtime_identity(runtime_root: Path) -> dict[str, Any]:
    commit = git_value(runtime_root, "rev-parse", "HEAD")
    tree = git_value(runtime_root, "rev-parse", "HEAD^{tree}")
    tracked = git_value(
        runtime_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    )
    return {
        "commit": commit,
        "tree_sha256": hashlib.sha256(tree.encode()).hexdigest(),
        "tracked_clean": tracked == "",
    }


def collect_launchd_identity(runtime_root: Path) -> dict[str, Any]:
    plist_path = (
        Path.home()
        / "Library"
        / "LaunchAgents"
        / f"{LAUNCHD_LABEL}.plist"
    )
    try:
        with plist_path.open("rb") as handle:
            plist = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise RuntimeError("s6_07_rebind_launchd_drift") from exc
    arguments = plist.get("ProgramArguments")
    environment = plist.get("EnvironmentVariables") or {}
    if (
        plist.get("Label") != LAUNCHD_LABEL
        or not isinstance(arguments, list)
        or len(arguments) != 2
        or arguments[0] != "/bin/bash"
        or environment.get("GUIYI_PROJECT_ROOT")
        != str(runtime_root.resolve())
    ):
        raise RuntimeError("s6_07_rebind_launchd_drift")
    runner = Path(str(arguments[1]))
    if not runner.is_file() or runner.is_symlink():
        raise RuntimeError("s6_07_rebind_launchd_drift")
    service = subprocess.run(
        (
            "launchctl",
            "print",
            f"gui/{os.getuid()}/{LAUNCHD_LABEL}",
        ),
        check=False,
        capture_output=True,
        text=True,
        timeout=2,
    )
    if service.returncode == 0:
        match = re.search(
            r"^\s*pid = (\d+)\s*$",
            service.stdout,
            flags=re.MULTILINE,
        )
        if match is None:
            raise RuntimeError("s6_07_rebind_launchd_drift")
        loaded = True
        pid: int | None = int(match.group(1))
    elif launchd_service_is_absent(service, LAUNCHD_LABEL):
        loaded = False
        pid = None
    else:
        raise RuntimeError("s6_07_rebind_launchd_drift")
    return {
        "label": LAUNCHD_LABEL,
        "loaded": loaded,
        "pid": pid,
        "plist_path": str(plist_path.resolve()),
        "plist_sha256": sha256_file(plist_path),
        "runner_path": str(runner.resolve()),
        "runner_sha256": sha256_file(runner),
        "project_root": str(runtime_root.resolve()),
    }


def launchd_binding(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in value.items()
        if key != "pid"
    }


def collect_database_state() -> dict[str, Any]:
    from sqlalchemy import text

    from app.db.session import SessionLocal
    from app.services.htdy_s6_08_runtime_gate import _database_state

    with SessionLocal() as session:
        if session.get_bind().dialect.name == "postgresql":
            session.execute(text("SET TRANSACTION READ ONLY"))
        revision = str(
            session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        )
        counts, hashes = _database_state(session)
        checkpoint = _checkpoint_state(session)
        session.rollback()
    return {
        "database_revision": revision,
        "counts": counts,
        "hashes": hashes,
        "checkpoint_count": checkpoint["count"],
        "checkpoint_sha256": checkpoint["sha256"],
    }


def _checkpoint_state(session: Any) -> dict[str, Any]:
    from app.models.data_center import AfterMarketSchedulerCheckpoint
    from app.services.live_signal_event_gate import _table_baseline

    return _table_baseline(session, AfterMarketSchedulerCheckpoint)


def collect_after_market_health() -> dict[str, Any]:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/runtime/health",
            timeout=2,
        ) as response:
            payload = json.load(response)
    except (OSError, TimeoutError, ValueError) as exc:
        raise RuntimeError("s6_07_rebind_health_unavailable") from exc
    component = (payload.get("components") or {}).get(
        "after_market_scheduler"
    )
    if not isinstance(component, dict):
        raise RuntimeError("s6_07_rebind_health_unavailable")
    return {
        "status": component.get("status"),
        "enabled": component.get("enabled"),
    }


def require_disabled_health(value: Mapping[str, Any]) -> None:
    if dict(value) != DISABLED_HEALTH:
        raise RuntimeError("s6_07_rebind_health_unsafe")


def restart_after_market_scheduler(label: str) -> None:
    if label != LAUNCHD_LABEL:
        raise RuntimeError("s6_07_rebind_launchd_drift")
    subprocess.run(
        (
            "launchctl",
            "kickstart",
            "-k",
            f"gui/{os.getuid()}/{label}",
        ),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )


def write_create_only(
    path: Path,
    payload: Mapping[str, Any],
) -> None:
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise RuntimeError("create_only_path_exists") from exc
    try:
        encoded = json.dumps(
            dict(payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        os.write(descriptor, encoded)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def git_value(root: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def launchd_service_is_absent(result: Any, label: str) -> bool:
    output = (
        f"{getattr(result, 'stdout', '')}\n"
        f"{getattr(result, 'stderr', '')}"
    )
    return (
        result.returncode == 113
        and f'Could not find service "{label}"' in output
    )
