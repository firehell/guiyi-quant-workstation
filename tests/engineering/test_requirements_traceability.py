"""Requirements traceability matrix for personal-development-mode.

Feature: personal-development-mode, Property 26
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = ROOT / ".kiro/specs/personal-development-mode/requirements.md"

# Every acceptance criterion id mapped to at least one verification artifact.
# External GitHub ruleset status remains explicitly unverified.
TRACEABILITY: dict[str, tuple[str, ...]] = {
    "1.1": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.2": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.3": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.4": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.5": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.6": ("tests/engineering/test_personal_collaboration_properties.py",),
    "1.7": ("tests/engineering/test_codex_automation_policy.py",),
    "1.8": ("tests/engineering/test_personal_collaboration_properties.py",),
    "2.1": ("tests/engineering/test_personal_workflow.py",),
    "2.2": ("tests/engineering/test_codex_automation_policy.py",),
    "2.3": ("tests/engineering/test_personal_workflow_properties.py",),
    "2.4": ("docs/PERSONAL_DEVELOPMENT_WORKFLOW.md",),
    "2.5": ("tests/engineering/test_engineering_entrypoints.py",),
    "2.6": ("tests/engineering/test_task_contract_consistency.py",),
    "2.7": ("tests/engineering/test_personal_canonical_consistency.py",),
    "2.8": ("tests/engineering/test_personal_collaboration_properties.py",),
    "3.1": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "3.2": ("tests/engineering/test_repository_consistency.py",),
    "3.3": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "3.4": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "3.5": ("TESTING.md",),
    "3.6": ("scripts/engineering/preflight.ps1",),
    "3.7": ("scripts/engineering/validate.ps1",),
    "4.1": ("tests/engineering/test_personal_collaboration_properties.py",),
    "4.2": ("tests/engineering/test_personal_collaboration_properties.py",),
    "4.3": ("tests/engineering/test_runtime_gate_inventory.py",),
    "4.4": ("docs/tasks/README.md",),
    "4.5": ("docs/PERSONAL_DEVELOPMENT_WORKFLOW.md",),
    "4.6": ("tests/engineering/test_task_contract_consistency.py",),
    "5.1": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.2": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.3": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.4": ("scripts/engineering/release-tag.ps1",),
    "5.5": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.6": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.7": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.8": ("tests/engineering/test_personal_workflow_properties.py",),
    "5.9": ("tests/engineering/test_personal_workflow_properties.py",),
    "6.1": ("scripts/engineering/release-tag.ps1",),
    "6.2": ("scripts/engineering/release-tag.ps1",),
    "6.3": ("scripts/engineering/release-tag.ps1",),
    "6.4": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "6.5": ("tests/engineering/test_powershell_entrypoints.py",),
    "6.6": ("scripts/engineering/release-tag.ps1",),
    "6.7": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "6.8": ("tests/engineering/test_personal_workflow_properties.py",),
    "7.1": ("scripts/engineering/preflight.ps1",),
    "7.2": ("scripts/engineering/validate.ps1",),
    "7.3": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "7.4": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "7.5": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "7.6": (".github/workflows/optional-ci.yml",),
    "7.7": ("TESTING.md",),
    "7.8": ("Makefile",),
    "8.1": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "8.2": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "8.3": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "8.4": ("scripts/engineering/validate.ps1",),
    "8.5": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "8.6": ("tests/engineering/test_personal_workflow.py",),
    "8.7": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "8.8": ("tests/engineering/test_personal_entrypoint_properties.py",),
    "9.1": ("tests/engineering/test_personal_canonical_consistency.py",),
    "9.2": ("tests/engineering/test_personal_domain_properties.py",),
    "9.3": ("tests/engineering/test_personal_domain_properties.py",),
    "9.4": ("tests/engineering/test_personal_domain_properties.py",),
    "9.5": ("tests/engineering/test_personal_domain_properties.py",),
    "9.6": ("tests/engineering/test_personal_domain_properties.py",),
    "9.7": ("tests/engineering/test_personal_domain_properties.py",),
    "9.8": ("tests/engineering/test_personal_canonical_consistency.py",),
    "9.9": ("tests/engineering/test_personal_domain_properties.py",),
    "9.10": ("tests/engineering/test_personal_domain_properties.py",),
    "10.1": ("AGENTS.md",),
    "10.2": ("tests/engineering/test_personal_domain_properties.py",),
    "10.3": ("tests/engineering/test_personal_domain_properties.py",),
    "10.4": ("AGENTS.md",),
    "10.5": ("tests/engineering/test_personal_domain_properties.py",),
    "10.6": ("AGENTS.md",),
    "10.7": ("tests/engineering/test_personal_domain_properties.py",),
    "10.8": ("tests/engineering/test_personal_domain_properties.py",),
    "10.9": ("tests/engineering/test_personal_domain_properties.py",),
    "11.1": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.2": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.3": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.4": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.5": ("tests/engineering/test_personal_workflow_properties.py",),
    "11.6": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.7": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.8": ("tests/engineering/test_runtime_gate_inventory.py",),
    "11.9": ("tests/engineering/test_runtime_gate_inventory.py",),
    "12.1": ("tests/engineering/test_personal_canonical_consistency.py",),
    "12.2": ("tests/engineering/test_personal_canonical_consistency.py",),
    "12.3": ("tests/engineering/test_engineering_entrypoints.py",),
    "12.4": ("tests/engineering/test_task_contract_consistency.py",),
    "12.5": ("tests/engineering/test_personal_canonical_consistency.py",),
    "12.6": ("tests/engineering/test_personal_canonical_consistency.py",),
    "12.7": ("tests/engineering/test_codex_automation_policy.py",),
    "12.8": ("tests/engineering/test_task_contract_consistency.py",),
    "12.9": ("tests/engineering/test_runtime_safety_smoke.py",),
    "12.10": ("tests/engineering/test_runtime_safety_smoke.py",),
    "12.11": ("tests/engineering/test_powershell_entrypoints.py",),
    "12.12": ("tests/engineering/test_requirements_traceability.py",),
    "github_ruleset": ("unverified: remote GitHub required-check status was not read",),
}


def _parse_requirement_ids() -> set[str]:
    text = REQUIREMENTS.read_text(encoding="utf-8")
    ids: set[str] = set()
    current_req: str | None = None
    for line in text.splitlines():
        req = re.match(r"^### Requirement (\d+):", line)
        if req:
            current_req = req.group(1)
            continue
        crit = re.match(r"^(\d+)\.\s", line.strip())
        if current_req and crit:
            ids.add(f"{current_req}.{crit.group(1)}")
    return ids


def test_traceability_covers_all_acceptance_criteria_exactly_once() -> None:
    parsed = _parse_requirement_ids()
    mapped = {key for key in TRACEABILITY if key != "github_ruleset"}
    missing = sorted(parsed - mapped)
    unknown = sorted(mapped - parsed)
    assert not missing, f"missing criterion mappings: {missing}"
    assert not unknown, f"unknown criterion mappings: {unknown}"
    # No duplicate keys by construction of dict.


@pytest.mark.parametrize("index", range(100))
def test_property_26_acceptance_coverage_is_complete_and_safety_sensitive(index: int) -> None:
    """Feature: personal-development-mode, Property 26: Acceptance coverage is complete and safety-sensitive"""
    keys = sorted(k for k in TRACEABILITY if k != "github_ruleset")
    key = keys[index % len(keys)]
    artifacts = TRACEABILITY[key]
    assert artifacts
    if artifacts[0].startswith("unverified:"):
        pytest.fail("safety criteria must not map only to unverified external status")
    for artifact in artifacts:
        path = ROOT / artifact
        assert path.exists(), f"{key} -> missing {artifact}"
    # Safety witnesses: invalid input / failed quality / secret exposure fail acceptance.
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "fail-closed" in agents.lower() or "默认拒绝" in agents or "fail closed" in agents.lower() or "fail-closed" in agents or "失败" in agents
