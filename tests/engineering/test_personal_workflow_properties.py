"""Property 4/5/6: scoped one-shot intent, bounded results, business precedence.

Feature: personal-development-mode
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "engineering" / "personal_workflow.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("personal_workflow_pbt", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load_module()

CATEGORIES = list(workflow.OperationCategory)
ENVIRONMENTS = ("staging", "local", "research")
TARGETS = ("runtime-observer", "main", "formal-parquet", "notification-channel")
RESOURCES = (
    ("scheduler",),
    ("worker", "scheduler"),
    ("branch",),
    ("dataset", "manifest"),
)


def _scope_for_index(index: int) -> workflow.ExecutionScope:
    category = CATEGORIES[index % len(CATEGORIES)]
    return workflow.ExecutionScope(
        category=category,
        environment=ENVIRONMENTS[index % len(ENVIRONMENTS)],
        target=TARGETS[index % len(TARGETS)],
        resource_boundary=RESOURCES[index % len(RESOURCES)],
    )


def _safe_constraints() -> tuple[workflow.ConstraintCheck, ...]:
    return (
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.INPUT_VALIDATION,
            workflow.ConstraintStatus.SATISFIED,
        ),
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.NO_ORDER,
            workflow.ConstraintStatus.SATISFIED,
        ),
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.SECRETS_PROTECTED,
            workflow.ConstraintStatus.SATISFIED,
        ),
    )


@pytest.mark.parametrize("index", range(120))
def test_property_4_explicit_intent_is_scoped_one_shot_and_non_persistent(index: int) -> None:
    """Feature: personal-development-mode, Property 4: Explicit intent is scoped, one-shot and non-persistent"""
    state = workflow.IntentState()
    scope = _scope_for_index(index)
    mode_cycle = index % 7

    if mode_cycle == 0:
        # Matching mutation succeeds exactly once.
        intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
        first = state.consume_for_attempt(
            intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
        )
        assert first.scope == scope
        with pytest.raises(workflow.PolicyError) as consumed:
            state.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert consumed.value.error_type is workflow.ErrorType.INTENT_CONSUMED
        return

    if mode_cycle == 1:
        # Missing intent.
        with pytest.raises(workflow.PolicyError) as missing:
            state.consume_for_attempt(
                None, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert missing.value.error_type is workflow.ErrorType.INTENT_REQUIRED
        return

    if mode_cycle == 2:
        # Changed scope consumes without authorizing.
        intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
        other = _scope_for_index(index + 1)
        with pytest.raises(workflow.PolicyError) as mismatch:
            state.consume_for_attempt(
                intent, other, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert mismatch.value.error_type is workflow.ErrorType.SCOPE_MISMATCH
        with pytest.raises(workflow.PolicyError) as retry:
            state.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert retry.value.error_type is workflow.ErrorType.INTENT_CONSUMED
        return

    if mode_cycle == 3:
        # Dry-run cannot convert to mutation.
        intent = state.issue(scope, mode=workflow.IntentMode.DRY_RUN)
        with pytest.raises(workflow.PolicyError) as mode_error:
            state.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert mode_error.value.error_type is workflow.ErrorType.INTENT_MODE_MISMATCH
        with pytest.raises(workflow.PolicyError) as reuse:
            state.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.DRY_RUN, constraints=_safe_constraints()
            )
        assert reuse.value.error_type is workflow.ErrorType.DRY_RUN_REUSE
        return

    if mode_cycle == 4:
        # Later session reconstruction fails closed.
        intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
        later = workflow.IntentState()
        with pytest.raises(workflow.PolicyError) as session:
            later.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
            )
        assert session.value.error_type is workflow.ErrorType.INTENT_SESSION_MISMATCH
        return

    if mode_cycle == 5:
        # Matching dry-run one-shot.
        intent = state.issue(scope, mode=workflow.IntentMode.DRY_RUN)
        authorized = state.consume_for_attempt(
            intent, scope, mode=workflow.IntentMode.DRY_RUN, constraints=_safe_constraints()
        )
        assert authorized.mode is workflow.IntentMode.DRY_RUN
        with pytest.raises(workflow.PolicyError) as reuse:
            state.consume_for_attempt(
                intent, scope, mode=workflow.IntentMode.DRY_RUN, constraints=_safe_constraints()
            )
        assert reuse.value.error_type is workflow.ErrorType.DRY_RUN_REUSE
        return

    # Retry after success requires a new issue.
    intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
    state.consume_for_attempt(
        intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
    )
    with pytest.raises(workflow.PolicyError):
        state.consume_for_attempt(
            intent, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
        )
    fresh = state.issue(scope, mode=workflow.IntentMode.MUTATION)
    again = state.consume_for_attempt(
        fresh, scope, mode=workflow.IntentMode.MUTATION, constraints=_safe_constraints()
    )
    assert again.scope == scope


@pytest.mark.parametrize("index", range(100))
def test_property_5_external_result_reporting_is_bounded_and_receipt_free(index: int) -> None:
    """Feature: personal-development-mode, Property 5: External result reporting is bounded and receipt-free"""
    statuses = (
        workflow.ResultStatus.OK,
        workflow.ResultStatus.FAILED,
        workflow.ResultStatus.BLOCKED,
        workflow.ResultStatus.UNAVAILABLE,
    )
    status = statuses[index % len(statuses)]
    scope = _scope_for_index(index)
    checks: list[workflow.CheckResult]
    error = None
    if status is workflow.ResultStatus.OK:
        checks = [
            workflow.CheckResult("publish", workflow.CheckStatus.PASSED, "ok"),
        ]
    elif status is workflow.ResultStatus.FAILED:
        checks = [
            workflow.CheckResult("publish", workflow.CheckStatus.FAILED, "failed"),
        ]
    elif status is workflow.ResultStatus.BLOCKED:
        checks = [
            workflow.CheckResult("publish", workflow.CheckStatus.FAILED, "blocked"),
        ]
        error = workflow.BoundedError(workflow.ErrorType.OPERATION_BLOCKED, "blocked")
    else:
        checks = [
            workflow.CheckResult("tool", workflow.CheckStatus.UNAVAILABLE, "missing"),
        ]
        error = workflow.BoundedError(workflow.ErrorType.TOOL_UNAVAILABLE, "missing tool")

    result = workflow.StableResult(
        tool="scripts/engineering/release-tag.ps1",
        operation=workflow.ToolOperation.PUBLISH_TAG,
        mode=workflow.ResultMode.MUTATION,
        status=status,
        checks=tuple(checks),
        scope=scope,
        error=error,
    )
    payload = result.to_dict()
    text = result.to_json()
    assert payload["schema_version"] == 1
    assert set(payload["summary"]) == {"passed", "failed", "warn", "unavailable"}
    assert "receipt" not in text.lower()
    assert "password" not in text.lower()
    assert "approval_packet" not in text
    assert Path(ROOT / "scripts" / "engineering").joinpath("receipt.json").exists() is False


@pytest.mark.parametrize("index", range(100))
def test_property_6_business_constraints_dominate_intent(index: int) -> None:
    """Feature: personal-development-mode, Property 6: Business constraints dominate intent"""
    state = workflow.IntentState()
    scope = _scope_for_index(index)
    intent = state.issue(scope, mode=workflow.IntentMode.MUTATION)
    constraint = list(workflow.BusinessConstraint)[index % len(workflow.BusinessConstraint)]
    bad_status = (
        workflow.ConstraintStatus.VIOLATED,
        workflow.ConstraintStatus.MISSING,
        workflow.ConstraintStatus.MALFORMED,
    )[index % 3]
    sensitive_calls = {"count": 0}

    def sensitive_operation() -> None:
        sensitive_calls["count"] += 1

    with pytest.raises(workflow.PolicyError) as blocked:
        state.consume_for_attempt(
            intent,
            scope,
            mode=workflow.IntentMode.MUTATION,
            constraints=(
                workflow.ConstraintCheck(constraint, bad_status),
            ),
        )
    assert blocked.value.error_type is workflow.ErrorType.BUSINESS_CONSTRAINT
    assert sensitive_calls["count"] == 0
    # Constraints are checked before consume, so a later matching attempt still
    # requires a fresh satisfied constraint set and does not inherit authority.
    authorized = state.consume_for_attempt(
        intent,
        scope,
        mode=workflow.IntentMode.MUTATION,
        constraints=_safe_constraints(),
    )
    assert authorized.scope == scope
    sensitive_operation()
    assert sensitive_calls["count"] == 1
