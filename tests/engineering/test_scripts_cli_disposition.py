"""Engineering tests for script disposition and replacement gate."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

from hypothesis import given, settings, strategies as st


ROOT = Path(__file__).resolve().parents[2]


def _load(name: str):
    path = ROOT / "scripts" / "engineering" / name
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


disposition = _load("script_disposition.py")
replacement = _load("replacement_gate.py")


def _baseline_inventory() -> list[str]:
    """Synthetic design-time inventory that satisfies the disposition partition."""
    paths: list[str] = []
    for idx in range(9):
        paths.append(f"scripts/engineering/keep_{idx}.py")
    for name in (
        "dev-down.sh",
        "dev-healthcheck.sh",
        "dev-status.sh",
        "dev-up.sh",
    ):
        paths.append(f"scripts/{name}")
    for name in (
        "install-local-services.sh",
        "local-services-status.sh",
        "post-reboot-verify.sh",
        "rotate-local-service-logs.sh",
        "run-local-service.sh",
    ):
        paths.append(f"scripts/{name}")
    paths.append("scripts/server-status.sh")
    for name in (
        "local-tunnel-healthcheck.sh",
        "public-healthcheck.sh",
        "tunnel-healthcheck.sh",
    ):
        paths.append(f"scripts/{name}")
    for idx in range(5):
        paths.append(f"scripts/backup/file_{idx}.py")
    for idx in range(3):
        paths.append(f"scripts/restore/file_{idx}.py")
    for idx in range(71):
        paths.append(f"scripts/rqdata_item_{idx}.py")
    for idx in range(27):
        paths.append(f"scripts/htdy_runtime_{idx}.py")
    paths.extend(
        [
            "scripts/backfill_jm_price_tick.py",
            "scripts/data_stage_closure_audit.py",
            "scripts/derived_reference_inventory.py",
            "scripts/full_history_audit_v2_closure.py",
            "scripts/regenerate_jm_aggregated_bars.sh",
            "scripts/consumer_contract_final_closeout_006.py",
            "scripts/profile_binding_rollout.py",
            "scripts/profile_binding_rollout_closeout_008b.py",
            "scripts/signal_review_lineage_gate_003.py",
            "scripts/stage13g_repair_report14_lineage.py",
            "scripts/backtest_trust_audit.py",
            "scripts/export_su_bing_daily_score2of4_package.py",
            "scripts/export_su_bing_daily_trend_cross_score2_package.py",
            "scripts/export_su_bing_report_10_review_package.py",
            "scripts/oos_validation_run.py",
            "scripts/jm_eod_automation_gate.py",
        ]
    )
    assert len(paths) == 144
    return paths


@settings(max_examples=100)
@given(
    mutate=st.sampled_from(["add", "remove", "overlap", "ok"]),
)
def test_property_17_disposition_manifest_is_total_partition(mutate: str) -> None:
    """Feature: scripts-cli-consolidation, Property 17: Disposition Manifest Is a Total Partition"""
    inventory = _baseline_inventory()
    if mutate == "add":
        inventory = inventory + ["scripts/extra_unmatched.py"]
    elif mutate == "remove":
        inventory = inventory[:-1]
    elif mutate == "overlap":
        # A path matching both rqdata_* and an exact replacement rule.
        inventory = [
            "scripts/rqdata_backfill_jm_price_tick.py"
            if item == "scripts/backfill_jm_price_tick.py"
            else item
            for item in inventory
        ]
        inventory.append("scripts/backfill_jm_price_tick.py")
        # Also include a path claimed by two globs: rqdata and runtime history.
        inventory.append("scripts/rqdata_htdy_overlap.py")
    report = disposition.classify_inventory(inventory)
    if mutate == "ok":
        assert report.ok
        keep = sum(
            1
            for item in report.assignments
            if item.disposition is disposition.Disposition.KEEP_IN_PLACE
        )
        move = sum(
            1
            for item in report.assignments
            if item.disposition is disposition.Disposition.MOVE
        )
        delete_or_replace = len(report.assignments) - keep - move
        assert (keep, move, delete_or_replace) == (9, 13, 122)
    else:
        assert not report.ok


@settings(max_examples=100)
@given(
    tests_ok=st.booleans(),
    refs=st.integers(min_value=0, max_value=3),
    validations_ok=st.booleans(),
    shim=st.booleans(),
)
def test_property_18_replacement_gate_permits_no_early_deletion(
    tests_ok: bool,
    refs: int,
    validations_ok: bool,
    shim: bool,
) -> None:
    """Feature: scripts-cli-consolidation, Property 18: Replacement Gate Permits No Early Deletion"""
    payload = replacement.ReplacementGateInput(
        replacement_tests_passed=tests_ok,
        active_non_historical_references=refs,
        required_validations_passed=validations_ok,
        has_forwarding_shim=shim,
    )
    result = replacement.evaluate_replacement_gate(payload)
    permitted = tests_ok and refs == 0 and validations_ok and not shim
    assert result.deletion_permitted is permitted


@settings(max_examples=100)
@given(
    include_protected=st.booleans(),
)
def test_property_19_protected_resources_never_enter_repository_deletion(
    include_protected: bool,
) -> None:
    """Feature: scripts-cli-consolidation, Property 19: Protected Resources Never Enter Repository Deletion"""
    assignments = [
        disposition.DispositionAssignment(
            path="scripts/rqdata_audit.py",
            disposition=disposition.Disposition.REPLACE_THEN_DELETE,
            rule_name="rqdata_family",
        )
    ]
    if include_protected:
        assignments.append(
            disposition.DispositionAssignment(
                path=".kiro/specs/personal-development-mode/tasks.md",
                disposition=disposition.Disposition.DELETE,
                rule_name="bad",
            )
        )
    plan = disposition.repository_deletion_plan(assignments)
    assert ".kiro/specs/personal-development-mode/tasks.md" not in plan
    disposition.assert_protected_excluded(plan)
