from __future__ import annotations

from copy import deepcopy

import pytest


def _packet() -> dict[str, object]:
    return {
        "task_id": "JM-EOD-AUTOMATION-S6-07-CODE-REBIND",
        "packet_hash": "1" * 64,
        "deployment_packet_sha256": "2" * 64,
        "target_runtime_commit": "3" * 40,
        "launchd_label": "com.guiyi.quant-after-market-scheduler",
    }


def _deployment_receipt() -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": "JM-LIVE-SIGNAL-EVENT-S6-08-DEPLOY",
        "status": "completed",
        "approval_packet_hash": "2" * 64,
        "target_commit": "3" * 40,
        "database_unchanged": True,
        "flags_safe": True,
        "health_verified": True,
        "rollback": False,
    }


def _rebind_receipt() -> dict[str, object]:
    from app.services.htdy_s6_08_approval_artifacts import (
        canonical_hash,
    )

    receipt: dict[str, object] = {
        "schema_version": 1,
        "task_id": "JM-EOD-AUTOMATION-S6-07-CODE-REBIND",
        "status": "completed",
        "gate": "JM_EOD_AUTOMATION_CODE_REBIND_PASSED",
        "approval_packet_hash": "1" * 64,
        "deployment_packet_hash": "2" * 64,
        "deployment_receipt_hash": canonical_hash(
            _deployment_receipt()
        ),
        "runtime_commit": "3" * 40,
        "scheduler_restart": {
            "label": "com.guiyi.quant-after-market-scheduler",
            "loaded_before": False,
            "loaded_after": False,
            "restart_performed": False,
            "previous_pid": None,
            "new_pid": None,
        },
        "database_state": {
            "database_revision": "20260721_0025",
            "state_hash": "4" * 64,
        },
        "database_unchanged": True,
        "health": {"status": "disabled", "enabled": False},
        "archive_rerun": False,
        "historical_receipt_modified": False,
        "watermark_modified": False,
        "asset_or_profile_modified": False,
        "completed_at": "2026-07-26T13:00:00+00:00",
    }
    receipt["receipt_hash"] = canonical_hash(receipt)
    return receipt


def test_code_rebind_receipt_verifier_accepts_only_no_write_result() -> None:
    from app.services.s607_code_rebind import (
        verify_code_rebind_receipt,
    )

    receipt = _rebind_receipt()

    verify_code_rebind_receipt(
        receipt,
        packet=_packet(),
        deployment_receipt=_deployment_receipt(),
    )

    for field in (
        "database_unchanged",
        "archive_rerun",
        "historical_receipt_modified",
        "watermark_modified",
        "asset_or_profile_modified",
    ):
        drift = deepcopy(receipt)
        drift[field] = not bool(receipt[field])
        with pytest.raises(
            RuntimeError,
            match="s6_07_rebind_receipt_invalid",
        ):
            verify_code_rebind_receipt(
                drift,
                packet=_packet(),
                deployment_receipt=_deployment_receipt(),
            )


def test_code_rebind_receipt_verifier_rejects_hash_tamper() -> None:
    from app.services.s607_code_rebind import (
        verify_code_rebind_receipt,
    )

    receipt = _rebind_receipt()
    receipt["runtime_commit"] = "9" * 40

    with pytest.raises(
        RuntimeError,
        match="s6_07_rebind_receipt_invalid",
    ):
        verify_code_rebind_receipt(
            receipt,
            packet=_packet(),
            deployment_receipt=_deployment_receipt(),
        )
