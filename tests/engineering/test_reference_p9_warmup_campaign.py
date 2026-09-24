"""The P9 data campaign must stay inside the frozen physical target set."""

from __future__ import annotations

import json
from pathlib import Path
import runpy
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
MODULE = runpy.run_path(str(ROOT / "scripts/reference_p9_warmup_campaign.py"))
CANDIDATE = json.loads((
    ROOT / "outputs/reference-p9-warmup-wave1-20260925/candidate-plan.json"
).read_text())


def _one() -> tuple[dict, dict, dict]:
    units, allowed = MODULE["_candidate"](CANDIDATE)
    unit = next(unit for unit in units if any(
        key[1] == unit["symbol"] and key[2] == unit["contract"] and key[3] == "1m"
        for key in allowed
    ))
    target = next(value for key, value in allowed.items()
                  if key[1] == unit["symbol"] and key[2] == unit["contract"]
                  and key[3] == "1m")
    plan = {
        "status": "planned", "readonly": True, "provider_requests": 0,
        "symbol": unit["symbol"], "contract": unit["contract"],
        "frequency": unit["frequency"],
        "requested_window": {"through": unit["owner_last"]},
        "plan_sha256": unit["baseline_plan_sha256"],
        "targets": [{key: value for key, value in target.items()
                     if key != "required_by_stream_ids"}],
        "provider_request_count": 1,
    }
    return unit, allowed, plan


def test_candidate_binds_exact_source_and_unique_targets() -> None:
    units, allowed = MODULE["_candidate"](CANDIDATE)
    assert len(units) == 175
    assert len(allowed) == 2011
    assert len({unit["stream_id"] for unit in units}) == 175


def test_fresh_plan_rejects_target_growth_or_new_partition() -> None:
    unit, allowed, plan = _one()
    assert MODULE["_validate_plan"](unit, plan, allowed)[1:] == (1, 1)
    plan["targets"][0]["missing_bar_count"] += 1
    with pytest.raises(MODULE["CampaignBlocked"], match="UNIT_TARGET_DRIFT"):
        MODULE["_validate_plan"](unit, plan, allowed)
    plan["targets"][0]["missing_bar_count"] -= 1
    plan["targets"][0]["year"] = 2020
    with pytest.raises(MODULE["CampaignBlocked"], match="UNIT_TARGET_DRIFT"):
        MODULE["_validate_plan"](unit, plan, allowed)


def test_preflight_fails_on_baseline_plan_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    unit, allowed, plan = _one()
    plan["plan_sha256"] = "f" * 64
    monkeypatch.setitem(MODULE["_preflight"].__globals__, "_cli", lambda *_a, **_k: plan)
    with pytest.raises(MODULE["CampaignBlocked"], match="BASELINE_PLAN_DRIFT"):
        MODULE["_preflight"](
            [unit], allowed, {}, code_sha="a" * 40, candidate_sha="b" * 64,
            endpoint_sha="c" * 64, canonical_sha="d" * 64,
            max_provider_requests=526, max_total_seconds=30,
        )


def test_uncertain_apply_stops_with_attempt_receipt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    unit, allowed, plan = _one()
    calls = []

    def cli(_unit, _env, *, plan_hash, timeout_seconds):
        calls.append(plan_hash)
        if plan_hash is not None:
            raise MODULE["CampaignBlocked"]("UNIT_OUTCOME_UNKNOWN")
        return plan

    monkeypatch.setitem(MODULE["_apply"].__globals__, "_cli", cli)
    journal = tmp_path / "campaign"
    with pytest.raises(MODULE["CampaignBlocked"], match="UNIT_OUTCOME_UNKNOWN"):
        MODULE["_apply"](
            [unit], allowed, {}, journal_dir=journal,
            max_provider_requests=526, max_total_seconds=30,
        )
    assert calls == [None, unit["baseline_plan_sha256"]]
    unit_dir = next(journal.iterdir())
    assert json.loads((unit_dir / "attempt.json").read_text())["status"] == "started"
    assert not (unit_dir / "result.json").exists()


def test_apply_budget_blocks_before_provider_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    unit, allowed, plan = _one()
    calls = []

    def cli(_unit, _env, *, plan_hash, timeout_seconds):
        calls.append(plan_hash)
        return plan

    monkeypatch.setitem(MODULE["_apply"].__globals__, "_cli", cli)
    journal = tmp_path / "campaign"
    with pytest.raises(MODULE["CampaignBlocked"], match="CAMPAIGN_PROVIDER_BUDGET_EXCEEDED"):
        MODULE["_apply"](
            [unit], allowed, {}, journal_dir=journal,
            max_provider_requests=0, max_total_seconds=30,
        )
    assert calls == [None]
    assert list(journal.iterdir()) == []


def test_apply_checks_zero_remaining_after_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    unit, allowed, plan = _one()
    readback = {**plan, "targets": [], "provider_request_count": 0}
    calls = []

    def cli(_unit, _env, *, plan_hash, timeout_seconds):
        calls.append(plan_hash)
        if plan_hash is not None:
            return {
                "status": "passed", "readonly": False, "plan_sha256": plan_hash,
                "symbol": unit["symbol"], "contract": unit["contract"],
                "frequency": unit["frequency"], "blocked": 0, "failed": 0,
                "provider_requests": 1, "applied": 1,
            }
        return plan if len(calls) == 1 else readback

    monkeypatch.setitem(MODULE["_apply"].__globals__, "_cli", cli)
    result = MODULE["_apply"](
        [unit], allowed, {}, journal_dir=tmp_path / "campaign",
        max_provider_requests=1, max_total_seconds=30,
    )
    assert result["completed_units"] == 1
    assert result["provider_requests"] == 1
    assert calls == [None, plan["plan_sha256"], None]


def test_cli_nonzero_apply_is_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    unit, _, _ = _one()
    monkeypatch.setitem(
        MODULE["_cli"].__globals__["subprocess"].__dict__, "run",
        lambda *_a, **_k: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(MODULE["CampaignBlocked"], match="UNIT_OUTCOME_UNKNOWN"):
        MODULE["_cli"](unit, {}, plan_hash="a" * 64, timeout_seconds=30)
