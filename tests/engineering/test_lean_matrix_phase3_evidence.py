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
IMMUTABLE_BASE = "7a668eeb802b50d140591b75895398550f6c3ae8"
PHASE3_TASK_HEAD = "0d84c9ab512c7ca03eb8c4b10831e041a41dd249"
PHASE3_MERGE_SHA = "c59cda243c141d68ae006c6879da5ce5822a0044"
PHASE3_MERGED_AT = "2026-08-02T09:40:01Z"
CHARTER_URL = "https://github.com/firehell/guiyi-quant-workstation/issues/102"
PHASE3_PR_URL = "https://github.com/firehell/guiyi-quant-workstation/pull/103"
POST_MERGE_CI_URL = (
    "https://github.com/firehell/guiyi-quant-workstation/actions/runs/30742215606"
)
CHECKPOINT_1_URL = f"{CHARTER_URL}#issuecomment-5156225160"
CHECKPOINT_2_URL = f"{CHARTER_URL}#issuecomment-5156261324"
CHECKPOINT_4_URL = f"{CHARTER_URL}#issuecomment-5156354955"
CHECKPOINT_6_URL = f"{CHARTER_URL}#issuecomment-5156412693"
CHECKPOINT_8_URL = f"{CHARTER_URL}#issuecomment-5156427389"
CHARTER_TO_DEVELOP_SOURCE = (
    f"{CHARTER_URL} createdAt 2026-08-02T07:22:32Z; "
    f"{PHASE3_PR_URL} mergedAt {PHASE3_MERGED_AT}"
)
FINAL_SNAPSHOT_METRICS = {
    "Logical sessions through current known checkpoint": "11",
    "User interruptions through current known checkpoint": "0",
    "Independent review-fix rounds through current known checkpoint": "2",
    "Charter-to-local-complete timing through Task 2": "NOT_MEASURABLE",
    "Charter-to-develop cycle": "2h17m29s",
    "Three-round stop status": "NOT_TRIGGERED",
    "Changed-path isolation": "4 tracked paths in PR #103",
}
RECOGNIZED_MEASURED_SOURCES = {
    CHARTER_URL,
    PHASE3_PR_URL,
    POST_MERGE_CI_URL,
    CHARTER_TO_DEVELOP_SOURCE,
    f"Git repository exact base `{IMMUTABLE_BASE}`",
    "Canonical repository design `docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md`",
    "Git repository exact commit range "
    "00c0e7564577aa185f82c20b9f1d6225d1262035.."
    "295f65992615822204c5529380016f87621504f0",
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

    for field in ("Issue: #102", f"Base SHA: `{IMMUTABLE_BASE}`", "Source type: controlled_trial"):
        assert field in identity
    for field in (
        "PR: #103",
        f"Task HEAD: `{PHASE3_TASK_HEAD}`",
        f"Merge SHA: `{PHASE3_MERGE_SHA}`",
        f"Merge time: {PHASE3_MERGED_AT}",
    ):
        assert field in identity
    assert "Classification: controlled_trial" in classification
    assert "Classification provenance: MEASURED" in classification
    assert CHARTER_URL in classification
    for field in (
        "Predicted base roles: 4",
        "Predicted specialists: none",
        "Predicted specialist count: 0",
        "Predicted context separation: implementation and independent review are separate",
        "Prediction provenance: MEASURED",
        f"Prediction evidence: {CHARTER_URL}",
    ):
        assert field in routing
    for field in (
        "Observed base roles: 4",
        "Observed specialists: none",
        "Observed specialist count: 0",
        "Observed context separation: implementation and independent review are separate",
        "Start timestamp: 2026-08-02T07:22:32Z",
        f"Merge timestamp: {PHASE3_MERGED_AT}",
        "Review-fix rounds: 2",
        "Total agent sessions: 11",
        "User interruption count: 0",
        "Observation provenance: MANUALLY_RECORDED",
        f"Observation evidence: human observation: Issue #102 checkpoint 8 ({CHECKPOINT_8_URL})",
        "Current process checkpoints:",
    ):
        assert field in observed
    _assert_metric_contract(metrics)
    assert _metric_fields(metrics, "Immutable base revision")["Value"] == IMMUTABLE_BASE
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
        "Final independent reviewer result",
        "Final PR exact-head and merge result",
        "Post-merge engineering CI",
    ):
        _metric_fields(metrics, metric_name)
    assert "Spec PASS; Quality APPROVED; no findings" in metrics
    assert "0 Critical; 0 Important; 0 Minor; Spec PASS; Quality APPROVED; Draft PR YES" in metrics
    assert "Three-round stop status" in metrics
    assert "NO_GO_PENDING_SEPARATE_APPROVAL" in metrics
    assert "NO_GO" in metrics
    assert PHASE3_PR_URL in metrics
    assert POST_MERGE_CI_URL in metrics
    assert CHARTER_TO_DEVELOP_SOURCE in metrics
    assert "Phase 4: NO_GO_PENDING_SEPARATE_APPROVAL" in gate
    assert "Phase 5: NO_GO" in gate
    assert "Gate evidence:" in gate
    assert "cannot authorize Phase 4" in findings
    assert "workflow mechanics" in findings
    assert "Unmeasurable or manually recorded observations:" in findings
    assert "Decision: Phase 3 controlled trial merged and post-merge verified" in decision
    assert "Required human decision or Gate:" in decision
    assert "NO_GO_PENDING_SEPARATE_APPROVAL" in decision
    assert "NO_GO" in decision
    assert "PR #100 cannot be retroactively counted as Phase 3" in report
    assert "Phase 2 merged through PR #101 at `develop@7a668eeb`" in report
    assert "SDD ledger" not in report
    assert "GitHub Issue #102 Charter/checkpoints" not in report
    assert "PENDING_EXTERNAL_GITHUB_EXACT_HEAD" not in report
    assert "remain external pending" not in report
    assert not re.search(
        r"\b(?:Phase 4|Phase 5|Runtime|main|release|data writes|notifications|deployment)"
        r"\s+is\s+authorized\b",
        report,
        re.IGNORECASE,
    )


def test_phase_three_retrospective_is_a_source_bound_controlled_trial() -> None:
    """Removing any local report section must make the trial evidence incomplete."""
    _assert_trial_report_contract(_report())


def test_phase_three_report_rejects_metric_and_authority_mutations() -> None:
    """Missing provenance or a higher-risk grant must fail the versioned snapshot."""
    report = _report()

    mutations = (
        report.replace(f"- Evidence source: {CHARTER_URL}", "- Evidence source: ", 1),
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
        report.replace("- Value: 11", "- Value: 12", 1),
        report.replace(PHASE3_MERGE_SHA, "0" * 40, 1),
        report.replace("- Value: 2h17m29s", "- Value: 2h17m28s", 1),
        *(
            f"{report}\n{target} is authorized.\n"
            for target in (
                "Phase 4", "Phase 5", "Runtime", "main", "release", "data writes",
                "notifications", "deployment",
            )
        ),
    )
    for mutated_report in mutations:
        with pytest.raises(AssertionError):
            _assert_trial_report_contract(mutated_report)


def test_phase_status_records_the_merged_and_verified_phase_three_pilot() -> None:
    """The canonical status must not retain Phase 3's pre-merge snapshot."""
    design = _design()
    phased_implementation = _section(design, "19. 分阶段实施")

    assert "Phase 2 merged through PR #101 at `develop@7a668eeb`" in design
    assert "remains pending Draft PR exact-head review, CI, and merge" not in design
    assert "Issue #102" in design
    assert PLANNED_BRANCH in design
    assert "Phase 3 merged through PR #103 at `develop@c59cda24`" in design
    assert "post-merge engineering CI passed" in design
    assert "Phase 3 is active under Issue #102 and is not merged" not in design
    assert "PR #100 不能追认为该试运行" in phased_implementation


def test_current_phase_status_retains_the_no_new_authority_boundary() -> None:
    """A Phase 3 status correction must not grant higher-risk delivery authority."""
    design = _design()

    assert (
        "This does not authorize Phase 4 or Phase 5, `main`, Runtime, data writes, "
        "notifications, release, or deployment."
    ) in design
