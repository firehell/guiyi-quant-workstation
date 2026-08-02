"""Evidence contract for the source-bound Lean Matrix Phase 2 retrospective."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RETROSPECTIVE = ROOT / "docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-2.md"
DESIGN = ROOT / "docs/superpowers/specs/2026-08-02-lean-matrix-ai-team-design.md"


def _report() -> str:
    return RETROSPECTIVE.read_text(encoding="utf-8")


def _design() -> str:
    return DESIGN.read_text(encoding="utf-8")


def _section(markdown: str, heading: str) -> str:
    body = markdown.split(f"## {heading}\n", 1)[1]
    return body.split("\n## ", 1)[0]


def _metric_block(section: str, name: str) -> str:
    body = section.split(f"- Metric name: {name}\n", 1)[1]
    return body.split("\n- Metric name: ", 1)[0]


def test_retrospective_preserves_two_source_bound_samples() -> None:
    """Removing a measured chain fact must make the historical comparison incomplete."""
    report = _report()

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
        "no Phase 4/5 automation or delegation authority",
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


def test_external_task05_merge_does_not_reclassify_phase3_or_expand_authority() -> None:
    """Later independent Task 05 delivery must not rewrite Phase 2 evidence."""
    report = _report()
    decision = _section(report, "Phase 3 decision")
    design = _design()

    for fact in (
        "b64453eab89692e5250a4275f04cac1bd26f02d4",
        "a932793830e1e68a3e2c1634a38f50840a55efc5",
        "2026-08-02T05:34:14Z",
        "Phase 2's branch base is `0867e123`",
        "no path overlap or merge conflict with PR #100",
        "new independent ordinary reversible task",
        "frozen Charter",
        "metrics recorded from task start",
        "new Issue/task worktree",
        "separate implementation and final-review contexts",
        "PR #100 cannot be retroactively counted as Phase 3",
        "does not authorize Phase 4 or Phase 5, `main`, release, Runtime, data writes, or notifications",
    ):
        assert fact in report

    for fact in (
        "Task 05 later merged independently through PR #100",
        "did not adopt or modify the then-active Task 05 worktree",
        "does not count retroactively as Phase 3",
        "Phase 3：新的普通可逆工程试运行",
        "PR #100 不能追认为该试运行",
    ):
        assert fact in design

    assert "PR #100 cannot be retroactively counted as Phase 3" in decision
