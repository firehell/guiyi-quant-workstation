from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts/consumer_contract_final_closeout_006.py"
SPEC = importlib.util.spec_from_file_location("consumer_contract_final_closeout_006", SCRIPT_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_plan_digest_is_stable_and_excludes_generated_metadata() -> None:
    operations = [
        {"action": "replace", "profile_id": "p", "binding_id": 2, "target_file_id": 8},
        {"action": "deactivate", "profile_id": "p", "binding_id": 3, "target_file_id": None},
    ]
    first = MODULE.plan_digest(operations)
    second = MODULE.plan_digest(list(reversed(list(reversed(operations)))))

    assert first == second
    assert len(first) == 64


def test_select_replacement_requires_primary_passed_coverage_and_provenance() -> None:
    current = {"start_time": "2020-01-01T00:00:00", "end_time": "2026-07-10T00:00:00"}
    candidates = [
        {"id": 1, "data_role": "primary", "quality_status": "warning", "start_time": "2019-01-01T00:00:00", "end_time": "2026-07-10T00:00:00", "source_interval": "1m", "physical_ok": True},
        {"id": 2, "data_role": "primary", "quality_status": "passed", "start_time": "2021-01-01T00:00:00", "end_time": "2026-07-10T00:00:00", "source_interval": "1m", "physical_ok": True},
        {"id": 3, "data_role": "primary", "quality_status": "passed", "start_time": "2019-01-01T00:00:00", "end_time": "2026-07-10T00:00:00", "source_interval": None, "physical_ok": True},
        {"id": 4, "data_role": "primary", "quality_status": "passed", "start_time": "2019-01-01T00:00:00", "end_time": "2026-07-10T00:00:00", "source_interval": "1m", "physical_ok": True},
    ]

    selected = MODULE.select_replacement(current=current, candidates=candidates)

    assert selected is not None
    assert selected["id"] == 4


def test_live_tables_only_period_is_deactivated_instead_of_rebound() -> None:
    assert MODULE.action_for_invalid_binding(
        profile_id="live_observation_v1",
        period="30m",
        replacement={"id": 9},
    ) == "deactivate"
    assert MODULE.action_for_invalid_binding(
        profile_id="intraday_research_v1",
        period="30m",
        replacement={"id": 9},
    ) == "replace"
