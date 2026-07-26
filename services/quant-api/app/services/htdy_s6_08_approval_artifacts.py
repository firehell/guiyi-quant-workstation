"""Pure, hash-bound approval artifacts for HTDY S6-08 Step 4."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
from typing import Any


DEPLOYMENT_PACKET_TYPE = "htdy_code_only_deployment_v1"
REBIND_PACKET_TYPE = "s6_07_code_only_rebind_v1"
APPROVAL_BUNDLE_TYPE = "htdy_s6_08_approval_bundle_v1"
ALLOWED_DEPLOYMENT_OPERATIONS = (
    "fast_forward_runtime_to_exact_target_commit",
    "purge_nonvenv_python_bytecode",
    "sync_dependency_lock",
    "restart_live_runtime_scheduler",
)
FORBIDDEN_DEPLOYMENT_OPERATIONS = (
    "database_migration",
    "historical_archive",
    "profile_write",
    "signal_event_enable",
    "wechat_autosend_enable",
    "notification_delivery",
    "automatic_order",
)


class HtDyApprovalArtifactError(RuntimeError):
    """Raised when approval artifacts are incomplete or drifted."""


def canonical_hash(value: Mapping[str, Any]) -> str:
    payload = {
        str(key): deepcopy(item)
        for key, item in value.items()
        if key != "packet_hash"
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


def build_code_only_deployment_packet(
    bound_facts: Mapping[str, Any],
) -> dict[str, Any]:
    _validate_deployment_facts(bound_facts)
    packet: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": DEPLOYMENT_PACKET_TYPE,
        "task_id": "V1-HTDY-04-SCHEMA-V3-RUNTIME-GATE",
        "status": "approval_required",
        "writes_authorized": False,
        "bound_facts": deepcopy(dict(bound_facts)),
        "allowed_operations": list(ALLOWED_DEPLOYMENT_OPERATIONS),
        "forbidden_operations": list(
            FORBIDDEN_DEPLOYMENT_OPERATIONS
        ),
        "post_deployment_required_flags": {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        },
        "deployment_receipt": None,
        "runtime_ready": False,
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_code_only_deployment_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    current_facts: Mapping[str, Any],
) -> None:
    if (
        packet.get("schema_version") != 1
        or packet.get("packet_type") != DEPLOYMENT_PACKET_TYPE
        or packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("allowed_operations")
        != list(ALLOWED_DEPLOYMENT_OPERATIONS)
        or packet.get("forbidden_operations")
        != list(FORBIDDEN_DEPLOYMENT_OPERATIONS)
        or packet.get("deployment_receipt") is not None
        or packet.get("runtime_ready") is not False
    ):
        raise HtDyApprovalArtifactError("deployment_packet_invalid")
    _verify_packet_hash(packet, approval_hash)
    _validate_deployment_facts(current_facts)
    if packet.get("bound_facts") != dict(current_facts):
        raise HtDyApprovalArtifactError("deployment_fact_drift")


def build_s6_07_code_rebind_packet(
    *,
    deployment_packet: Mapping[str, Any],
    target_runtime_commit: str,
    s6_07_final_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    _verify_dependency_packet_hash(
        deployment_packet,
        str(deployment_packet.get("packet_hash") or ""),
    )
    if not _commit(target_runtime_commit):
        raise HtDyApprovalArtifactError("target_runtime_commit_invalid")
    _validate_receipt(s6_07_final_receipt)
    packet: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": REBIND_PACKET_TYPE,
        "task_id": "JM-EOD-AUTOMATION-S6-07-CODE-REBIND",
        "status": "approval_required",
        "writes_authorized": False,
        "deployment_packet_sha256": deployment_packet["packet_hash"],
        "target_runtime_commit": target_runtime_commit,
        "s6_07_final_receipt": deepcopy(dict(s6_07_final_receipt)),
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
        "allowed_operations": [
            "rebind_after_market_code_to_exact_runtime_commit",
            "restart_after_market_scheduler",
        ],
        "reruns_archive": False,
        "modifies_historical_receipt": False,
        "modifies_watermark": False,
        "modifies_asset_or_profile": False,
        "deployment_receipt_required_before_execution": True,
    }
    packet["packet_hash"] = canonical_hash(packet)
    return packet


def verify_s6_07_code_rebind_packet(
    packet: Mapping[str, Any],
    *,
    approval_hash: str,
    deployment_packet: Mapping[str, Any],
    current_s6_07_final_receipt: Mapping[str, Any],
) -> None:
    if (
        packet.get("schema_version") != 1
        or packet.get("packet_type") != REBIND_PACKET_TYPE
        or packet.get("status") != "approval_required"
        or packet.get("writes_authorized") is not False
        or packet.get("reruns_archive") is not False
        or packet.get("modifies_historical_receipt") is not False
        or packet.get("modifies_watermark") is not False
        or packet.get("modifies_asset_or_profile") is not False
        or packet.get("deployment_receipt_required_before_execution")
        is not True
    ):
        raise HtDyApprovalArtifactError("s6_07_rebind_packet_invalid")
    _verify_packet_hash(packet, approval_hash)
    _verify_dependency_packet_hash(
        deployment_packet,
        str(deployment_packet.get("packet_hash") or ""),
    )
    if (
        packet.get("deployment_packet_sha256")
        != deployment_packet.get("packet_hash")
    ):
        raise HtDyApprovalArtifactError("deployment_dependency_drift")
    _validate_receipt(current_s6_07_final_receipt)
    if packet.get("s6_07_final_receipt") != dict(
        current_s6_07_final_receipt
    ):
        raise HtDyApprovalArtifactError("s6_07_receipt_drift")


def build_approval_bundle(
    *,
    deployment_packet_path: Path,
    deployment_packet: Mapping[str, Any],
    rebind_packet_path: Path,
    rebind_packet: Mapping[str, Any],
    service_parent_packet_path: Path,
    service_parent_packet: Mapping[str, Any],
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": APPROVAL_BUNDLE_TYPE,
        "status": "approval_required",
        "writes_authorized": False,
        "approval_name": "Approval A",
        "artifacts": {
            "deployment": {
                "path": str(deployment_packet_path.resolve(strict=False)),
                "sha256": deployment_packet.get("packet_hash"),
            },
            "s6_07_rebind": {
                "path": str(rebind_packet_path.resolve(strict=False)),
                "sha256": rebind_packet.get("packet_hash"),
            },
            "service_parent": {
                "path": str(
                    service_parent_packet_path.resolve(strict=False)
                ),
                "sha256": service_parent_packet.get("packet_hash"),
            },
        },
        "dependency_order": [
            "deployment",
            "s6_07_rebind",
            "service_parent",
        ],
        "deployment_performed": False,
        "runtime_enabled": False,
        "signal_event_written": False,
        "notification_sent": False,
    }
    bundle["packet_hash"] = canonical_hash(bundle)
    return bundle


def verify_approval_bundle(
    bundle: Mapping[str, Any],
    *,
    deployment_packet: Mapping[str, Any],
    rebind_packet: Mapping[str, Any],
    service_parent_packet: Mapping[str, Any],
) -> None:
    if (
        bundle.get("schema_version") != 1
        or bundle.get("packet_type") != APPROVAL_BUNDLE_TYPE
        or bundle.get("status") != "approval_required"
        or bundle.get("writes_authorized") is not False
        or bundle.get("dependency_order")
        != ["deployment", "s6_07_rebind", "service_parent"]
        or canonical_hash(bundle) != bundle.get("packet_hash")
    ):
        raise HtDyApprovalArtifactError("approval_bundle_invalid")
    artifacts = bundle.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise HtDyApprovalArtifactError("approval_bundle_invalid")
    expected = {
        "deployment": deployment_packet.get("packet_hash"),
        "s6_07_rebind": rebind_packet.get("packet_hash"),
        "service_parent": service_parent_packet.get("packet_hash"),
    }
    if any(
        not isinstance(artifacts.get(key), Mapping)
        or artifacts[key].get("sha256") != value
        for key, value in expected.items()
    ):
        raise HtDyApprovalArtifactError("approval_bundle_dependency_drift")
    bindings = service_parent_packet.get("bindings")
    if (
        not isinstance(bindings, Mapping)
        or bindings.get("deployment_packet_sha256")
        != deployment_packet.get("packet_hash")
        or bindings.get("s6_07_rebind_packet_sha256")
        != rebind_packet.get("packet_hash")
    ):
        raise HtDyApprovalArtifactError("approval_bundle_dependency_drift")


def write_json_create_only(
    path: Path,
    value: Mapping[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        raise HtDyApprovalArtifactError("create_only_path_exists") from exc
    try:
        payload = json.dumps(
            dict(value),
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _verify_packet_hash(
    packet: Mapping[str, Any],
    approval_hash: str,
) -> None:
    if (
        not _sha256(approval_hash)
        or packet.get("packet_hash") != approval_hash
        or canonical_hash(packet) != approval_hash
    ):
        raise HtDyApprovalArtifactError("packet_hash_invalid")


def _verify_dependency_packet_hash(
    packet: Mapping[str, Any],
    approval_hash: str,
) -> None:
    payload = {
        str(key): deepcopy(item)
        for key, item in packet.items()
        if key != "packet_hash"
    }
    mature_hash = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    if (
        not _sha256(approval_hash)
        or packet.get("packet_hash") != approval_hash
        or approval_hash not in {canonical_hash(packet), mature_hash}
    ):
        raise HtDyApprovalArtifactError("packet_hash_invalid")


def _validate_deployment_facts(value: Mapping[str, Any]) -> None:
    expected_keys = {
        "source",
        "runtime",
        "database_revision",
        "s6_07_final_receipt",
        "launchd",
        "runtime_flags",
        "output",
    }
    if set(value) != expected_keys:
        raise HtDyApprovalArtifactError("deployment_facts_invalid")
    source = value.get("source")
    runtime = value.get("runtime")
    launchd = value.get("launchd")
    flags = value.get("runtime_flags")
    output = value.get("output")
    if not all(
        isinstance(item, Mapping)
        for item in (source, runtime, launchd, flags, output)
    ):
        raise HtDyApprovalArtifactError("deployment_facts_invalid")
    _validate_receipt(value.get("s6_07_final_receipt"))
    if (
        not str(source.get("root") or "").startswith("/")
        or source.get("branch")
        not in {"main", "codex/v1-htdy-step34-completion"}
        or not _commit(str(source.get("commit") or ""))
        or not _commit(str(source.get("tree") or ""))
        or source.get("tracked_clean") is not True
        or not _sha256(str(source.get("uv_lock_sha256") or ""))
        or not str(runtime.get("root") or "").startswith("/")
        or not _commit(str(runtime.get("current_commit") or ""))
        or not _commit(str(runtime.get("current_tree") or ""))
        or runtime.get("tracked_clean") is not True
        or value.get("database_revision") != "20260721_0025"
        or launchd.get("label")
        != "com.guiyi.quant-runtime-scheduler"
        or not _sha256(str(launchd.get("plist_sha256") or ""))
        or dict(flags)
        != {
            "GUIYI_LIVE_SIGNAL_EVENTS_ENABLED": False,
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_PACKET": "",
            "GUIYI_LIVE_SIGNAL_EVENTS_APPROVAL_HASH": "",
            "GUIYI_WECHAT_AUTOSEND_ENABLED": False,
        }
        or not str(output.get("root") or "").startswith("/")
        or isinstance(output.get("device"), bool)
        or not isinstance(output.get("device"), int)
        or int(output["device"]) < 0
    ):
        raise HtDyApprovalArtifactError("deployment_facts_invalid")


def _validate_receipt(value: Any) -> None:
    if (
        not isinstance(value, Mapping)
        or not str(value.get("path") or "").endswith(
            "completion_receipt.json"
        )
        or not _sha256(str(value.get("sha256") or ""))
    ):
        raise HtDyApprovalArtifactError("s6_07_receipt_invalid")


def _sha256(value: str) -> bool:
    return len(value) == 64 and value == value.lower() and _hex(value)


def _commit(value: str) -> bool:
    return len(value) == 40 and value == value.lower() and _hex(value)


def _hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True
