"""Evidence contract for the source-bound Lean Matrix Phase 2 retrospective."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RETROSPECTIVE = ROOT / "docs/superpowers/retrospectives/2026-08-02-lean-matrix-phase-2.md"


def _report() -> str:
    return RETROSPECTIVE.read_text(encoding="utf-8")


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
        "Observed specialists: no permanent specialist",
        "temporary fresh-context pressure-test agents",
        "implementation and final review stayed separate",
        "new independent ordinary reversible task",
        "frozen Charter",
        "metrics recorded from task start",
        "new Issue/task worktree",
        "Zero Task 05 adoption",
        "Zero main/Runtime/data/notification authority",
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
