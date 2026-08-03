"""End-to-end bootstrap contracts for truthful V06/V07 stage ownership."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
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


def _digest(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, ensure_ascii=False, sort_keys=True))


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _contracts():  # noqa: ANN202
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.briefs import build_role_brief, intake_digest
        from lean_matrix.contracts import (
            DocumentIntakeV1,
            ExecutionPlanV1,
            HandoffReportV1,
            TaskCharterV1,
            required_checks_for_owner,
        )
        from lean_matrix.errors import LeanMatrixError
        from lean_matrix.planning import build_execution_plan
        from lean_matrix.review_packages import build_review_package
        from lean_matrix.workspace import intake_workspace
    finally:
        sys.path.pop(0)
    return {
        "build_execution_plan": build_execution_plan,
        "build_review_package": build_review_package,
        "build_role_brief": build_role_brief,
        "DocumentIntakeV1": DocumentIntakeV1,
        "ExecutionPlanV1": ExecutionPlanV1,
        "HandoffReportV1": HandoffReportV1,
        "LeanMatrixError": LeanMatrixError,
        "TaskCharterV1": TaskCharterV1,
        "intake_digest": intake_digest,
        "intake_workspace": intake_workspace,
        "required_checks_for_owner": required_checks_for_owner,
    }


def _gate_module():  # noqa: ANN202
    sys.path.insert(0, str(ENGINEERING))
    try:
        name = f"lean_matrix_team_bootstrap_{id(object())}"
        spec = importlib.util.spec_from_file_location(name, CLI)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.pop(0)


def _charter(
    *,
    lane: int = 2,
    domains: list[str] | None = None,
    external_gates: list[str] | None = None,
) -> dict[str, object]:
    gates = external_gates
    if gates is None:
        gates = (
            ["Owner Gate: Lane 3, product direction, active canonical, or real operation"]
            if lane == 3
            else []
        )
    allowed_paths = (
        ["tests/engineering/**"]
        if lane == 1
        else [
            "scripts/engineering/lean_matrix/**",
            "scripts/engineering/lean_matrix_team.py",
            "tests/engineering/**",
        ]
    )
    return {
        "schema_version": 1,
        "issue_number": 120,
        "task_id": "AI-TEAM-008",
        "kind": "research",
        "slug": "lean-matrix-v1-bootstrap-trial",
        "title": "Bootstrap the first real Team Path",
        "value": "Prove truthful stage ownership.",
        "goal": "Keep V06 local and V07 pure.",
        "current_facts": ["Bootstrap defects are reproduced."],
        "lane": lane,
        "domains": domains or [],
        "allowed_paths": allowed_paths,
        "forbidden_paths": ["Runtime/**", "data/**", ".env"],
        "acceptance": ["Full negative matrix passes."],
        "external_gates": gates,
    }


def _plan(
    *,
    lane: int = 2,
    domains: list[str] | None = None,
    external_gates: list[str] | None = None,
) -> dict[str, object]:
    api = _contracts()
    charter = api["TaskCharterV1"].from_mapping(_charter(
        lane=lane,
        domains=domains,
        external_gates=external_gates,
    ))
    return api["build_execution_plan"](
        charter, base_ref="origin/develop", base_sha=BASE_SHA,
    ).to_dict()


def _old_plan(base_sha: str, *, with_specialist: bool = True) -> dict[str, object]:
    payload = _plan(domains=["security"] if with_specialist else [])
    payload["base"] = {"ref": "origin/develop", "expected_sha": base_sha}
    if with_specialist:
        payload["dispatch"]["specialists"] = ["security-specialist"]
    return payload


def _review(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "status": "APPROVED",
        "reviewer_context_id": "reviewer-sol",
        "implementer_context_id": "implementer-sol",
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
    plan: dict[str, object] | None = None,
    charter: dict[str, object] | None = None,
    stage: str = "pre_merge",
    checks: list[dict[str, object]] | None = None,
    observed_at: datetime = NOW,
    **overrides: object,
) -> dict[str, object]:
    plan_payload = plan or _plan()
    charter_payload = charter or _charter()
    requested_operations = {
        "pre_merge": ["develop_merge"],
        "merge_readback": ["merge_readback"],
        "cleanup": ["cleanup"],
    }[stage]
    payload: dict[str, object] = {
        "schema_version": 1,
        "stage": stage,
        "plan_digest": _digest(plan_payload),
        "charter_digest": _digest(charter_payload),
        "charter": charter_payload,
        "repository_id": 1276918660,
        "repository_full_name": "firehell/guiyi-quant-workstation",
        "pr_number": 120,
        "pr_state": "OPEN",
        "pr_merged": False,
        "pr_draft": False,
        "base_ref": "develop",
        "base_sha": BASE_SHA,
        "head_ref": "research/AI-TEAM-008-lean-matrix-v1-bootstrap-trial",
        "head_sha": HEAD_SHA,
        "current_task_head_sha": HEAD_SHA,
        "current_develop_sha": BASE_SHA,
        "changed_paths": [
            "scripts/engineering/lean_matrix_team.py",
            "tests/engineering/test_lean_matrix_v1_bootstrap.py",
        ],
        "checks": checks if checks is not None else [{
            "schema_version": 1,
            "name": "exact-head-ci",
            "status": "SUCCESS",
            "head_sha": HEAD_SHA,
        }],
        "review": _review(),
        "pending_external_gates": [],
        "requested_operations": requested_operations,
        "change_categories": [],
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
    payload["facts_digest"] = _digest(payload)
    return payload


def _decision(facts: dict[str, object], *, plan: dict[str, object] | None = None):  # noqa: ANN202
    return _gate_module().evaluate_develop_gate(plan or _plan(), facts, now=NOW)


def _mutated(facts: dict[str, object], **updates: object) -> dict[str, object]:
    changed = facts | updates
    changed.pop("facts_digest", None)
    changed["facts_digest"] = _digest(changed)
    return changed


def test_generated_plan_uses_domain_literals_and_old_role_label_plan_still_loads() -> None:
    """Mapping a domain into a role label must not make the documented brief CLI unusable."""
    api = _contracts()
    generated = _plan(domains=["security"])

    assert generated["dispatch"]["specialists"] == ["security"]
    assert generated["validation"]["required_checks"] == [
        "independent-review",
        "exact-head-ci",
        "diff-check",
        "secret-scan",
    ]
    old = _old_plan(BASE_SHA)
    assert api["ExecutionPlanV1"].from_mapping(old).dispatch.specialists == (
        "security-specialist",
    )


def test_unknown_required_check_owner_fails_closed_after_wire_loading() -> None:
    """A typo or future check must not silently inherit implementer authority."""
    api = _contracts()
    payload = _plan()
    payload["validation"]["required_checks"] = ["diff-check", "mystery-policy-check"]
    loaded = api["ExecutionPlanV1"].from_mapping(payload)

    with pytest.raises(api["LeanMatrixError"]) as raised:
        api["required_checks_for_owner"](
            loaded.validation.required_checks,
            "implementer",
        )

    assert raised.value.error_type == "unknown_required_check"

    with pytest.raises(api["LeanMatrixError"]) as gate_raised:
        _decision(
            _facts(plan=loaded.to_dict()),
            plan=loaded.to_dict(),
        )
    assert gate_raised.value.error_type == "unknown_required_check"


def test_old_plan_review_package_requires_only_pre_review_local_receipts(tmp_path: Path) -> None:
    """An implementer cannot truthfully issue independent-review or exact-head-ci receipts."""
    api = _contracts()
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo / ".gitignore", ".ai/\n")
    _write(repo / "docs/design.md", "approved design\n")
    _write(repo / "docs/plan.md", "approved implementation plan\n")
    _write(repo / "scripts/engineering/lean_matrix/seed.py", "VALUE = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "bootstrap@example.invalid")
    _git(repo, "config", "user.name", "Bootstrap Tests")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD^{commit}")
    _git(repo, "update-ref", "refs/remotes/origin/develop", base)
    _write(repo / "scripts/engineering/lean_matrix/feature.py", "VALUE = 2\n")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "feature")
    head = _git(repo, "rev-parse", "HEAD^{commit}")

    execution = api["ExecutionPlanV1"].from_mapping(_old_plan(base, with_specialist=False))
    intake = api["DocumentIntakeV1"].from_mapping({
        "schema_version": 1,
        "design_path": "docs/design.md",
        "design_digest": _file_digest(repo / "docs/design.md"),
        "implementation_plan_path": "docs/plan.md",
        "implementation_plan_digest": _file_digest(repo / "docs/plan.md"),
        "execution_plan_digest": _digest(execution.to_dict()),
        "execution_plan": execution.to_dict(),
        "delivery_mode": "team_path",
        "task_id": execution.task.task_id,
        "develop_ref": "origin/develop",
        "develop_sha": base,
    }, repo_root=repo, approved_execution_plan=execution)
    contexts: dict[str, str] = {}
    implementer = api["build_role_brief"](
        intake,
        role="implementer",
        context_id="implementer-sol",
        implementer_context_id="implementer-sol",
        reviewer_context_id="reviewer-sol",
        specialist_contexts=contexts,
        round_number=0,
        original_implementer_context_id="implementer-sol",
    )
    reviewer = api["build_role_brief"](
        intake,
        role="reviewer",
        context_id="reviewer-sol",
        implementer_context_id="implementer-sol",
        reviewer_context_id="reviewer-sol",
        specialist_contexts=contexts,
        round_number=0,
        original_implementer_context_id="implementer-sol",
    )
    receipt_paths = []
    for check in ("diff-check", "secret-scan"):
        path = api["intake_workspace"](repo, intake) / f"receipts/{check}.json"
        _write_json(path, {
            "schema_version": 1,
            "required_check": check,
            "exact_head_sha": head,
            "status": "PASS",
            "exit_code": 0,
        })
        receipt_paths.append(path.relative_to(repo).as_posix())
    handoff = api["HandoffReportV1"].from_mapping({
        "schema_version": 1,
        "report_kind": "implementer",
        "specialist_domain": None,
        "intake_digest": api["intake_digest"](intake),
        "brief_digest": _digest(implementer.to_dict()),
        "context_id": implementer.context_id,
        "round": 0,
        "report_path": implementer.report_path,
        "exact_head_sha": head,
        "changed_paths": ["scripts/engineering/lean_matrix/feature.py"],
        "test_evidence": receipt_paths,
        "advisory_evidence_digests": [],
        "status": "DONE",
        "concerns": [],
        "predecessor_decision_digest": None,
    }, role_brief=implementer)

    package = api["build_review_package"](
        repo,
        intake,
        implementer_brief=implementer,
        implementer_handoff=handoff,
        reviewer_brief=reviewer,
    )

    assert tuple(receipt.path for receipt in package.test_receipts) == tuple(receipt_paths)

    forged_receipt_paths = list(receipt_paths)
    for check in ("independent-review", "exact-head-ci"):
        path = api["intake_workspace"](repo, intake) / f"receipts/fake-{check}.json"
        _write_json(path, {
            "schema_version": 1,
            "required_check": check,
            "exact_head_sha": head,
            "status": "PASS",
            "exit_code": 0,
        })
        forged_receipt_paths.append(path.relative_to(repo).as_posix())
    forged_payload = handoff.to_dict()
    forged_payload["test_evidence"] = forged_receipt_paths
    forged_handoff = api["HandoffReportV1"].from_mapping(
        forged_payload,
        role_brief=implementer,
    )
    with pytest.raises(api["LeanMatrixError"]) as raised:
        api["build_review_package"](
            repo,
            intake,
            implementer_brief=implementer,
            implementer_handoff=forged_handoff,
            reviewer_brief=reviewer,
        )
    assert raised.value.error_type == "required_check_coverage_missing"


def test_v07_requires_only_fresh_ci_owned_checks_and_validates_review_separately() -> None:
    """Local checks and independent review must never be duplicated into GitHub checks."""
    plan = _plan()
    allowed = _decision(_facts(plan=plan), plan=plan)
    assert (allowed.decision, allowed.reason_codes) == (
        "ALLOW_DEVELOP_MERGE",
        ("DEVELOP_MERGE_ALLOWED",),
    )

    local_and_review_only = [{
        "schema_version": 1,
        "name": name,
        "status": "SUCCESS",
        "head_sha": HEAD_SHA,
    } for name in ("diff-check", "secret-scan", "independent-review")]
    missing_ci = _decision(_facts(plan=plan, checks=local_and_review_only), plan=plan)
    assert (missing_ci.decision, missing_ci.reason_codes) == (
        "BLOCKED_CI", ("CI_CHECK_MISSING",),
    )

    non_independent = _mutated(
        _facts(plan=plan),
        review=_review(reviewer_context_id="implementer-sol"),
    )
    blocked_review = _decision(non_independent, plan=plan)
    assert (blocked_review.decision, blocked_review.reason_codes) == (
        "BLOCKED_REVIEW",
        ("INDEPENDENT_REVIEW_REQUIRED",),
    )


@pytest.mark.parametrize(
    "gate",
    [
        "Owner Gate: product-direction change",
        "Owner Gate: active-canonical conflict",
    ],
)
def test_product_direction_and_active_canonical_each_require_owner_gate(gate: str) -> None:
    """Neither protected decision can be hidden inside an otherwise safe Lane 2 PR."""
    charter = _charter(lane=3, external_gates=[gate])
    plan = _plan(lane=3, external_gates=[gate])
    facts = _facts(
        plan=plan,
        charter=charter,
        pending_external_gates=[gate],
    )

    result = _decision(facts, plan=plan)

    assert (result.decision, result.reason_codes) == (
        "MANUAL_GATE_REQUIRED",
        ("EXTERNAL_GATE_REQUIRED",),
    )


@pytest.mark.parametrize(
    ("updates", "decision", "reason"),
    [
        ({"base_sha": "4" * 40}, "BLOCKED_BASE_DRIFT", "PR_BASE_SHA_DRIFT"),
        ({"current_task_head_sha": "4" * 40}, "BLOCKED_HEAD_DRIFT", "TASK_HEAD_DRIFT"),
        ({"review": _review(head_sha="4" * 40)}, "BLOCKED_HEAD_DRIFT", "REVIEW_HEAD_DRIFT"),
        ({"review": _review(base_sha="4" * 40)}, "BLOCKED_BASE_DRIFT", "REVIEW_BASE_DRIFT"),
        ({"changed_paths": ["Runtime/enable.py"]}, "BLOCKED_SCOPE_DRIFT", "CHANGED_PATH_FORBIDDEN"),
        ({"review": _review(blocking_threads=1)}, "BLOCKED_THREADS", "BLOCKING_THREADS_OPEN"),
        ({"mergeability": "CONFLICTING"}, "BLOCKED_MERGEABILITY", "MERGEABILITY_CONFLICTING"),
    ],
)
def test_provenance_scope_thread_and_merge_conflict_matrix(
    updates: dict[str, object], decision: str, reason: str,
) -> None:
    """Base/head/path/thread/conflict drift must fail before any integration execution."""
    facts = _mutated(_facts(), **updates)
    result = _decision(facts)
    assert (result.decision, result.reason_codes) == (decision, (reason,))


@pytest.mark.parametrize(
    ("updates", "decision", "reason"),
    [
        ({"repository_id": 999}, "BLOCKED_PR_IDENTITY", "REPOSITORY_ID_MISMATCH"),
        ({"head_ref": "feature/wrong-branch"}, "BLOCKED_PR_IDENTITY", "PR_HEAD_REF_MISMATCH"),
        (
            {"review": _review(reviewer_context_id="implementer-sol")},
            "BLOCKED_REVIEW",
            "INDEPENDENT_REVIEW_REQUIRED",
        ),
    ],
)
def test_repository_branch_and_context_identity_fail_closed(
    updates: dict[str, object], decision: str, reason: str,
) -> None:
    """Repository, branch, and independent-context identity are load-bearing facts."""
    result = _decision(_mutated(_facts(), **updates))
    assert (result.decision, result.reason_codes) == (decision, (reason,))


def test_expired_future_and_tampered_facts_are_rejected() -> None:
    """Stale, future, or digest-tampered GitHub evidence cannot authorize integration."""
    expired = _facts(observed_at=NOW - timedelta(minutes=5))
    future = _facts(observed_at=NOW + timedelta(seconds=1))
    tampered = _facts()
    tampered["head_sha"] = "9" * 40

    assert _decision(expired).reason_codes == ("FACTS_EXPIRED",)
    assert _decision(future).reason_codes == ("FACTS_FROM_FUTURE",)
    assert _decision(tampered).reason_codes == ("FACTS_DIGEST_MISMATCH",)


def test_ci_failure_is_repairable_only_with_fresh_success_on_the_new_exact_head() -> None:
    """A failed old head cannot authorize a repaired head, while new exact-head CI can."""
    failed = _facts(checks=[{
        "schema_version": 1,
        "name": "exact-head-ci",
        "status": "FAILURE",
        "head_sha": HEAD_SHA,
    }])
    assert _decision(failed).reason_codes == ("CI_FAILURE",)

    new_head = "5" * 40
    repaired = _mutated(
        _facts(),
        head_sha=new_head,
        current_task_head_sha=new_head,
        review=_review(head_sha=new_head),
        checks=[{
            "schema_version": 1,
            "name": "exact-head-ci",
            "status": "SUCCESS",
            "head_sha": new_head,
        }],
    )
    assert _decision(repaired).reason_codes == ("DEVELOP_MERGE_ALLOWED",)

    stale = _mutated(repaired, checks=[{
        "schema_version": 1,
        "name": "exact-head-ci",
        "status": "SUCCESS",
        "head_sha": HEAD_SHA,
    }])
    assert _decision(stale).reason_codes == ("CI_HEAD_DRIFT",)


def test_timeout_readback_and_merged_cleanup_recovery_matrix() -> None:
    """Interrupted merge recovery is read-only until merge and both ancestries are confirmed."""
    unmerged = _facts(stage="merge_readback", mergeability="UNKNOWN")
    assert _decision(unmerged).reason_codes == ("MERGE_RESULT_UNCONFIRMED",)

    merged_values = {
        "pr_state": "MERGED",
        "pr_merged": True,
        "current_develop_sha": MERGE_SHA,
        "readback_merge_sha": MERGE_SHA,
        "readback_develop_contains_task_head": True,
    }
    merged = _facts(stage="merge_readback", mergeability="UNKNOWN", **merged_values)
    assert _decision(merged).reason_codes == ("MERGE_READBACK_CONFIRMED",)

    cleanup_values = merged_values | {
        "cleanup_worktree_clean": True,
        "cleanup_local_develop_contains_task_head": True,
        "cleanup_remote_develop_contains_task_head": True,
    }
    assert _decision(_facts(stage="cleanup", **cleanup_values)).reason_codes == (
        "CLEANUP_ALLOWED",
    )
    for field, reason in (
        ("cleanup_worktree_clean", "WORKTREE_NOT_CLEAN"),
        ("cleanup_local_develop_contains_task_head", "LOCAL_DEVELOP_MISSING_TASK_HEAD"),
        ("cleanup_remote_develop_contains_task_head", "REMOTE_DEVELOP_MISSING_TASK_HEAD"),
    ):
        blocked = _facts(stage="cleanup", **(cleanup_values | {field: False}))
        assert _decision(blocked).reason_codes == (reason,)


def test_missing_workspace_observation_is_read_only(tmp_path: Path) -> None:
    """Interrupted local evidence recovery must not invent a workspace or success state."""
    api = _contracts()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.workspace import load_evidence
    finally:
        sys.path.pop(0)
    plan = api["ExecutionPlanV1"].from_mapping(_plan())

    evidence = load_evidence(tmp_path, plan)

    assert evidence.records == ()
    assert evidence.attempted_actions == frozenset()
    assert not (tmp_path / ".ai").exists()


def test_round_three_load_bearing_review_is_terminally_blocked(tmp_path: Path) -> None:
    """Round three cannot produce another repair when a Critical finding remains."""
    review_test = ROOT / "tests/engineering/test_lean_matrix_review_protocol.py"
    name = f"lean_matrix_review_protocol_bootstrap_{id(tmp_path)}"
    spec = importlib.util.spec_from_file_location(name, review_test)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    state = module._round_zero(tmp_path)
    predecessor = "sha256:" + "7" * 64
    implementer = module._brief(
        state["api"],
        state["intake"],
        role="implementer",
        context_id="implementer-0",
        round_number=3,
        predecessor=predecessor,
        round_zero_brief=state["implementer"],
    )
    reviewer = module._brief(
        state["api"],
        state["intake"],
        role="reviewer",
        context_id="reviewer-0",
        round_number=3,
        predecessor=predecessor,
        round_zero_brief=state["implementer"],
    )
    handoff = module._handoff(
        state["api"],
        implementer,
        head=state["head"],
        changed_paths=["src/feature.py"],
        test_evidence=module._receipts(
            state["api"],
            state["repo"],
            state["intake"],
            head=state["head"],
            prefix="bootstrap-round-3",
        ),
    )
    terminal = {**state, "implementer": implementer, "reviewer": reviewer, "handoff": handoff}
    package = module._package(terminal)

    decision = module._decision(
        terminal,
        package,
        round_number=3,
        spec="FAIL",
        quality="CHANGES_REQUIRED",
        findings=[{"severity": "Critical", "summary": "load-bearing finding remains"}],
        decision="阻塞",
    )

    assert decision.decision == "阻塞"


@pytest.mark.parametrize(
    "operation",
    ["main", "tag", "runtime", "notification", "data_write", "live", "delete"],
)
def test_sensitive_operations_are_rejected_without_execution(operation: str) -> None:
    """A prompt or facts payload cannot authorize sensitive Lane 3 or real operations."""
    facts = _mutated(_facts(), requested_operations=[operation])
    result = _decision(facts)
    assert (result.decision, result.reason_codes) == (
        "MANUAL_GATE_REQUIRED",
        ("SENSITIVE_OPERATION_REQUESTED",),
    )


def test_fast_path_owner_gates_and_prompt_injection_remain_fail_closed(tmp_path: Path) -> None:
    """Only Lane 1 is Fast Path; Lane 3, frozen-scope expansion, and injected policy stop."""
    api = _contracts()
    repo = tmp_path / "repo"
    repo.mkdir()
    _write(repo / "docs/design.md", "approved design\n")
    _write(repo / "docs/plan.md", "approved plan\n")
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "bootstrap@example.invalid")
    _git(repo, "config", "user.name", "Bootstrap Tests")
    _git(repo, "add", "--all")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD^{commit}")
    _git(repo, "update-ref", "refs/remotes/origin/develop", base)

    def intake_for(lane: int):  # noqa: ANN202
        charter = api["TaskCharterV1"].from_mapping(_charter(lane=lane))
        plan = api["build_execution_plan"](
            charter, base_ref="origin/develop", base_sha=base,
        )
        payload = {
            "schema_version": 1,
            "design_path": "docs/design.md",
            "design_digest": _file_digest(repo / "docs/design.md"),
            "implementation_plan_path": "docs/plan.md",
            "implementation_plan_digest": _file_digest(repo / "docs/plan.md"),
            "execution_plan_digest": _digest(plan.to_dict()),
            "execution_plan": plan.to_dict(),
            "delivery_mode": "fast_path" if lane == 1 else "team_path",
            "task_id": plan.task.task_id,
            "develop_ref": "origin/develop",
            "develop_sha": base,
        }
        return plan, payload, api["DocumentIntakeV1"].from_mapping(
            payload, repo_root=repo, approved_execution_plan=plan,
        )

    _, _, lane_one = intake_for(1)
    _, _, lane_two = intake_for(2)
    lane_three_plan, lane_three_payload, lane_three = intake_for(3)
    assert lane_one.delivery_mode == "fast_path" and not lane_one.owner_gate_required()
    assert lane_two.charter_freeze == "automatic" and not lane_two.owner_gate_required()
    assert lane_three.owner_gate_required()
    assert lane_two.owner_gate_required(
        proposed_allowed_paths=[*lane_two.trusted_allowed_paths, "services/**"],
    )
    assert lane_three.trusted_external_gates == (
        "Owner Gate: Lane 3, product direction, active canonical, or real operation",
    )

    injected = lane_three_payload | {"owner_gate_required": False}
    with pytest.raises(Exception) as raised:  # strict loader owns the concrete error type
        api["DocumentIntakeV1"].from_mapping(
            injected, repo_root=repo, approved_execution_plan=lane_three_plan,
        )
    assert getattr(raised.value, "error_type", None) == "invalid_contract_keys"

    _write(repo / "docs/design.md", "drifted after approval\n")
    with pytest.raises(Exception) as raised:
        api["DocumentIntakeV1"].from_mapping(
            lane_three_payload, repo_root=repo, approved_execution_plan=lane_three_plan,
        )
    assert getattr(raised.value, "error_type", None) == "stale_design_document"
