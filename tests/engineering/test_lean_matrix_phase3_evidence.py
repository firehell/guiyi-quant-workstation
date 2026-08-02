"""Current-status contract for the Lean Matrix Phase 3 pilot."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
DESIGN = ROOT / "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md"
RETROSPECTIVE = ROOT / "docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md"
PLANNED_BRANCH = "research/AI-TEAM-003-phase3-status-consistency-pilot"
TRIAL_REPORT_HEADINGS = (
    "Identity",
    "Sample classification",
    "Routing prediction",
    "Observed execution",
    "Metrics",
    "Gate preservation",
    "Findings",
    "Decision",
)
METRIC_FIELDS = ("Metric name", "Value", "Provenance", "Evidence source")
METRIC_PROVENANCE_STATES = {"MEASURED", "MANUALLY_RECORDED", "NOT_MEASURABLE"}
FINAL_SNAPSHOT_METRICS = {
    "Logical sessions through versioned snapshot": "5",
    "User interruptions through versioned snapshot": "0",
    "Independent review-fix rounds through versioned snapshot": "0",
    "Charter-to-local-complete timing through Task 2": "NOT_MEASURABLE",
    "Three-round stop status": "NOT_TRIGGERED",
    "Changed-path isolation": (
        "only docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-3.md "
        "and tests/engineering/test_lean_matrix_phase3_evidence.py"
    ),
}
RECOGNIZED_MEASURED_SOURCES = {
    "GitHub Issue #102 Charter/checkpoints",
    "Git repository exact base `7a668eeb`",
    "Canonical repository design `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`",
    "SDD ledger `.superpowers/sdd/2026-08-02-lean-matrix-phase-3-status-consistency/progress.md` checkpoint 2",
    "SDD ledger `.superpowers/sdd/2026-08-02-lean-matrix-phase-3-status-consistency/progress.md` Task 1 entry",
    "SDD ledger `.superpowers/sdd/2026-08-02-lean-matrix-phase-3-status-consistency/progress.md` Task 2 entry",
    "Git repository exact pre-review diff from Task 3 base `00c0e756`",
}


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def _report() -> str:
    return RETROSPECTIVE.read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    body = markdown.split(f"## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def _metric_blocks(metrics: str) -> list[str]:
    starts = [match.start() for match in re.finditer(r"(?m)^- Metric name:", metrics)]
    assert starts, "Metrics section must contain at least one metric block"
    return [
        metrics[start:end].rstrip()
        for start, end in zip(starts, (*starts[1:], len(metrics)), strict=True)
    ]


def _assert_metric_contract(metrics: str) -> None:
    for index, block in enumerate(_metric_blocks(metrics), start=1):
        fields: dict[str, str] = {}
        for field in METRIC_FIELDS:
            matches = re.findall(rf"(?m)^- {re.escape(field)}:[ \t]*(.*)$", block)
            assert len(matches) == 1, f"metric block {index} must contain exactly one {field}"
            assert matches[0].strip(), f"metric block {index} has empty {field}"
            fields[field] = matches[0].strip()

        provenance = fields["Provenance"]
        assert provenance in METRIC_PROVENANCE_STATES, (
            f"metric {fields['Metric name']} has invalid provenance {provenance}"
        )
        evidence_source = fields["Evidence source"]
        if provenance == "MEASURED":
            assert evidence_source in RECOGNIZED_MEASURED_SOURCES, (
                f"metric {fields['Metric name']} must cite a recognized repository or GitHub source"
            )
        elif provenance == "MANUALLY_RECORDED":
            assert re.search(r"\bhuman observation\s*:\s*\S", evidence_source, re.IGNORECASE), (
                f"metric {fields['Metric name']} must name the human observation"
            )
            assert re.search(
                r"\bcannot\s+(?:satisfy\s+or\s+)?drive\s+(?:a|any)\s+Gate\b",
                block,
                re.IGNORECASE,
            ), f"metric {fields['Metric name']} must state that it cannot drive a Gate"
        else:
            assert re.search(
                r"\b(?:absent|absence|missing|unavailable|not recorded|"
                r"do not record|does not record|no (?:canonical|GitHub|source|evidence))\b",
                block,
                re.IGNORECASE,
            ), f"metric {fields['Metric name']} must document absence evidence"


def _metric_fields(metrics: str, metric_name: str) -> dict[str, str]:
    for block in _metric_blocks(metrics):
        fields = {
            field: re.search(rf"(?m)^- {re.escape(field)}:[ \t]*(.*)$", block).group(1).strip()
            for field in METRIC_FIELDS
        }
        if fields["Metric name"] == metric_name:
            return fields
    raise AssertionError(f"missing final-snapshot metric: {metric_name}")


def _assert_trial_report_contract(report: str) -> None:
    for heading in TRIAL_REPORT_HEADINGS:
        assert f"## {heading}\n" in report

    identity = _section(report, "Identity")
    classification = _section(report, "Sample classification")
    routing = _section(report, "Routing prediction")
    observed = _section(report, "Observed execution")
    metrics = _section(report, "Metrics")
    gate = _section(report, "Gate preservation")
    findings = _section(report, "Findings")
    decision = _section(report, "Decision")

    for field in ("Issue: #102", "Base SHA: `7a668eeb`", "Source type: controlled_trial"):
        assert field in identity
    for field in (
        "PR: PENDING_EXTERNAL_GITHUB_EXACT_HEAD",
        "Task HEAD: PENDING_EXTERNAL_GITHUB_EXACT_HEAD",
        "Merge SHA: PENDING_EXTERNAL_GITHUB_EXACT_HEAD",
        "Merge time: PENDING_EXTERNAL_GITHUB_EXACT_HEAD",
    ):
        assert field in identity
    assert "Classification: controlled_trial" in classification
    assert "Classification provenance: MEASURED" in classification
    assert "GitHub Issue #102 Charter/checkpoints" in classification
    for field in (
        "Predicted base roles: 4",
        "Predicted specialists: none",
        "Predicted specialist count: 0",
        "Predicted context separation: implementation and independent review are separate",
    ):
        assert field in routing
    for field in (
        "Observed base roles: 4",
        "Observed specialists: none",
        "Observed specialist count: 0",
        "Observed context separation: implementation and independent review are separate",
        "Start timestamp: 2026-08-02T07:22:32Z",
        "Current process checkpoints:",
    ):
        assert field in observed
    _assert_metric_contract(metrics)
    for metric_name, expected_value in FINAL_SNAPSHOT_METRICS.items():
        assert _metric_fields(metrics, metric_name)["Value"] == expected_value
    charter_to_local_complete = _metric_fields(
        metrics, "Charter-to-local-complete timing through Task 2"
    )
    assert charter_to_local_complete["Provenance"] == "NOT_MEASURABLE"
    assert "timestamp receipt is absent" in charter_to_local_complete["Evidence source"]
    assert not any("Task 2 commit" in source for source in RECOGNIZED_MEASURED_SOURCES)
    for metric_name in (
        "Task 1 independent review result",
        "Task 2 independent review result",
        "Final independent reviewer result at versioned task snapshot",
        "Final GitHub evidence required after versioned snapshot",
    ):
        _metric_fields(metrics, metric_name)
    assert "Spec PASS; Quality APPROVED; no findings" in metrics
    assert "Three-round stop status" in metrics
    assert "NO_GO_PENDING_SEPARATE_APPROVAL" in metrics
    assert "NO_GO" in metrics
    assert "Draft PR evidence comment" in metrics
    assert "final logical-session count" in metrics
    assert "final review-fix count" in metrics
    assert "final reviewer result" in metrics
    assert "PR number" in metrics
    assert "exact head" in metrics
    assert "CI" in metrics
    assert "merge facts" in metrics
    assert "Phase 4: NO_GO_PENDING_SEPARATE_APPROVAL" in gate
    assert "Phase 5: NO_GO" in gate
    assert "cannot authorize Phase 4" in findings
    assert "workflow mechanics" in findings
    assert "Decision: controlled-trial evidence only" in decision
    assert "Required human decision or Gate:" in decision
    assert "NO_GO_PENDING_SEPARATE_APPROVAL" in decision
    assert "NO_GO" in decision
    assert "PR #100 cannot be retroactively counted as Phase 3" in report
    assert "Phase 2 merged through PR #101 at `develop@7a668eeb`" in report
    assert not re.search(r"\b(?:Phase 4|Phase 5|Runtime)\s+is\s+authorized\b", report, re.IGNORECASE)


def test_phase_three_retrospective_is_a_source_bound_controlled_trial() -> None:
    """Removing any local report section must make the trial evidence incomplete."""
    _assert_trial_report_contract(_report())


def test_phase_three_report_rejects_metric_and_authority_mutations() -> None:
    """Missing provenance or a higher-risk grant must fail the versioned snapshot."""
    report = _report()

    mutations = (
        report.replace("- Evidence source: GitHub Issue #102 Charter/checkpoints", "- Evidence source: ", 1),
        report.replace("- Provenance: MEASURED", "- Provenance: INFERRED", 1),
        report.replace(
            "PR #100 cannot be retroactively counted as Phase 3",
            "PR #100 is the Phase 3 controlled trial",
            1,
        ),
        report.replace(
            "Phase 2 merged through PR #101 at `develop@7a668eeb`",
            "Phase 2 remains pending Draft PR exact-head review, CI, and merge",
            1,
        ),
        report.replace(
            "- Value: 0\n- Provenance: MEASURED\n- Evidence source: "
            "SDD ledger `.superpowers/sdd/2026-08-02-lean-matrix-phase-3-status-consistency/progress.md` "
            "checkpoint 2",
            "- Value: 1\n- Provenance: MEASURED\n- Evidence source: "
            "SDD ledger `.superpowers/sdd/2026-08-02-lean-matrix-phase-3-status-consistency/progress.md` "
            "checkpoint 2",
            1,
        ),
        f"{report}\nPhase 4 is authorized.\nRuntime is authorized.\n",
    )
    for mutated_report in mutations:
        with pytest.raises(AssertionError):
            _assert_trial_report_contract(mutated_report)


def test_phase_status_records_the_merged_phase_two_and_active_phase_three_pilot() -> None:
    """A stale pending-PR status must not hide Phase 2's merged evidence."""
    design = _design()
    phased_implementation = _section(design, "19. 分阶段实施")

    assert "Phase 2 merged through PR #101 at `develop@7a668eeb`" in design
    assert "remains pending Draft PR exact-head review, CI, and merge" not in design
    assert "Issue #102" in design
    assert PLANNED_BRANCH in design
    assert "Phase 3 is active under Issue #102 and is not merged" in design
    assert "implemented on its task branch only after tracked evidence exists" in design
    assert "PR #100 不能追认为该试运行" in phased_implementation


def test_current_phase_status_retains_the_no_new_authority_boundary() -> None:
    """A Phase 3 status correction must not grant higher-risk delivery authority."""
    design = _design()

    assert (
        "This does not authorize Phase 4 or Phase 5, `main`, Runtime, data writes, "
        "notifications, release, or deployment."
    ) in design
