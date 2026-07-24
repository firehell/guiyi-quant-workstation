from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest


DEPLOYMENT_COMMIT = "9" * 40
RUNTIME_COMMIT = "f" * 40
D1_PACKET_HASH = "1" * 64
D2_PACKET_HASH = "2" * 64
ZERO_WRITE_COUNTS = {
    "signal_events": 3,
    "signal_notifications": 1,
    "signal_scan_tasks": 5,
    "strategy_signals": 5,
}


def _deployment_receipt() -> dict:
    return {
        "schema_version": 1,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07-DEPLOY",
        "status": "completed",
        "gate": "JM_EOD_AUTOMATION_DEPLOYMENT_PASSED",
        "runtime_commit": DEPLOYMENT_COMMIT,
        "database_revision": "20260721_0025",
        "after_market_scheduler_loaded": False,
    }


def _enable_packet() -> dict:
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    packet = {
        "schema_version": 2,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "status": "approval_required",
        "product": "jm",
        "exchange": "DCE",
        "allowed_writes": [
            "create_only_rqdata_parquet",
            "create_only_manifest_and_receipt",
            "market_data_metadata_and_quality",
            "profile_compare_and_switch",
            "after_market_scheduler_checkpoint",
        ],
        "forbidden_writes": [
            "signal_event",
            "notification",
            "strategy_signal",
            "order",
        ],
        "bound_facts": {
            "git": {
                "commit": RUNTIME_COMMIT,
                "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
            },
            "database": {"alembic_revision": "20260721_0025"},
            "launchd_label": "com.guiyi.quant-after-market-scheduler",
            "output_root": "/data",
        },
    }
    packet["packet_hash"] = canonical_packet_hash(packet)
    return packet


def _enable_hash() -> str:
    return str(_enable_packet()["packet_hash"])


def _day_evidence(day: str, packet_hash: str) -> dict:
    return {
        "trading_day": day,
        "batch_id": f"s607_{day.replace('-', '')}_{RUNTIME_COMMIT[:8]}",
        "gate": "JM_EOD_ARCHIVE_DAY_PASSED",
        "receipt_sha256": "a" * 64,
        "execution_packet_hash": packet_hash,
        "parent_automation_approval_hash": _enable_hash(),
        "provider_final_stability": {"stable": True, "check_count": 2},
        "assets": [
            {"period": period, "quality_status": "passed", "checksum_match": True}
            for period in ("1m", "5m", "15m", "30m", "60m", "1d")
        ],
        "manifest": {"row_count": 6, "sha256": "b" * 64},
        "immutable_active_assets": {
            "unique_file_count": 42,
            "files": [{"file_path": "old.parquet", "checksum_match": True}],
        },
    }


def _d1_snapshot() -> dict:
    return {
        "schema_version": 1,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "evidence_type": "d1_normal_automatic_archive_baseline",
        "status": "passed",
        "generated_at": "2026-07-22T09:40:00+00:00",
        "runtime": {"commit": RUNTIME_COMMIT},
        "authorization": {"service_enable_packet_hash": _enable_hash()},
        "d1": _day_evidence("2026-07-22", D1_PACKET_HASH),
        "checkpoint": {
            "last_successful_trading_day": "2026-07-22",
            "current_trading_day": None,
            "retry_count": 0,
            "last_error_type": None,
        },
        "health": {"archive_lag_trading_days": 0, "active_binding_end": "2026-07-22"},
        "forbidden_counts": copy.deepcopy(ZERO_WRITE_COUNTS),
        "assertions": {"automatic_success": True, "immutable_assets_unchanged": True},
    }


def _d2_outage_snapshot() -> dict:
    return {
        "schema_version": 1,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "evidence_type": "d2_outage_pre_restart",
        "status": "passed",
        "generated_at": "2026-07-23T09:06:00+00:00",
        "runtime": {"commit": RUNTIME_COMMIT},
        "authorization": {"service_enable_packet_hash": _enable_hash()},
        "enabled": True,
        "launchd": {"loaded": False},
        "d2": {"trading_day": "2026-07-23", "receipt_absent": True},
        "checkpoint": {"last_successful_trading_day": "2026-07-22"},
        "health": {
            "archive_lag_trading_days": 1,
            "scheduler_heartbeat": {
                "status": "degraded",
                "error_type": "heartbeat_missing",
            },
        },
        "d1_unchanged": True,
        "forbidden_counts": copy.deepcopy(ZERO_WRITE_COUNTS),
        "assertions": {"outage_observed": True, "d2_not_manually_archived": True},
    }


def _d2_completion_snapshot() -> dict:
    return {
        "schema_version": 1,
        "task_id": "JM-EOD-INCREMENTAL-AUTOMATION-S6-07",
        "evidence_type": "d2_automatic_catchup_completion",
        "status": "passed",
        "generated_at": "2026-07-23T09:10:00+00:00",
        "runtime": {"commit": RUNTIME_COMMIT},
        "authorization": {"service_enable_packet_hash": _enable_hash()},
        "d2": _day_evidence("2026-07-23", D2_PACKET_HASH),
        "checkpoint": {
            "last_successful_trading_day": "2026-07-23",
            "current_trading_day": None,
            "retry_count": 0,
            "last_error_type": None,
        },
        "health": {"archive_lag_trading_days": 0, "active_binding_end": "2026-07-23"},
        "d1_unchanged": True,
        "forbidden_counts": copy.deepcopy(ZERO_WRITE_COUNTS),
        "assertions": {"automatic_catchup_success": True, "d1_immutable": True},
    }


def _artifact(tmp_path: Path, name: str, payload: dict) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _build(
    tmp_path: Path,
    *,
    enable: dict | None = None,
    outage: dict | None = None,
    completion: dict | None = None,
) -> dict:
    from app.services.after_market_real_acceptance import build_real_acceptance_receipt

    return build_real_acceptance_receipt(
        deployment_receipt_path=_artifact(
            tmp_path, "deployment.json", _deployment_receipt()
        ),
        enable_packet_path=_artifact(
            tmp_path, "enable.json", enable or _enable_packet()
        ),
        d1_snapshot_path=_artifact(tmp_path, "d1.json", _d1_snapshot()),
        d2_outage_snapshot_path=_artifact(
            tmp_path, "d2-outage.json", outage or _d2_outage_snapshot()
        ),
        d2_completion_snapshot_path=_artifact(
            tmp_path, "d2-completion.json", completion or _d2_completion_snapshot()
        ),
        verifier_git={
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        deployment_is_ancestor=True,
    )


def test_real_acceptance_builds_final_gate_from_normal_day_and_outage_catchup(
    tmp_path: Path,
) -> None:
    receipt = _build(tmp_path)

    assert receipt["gate"] == "JM_EOD_INCREMENTAL_AUTOMATION_READY"
    assert receipt["status"] == "completed"
    assert receipt["runtime_commit"] == RUNTIME_COMMIT
    assert receipt["deployment_lineage"]["deployment_commit"] == DEPLOYMENT_COMMIT
    assert receipt["deployment_lineage"]["deployment_is_ancestor"] is True
    assert receipt["d1"]["trading_day"] == "2026-07-22"
    assert receipt["d2"]["trading_day"] == "2026-07-23"
    assert receipt["forbidden_write_deltas"] == {name: 0 for name in ZERO_WRITE_COUNTS}
    assert receipt["scope_boundaries"]["signal_event_ready"] is False
    assert receipt["scope_boundaries"]["automatic_trading_ready"] is False


def test_real_acceptance_accepts_approved_runtime_recovery_between_d1_and_d2(
    tmp_path: Path,
) -> None:
    from app.services.after_market_real_acceptance import build_real_acceptance_receipt
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    d1_runtime_commit = "d" * 40
    d1_enable = _enable_packet()
    d1_enable["bound_facts"]["git"]["commit"] = d1_runtime_commit
    d1_enable["packet_hash"] = canonical_packet_hash(d1_enable)

    d1 = _d1_snapshot()
    d1["runtime"]["commit"] = d1_runtime_commit
    d1["authorization"]["service_enable_packet_hash"] = d1_enable["packet_hash"]
    d1["d1"]["parent_automation_approval_hash"] = d1_enable["packet_hash"]

    outage = _d2_outage_snapshot()
    outage["d2"]["trading_day"] = "2026-07-24"
    outage["checkpoint"]["last_successful_trading_day"] = "2026-07-23"

    completion = _d2_completion_snapshot()
    completion["generated_at"] = "2026-07-24T09:10:00+00:00"
    completion["d2"] = _day_evidence("2026-07-24", D2_PACKET_HASH)
    completion["checkpoint"]["last_successful_trading_day"] = "2026-07-24"
    completion["health"]["active_binding_end"] = "2026-07-24"

    receipt = build_real_acceptance_receipt(
        deployment_receipt_path=_artifact(
            tmp_path, "deployment.json", _deployment_receipt()
        ),
        enable_packet_path=_artifact(tmp_path, "enable.json", _enable_packet()),
        d1_enable_packet_path=_artifact(tmp_path, "d1-enable.json", d1_enable),
        d1_snapshot_path=_artifact(tmp_path, "d1.json", d1),
        d2_outage_snapshot_path=_artifact(tmp_path, "d2-outage.json", outage),
        d2_completion_snapshot_path=_artifact(
            tmp_path, "d2-completion.json", completion
        ),
        verifier_git={
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        deployment_is_ancestor=True,
        d1_runtime_is_ancestor=True,
    )

    assert receipt["d1"]["runtime_commit"] == d1_runtime_commit
    assert receipt["d1"]["authorization_hash"] == d1_enable["packet_hash"]
    assert receipt["d2_outage"]["last_successful_before_outage"] == "2026-07-23"
    assert receipt["d2"]["trading_day"] == "2026-07-24"


def test_real_acceptance_accepts_approved_outage_runtime_before_d2_recovery(
    tmp_path: Path,
) -> None:
    from app.services.after_market_real_acceptance import build_real_acceptance_receipt
    from app.services.rqdata_ingest.jm_historical_catchup import canonical_packet_hash

    outage_runtime_commit = "e" * 40
    outage_enable = _enable_packet()
    outage_enable["bound_facts"]["git"]["commit"] = outage_runtime_commit
    outage_enable["packet_hash"] = canonical_packet_hash(outage_enable)

    outage = _d2_outage_snapshot()
    outage["runtime"]["commit"] = outage_runtime_commit
    outage["authorization"]["service_enable_packet_hash"] = outage_enable["packet_hash"]

    receipt = build_real_acceptance_receipt(
        deployment_receipt_path=_artifact(
            tmp_path, "deployment.json", _deployment_receipt()
        ),
        enable_packet_path=_artifact(tmp_path, "enable.json", _enable_packet()),
        d2_outage_enable_packet_path=_artifact(
            tmp_path, "outage-enable.json", outage_enable
        ),
        d1_snapshot_path=_artifact(tmp_path, "d1.json", _d1_snapshot()),
        d2_outage_snapshot_path=_artifact(tmp_path, "d2-outage.json", outage),
        d2_completion_snapshot_path=_artifact(
            tmp_path, "d2-completion.json", _d2_completion_snapshot()
        ),
        verifier_git={
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        deployment_is_ancestor=True,
        d2_outage_runtime_is_ancestor=True,
    )

    assert receipt["deployment_lineage"]["d2_outage_runtime_commit"] == (
        outage_runtime_commit
    )
    assert receipt["deployment_lineage"]["d2_outage_runtime_is_ancestor"] is True
    assert receipt["d2_outage"]["authorization_hash"] == outage_enable["packet_hash"]


def test_real_acceptance_rejects_unrelated_outage_runtime(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import (
        RealAcceptanceError,
        build_real_acceptance_receipt,
    )

    with pytest.raises(
        RealAcceptanceError, match="d2_outage_runtime_lineage_invalid"
    ):
        build_real_acceptance_receipt(
            deployment_receipt_path=_artifact(
                tmp_path, "deployment.json", _deployment_receipt()
            ),
            enable_packet_path=_artifact(tmp_path, "enable.json", _enable_packet()),
            d1_snapshot_path=_artifact(tmp_path, "d1.json", _d1_snapshot()),
            d2_outage_snapshot_path=_artifact(
                tmp_path, "d2-outage.json", _d2_outage_snapshot()
            ),
            d2_completion_snapshot_path=_artifact(
                tmp_path, "d2-completion.json", _d2_completion_snapshot()
            ),
            verifier_git={
                "commit": "v" * 40,
                "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
            },
            deployment_is_ancestor=True,
            d2_outage_runtime_is_ancestor=False,
        )


def test_real_acceptance_accepts_optional_completed_week_asset_on_d2(
    tmp_path: Path,
) -> None:
    completion = _d2_completion_snapshot()
    completion["d2"]["assets"].append(
        {"period": "1w", "quality_status": "passed", "checksum_match": True}
    )
    completion["d2"]["manifest"]["row_count"] = 7

    receipt = _build(tmp_path, completion=completion)

    assert receipt["gate"] == "JM_EOD_INCREMENTAL_AUTOMATION_READY"
    assert receipt["d2"]["trading_day"] == "2026-07-23"


def test_real_acceptance_rejects_unapproved_extra_period_on_d2(
    tmp_path: Path,
) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    completion = _d2_completion_snapshot()
    completion["d2"]["assets"].append(
        {"period": "2h", "quality_status": "passed", "checksum_match": True}
    )
    completion["d2"]["manifest"]["row_count"] = 7

    with pytest.raises(RealAcceptanceError, match="daily_evidence_invalid"):
        _build(tmp_path, completion=completion)


def test_real_acceptance_rejects_unrelated_d1_runtime(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import (
        RealAcceptanceError,
        build_real_acceptance_receipt,
    )

    with pytest.raises(RealAcceptanceError, match="d1_runtime_lineage_invalid"):
        build_real_acceptance_receipt(
            deployment_receipt_path=_artifact(
                tmp_path, "deployment.json", _deployment_receipt()
            ),
            enable_packet_path=_artifact(tmp_path, "enable.json", _enable_packet()),
            d1_enable_packet_path=_artifact(
                tmp_path, "d1-enable.json", _enable_packet()
            ),
            d1_snapshot_path=_artifact(tmp_path, "d1.json", _d1_snapshot()),
            d2_outage_snapshot_path=_artifact(
                tmp_path, "d2-outage.json", _d2_outage_snapshot()
            ),
            d2_completion_snapshot_path=_artifact(
                tmp_path, "d2-completion.json", _d2_completion_snapshot()
            ),
            verifier_git={
                "commit": "v" * 40,
                "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
            },
            deployment_is_ancestor=True,
            d1_runtime_is_ancestor=False,
        )


def test_real_acceptance_rejects_outage_checkpoint_at_d2_day(
    tmp_path: Path,
) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    outage = _d2_outage_snapshot()
    outage["checkpoint"]["last_successful_trading_day"] = "2026-07-23"

    with pytest.raises(RealAcceptanceError, match="d2_outage_snapshot_invalid"):
        _build(tmp_path, outage=outage)


def test_real_acceptance_rejects_missing_lag_during_outage(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    outage = _d2_outage_snapshot()
    outage["health"]["archive_lag_trading_days"] = 0

    with pytest.raises(RealAcceptanceError, match="d2_outage_lag_invalid"):
        _build(tmp_path, outage=outage)


def test_real_acceptance_rejects_d1_mutation_after_catchup(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    completion = _d2_completion_snapshot()
    completion["d1_unchanged"] = False

    with pytest.raises(RealAcceptanceError, match="d1_immutable_verification_failed"):
        _build(tmp_path, completion=completion)


def test_real_acceptance_rejects_forbidden_write_counter_delta(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    completion = _d2_completion_snapshot()
    completion["forbidden_counts"]["signal_events"] += 1

    with pytest.raises(RealAcceptanceError, match="forbidden_write_counter_changed"):
        _build(tmp_path, completion=completion)


def test_real_acceptance_rejects_enable_packet_hash_drift(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import RealAcceptanceError

    enable = _enable_packet()
    enable["bound_facts"]["output_root"] = "/tampered"

    with pytest.raises(RealAcceptanceError, match="service_enable_packet_hash_invalid"):
        _build(tmp_path, enable=enable)


def test_real_acceptance_publish_is_create_only(tmp_path: Path) -> None:
    from app.services.after_market_real_acceptance import (
        RealAcceptanceError,
        publish_real_acceptance_receipt,
    )

    receipt = _build(tmp_path)
    output = tmp_path / "completion_receipt.json"

    assert publish_real_acceptance_receipt(output, receipt) == output
    assert json.loads(output.read_text(encoding="utf-8")) == receipt
    assert publish_real_acceptance_receipt(output, receipt) == output

    drifted = {**receipt, "status": "failed"}
    with pytest.raises(RealAcceptanceError, match="real_acceptance_receipt_drift"):
        publish_real_acceptance_receipt(output, drifted)


def test_real_acceptance_receipt_is_deterministic_for_same_evidence(
    tmp_path: Path,
) -> None:
    first = _build(tmp_path)
    second = _build(tmp_path)

    assert second == first


def _cli_arguments(tmp_path: Path) -> list[str]:
    return [
        "--deployment-receipt",
        str(_artifact(tmp_path, "deployment.json", _deployment_receipt())),
        "--enable-packet",
        str(_artifact(tmp_path, "enable.json", _enable_packet())),
        "--d1-enable-packet",
        str(_artifact(tmp_path, "d1-enable.json", _enable_packet())),
        "--d2-outage-enable-packet",
        str(_artifact(tmp_path, "d2-outage-enable.json", _enable_packet())),
        "--d1-snapshot",
        str(_artifact(tmp_path, "d1.json", _d1_snapshot())),
        "--d2-outage-snapshot",
        str(_artifact(tmp_path, "d2-outage.json", _d2_outage_snapshot())),
        "--d2-completion-snapshot",
        str(_artifact(tmp_path, "d2-completion.json", _d2_completion_snapshot())),
    ]


def test_real_acceptance_cli_verify_only_does_not_publish(
    tmp_path: Path, capsys
) -> None:
    from app.after_market_real_acceptance import main

    output = tmp_path / "completion_receipt.json"
    result = main(
        ["--verify-only", *_cli_arguments(tmp_path), "--receipt-out", str(output)],
        git_identity_provider=lambda: {
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        ancestry_checker=lambda _ancestor, _descendant: True,
    )

    assert result == 0
    assert not output.exists()
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "verified"
    assert payload["gate"] == "JM_EOD_INCREMENTAL_AUTOMATION_READY"
    assert payload["writes_authorized"] is False


def test_real_acceptance_cli_publish_requires_confirmation(
    tmp_path: Path, capsys
) -> None:
    from app.after_market_real_acceptance import main

    output = tmp_path / "completion_receipt.json"
    result = main(
        ["--publish", *_cli_arguments(tmp_path), "--receipt-out", str(output)],
        git_identity_provider=lambda: {
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        ancestry_checker=lambda _ancestor, _descendant: True,
    )

    assert result == 2
    assert not output.exists()
    assert (
        json.loads(capsys.readouterr().out)["error_type"]
        == "final_gate_confirmation_required"
    )


def test_real_acceptance_cli_publish_is_explicit_and_create_only(
    tmp_path: Path, capsys
) -> None:
    from app.after_market_real_acceptance import main

    output = tmp_path / "completion_receipt.json"
    result = main(
        [
            "--publish",
            "--confirm-final-gate",
            *_cli_arguments(tmp_path),
            "--receipt-out",
            str(output),
        ],
        git_identity_provider=lambda: {
            "commit": "v" * 40,
            "tracked_status_sha256": hashlib.sha256(b"").hexdigest(),
        },
        ancestry_checker=lambda _ancestor, _descendant: True,
    )

    assert result == 0
    assert (
        json.loads(output.read_text(encoding="utf-8"))["gate"]
        == "JM_EOD_INCREMENTAL_AUTOMATION_READY"
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "published"
    assert payload["writes_authorized"] is True
