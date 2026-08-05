"""Unit contracts for the shared personal-workflow policy models."""

from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "engineering" / "personal_workflow.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("personal_workflow", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


workflow = _load_module()


def _scope(
    *,
    category=workflow.OperationCategory.RUNTIME_SWITCH,
    target: str = "runtime-observer",
    resources: tuple[str, ...] = ("scheduler", "worker"),
):
    return workflow.ExecutionScope(
        category=category,
        environment="staging",
        target=target,
        resource_boundary=resources,
    )


def _safe_constraints():
    return (
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.INPUT_VALIDATION,
            workflow.ConstraintStatus.SATISFIED,
        ),
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.NO_ORDER,
            workflow.ConstraintStatus.SATISFIED,
        ),
    )


def test_classifies_repository_change_deletion_and_business_constraint() -> None:
    change = workflow.classify_operation("modify", "repository_tracked")
    deletion = workflow.classify_operation("delete", "repository_tracked")
    constraint = workflow.classify_operation("enforce", "business_correctness")

    assert change.operation_class is workflow.OperationClass.ORDINARY_REPOSITORY_CHANGE
    assert deletion.operation_class is workflow.OperationClass.ORDINARY_REPOSITORY_DELETION
    assert constraint.operation_class is workflow.OperationClass.BUSINESS_CORRECTNESS_CONSTRAINT
    assert change.category is None


def test_classifies_only_resource_compatible_controlled_category() -> None:
    result = workflow.classify_operation(
        "modify",
        "runtime_state",
        category="runtime_switch",
    )
    assert result == workflow.OperationClassification(
        workflow.OperationClass.CONTROLLED_EXTERNAL_ACTION,
        workflow.OperationCategory.RUNTIME_SWITCH,
    )

    with pytest.raises(workflow.PolicyError) as mismatch:
        workflow.classify_operation(
            "modify",
            "runtime_state",
            category="real_notification",
        )
    assert mismatch.value.error_type is workflow.ErrorType.INVALID_OPERATION


@pytest.mark.parametrize(
    ("action", "resource", "category"),
    [
        ("unknown", "repository_tracked", None),
        ("modify", "unknown", None),
        ("modify", "runtime_state", None),
        ("modify", "repository_tracked", "runtime_switch"),
        ("modify", "production_database", "production_delete"),
        ("delete", "production_database", "production_data_write"),
    ],
)
def test_operation_classification_fails_closed(
    action: str,
    resource: str,
    category: str | None,
) -> None:
    with pytest.raises(workflow.PolicyError):
        workflow.classify_operation(action, resource, category=category)


def test_execution_scope_normalizes_unicode_whitespace_order_and_type() -> None:
    scope = workflow.ExecutionScope(
        category="push_tag",
        environment="  staging  ",
        target="ｖ1.2.3",
        resource_boundary=(" tag/v1.2.3 ", "origin"),
    )

    assert scope.category is workflow.OperationCategory.PUSH_TAG
    assert scope.environment == "staging"
    assert scope.target == "v1.2.3"
    assert scope.resource_boundary == ("origin", "tag/v1.2.3")
    assert scope.to_public_dict() == {
        "category": "push_tag",
        "environment": "staging",
        "target": "v1.2.3",
        "resource_boundary": ["origin", "tag/v1.2.3"],
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"category": "unknown"},
        {"target": ""},
        {"target": "line\nbreak"},
        {"resources": ()},
        {"resources": ("same", " same ")},
        {"target": "https://name:synthetic-value@example.invalid/item"},
        {"target": "item?token=synthetic-value"},
    ],
)
def test_execution_scope_rejects_malformed_or_disclosive_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(workflow.PolicyError) as raised:
        _scope(**kwargs)
    assert raised.value.error_type in {
        workflow.ErrorType.INVALID_INPUT,
        workflow.ErrorType.INVALID_SCOPE,
    }


def test_matching_intent_authorizes_exactly_one_mutation_attempt() -> None:
    state = workflow.IntentState()
    scope = _scope()
    intent = state.issue(scope)

    attempt = state.consume_for_attempt(
        intent,
        scope,
        mode="mutation",
        constraints=_safe_constraints(),
    )

    assert attempt.scope == scope
    assert attempt.mode is workflow.IntentMode.MUTATION
    assert intent.consumed is True
    with pytest.raises(workflow.PolicyError) as reused:
        state.consume_for_attempt(
            intent,
            scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert reused.value.error_type is workflow.ErrorType.INTENT_CONSUMED


def test_changed_scope_consumes_intent_without_authorizing_mutation() -> None:
    state = workflow.IntentState()
    approved_scope = _scope()
    changed_scope = _scope(target="different-runtime")
    intent = state.issue(approved_scope)

    with pytest.raises(workflow.PolicyError) as changed:
        state.consume_for_attempt(
            intent,
            changed_scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert changed.value.error_type is workflow.ErrorType.SCOPE_MISMATCH
    assert intent.consumed is True

    with pytest.raises(workflow.PolicyError) as retry:
        state.consume_for_attempt(
            intent,
            approved_scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert retry.value.error_type is workflow.ErrorType.INTENT_CONSUMED


def test_dry_run_intent_cannot_convert_to_mutation_or_be_reused() -> None:
    state = workflow.IntentState()
    scope = _scope()
    intent = state.issue(scope, mode="dry_run")

    dry_run = state.consume_for_attempt(
        intent,
        scope,
        mode="dry_run",
        constraints=_safe_constraints(),
    )
    assert dry_run.mode is workflow.IntentMode.DRY_RUN

    with pytest.raises(workflow.PolicyError) as reuse:
        state.consume_for_attempt(
            intent,
            scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert reuse.value.error_type is workflow.ErrorType.DRY_RUN_REUSE

    mutation_intent = state.issue(scope, mode="dry_run")
    with pytest.raises(workflow.PolicyError) as conversion:
        state.consume_for_attempt(
            mutation_intent,
            scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert conversion.value.error_type is workflow.ErrorType.INTENT_MODE_MISMATCH
    assert mutation_intent.consumed is True


def test_missing_or_later_session_intent_fails_closed() -> None:
    scope = _scope()
    first_session = workflow.IntentState()
    later_session = workflow.IntentState()

    with pytest.raises(workflow.PolicyError) as missing:
        first_session.consume_for_attempt(
            None,
            scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert missing.value.error_type is workflow.ErrorType.INTENT_REQUIRED

    intent = first_session.issue(scope)
    with pytest.raises(workflow.PolicyError) as later:
        later_session.consume_for_attempt(
            intent,
            scope,
            mode="mutation",
            constraints=_safe_constraints(),
        )
    assert later.value.error_type is workflow.ErrorType.INTENT_SESSION_MISMATCH
    assert intent.consumed is False


def test_business_constraint_violation_precedes_intent_authority() -> None:
    state = workflow.IntentState()
    scope = _scope()
    intent = state.issue(scope)
    constraints = (
        workflow.ConstraintCheck(
            workflow.BusinessConstraint.NO_ORDER,
            workflow.ConstraintStatus.VIOLATED,
        ),
    )

    with pytest.raises(workflow.PolicyError) as blocked:
        state.consume_for_attempt(
            intent,
            scope,
            mode="mutation",
            constraints=constraints,
        )
    assert blocked.value.error_type is workflow.ErrorType.BUSINESS_CONSTRAINT
    assert "no_order" in blocked.value.detail
    assert intent.consumed is False


@pytest.mark.parametrize("status", ["violated", "missing", "malformed"])
def test_each_non_satisfied_business_status_fails_closed(status: str) -> None:
    check = workflow.ConstraintCheck("data_quality", status)
    with pytest.raises(workflow.PolicyError) as blocked:
        workflow.enforce_business_constraints((check,))
    assert blocked.value.error_type is workflow.ErrorType.BUSINESS_CONSTRAINT


def test_redaction_and_bounded_errors_do_not_disclose_synthetic_values() -> None:
    synthetic_value = "synthetic-example-value"
    detail = (
        f"password={synthetic_value} "
        f"https://person:{synthetic_value}@example.invalid/path "
        f"?token={synthetic_value} "
        + ("x" * 800)
    )

    redacted = workflow.redact_text(detail, max_length=96)
    error = workflow.BoundedError(
        workflow.ErrorType.OPERATION_BLOCKED,
        detail,
    )

    assert synthetic_value not in redacted
    assert synthetic_value not in error.detail
    assert len(redacted) <= 96
    assert len(error.detail) <= workflow.MAX_ERROR_DETAIL_LENGTH
    assert error.to_dict()["type"] == "operation_blocked"


def test_stable_result_emits_exact_schema_and_truthful_summary() -> None:
    result = workflow.StableResult(
        tool="scripts/engineering/validate.ps1",
        operation="validate",
        mode="read_only",
        status="ok",
        checks=(
            workflow.CheckResult("unit tests", "passed", "12 passed"),
            workflow.CheckResult("optional tool", "warn", "not configured"),
        ),
    )

    payload = result.to_dict()
    assert payload == {
        "schema_version": 1,
        "tool": "scripts/engineering/validate.ps1",
        "operation": "validate",
        "mode": "read_only",
        "status": "ok",
        "summary": {"passed": 1, "failed": 0, "warn": 1, "unavailable": 0},
        "checks": [
            {"name": "unit tests", "status": "passed", "detail": "12 passed"},
            {"name": "optional tool", "status": "warn", "detail": "not configured"},
        ],
    }
    assert json.loads(result.to_json()) == payload


def test_controlled_result_contains_public_scope_and_bounded_error_only() -> None:
    scope = _scope(category="real_notification", resources=("channel:test",))
    error = workflow.BoundedError(
        "operation_blocked",
        "authorization=synthetic-example-value",
    )
    result = workflow.StableResult(
        tool="scripts/engineering/personal_workflow.py",
        operation="policy",
        mode="mutation",
        status="blocked",
        scope=scope,
        error=error,
    )

    payload = result.to_dict()
    encoded = result.to_json()
    assert payload["scope"] == scope.to_public_dict()
    assert payload["error"]["type"] == "operation_blocked"
    assert "synthetic-example-value" not in encoded
    assert "intent" not in encoded


@pytest.mark.parametrize(
    "factory",
    [
        lambda: workflow.CheckResult("check", "unknown", "detail"),
        lambda: workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation="unknown",
            mode="read_only",
            status="ok",
        ),
        lambda: workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation="validate",
            mode="unknown",
            status="ok",
        ),
        lambda: workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation="validate",
            mode="read_only",
            status="unknown",
        ),
    ],
)
def test_unknown_closed_enum_values_fail(factory) -> None:
    with pytest.raises(workflow.PolicyError):
        factory()


def test_result_rejects_false_success_and_unbounded_failure_shape() -> None:
    failed_check = workflow.CheckResult("unit", "failed", "failed")
    with pytest.raises(workflow.PolicyError):
        workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation="validate",
            mode="read_only",
            status="ok",
            checks=(failed_check,),
        )
    with pytest.raises(workflow.PolicyError):
        workflow.StableResult(
            tool="scripts/engineering/validate.ps1",
            operation="validate",
            mode="read_only",
            status="blocked",
        )


def test_module_has_no_persistence_command_network_or_credential_input_capability() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    imported_roots = {
        alias.name.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }

    assert imported_roots.isdisjoint(
        {
            "argparse",
            "http",
            "os",
            "pathlib",
            "requests",
            "socket",
            "subprocess",
            "urllib",
        }
    )
    assert not hasattr(workflow.ExplicitIntent, "to_dict")
    assert not hasattr(workflow.ExplicitIntent, "to_json")
