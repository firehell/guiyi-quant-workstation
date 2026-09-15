from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from scripts import newow_weekly_recovery as native


def _campaign() -> dict[str, Any]:
    from app.market_data.operational_universe import load_operational_products
    from scripts import newow_weekly_recovery_campaign as campaign_module

    products = tuple(load_operational_products())
    unit = {
        "symbol": "ag",
        "contract": "AG2601",
        "frequency": "1d",
        "through": "2026-09-11",
        "plan_sha256": "a" * 64,
        "target_count": 1,
    }
    campaign = {
        "schema_version": "newow_daily_recovery_campaign_v1",
        "audit": {
            "sha256": "b" * 64,
            "as_of": "2026-09-13T06:36:13+00:00",
            "frequency_scope": ["1d"],
        },
        "execution_identity": {
            "code_commit": "c" * 40,
            "execution_code_sha256": "d" * 64,
            "config_sha256": "e" * 64,
            "canonical_root_sha256": "f" * 64,
        },
        "scope": {
            "product_count": len(products),
            "product_universe_sha256": campaign_module._identity_sha256(list(products)),
            "denominator_unit_count": 1,
            "excluded_status_counts": {},
        },
        "children": [{"batch_id": "batch-001", "units": [unit]}],
    }
    campaign["campaign_sha256"] = hashlib.sha256(
        native._canonical_json(campaign).encode("utf-8")
    ).hexdigest()
    return campaign


def _execution(campaign: dict[str, Any], *, status: str = "passed") -> dict[str, Any]:
    counts = {
        "denominator_unit_count": 1,
        "success_unit_count": 1 if status == "passed" else 0,
        "isolated_unit_count": 0,
        "partial_source_exception_unit_count": 0,
        "stopping_failure_unit_count": 0,
        "unattempted_unit_count": 0,
        "unknown_unit_count": 1 if status == "unknown" else 0,
    }
    return {
        "status": status,
        "campaign_manifest_sha256": campaign["campaign_sha256"],
        "summary": counts,
    }


def _audit(*, complete: bool = True, dependency_status: str = "DATA_READY"):
    from tests.newow.test_weekly_recovery_campaign import _daily_report

    report = _daily_report([])
    report["status"] = "audited" if complete else "incomplete"
    report["complete"] = complete
    report["budget_exhausted"] = not complete
    for dependency in report["dependencies"]:
        dependency["status"] = dependency_status
        dependency["reason"] = (
            None if dependency_status == "DATA_READY" else "REPLAY_PREFIX_MISSING"
        )
    if dependency_status != "DATA_READY":
        for dependency in report["dependencies"]:
            dependency.pop("cutoff", None)
            dependency.pop("actual_bar_count", None)
            dependency.pop("expected_bar_count", None)
            dependency["error"] = {
                "code": "NEWOW_DATA_UNAVAILABLE",
                "diagnostic": {},
            }
    return report


def _replan(unit):
    return {
        "status": "passed",
        "symbol": unit["symbol"],
        "contract": unit["contract"],
        "frequency": "1d",
        "requested_through": unit["through"],
        "plan_sha256": "1" * 64,
        "targets": [],
        "remaining_target_count": 0,
    }


def test_successful_execution_and_complete_audit_are_independently_verified() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()
    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign),
        run_audit=lambda _request: _audit(),
        replan_unit=_replan,
    )

    assert result["inventory_complete"] is True
    assert result["ordinary_recovery_complete"] is True
    assert result["verification_status"] == "verified"
    assert result["execution"]["counts"]["success"] == 1
    assert result["metrics"] == {
        "dependency_count": 120,
        "execution_unit_count": 1,
        "partition_count": 1,
        "missing_endpoint_count": 0,
        "provider_request_count": 0,
    }
    assert len(result["input_availability"]) == 60 * 3 * 3
    assert {item["status"] for item in result["input_availability"]} == {"available"}


def test_zero_ordinary_targets_still_require_complete_input_audit() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign
    from tests.newow.test_weekly_recovery_campaign import _daily_report, _daily_unit

    campaign = _campaign()
    campaign["children"] = []
    campaign["scope"]["denominator_unit_count"] = 0
    campaign["campaign_sha256"] = hashlib.sha256(
        native._canonical_json(
            {key: value for key, value in campaign.items() if key != "campaign_sha256"}
        ).encode("utf-8")
    ).hexdigest()
    execution = {
        "status": "passed",
        "campaign_manifest_sha256": campaign["campaign_sha256"],
        "summary": {
            "denominator_unit_count": 0,
            "success_unit_count": 0,
            "isolated_unit_count": 0,
            "partial_source_exception_unit_count": 0,
            "stopping_failure_unit_count": 0,
            "unattempted_unit_count": 0,
            "unknown_unit_count": 0,
        },
    }

    result = verify_daily_campaign(
        campaign=campaign,
        execution=execution,
        run_audit=lambda _request: _daily_report([_daily_unit()]),
        replan_unit=lambda _unit: pytest.fail("zero target must not replan"),
    )

    assert result["ordinary_recovery_complete"] is True
    assert result["inventory_complete"] is True
    assert result["verification_status"] == "incomplete"
    assert {row["status"] for row in result["input_availability"]} == {
        "available",
        "missing",
    }


def test_incomplete_final_audit_preserves_proven_execution_facts() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()
    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign),
        run_audit=lambda _request: _audit(complete=False),
        replan_unit=_replan,
    )

    assert result["inventory_complete"] is False
    assert result["ordinary_recovery_complete"] is True
    assert result["execution"]["counts"]["success"] == 1
    assert result["verification_status"] == "incomplete"


def test_successful_final_audit_cannot_erase_unknown_execution() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()
    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign, status="unknown"),
        run_audit=lambda _request: _audit(),
        replan_unit=lambda _unit: pytest.fail(
            "unknown unit must not be replanned as passed"
        ),
    )

    assert result["inventory_complete"] is True
    assert result["ordinary_recovery_complete"] is False
    assert result["execution"]["counts"]["unknown"] == 1
    assert result["verification_status"] == "incomplete"


def test_audit_exception_is_sanitized_without_changing_execution() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()

    def fail(_request):
        raise RuntimeError("private connection detail")

    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign),
        run_audit=fail,
        replan_unit=_replan,
    )

    assert result["inventory_complete"] is False
    assert result["execution"]["counts"]["success"] == 1
    assert result["verification_status"] == "failed"
    assert result["verification_error"] == "FINAL_AUDIT_FAILED"
    assert "private" not in native._canonical_json(result)


def test_final_replan_failure_is_sanitized_without_changing_execution() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()

    def fail(_unit):
        raise RuntimeError("private canonical path")

    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign),
        run_audit=lambda _request: _audit(),
        replan_unit=fail,
    )

    assert result["inventory_complete"] is True
    assert result["ordinary_recovery_complete"] is True
    assert result["execution"]["counts"]["success"] == 1
    assert result["verification_status"] == "failed"
    assert result["verification_error"] == "FINAL_REPLAN_FAILED"
    assert "private" not in native._canonical_json(result)


def test_cropped_complete_audit_cannot_be_reported_as_inventory_complete() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()
    cropped = _audit()
    cropped["enumerations"].pop()
    result = verify_daily_campaign(
        campaign=campaign,
        execution=_execution(campaign),
        run_audit=lambda _request: cropped,
        replan_unit=_replan,
    )

    assert result["inventory_complete"] is False
    assert result["verification_status"] == "failed"
    assert result["execution"]["counts"]["success"] == 1


def test_campaign_execution_binding_mismatch_fails_closed() -> None:
    from scripts.newow_daily_recovery_verification import verify_daily_campaign

    campaign = _campaign()
    execution = _execution(campaign)
    execution["campaign_manifest_sha256"] = "0" * 64

    with pytest.raises(native.RecoveryError, match="^VERIFICATION_IDENTITY_CHANGED$"):
        verify_daily_campaign(
            campaign=campaign,
            execution=execution,
            run_audit=lambda _request: _audit(),
            replan_unit=_replan,
        )


def test_verification_cli_writes_one_hash_bound_observation(
    tmp_path: Path, monkeypatch
) -> None:
    from scripts import newow_daily_recovery_verification as module

    campaign = _campaign()
    execution = _execution(campaign)
    campaign_path = tmp_path / "campaign.json"
    execution_path = tmp_path / "execution.json"
    campaign_sha = native._write_json_exclusive(campaign_path, campaign)
    execution["campaign_manifest_sha256"] = campaign_sha
    execution_sha = native._write_json_exclusive(execution_path, execution)
    expected = {
        "schema_version": "newow_daily_recovery_verification_v1",
        "inventory_complete": True,
        "ordinary_recovery_complete": True,
        "verification_status": "verified",
        "execution": {"counts": {"success": 1}},
    }
    monkeypatch.setattr(
        module.campaign_module,
        "validate_campaign_manifest",
        lambda value, evidence_root: value,
    )
    monkeypatch.setattr(
        module,
        "_run_readonly_verification",
        lambda **_kwargs: expected,
    )

    code = module.main(
        [
            "--project-env",
            str(tmp_path / "project.env"),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha,
            "--execution",
            str(execution_path),
            "--expected-execution-sha256",
            execution_sha,
            "--output-root",
            str(tmp_path),
            "--observation-id",
            "verify-001",
        ]
    )

    observation = tmp_path / "verify-001"
    assert code == 0
    assert json.loads((observation / "verification.json").read_text()) == expected
    assert (observation / "summary.md").read_text().startswith("# 牛哇日线恢复独立结算")


def test_verification_cli_reports_identity_change_without_raw_details(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    from scripts import newow_daily_recovery_verification as module

    campaign = _campaign()
    execution = _execution(campaign)
    campaign_path = tmp_path / "campaign.json"
    execution_path = tmp_path / "execution.json"
    campaign_sha = native._write_json_exclusive(campaign_path, campaign)
    execution["campaign_manifest_sha256"] = campaign_sha
    execution_sha = native._write_json_exclusive(execution_path, execution)
    monkeypatch.setattr(
        module.campaign_module,
        "validate_campaign_manifest",
        lambda value, evidence_root: value,
    )

    def changed(**_kwargs):
        raise native.RecoveryError("VERIFICATION_IDENTITY_CHANGED")

    monkeypatch.setattr(module, "_run_readonly_verification", changed)
    code = module.main(
        [
            "--project-env",
            str(tmp_path / "project.env"),
            "--campaign",
            str(campaign_path),
            "--expected-campaign-sha256",
            campaign_sha,
            "--execution",
            str(execution_path),
            "--expected-execution-sha256",
            execution_sha,
            "--output-root",
            str(tmp_path),
            "--observation-id",
            "verify-identity",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 2
    assert payload["status"] == "identity_changed"
    assert payload["error_code"] == "VERIFICATION_IDENTITY_CHANGED"


@pytest.mark.parametrize("option", ["--apply", "--retry", "--resume"])
def test_verification_cli_has_no_mutating_or_resume_options(option: str) -> None:
    from scripts.newow_daily_recovery_verification import parser

    with pytest.raises(SystemExit) as exc:
        parser().parse_args([option])
    assert exc.value.code == 2
