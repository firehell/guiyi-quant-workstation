"""Behavioral contracts for the pure Lean Matrix V07 develop Gate evaluator."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"
CLI = ENGINEERING / "lean_matrix_team.py"
BASE_SHA = "1" * 40
HEAD_SHA = "2" * 40
MERGE_SHA = "3" * 40
NOW = datetime(2026, 8, 3, 4, 0, tzinfo=UTC)


def _semantic_digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _module():
    sys.path.insert(0, str(ENGINEERING))
    try:
        spec = importlib.util.spec_from_file_location("lean_matrix_team_develop_gate", CLI)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _charter() -> dict[str, object]:
    return {
        "schema_version": 1,
        "issue_number": 116,
        "task_id": "AI-TEAM-007",
        "kind": "feature",
        "slug": "github-gate-evaluator",
        "title": "Build the GitHub Gate evaluator",
        "value": "Make develop integration deterministic.",
        "goal": "Evaluate normalized GitHub facts without side effects.",
        "current_facts": ["V06 has no GitHub Gate."],
        "lane": 2,
        "domains": [],
        "allowed_paths": [
            "scripts/engineering/lean_matrix_team.py",
            "tests/engineering/test_lean_matrix_develop_gate.py",
        ],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["Fake facts cover every decision."],
        "external_gates": [],
    }


def _plan(charter: dict[str, object] | None = None) -> dict[str, object]:
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import TaskCharterV1
        from lean_matrix.planning import build_execution_plan
    finally:
        sys.path.pop(0)
    contract = TaskCharterV1.from_mapping(charter or _charter())
    return build_execution_plan(
        contract, base_ref="origin/develop", base_sha=BASE_SHA,
    ).to_dict()


def _review(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "APPROVED",
        "reviewer_context_id": "reviewer-sol-001",
        "implementer_context_id": "implementer-sol-001",
        "head_sha": HEAD_SHA,
        "base_sha": BASE_SHA,
        "critical_findings": 0,
        "important_findings": 0,
        "minor_findings": 0,
        "blocking_threads": 0,
    }
    payload.update(overrides)
    return payload


def _facts(
    *,
    stage: str = "pre_merge",
    charter: dict[str, object] | None = None,
    plan: dict[str, object] | None = None,
    observed_at: datetime = NOW,
    **overrides: object,
) -> dict[str, object]:
    charter_payload = charter or _charter()
    plan_payload = plan or _plan(charter_payload)
    requested_operations = {
        "pre_merge": ["develop_merge"],
        "merge_readback": ["merge_readback"],
        "cleanup": ["cleanup"],
    }[stage]
    payload: dict[str, object] = {
        "schema_version": 1,
        "stage": stage,
        "plan_digest": _semantic_digest(plan_payload),
        "charter_digest": _semantic_digest(charter_payload),
        "charter": charter_payload,
        "repository_id": 1276918660,
        "repository_full_name": "firehell/guiyi-quant-workstation",
        "pr_number": 117,
        "pr_state": "OPEN",
        "pr_merged": False,
        "pr_draft": False,
        "base_ref": "develop",
        "base_sha": BASE_SHA,
        "head_ref": "feature/AI-TEAM-007-github-gate-evaluator",
        "head_sha": HEAD_SHA,
        "current_task_head_sha": HEAD_SHA,
        "current_develop_sha": BASE_SHA,
        "changed_paths": [
            "scripts/engineering/lean_matrix_team.py",
            "tests/engineering/test_lean_matrix_develop_gate.py",
        ],
        "checks": [
            {"schema_version": 1, "name": name, "status": "SUCCESS", "head_sha": HEAD_SHA}
            for name in sorted(plan_payload["validation"]["required_checks"])
        ],
        "review": _review(),
        "pending_external_gates": [],
        "requested_operations": requested_operations,
        "mergeability": "MERGEABLE",
        "observed_at": observed_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (observed_at + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "readback_merge_sha": None,
        "readback_develop_contains_task_head": False,
        "cleanup_worktree_clean": False,
        "cleanup_local_develop_contains_task_head": False,
        "cleanup_remote_develop_contains_task_head": False,
    }
    payload.update(overrides)
    payload["facts_digest"] = _semantic_digest(payload)
    return payload


def _mutated(facts: dict[str, object], **overrides: object) -> dict[str, object]:
    result = facts | overrides
    result.pop("facts_digest", None)
    result["facts_digest"] = _semantic_digest(result)
    return result


def _evaluate(
    facts: object,
    *,
    plan: dict[str, object] | None = None,
    now: datetime = NOW,
) -> dict[str, object] | None:
    evaluator = getattr(_module(), "evaluate_develop_gate", None)
    if evaluator is None:
        return None
    return evaluator(plan or _plan(), facts, now=now).to_dict()


def _assert_decision(
    facts: object,
    decision: str,
    reason: str,
    *,
    plan: dict[str, object] | None = None,
    now: datetime = NOW,
) -> dict[str, object]:
    result = _evaluate(facts, plan=plan, now=now)
    assert result is not None
    assert result["decision"] == decision
    assert result["reason_codes"][0] == reason
    return result


def test_valid_exact_head_facts_allow_develop_merge_with_digest_bound_decision() -> None:
    """Removing the success branch must stop an exact-head, fully approved merge transition."""
    facts = _facts()

    result = _assert_decision(facts, "ALLOW_DEVELOP_MERGE", "DEVELOP_MERGE_ALLOWED")

    assert result["stage"] == "pre_merge"
    assert result["plan_digest"] == facts["plan_digest"]
    assert result["facts_digest"] == facts["facts_digest"]
    assert result["evaluated_at"] == "2026-08-03T04:00:00Z"


def test_strict_contracts_reject_unknown_keys_and_tampered_facts_fail_closed() -> None:
    """Dropping exact-key or semantic-digest validation must make malformed evidence advance."""
    extra = _facts() | {"untrusted": True}
    tampered = _facts()
    tampered["current_task_head_sha"] = "9" * 40

    malformed = _assert_decision(extra, "BLOCKED", "FACTS_MALFORMED")
    digest_mismatch = _assert_decision(tampered, "BLOCKED", "FACTS_DIGEST_MISMATCH")

    assert malformed["reason_codes"] == ["FACTS_MALFORMED"]
    assert digest_mismatch["reason_codes"] == ["FACTS_DIGEST_MISMATCH"]


def test_facts_expire_at_exactly_five_minutes_but_not_one_second_before() -> None:
    """Changing the five-minute replay boundary must fail at one of its two adjacent instants."""
    facts = _facts()

    _assert_decision(
        facts,
        "ALLOW_DEVELOP_MERGE",
        "DEVELOP_MERGE_ALLOWED",
        now=NOW + timedelta(minutes=4, seconds=59),
    )
    _assert_decision(facts, "BLOCKED", "FACTS_EXPIRED", now=NOW + timedelta(minutes=5))


def test_preconstructed_facts_are_revalidated_before_evaluation() -> None:
    """A replaced frozen instance must not bypass digest and exact five-minute expiry validation."""
    module = _module()
    validated = module.GitHubGateFactsV1.from_mapping(_facts())
    unchecked = replace(
        validated,
        expires_at=(NOW + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )

    result = module.evaluate_develop_gate(
        _plan(), unchecked, now=NOW + timedelta(minutes=6),
    ).to_dict()

    assert result["decision"] == "BLOCKED"
    assert result["reason_codes"] == ["FACTS_DIGEST_MISMATCH"]


@pytest.mark.parametrize(
    ("stage", "decision", "reason", "error_type"),
    [
        ("pre_merge", "WAIT_CI", "FREE_TEXT", "invalid_reason_code"),
        (
            "pre_merge",
            "WAIT_CI",
            "DEVELOP_MERGE_ALLOWED",
            "invalid_decision_reason_combination",
        ),
        (
            "cleanup",
            "ALLOW_DEVELOP_MERGE",
            "DEVELOP_MERGE_ALLOWED",
            "invalid_decision_reason_combination",
        ),
    ],
)
def test_decision_contract_rejects_unknown_or_invalid_stage_decision_reason_combinations(
    stage: str,
    decision: str,
    reason: str,
    error_type: str,
) -> None:
    """Reason text cannot invent authority or be paired with an unrelated decision/stage."""
    module = _module()

    with pytest.raises(module.LeanMatrixError) as captured:
        module.DevelopGateDecisionV1.from_mapping({
            "schema_version": 1,
            "stage": stage,
            "decision": decision,
            "reason_codes": [reason],
            "plan_digest": "sha256:" + "1" * 64,
            "facts_digest": "sha256:" + "2" * 64,
            "evaluated_at": "2026-08-03T04:00:00Z",
        })

    assert captured.value.error_type == error_type


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"repository_id": 1}, "REPOSITORY_ID_MISMATCH"),
        ({"repository_full_name": "fork/guiyi-quant-workstation"}, "REPOSITORY_NAME_MISMATCH"),
        ({"base_ref": "main"}, "PR_BASE_REF_MISMATCH"),
        ({"head_ref": "feature/other"}, "PR_HEAD_REF_MISMATCH"),
        ({"pr_state": "CLOSED"}, "PR_CLOSED_UNMERGED"),
    ],
)
def test_pr_identity_mismatch_blocks_before_later_gate_states(
    overrides: dict[str, object], reason: str,
) -> None:
    """Weakening repository or PR identity must never reach CI/review evaluation."""
    facts = _mutated(_facts(), **overrides)

    _assert_decision(facts, "BLOCKED_PR_IDENTITY", reason)


def test_stale_replay_after_task_head_drift_blocks_before_base_and_ci() -> None:
    """Replaying approved evidence after a new task commit must report head drift first."""
    facts = _mutated(
        _facts(),
        current_task_head_sha="4" * 40,
        current_develop_sha="5" * 40,
        checks=[],
    )

    _assert_decision(facts, "BLOCKED_HEAD_DRIFT", "TASK_HEAD_DRIFT")


def test_stale_replay_after_develop_drift_requires_fresh_intake_review_and_ci() -> None:
    """Changing develop after exact-base review must invalidate the whole pre-merge packet."""
    facts = _mutated(_facts(), current_develop_sha="5" * 40)

    _assert_decision(facts, "BLOCKED_BASE_DRIFT", "CURRENT_DEVELOP_DRIFT")


def test_plan_charter_digest_or_semantic_binding_mismatch_fails_closed() -> None:
    """A model/routing plan cannot substitute for the full digest-bound Task Charter."""
    facts = _facts()
    changed_charter = dict(facts["charter"])
    changed_charter["goal"] = "A different trusted goal."
    facts = _mutated(facts, charter=changed_charter)

    _assert_decision(facts, "BLOCKED", "CHARTER_DIGEST_MISMATCH")


def test_external_gate_or_sensitive_requested_operation_requires_manual_gate() -> None:
    """Automatic develop permission must not consume an unresolved external or release Gate."""
    charter = _charter()
    charter["lane"] = 3
    charter["external_gates"] = ["owner must approve production apply"]
    plan = _plan(charter)
    with_external_gate = _facts(
        charter=charter,
        plan=plan,
        pending_external_gates=["owner must approve production apply"],
    )
    sensitive = _mutated(_facts(), requested_operations=["release"])

    _assert_decision(
        with_external_gate,
        "MANUAL_GATE_REQUIRED",
        "EXTERNAL_GATE_REQUIRED",
        plan=plan,
    )
    _assert_decision(sensitive, "MANUAL_GATE_REQUIRED", "SENSITIVE_OPERATION_REQUESTED")


def test_changed_paths_must_remain_sorted_exact_and_within_frozen_scope() -> None:
    """An out-of-scope PR path must fail even if every remote status is green."""
    facts = _mutated(
        _facts(),
        changed_paths=["README.md", "scripts/engineering/lean_matrix_team.py"],
    )

    _assert_decision(facts, "BLOCKED_SCOPE_DRIFT", "CHANGED_PATH_OUTSIDE_SCOPE")


@pytest.mark.parametrize("status", ["FAILURE", "CANCELLED", "SKIPPED", "TIMED_OUT", "STALE", "MISSING"])
def test_failed_cancelled_skipped_timed_out_stale_or_missing_ci_blocks(status: str) -> None:
    """Treating any non-pending CI terminal state as success must make this case advance."""
    facts = _facts()
    checks = list(facts["checks"])
    checks[0] = checks[0] | {"status": status}
    facts = _mutated(facts, checks=checks)

    _assert_decision(facts, "BLOCKED_CI", f"CI_{status}")


def test_pending_ci_waits_before_a_missing_review_is_considered() -> None:
    """Changing CI-before-review precedence must return the wrong wait decision here."""
    facts = _facts()
    checks = list(facts["checks"])
    checks[0] = checks[0] | {"status": "PENDING"}
    review = _review(
        status="MISSING",
        reviewer_context_id=None,
        head_sha=None,
        base_sha=None,
    )
    facts = _mutated(facts, checks=checks, review=review)

    _assert_decision(facts, "WAIT_CI", "CI_PENDING")


def test_absent_required_ci_check_blocks_instead_of_waiting() -> None:
    """Forgetting to compare the required check-name set must allow incomplete CI evidence."""
    facts = _facts()
    facts = _mutated(facts, checks=list(facts["checks"])[1:])

    _assert_decision(facts, "BLOCKED_CI", "CI_CHECK_MISSING")


@pytest.mark.parametrize("status", ["MISSING", "PENDING"])
def test_missing_or_pending_independent_review_waits(status: str) -> None:
    """Missing review evidence is retryable only as an explicit review wait."""
    facts = _mutated(
        _facts(),
        review=_review(
            status=status,
            reviewer_context_id=None,
            head_sha=None,
            base_sha=None,
        ),
    )

    _assert_decision(facts, "WAIT_REVIEW", "REVIEW_PENDING")


@pytest.mark.parametrize(
    ("review_overrides", "reason"),
    [
        ({"status": "CHANGES_REQUESTED"}, "REVIEW_CHANGES_REQUESTED"),
        ({"critical_findings": 1}, "CRITICAL_FINDINGS"),
        ({"important_findings": 1}, "IMPORTANT_FINDINGS"),
        ({"reviewer_context_id": "implementer-sol-001"}, "INDEPENDENT_REVIEW_REQUIRED"),
    ],
)
def test_changes_critical_important_or_non_independent_review_blocks(
    review_overrides: dict[str, object], reason: str,
) -> None:
    """Weakening independent-review evidence must never allow an exact-head merge."""
    facts = _mutated(_facts(), review=_review(**review_overrides))

    _assert_decision(facts, "BLOCKED_REVIEW", reason)


def test_minor_findings_alone_do_not_block_but_blocking_threads_do() -> None:
    """Minor findings are advisory, while an unresolved thread remains a hard Gate."""
    minor = _mutated(_facts(), review=_review(minor_findings=2))
    threads = _mutated(_facts(), review=_review(minor_findings=2, blocking_threads=1))

    _assert_decision(minor, "ALLOW_DEVELOP_MERGE", "DEVELOP_MERGE_ALLOWED")
    _assert_decision(threads, "BLOCKED_THREADS", "BLOCKING_THREADS_OPEN")


@pytest.mark.parametrize("mergeability", ["CONFLICTING", "UNKNOWN"])
def test_non_mergeable_or_unknown_mergeability_blocks(mergeability: str) -> None:
    """Removing fail-closed mergeability handling must allow a conflict or unknown state."""
    facts = _mutated(_facts(), mergeability=mergeability)

    _assert_decision(facts, "BLOCKED_MERGEABILITY", f"MERGEABILITY_{mergeability}")


def test_draft_is_allowed_only_as_a_ready_transition() -> None:
    """A draft must not be described as immediately mergeable even when all evidence passes."""
    facts = _mutated(_facts(), pr_draft=True)

    _assert_decision(facts, "ALLOW_DEVELOP_MERGE", "READY_TRANSITION_REQUIRED")


def test_timeout_readback_allows_only_exact_head_confirmed_merge_without_retry() -> None:
    """An uncertain merge result is recoverable only from an exact-head merged readback."""
    merged = _facts(
        stage="merge_readback",
        pr_state="MERGED",
        pr_merged=True,
        current_develop_sha=MERGE_SHA,
        readback_merge_sha=MERGE_SHA,
        readback_develop_contains_task_head=True,
        mergeability="UNKNOWN",
    )
    unmerged = _facts(stage="merge_readback", mergeability="UNKNOWN")

    _assert_decision(merged, "ALLOW_DEVELOP_MERGE", "MERGE_READBACK_CONFIRMED")
    _assert_decision(unmerged, "BLOCKED", "MERGE_RESULT_UNCONFIRMED")


def test_pre_merge_already_merged_readback_is_idempotent() -> None:
    """Repeating the evaluator after a completed merge must not propose a second merge."""
    facts = _mutated(
        _facts(),
        pr_state="MERGED",
        pr_merged=True,
        current_develop_sha=MERGE_SHA,
        readback_merge_sha=MERGE_SHA,
        readback_develop_contains_task_head=True,
    )

    _assert_decision(facts, "ALLOW_DEVELOP_MERGE", "ALREADY_MERGED")


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"cleanup_worktree_clean": False}, "WORKTREE_NOT_CLEAN"),
        ({"cleanup_local_develop_contains_task_head": False}, "LOCAL_DEVELOP_MISSING_TASK_HEAD"),
        ({"cleanup_remote_develop_contains_task_head": False}, "REMOTE_DEVELOP_MISSING_TASK_HEAD"),
    ],
)
def test_cleanup_requires_confirmed_merge_clean_worktree_and_both_ancestries(
    overrides: dict[str, object], reason: str,
) -> None:
    """Dropping any cleanup prerequisite must allow destructive cleanup too early."""
    valid = {
        "pr_state": "MERGED",
        "pr_merged": True,
        "current_develop_sha": MERGE_SHA,
        "readback_merge_sha": MERGE_SHA,
        "readback_develop_contains_task_head": True,
        "cleanup_worktree_clean": True,
        "cleanup_local_develop_contains_task_head": True,
        "cleanup_remote_develop_contains_task_head": True,
    }
    blocked = _facts(stage="cleanup", **(valid | overrides))

    _assert_decision(blocked, "BLOCKED", reason)


def test_cleanup_allows_only_after_confirmed_merge_and_complete_ancestry() -> None:
    """The cleanup success branch must require every stage-specific readback fact."""
    facts = _facts(
        stage="cleanup",
        pr_state="MERGED",
        pr_merged=True,
        current_develop_sha=MERGE_SHA,
        readback_merge_sha=MERGE_SHA,
        readback_develop_contains_task_head=True,
        cleanup_worktree_clean=True,
        cleanup_local_develop_contains_task_head=True,
        cleanup_remote_develop_contains_task_head=True,
    )

    _assert_decision(facts, "ALLOW_DEVELOP_MERGE", "CLEANUP_ALLOWED")


def test_cli_reads_only_plan_and_facts_and_emits_the_decision(tmp_path: Path) -> None:
    """Removing the develop-gate route or adding hidden state must break the public CLI contract."""
    plan = _plan()
    now = datetime.now(UTC).replace(microsecond=0)
    facts = _facts(plan=plan, observed_at=now)
    plan_path = tmp_path / "plan.json"
    facts_path = tmp_path / "facts.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")
    facts_path.write_text(json.dumps(facts), encoding="utf-8")
    before = sorted(path.name for path in tmp_path.iterdir())

    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "develop-gate",
            "--plan",
            str(plan_path),
            "--facts",
            str(facts_path),
            "--format",
            "json",
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["decision"] == "ALLOW_DEVELOP_MERGE"
    assert sorted(path.name for path in tmp_path.iterdir()) == before
