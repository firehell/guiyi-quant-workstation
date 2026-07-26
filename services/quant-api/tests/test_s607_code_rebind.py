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
            "counts": {
                "strategy_signals": 5,
                "signal_events": 3,
                "signal_notifications": 1,
                "signal_scan_tasks": 5,
                "orders": 4225,
                "trades": 4361,
                "review_notes": 7,
                "backtest_tasks": 23,
                "profile_bindings": 5131,
                "canonical_assets": 103374,
            },
            "hashes": {
                "backtest_state_sha256": "2" * 64,
                "profile_bindings_sha256": "3" * 64,
                "canonical_assets_sha256": "4" * 64,
                "forbidden_tables_sha256": "5" * 64,
            },
            "checkpoint_count": 1,
            "checkpoint_sha256": "6" * 64,
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


def test_code_rebind_receipt_requires_complete_checkpoint_state() -> None:
    from app.services.htdy_s6_08_approval_artifacts import (
        canonical_hash,
    )
    from app.services.s607_code_rebind import (
        verify_code_rebind_receipt,
    )

    receipt = _rebind_receipt()
    del receipt["database_state"]["checkpoint_sha256"]
    payload = {
        key: value
        for key, value in receipt.items()
        if key != "receipt_hash"
    }
    receipt["receipt_hash"] = canonical_hash(payload)

    with pytest.raises(
        RuntimeError,
        match="s6_07_rebind_receipt_invalid",
    ):
        verify_code_rebind_receipt(
            receipt,
            packet=_packet(),
            deployment_receipt=_deployment_receipt(),
        )


def test_checkpoint_state_uses_real_0025_model_columns() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from app.models.data_center import (
        AfterMarketSchedulerCheckpoint,
    )
    from app.services.s607_code_rebind import _checkpoint_state

    engine = create_engine("sqlite+pysqlite:///:memory:")
    AfterMarketSchedulerCheckpoint.__table__.create(engine)
    with Session(engine) as session:
        session.add(
            AfterMarketSchedulerCheckpoint(
                product="jm",
                exchange_code="DCE",
                status="idle",
                authorization_hash="a" * 64,
                retry_count=0,
                last_result={"status": "idle"},
            )
        )
        session.commit()

        state = _checkpoint_state(session)

    assert state["count"] == 1
    assert len(state["sha256"]) == 64
