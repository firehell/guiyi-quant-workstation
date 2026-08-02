"""Evidence contract for the source-bound Lean Matrix Phase 2 retrospective."""

from __future__ import annotations

import re
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
RETROSPECTIVE = ROOT / "docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-2.md"
DESIGN = ROOT / "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md"
PLAN = ROOT / "docs/superpowers/plans/2026-08-02-lean-matrix-phase-2-controlled-retrospective.md"
METRIC_FIELDS = ("Metric name", "Value", "Provenance", "Evidence source")
METRIC_PROVENANCE_STATES = {"MEASURED", "MANUALLY_RECORDED", "NOT_MEASURABLE"}
CANONICAL_PATH = (
    r"(?:STATUS\.md|docs/tasks/[A-Za-z0-9._/-]+\.md|"
    r"docs/superpowers/specs/[A-Za-z0-9._/-]+\.md)"
)
RECOGNIZED_MEASURED_SOURCE_PATTERNS = (
    re.compile(rf"(?:{CANONICAL_PATH}|`{CANONICAL_PATH}`)"),
    re.compile(
        r"Canonical repository (?:status|design|task)"
        r"(?:/(?:status|design|task))* records?",
        re.IGNORECASE,
    ),
    re.compile(
        r"GitHub (?:Issue|PR) #\d+(?:-#\d+)? "
        r"(?:metadata|commit lists?|files? lists?|checks?|evidence comment)"
        r"(?:/(?:metadata|commit lists?|files? lists?|checks?|evidence comment))*",
        re.IGNORECASE,
    ),
)

FORBIDDEN_AFFIRMATIVE_PATTERNS = (
    re.compile(
        r"\bPR #100\s+(?:is|was|counts as|served as|completed)\s+"
        r"(?:the\s+)?Phase 3\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bTask 05\s+(?:is|was|became|served as)\s+(?:the\s+)?"
        r"Phase 3(?:\s+(?:trial|controlled trial|task))?\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bPhase 3(?:\s+(?:trial|controlled trial))?\s+(?:is|was)\s+Task 05\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<![\w`])(?:Phase 4(?:/| or )Phase 5|Phase 4|Phase 5|`main`|main|"
        r"release|`Runtime`|Runtime|data writes?(?:/notifications?)?|notifications?)"
        r"(?:\s+(?:automation|delegation|automation/delegation))?\s+"
        r"(?:is|are|has been|have been)\s+authorized\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?<!does not )(?<!doesn't )(?<!not )\bauthorizes?\s+"
        r"(?:Phase 4(?:/| or )Phase 5|Phase 4|Phase 5|`main`|main|release|"
        r"`Runtime`|Runtime|data writes?(?:/notifications?)?|notifications?)\b",
        re.IGNORECASE,
    ),
)


def _report() -> str:
    return RETROSPECTIVE.read_text(encoding="utf-8")


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def _plan() -> str:
    return PLAN.read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    body = markdown.split(f"## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def _subsection(markdown: str, heading: str) -> str:
    body = markdown.split(f"### {heading}\n", 1)[1]
    return body.split("\n### ", 1)[0]


def _metric_block(section: str, name: str) -> str:
    body = section.split(f"- Metric name: {name}\n", 1)[1]
    return body.split("\n- Metric name: ", 1)[0]


def _is_recognized_measured_source(evidence_source: str) -> bool:
    return any(
        pattern.fullmatch(evidence_source)
        for pattern in RECOGNIZED_MEASURED_SOURCE_PATTERNS
    )


def _validated_metric_blocks(sample_section: str) -> list[dict[str, str]]:
    """Return validated metric blocks from one sample's Metrics subsection."""
    metrics = _subsection(sample_section, "Metrics")
    starts = [match.start() for match in re.finditer(r"(?m)^- Metric name:", metrics)]
    assert starts, "Metrics subsection must contain at least one metric block"

    blocks = [
        metrics[start:end].rstrip()
        for start, end in zip(starts, (*starts[1:], len(metrics)), strict=True)
    ]
    validated: list[dict[str, str]] = []
    for index, block in enumerate(blocks, start=1):
        fields: dict[str, str] = {}
        for field in METRIC_FIELDS:
            matches = re.findall(rf"(?m)^- {re.escape(field)}:[ \t]*(.*)$", block)
            assert len(matches) == 1, f"metric block {index} must contain exactly one {field}"
            value = matches[0].strip()
            assert value, f"metric block {index} has empty {field}"
            fields[field] = value

        provenance = fields["Provenance"]
        assert provenance in METRIC_PROVENANCE_STATES, (
            f"metric {fields['Metric name']} has invalid provenance {provenance}"
        )
        evidence_source = fields["Evidence source"]
        if provenance == "MEASURED":
            assert _is_recognized_measured_source(evidence_source), (
                f"metric {fields['Metric name']} must cite a recognized canonical or GitHub source"
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
        elif provenance == "NOT_MEASURABLE":
            assert re.search(
                r"\b(?:absent|absence|missing|unavailable|not recorded|"
                r"do not record|does not record|no (?:canonical|GitHub|source|evidence))\b",
                block,
                re.IGNORECASE,
            ), f"metric {fields['Metric name']} must document limitation or absence evidence"

        validated.append(fields)

    return validated


def _affirmative_authority_claims(markdown: str) -> list[str]:
    return [
        match.group(0)
        for pattern in FORBIDDEN_AFFIRMATIVE_PATTERNS
        for match in pattern.finditer(markdown)
    ]


def _assert_sample_contract(section: str, classification: str) -> None:
    """Bind identity, provenance, and limits to one sample, not the whole report."""
    identity = _subsection(section, "Identity")
    sample_classification = _subsection(section, "Sample classification")
    prediction = _subsection(section, "Routing prediction")
    observed = _subsection(section, "Observed execution")
    gate = _subsection(section, "Gate preservation")
    findings = _subsection(section, "Findings")
    decision = _subsection(section, "Decision")

    for field in (
        "Issue:", "PR:", "Base SHA:", "Task HEAD:", "Merge SHA:",
        "Source type:", "Source references:",
    ):
        assert f"- {field}" in identity, (classification, field)
    for field in (
        f"Classification: {classification}",
        "Classification provenance: MEASURED",
        "Classification evidence:",
        "Issue #99",
    ):
        assert field in sample_classification, (classification, field)
    for field in (
        "Predicted base roles:", "Predicted specialists:",
        "Predicted specialist count:", "Predicted context separation:",
        "Prediction provenance: MEASURED", "Prediction evidence:",
    ):
        assert field in prediction, (classification, field)
    for field in (
        "Observed base roles:", "Observed specialists:",
        "Observed specialist count:", "Observed context separation:",
        "Start timestamp:", "Merge timestamp:", "Review-fix rounds:",
        "Total agent sessions:", "User interruption count:",
        "Observation provenance:", "Observation evidence:",
    ):
        assert field in observed, (classification, field)
    assert "Observation provenance: MEASURED" in observed, classification
    assert "NOT_MEASURABLE" in observed, classification
    for field in ("CI:", "External Gates:", "Gate evidence:", "No-authority statement:"):
        assert field in gate, (classification, field)
    for field in ("Finding:", "Evidence limitations:"):
        assert field in findings, (classification, field)
    for field in ("Decision:", "Required human decision or Gate:", "Next permitted action:"):
        assert field in decision, (classification, field)


def test_retrospective_preserves_two_source_bound_samples() -> None:
    """Removing a measured chain fact must make the historical comparison incomplete."""
    report = _report()
    task04 = _section(report, "Task 04 historical retrospective")
    trial = _section(report, "AI-TEAM-001 controlled trial")

    for heading in (
        "## Evidence policy and limitations",
        "## Task 04 historical retrospective",
        "## AI-TEAM-001 controlled trial",
        "## Cross-sample findings",
        "## Phase 3 decision",
    ):
        assert heading in report

    for source in (
        "STATUS.md",
        "docs/tasks/GY-DATA-CORE-V2.md",
        "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md",
        "GitHub PR #98 evidence comment",
    ):
        assert source in report

    for state in ("MEASURED", "MANUALLY_RECORDED", "NOT_MEASURABLE"):
        assert state in report

    _assert_sample_contract(task04, "historical_retrospective")
    _assert_sample_contract(trial, "controlled_trial")

    for fact in (
        "Classification: historical_retrospective",
        "observed_chain_base: da2233b0c3c0b2707cabd1d2774ec22a9ab5f75e",
        "closeout_head: 2851b2649bcdd4af1331c15bf2269c4455f2992b",
        "closeout_merge: cc4302b57728133a1471447902563d3abf3604fb",
        "pull_requests: 86, 87, 88, 89, 90, 91, 92, 93, 94, 95",
        "pr_chain_count: 10",
        "task_commits_in_prs: 11",
        "merge_commits: 10",
        "develop_commits_across_chain: 21",
        "first_pr_created: 2026-08-01T01:09:01Z",
        "final_pr_merged: 2026-08-01T22:37:58Z",
        "observed_pr_chain_window: 21h28m57s",
        "Classification: controlled_trial",
        "Issue: 97",
        "PR: 98",
        "Base SHA: 6ead11f1eef22386360a9be8238f52cd54592bd9",
        "Task HEAD: a4af1e8e5798802f4e553d1fe9e6460285e24a67",
        "Merge SHA: 0867e12353e6fbb145c0e14427432e5ba06b9b7e",
        "pr_created: 2026-08-02T04:34:47Z",
        "pr_merged: 2026-08-02T05:01:10Z",
        "pr_window: 26m23s",
        "commit_count: 4",
        "post_feature_remediation_commits: 3",
        "changed_files: 11",
        "exact_head_checks: 3",
    ):
        assert fact in report


def test_retrospective_preserves_measurement_and_gate_limits() -> None:
    """An inferred metric or expanded authority would misstate Phase 2 evidence."""
    report = _report()
    lowered = report.lower()

    for metric in (
        "Review-fix rounds: NOT_MEASURABLE",
        "Total agent sessions: NOT_MEASURABLE",
        "User interruption count: NOT_MEASURABLE",
    ):
        assert metric in report

    for finding in (
        "GitHub native review not recorded",
        "Task 04 completed on develop",
        "legacy historical Shadow is optional/frozen and not a Task 05 Gate",
        "exact-hash approval packets",
        "failed closed",
        "Predicted base roles: AI project lead, Technical lead, Implementer, Independent quality reviewer",
        "Predicted specialists: data/database specialist",
        "Observed base roles: NOT_MEASURABLE",
        "Observed specialists: NOT_MEASURABLE",
        "Observed specialist count: NOT_MEASURABLE",
        "Observed context separation: NOT_MEASURABLE",
        "new independent ordinary reversible task",
        "frozen Charter",
        "metrics recorded from task start",
        "new Issue/task worktree",
        "Phase 2 did not adopt or modify the then-active Task 05 worktree",
        "Task 05 later merged independently through PR #100",
        "PR #100 cannot be retroactively counted as Phase 3",
        "Charter metrics and separate contexts were not recorded from task start",
        "no Phase 4/5",
        "automation or delegation authority",
    ):
        assert finding in report

    for forbidden_claim in (
        "placeholder",
        "profitability",
        "trading instruction",
        "runtime-ready",
        "release-ready",
        "automatic gate",
    ):
        assert forbidden_claim not in lowered


def test_retrospective_binds_each_measured_metric_to_its_authoritative_source() -> None:
    """Swapping GitHub metadata and a PR comment must fail the evidence contract."""
    report = _report()
    task04 = _section(report, "Task 04 historical retrospective")
    trial = _section(report, "AI-TEAM-001 controlled trial")

    assert "GitHub PR #86-#95 metadata" in task04.split("### Sample classification", 1)[0]
    assert (
        "Canonical completion/Gate sources: `STATUS.md` and "
        "`docs/tasks/GY-DATA-CORE-V2.md`" in task04
    )
    for metric, facts in {
        "observed_chain_base": (
            "PR #86 baseRefOid",
            "Evidence source: GitHub PR #86-#95 metadata",
        ),
        "closeout_head": (
            "PR #95 headRefOid",
            "Evidence source: GitHub PR #86-#95 metadata",
        ),
        "closeout_merge": (
            "PR #95 mergeCommit.oid",
            "Evidence source: GitHub PR #86-#95 metadata",
        ),
        "pull_requests": (
            "PR numbers: 86 through 95",
            "Evidence source: GitHub PR #86-#95 metadata",
        ),
        "chain counts": (
            "Evidence source: GitHub PR #86-#95 metadata/commit lists",
            "PR commit-list lengths: 2, 1, 1, 1, 1, 1, 1, 1, 1, 1",
            "derived as 10 PRs + 11 task commits = 21 develop commits",
        ),
        "observed PR chain window": (
            "Evidence source: GitHub PR #86-#95 metadata",
            "PR #86 createdAt: 2026-08-01T01:09:01Z",
            "PR #95 mergedAt: 2026-08-01T22:37:58Z",
            "derived as final PR merge timestamp minus first PR creation timestamp",
        ),
    }.items():
        block = _metric_block(task04, metric)
        for fact in facts:
            assert fact in block, (metric, fact)

    assert "GitHub PR #98 metadata/commit list/files list" in trial.split("### Sample classification", 1)[0]
    for metric, facts in {
        "PR window": (
            "Evidence source: GitHub PR #98 metadata",
            "createdAt: 2026-08-02T04:34:47Z",
            "mergedAt: 2026-08-02T05:01:10Z",
        ),
        "change size": (
            "Evidence source: GitHub PR #98 metadata/commit list/files list",
            "commit list length: 4",
            "files list length: 11",
        ),
        "post-feature remediation commits": (
            "Evidence source: GitHub PR #98 commit list",
            "first `feat(workstation):` commit is the feature baseline",
            "later `test(workstation):` or `fix(workstation):` commits count",
            "a0f81680d72117f94335063228e4af355bd2cb98",
            "94b13024aed65fe023aa159f8bd1ff394787d598",
            "a4af1e8e5798802f4e553d1fe9e6460285e24a67",
        ),
        "exact-head checks": (
            "Evidence source: GitHub PR #98 evidence comment",
        ),
    }.items():
        block = _metric_block(trial, metric)
        for fact in facts:
            assert fact in block, (metric, fact)

    for label in (
        "Observed base roles: NOT_MEASURABLE",
        "Observed specialists: NOT_MEASURABLE",
        "Observed specialist count: NOT_MEASURABLE",
        "Observed context separation: NOT_MEASURABLE",
    ):
        assert label in trial
    assert "temporary fresh-context pressure-test agents" not in trial
    assert "implementation and final review stayed separate" not in trial
    assert "independent Spec PASS / Quality APPROVED / 0 findings" in trial
    assert "three read-only forward tests" in trial


def test_every_metric_block_has_a_complete_provenance_contract() -> None:
    """A newly added metric must be validated without adding its name to a test table."""
    report = _report()
    task04 = _section(report, "Task 04 historical retrospective")
    trial = _section(report, "AI-TEAM-001 controlled trial")

    task04_metrics = _validated_metric_blocks(task04)
    trial_metrics = _validated_metric_blocks(trial)

    assert len(task04_metrics) == 6
    assert len(trial_metrics) == 5
    assert "verification and boundary evidence" in {
        metric["Metric name"] for metric in trial_metrics
    }


@pytest.mark.parametrize(
    "mutation",
    ("invalid provenance", "deleted evidence", "duplicate value"),
)
def test_metric_contract_rejects_in_memory_provenance_and_evidence_mutations(
    mutation: str,
) -> None:
    """Changed provenance or deleted evidence must fail before the report can pass."""
    task04 = _section(_report(), "Task 04 historical retrospective")
    mutations = {
        "invalid provenance": task04.replace(
            "- Provenance: MEASURED",
            "- Provenance: ESTIMATED",
            1,
        ),
        "deleted evidence": task04.replace(
            "- Evidence source: GitHub PR #86-#95 metadata",
            "- Evidence source:",
            1,
        ),
        "duplicate value": task04.replace(
            "- Value: observed_chain_base:",
            "- Value:\n- Value: duplicated:",
            1,
        ),
    }

    with pytest.raises(AssertionError):
        _validated_metric_blocks(mutations[mutation])


def test_metric_contract_enforces_manual_and_unmeasurable_evidence_semantics() -> None:
    """Non-measured provenance requires its provenance-specific limitation evidence."""
    valid_manual = """### Metrics

- Metric name: human note
- Value: reviewed boundary
- Provenance: MANUALLY_RECORDED
- Evidence source: Human observation: Project owner Zhang Zhao
- Evidence limitation: This observation cannot satisfy or drive a Gate.

### Gate preservation
"""
    valid_unmeasurable = """### Metrics

- Metric name: session count
- Value: NOT_MEASURABLE
- Provenance: NOT_MEASURABLE
- Evidence source: Canonical and GitHub records do not record this value; evidence is absent.

### Gate preservation
"""

    assert _validated_metric_blocks(valid_manual)[0]["Provenance"] == "MANUALLY_RECORDED"
    assert _validated_metric_blocks(valid_unmeasurable)[0]["Provenance"] == "NOT_MEASURABLE"

    for invalid_sample in (
        valid_manual.replace("Human observation: Project owner Zhang Zhao", "conversation memory"),
        valid_manual.replace("cannot satisfy or drive a Gate", "is sufficient evidence"),
        valid_unmeasurable.replace(
            "do not record this value; evidence is absent",
            "were inspected",
        ),
    ):
        with pytest.raises(AssertionError):
            _validated_metric_blocks(invalid_sample)


def test_unenumerated_measured_metric_rejects_conversation_memory_source() -> None:
    """The generic parser must reject unsourced evidence on a metric absent from name tables."""
    trial = _section(_report(), "AI-TEAM-001 controlled trial")
    verification = _metric_block(trial, "verification and boundary evidence")
    mutated_verification = verification.replace(
        "- Evidence source: GitHub PR #98 evidence comment",
        "- Evidence source: conversation memory",
        1,
    )
    mutated_trial = trial.replace(verification, mutated_verification, 1)

    with pytest.raises(AssertionError):
        _validated_metric_blocks(mutated_trial)


@pytest.mark.parametrize(
    "recognized_source",
    (
        "STATUS.md",
        "docs/tasks/GY-DATA-CORE-V2.md",
        "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md",
        "Canonical repository status/design/task records",
        "GitHub Issue #99 metadata",
        "GitHub PR #98 metadata/commit list/files list",
        "GitHub PR #98 checks",
        "GitHub PR #98 evidence comment",
    ),
)
def test_measured_metric_accepts_only_bounded_recognized_source_forms(
    recognized_source: str,
) -> None:
    """Measured evidence accepts explicit canonical and structured GitHub source forms."""
    sample = f"""### Metrics

- Metric name: measured fixture
- Value: one
- Provenance: MEASURED
- Evidence source: {recognized_source}

### Gate preservation
"""

    assert _validated_metric_blocks(sample)[0]["Evidence source"] == recognized_source


@pytest.mark.parametrize(
    "unrecognized_source",
    (
        "conversation memory",
        "Human observation: project owner",
        "unsourced narrative",
        "GitHub says the check passed",
        "notes mentioning GitHub PR #98 evidence comment",
    ),
)
def test_measured_metric_rejects_unrecognized_source_forms(
    unrecognized_source: str,
) -> None:
    """A GitHub token or narrative label alone cannot make a source measured evidence."""
    sample = f"""### Metrics

- Metric name: measured fixture
- Value: one
- Provenance: MEASURED
- Evidence source: {unrecognized_source}

### Gate preservation
"""

    with pytest.raises(AssertionError):
        _validated_metric_blocks(sample)


def test_external_task05_merge_preserves_phase3_and_integration_boundaries() -> None:
    """Later Task 05 delivery must not rewrite Phase 2 policy or Gate limits."""
    report = _report()
    decision = _section(report, "Phase 3 decision")
    design = _design()

    for fact in (
        "new independent ordinary reversible task",
        "frozen Charter",
        "metrics recorded from task start",
        "new Issue/task worktree",
        "separate implementation and final-review contexts",
        "PR #100 cannot be retroactively counted as Phase 3",
        "Source-bound GitHub PR #100 metadata",
        "Evidence source and method: local Git inspection ran",
        "git merge-base HEAD a9327938",
        "cc4302b57728133a1471447902563d3abf3604fb",
        "Phase 2 task branch itself starts at `0867e123`",
        "zero changed-path intersection",
        "produced no conflict markers",
        "exact-head compatibility and integration against current `origin/develop` must be rechecked",
        "does not authorize Phase 4 or Phase 5, `main`, release, Runtime, data writes, or notifications",
    ):
        assert fact in report

    for fact in (
        "Task 05 later merged independently through PR #100",
        "did not adopt or modify the then-active Task 05 worktree",
        "does not count retroactively as Phase 3",
        "exact-head compatibility and integration against current `origin/develop` must be rechecked",
        "Phase 3：新的普通可逆工程试运行",
        "PR #100 不能追认为该试运行",
    ):
        assert fact in design

    assert "PR #100 cannot be retroactively counted as Phase 3" in decision


def test_phase_contracts_reject_affirmative_authority_claims_without_rejecting_denials() -> None:
    """A scoped positive Phase/Gate claim must fail while required denials remain valid."""
    report = _report()
    design = _design()
    plan = _plan()
    audited_scope = "\n".join((
        _section(report, "Cross-sample findings"),
        _section(report, "Phase 3 decision"),
        _section(design, "19. 分阶段实施"),
        _section(design, "20. 验收指标"),
        plan,
    ))

    assert not _affirmative_authority_claims(audited_scope)

    for injected_claim in (
        "PR #100 is Phase 3.",
        "Task 05 was the Phase 3 controlled trial.",
        "Phase 3 trial is Task 05.",
        "Phase 4/Phase 5 automation is authorized.",
        "Phase 4 is authorized.",
        "Phase 5 is authorized.",
        "`main` is authorized.",
        "main is authorized.",
        "release is authorized.",
        "`Runtime` is authorized.",
        "Runtime is authorized.",
        "data writes/notifications are authorized.",
        "data writes are authorized.",
        "notifications are authorized.",
    ):
        assert _affirmative_authority_claims(injected_claim), injected_claim

    for required_denial in (
        "PR #100 cannot be retroactively counted as Phase 3.",
        "This does not authorize Phase 4 or Phase 5, main, release, Runtime, "
        "data writes, or notifications.",
    ):
        assert not _affirmative_authority_claims(required_denial), required_denial


def test_phase2_history_and_phase3_new_task_remain_separate_in_design_and_plan() -> None:
    """Task 05 delivery cannot fill Phase 2 gaps or become the new Phase 3 trial."""
    design = _design()
    plan = _plan()
    phased_design = _section(design, "19. 分阶段实施")
    success_criteria = _subsection(_section(design, "20. 验收指标"), "20.4 第一版成功标准")

    for fact in (
        "### Phase 2：历史复盘",
        "NOT_MEASURABLE",
        "### Phase 3：新的普通可逆工程试运行",
        "新的 Issue 和 task worktree",
        "实现开始前冻结 Charter",
        "从任务开始记录 Charter 指标",
        "实现与最终 Review 的上下文分离",
        "PR #100 不能追认为该试运行",
    ):
        assert fact in phased_design
    assert "Task 05 试运行" not in success_criteria
    assert "未来 Phase 3 新独立试运行" in success_criteria

    for fact in (
        "Immutable task base",
        "0867e12353e6fbb145c0e14427432e5ba06b9b7e",
        "current `origin/develop`",
        "External drift addendum",
        "before implementation begins",
    ):
        assert fact in plan
