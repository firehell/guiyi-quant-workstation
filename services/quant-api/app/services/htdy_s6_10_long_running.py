"""Approval-D-bound no-code promotion and long-running daily children."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime
import json
from pathlib import Path
from typing import Any, Mapping

from app.services.htdy_s6_10_remaining_window import (
    _jm_15m_bucket_ends,
    canonical_hash,
)
from app.services.htdy_s6_10_stability import (
    _file_sha256,
    _verify_approved_signers_trust_root,
    _verify_ssh_signature,
)


class HtDyS610LongRunningError(RuntimeError):
    """Fail-closed long-running promotion violation."""


def build_approval_d_request(
    *,
    parent_packet: Mapping[str, Any],
    acceptance_sample: Mapping[str, Any],
    generated_at: datetime,
) -> dict[str, Any]:
    if generated_at.tzinfo is None:
        raise HtDyS610LongRunningError("generated_at_timezone_required")
    if (
        parent_packet.get("schema_version") != 7
        or parent_packet.get("window_mode") != "complete_trading_day"
        or parent_packet.get("complete_trading_day_claim_allowed") is not True
        or parent_packet.get("packet_hash") != canonical_hash(parent_packet)
    ):
        raise HtDyS610LongRunningError("full_day_parent_invalid")
    parent_hash = str(parent_packet["packet_hash"])
    event_counts = dict(acceptance_sample.get("event_counts") or {})
    notifications = dict(
        acceptance_sample.get("notification_counts") or {}
    )
    health = dict(acceptance_sample.get("health") or {})
    natural_events = int(event_counts.get("signal_created") or 0)
    sent = int(notifications.get("sent") or 0)
    if (
        acceptance_sample.get("schema_version") != 7
        or acceptance_sample.get("sample_type")
        != "htdy_s6_10_remaining_window_ledger"
        or acceptance_sample.get("parent_packet_hash") != parent_hash
        or acceptance_sample.get("trading_day")
        != parent_packet.get("trading_days", [None])[0]
        or acceptance_sample.get("expected_confirmed_15m_closes") != 23
        or acceptance_sample.get("evaluated_confirmed_15m_closes") != 23
        or acceptance_sample.get("partial_evaluations") != 0
        or acceptance_sample.get("partial_rejections") != 0
        or int(event_counts.get("signal_changed") or 0) != 0
        or int(notifications.get("failed") or 0) != 0
        or int(notifications.get("duplicate_dedupe_keys") or 0) != 0
        or int(notifications.get("attempts_over_limit") or 0) != 0
        or sent != natural_events
        or set(health)
        != {"runtime", "redis", "database", "after_market"}
        or any(value is not True for value in health.values())
        or acceptance_sample.get("eod_status") != "passed"
        or acceptance_sample.get("complete_trading_day_passed") is not True
        or not _acceptance_closes_exact(
            parent_packet=parent_packet,
            acceptance_sample=acceptance_sample,
        )
        or not _acceptance_sample_hash_valid(acceptance_sample)
    ):
        raise HtDyS610LongRunningError("full_day_acceptance_invalid")
    bindings = dict(parent_packet.get("bindings") or {})
    request: dict[str, Any] = {
        "schema_version": 1,
        "task_id": "JM-LIVE-STABILITY-S6-10",
        "request_type": "htdy_s6_10_approval_d_no_code_promotion",
        "approval": "Approval D",
        "generated_at": generated_at.astimezone(UTC).isoformat(),
        "parent_packet_hash": parent_hash,
        "acceptance_sample_hash": acceptance_sample["sample_hash"],
        "accepted_trading_day": acceptance_sample["trading_day"],
        "eod_authorization_hash": acceptance_sample[
            "eod_authorization_hash"
        ],
        "runtime_commit": bindings.get("runtime_commit"),
        "runtime_tree": bindings.get("runtime_tree"),
        "source_commit": bindings.get("source_commit"),
        "source_tree": bindings.get("source_tree"),
        "approval_d_approved_signers_sha256": bindings.get(
            "approval_c2_approved_signers_sha256"
        ),
        "approval_d_signature_namespace": "guiyi-htdy-s610",
        "approval_d_signer_principal": "guiyi-owner",
        "no_code_promotion": True,
        "reuse_s6_07_eod": True,
        "global_wechat_autosend": False,
        "auto_order": False,
    }
    if not all(
        (
            _commit(request["runtime_commit"]),
            _sha256(request["runtime_tree"]),
            _commit(request["source_commit"]),
            _sha256(request["source_tree"]),
            _sha256(request["approval_d_approved_signers_sha256"]),
            _sha256(request["eod_authorization_hash"]),
        )
    ):
        raise HtDyS610LongRunningError("code_binding_invalid")
    request["request_hash"] = _request_hash(request)
    return request


def verify_approval_d_receipt(
    *,
    request: Mapping[str, Any],
    receipt: Mapping[str, Any],
    approval_hash: str,
) -> None:
    if (
        request.get("request_hash") != _request_hash(request)
        or receipt.get("schema_version") != 1
        or receipt.get("approval") != "Approval D"
        or receipt.get("decision") != "approved"
        or receipt.get("request_hash") != request.get("request_hash")
        or receipt.get("parent_packet_hash")
        != request.get("parent_packet_hash")
        or receipt.get("runtime_commit") != request.get("runtime_commit")
        or receipt.get("runtime_tree") != request.get("runtime_tree")
        or receipt.get("no_code_promotion") is not True
        or receipt.get("reuse_s6_07_eod") is not True
        or receipt.get("approved_at") is None
        or receipt.get("receipt_hash") != approval_hash
        or canonical_hash(receipt) != approval_hash
    ):
        raise HtDyS610LongRunningError("approval_d_receipt_invalid")
    try:
        generated_at = datetime.fromisoformat(str(request["generated_at"]))
        approved_at = datetime.fromisoformat(str(receipt["approved_at"]))
    except (KeyError, ValueError) as exc:
        raise HtDyS610LongRunningError(
            "approval_d_receipt_invalid"
        ) from exc
    if (
        generated_at.tzinfo is None
        or approved_at.tzinfo is None
        or approved_at <= generated_at
    ):
        raise HtDyS610LongRunningError("approval_d_receipt_invalid")


def verify_signed_approval_d_receipt(
    *,
    request: Mapping[str, Any],
    receipt_path: Path,
    signature_path: Path,
    approved_signers_path: Path,
    approval_hash: str,
) -> dict[str, Any]:
    try:
        receipt_bytes = receipt_path.read_bytes()
        receipt = json.loads(receipt_bytes)
    except (OSError, json.JSONDecodeError) as exc:
        raise HtDyS610LongRunningError(
            "approval_d_receipt_invalid"
        ) from exc
    if not isinstance(receipt, dict):
        raise HtDyS610LongRunningError("approval_d_receipt_invalid")
    verify_approval_d_receipt(
        request=request,
        receipt=receipt,
        approval_hash=approval_hash,
    )
    if (
        _file_sha256(approved_signers_path)
        != request.get("approval_d_approved_signers_sha256")
        or not _verify_approved_signers_trust_root(approved_signers_path)
        or not _verify_ssh_signature(
            receipt_bytes,
            signature_path,
            approved_signers_path,
        )
    ):
        raise HtDyS610LongRunningError("approval_d_receipt_invalid")
    return receipt


def build_long_running_daily_child(
    *,
    approval_d_request: Mapping[str, Any],
    approval_d_receipt_path: Path,
    approval_d_signature_path: Path,
    approved_signers_path: Path,
    approval_d_hash: str,
    trading_day: date,
    actual_contract: str,
    mapping_sha256: str,
    session_geometry_sha256: str,
    source_facts_sha256: str,
    current_runtime_commit: str,
    current_runtime_tree: str,
    prior_eod: Mapping[str, Any],
    previous_trading_day: date,
    expected_bucket_ends: list[str],
    window_end: str | None = None,
) -> dict[str, Any]:
    verify_signed_approval_d_receipt(
        request=approval_d_request,
        receipt_path=approval_d_receipt_path,
        signature_path=approval_d_signature_path,
        approved_signers_path=approved_signers_path,
        approval_hash=approval_d_hash,
    )
    if (
        current_runtime_commit != approval_d_request.get("runtime_commit")
        or current_runtime_tree != approval_d_request.get("runtime_tree")
    ):
        raise HtDyS610LongRunningError("no_code_binding_drift")
    try:
        prior_day = date.fromisoformat(str(prior_eod.get("trading_day") or ""))
    except ValueError as exc:
        raise HtDyS610LongRunningError("prior_eod_not_passed") from exc
    if (
        previous_trading_day >= trading_day
        or prior_eod.get("status") != "passed"
        or prior_day != previous_trading_day
        or prior_eod.get("authorization_hash")
        != approval_d_request.get("eod_authorization_hash")
    ):
        raise HtDyS610LongRunningError("prior_eod_not_passed")
    parsed_bucket_ends: list[datetime] = []
    try:
        parsed_bucket_ends = [
            datetime.fromisoformat(value) for value in expected_bucket_ends
        ]
    except (TypeError, ValueError) as exc:
        raise HtDyS610LongRunningError("daily_binding_invalid") from exc
    try:
        parsed_window_end = datetime.fromisoformat(
            window_end or expected_bucket_ends[-1]
        )
    except (IndexError, TypeError, ValueError) as exc:
        raise HtDyS610LongRunningError("daily_binding_invalid") from exc
    if (
        not _actual_contract(actual_contract)
        or len(parsed_bucket_ends) != 23
        or len(set(parsed_bucket_ends)) != 23
        or any(value.tzinfo is None for value in parsed_bucket_ends)
        or parsed_window_end.tzinfo is None
        or parsed_window_end != max(parsed_bucket_ends)
        or not all(
            _sha256(value)
            for value in (
                mapping_sha256,
                session_geometry_sha256,
                source_facts_sha256,
            )
        )
    ):
        raise HtDyS610LongRunningError("daily_binding_invalid")
    child: dict[str, Any] = {
        "schema_version": 1,
        "packet_type": "htdy_s6_10_long_running_daily_child",
        "approval_d_receipt_hash": approval_d_hash,
        "parent_packet_hash": approval_d_request["parent_packet_hash"],
        "trading_day": trading_day.isoformat(),
        "actual_contract": actual_contract,
        "mapping_sha256": mapping_sha256,
        "session_geometry_sha256": session_geometry_sha256,
        "source_facts_sha256": source_facts_sha256,
        "runtime_commit": current_runtime_commit,
        "runtime_tree": current_runtime_tree,
        "previous_trading_day": previous_trading_day.isoformat(),
        "prior_eod": deepcopy(dict(prior_eod)),
        "expected_bucket_ends": [
            value.isoformat() for value in parsed_bucket_ends
        ],
        "window_end": parsed_window_end.isoformat(),
        "max_wecom_notifications": 23,
        "max_notification_attempts": 3,
        "purpose": "observation_only",
        "not_trading_instruction": True,
        "global_wechat_autosend": False,
        "auto_order": False,
        "reuse_s6_07_eod": True,
        "create_only": True,
    }
    child["packet_hash"] = canonical_hash(child)
    return child


def _sha256(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64 or value != value.lower():
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _request_hash(request: Mapping[str, Any]) -> str:
    return canonical_hash(
        {key: value for key, value in request.items() if key != "request_hash"}
    )


def _acceptance_sample_hash_valid(sample: Mapping[str, Any]) -> bool:
    sample_hash = sample.get("sample_hash")
    return _sha256(sample_hash) and canonical_hash(
        {key: value for key, value in sample.items() if key != "sample_hash"}
    ) == sample_hash


def _acceptance_closes_exact(
    *,
    parent_packet: Mapping[str, Any],
    acceptance_sample: Mapping[str, Any],
) -> bool:
    try:
        trading_day = date.fromisoformat(
            str(acceptance_sample["trading_day"])
        )
        night_session_date = date.fromisoformat(
            str(parent_packet["night_session_date"])
        )
        expected = [
            datetime.fromisoformat(str(value))
            for value in acceptance_sample["expected_bucket_ends"]
        ]
        evaluated = [
            datetime.fromisoformat(str(value))
            for value in acceptance_sample["evaluated_bucket_ends"]
        ]
    except (KeyError, TypeError, ValueError):
        return False
    authoritative = _jm_15m_bucket_ends(
        night_session_date,
        trading_day,
    )
    return bool(
        len(expected) == 23
        and len(set(expected)) == 23
        and all(value.tzinfo is not None for value in expected)
        and expected == authoritative
        and evaluated == expected
    )


def _commit(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 40:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()


def _actual_contract(value: Any) -> bool:
    return (
        isinstance(value, str)
        and value.upper().startswith("JM")
        and value[2:].isdigit()
        and not value.upper().endswith(".MAIN")
    )
