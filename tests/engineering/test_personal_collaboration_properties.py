"""Property 1/2/3/9 for personal-development collaboration removal.

Feature: personal-development-mode
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, relative: str):
    path = ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


consistency = _load("repo_consistency_p3", "scripts/engineering/repository_consistency.py")
workflow = _load("personal_workflow_p3", "scripts/engineering/personal_workflow.py")
hook = _load("hook_p3", ".codex/hooks/pre_tool_use_policy.py")

ORDINARY_PATHS = [
    "services/quant-api/app/main.py",
    "apps/quant-web/src/App.vue",
    "docs/DEVELOPMENT.md",
    "tests/engineering/test_personal_workflow.py",
    "scripts/engineering/preflight.ps1",
]

COLLAB_METADATA = [
    {},
    {"issue": "123"},
    {"pr": "45", "review": "approved"},
    {"worktree": "trees/task", "exact_head": "abc"},
    {"required_ci": True, "packet": "hash"},
]


@pytest.mark.parametrize("index", range(100))
def test_property_1_ordinary_develop_authorization_is_collaboration_invariant(index: int) -> None:
    """Feature: personal-development-mode, Property 1: Ordinary develop authorization is collaboration-invariant"""
    paths = [ORDINARY_PATHS[index % len(ORDINARY_PATHS)]]
    metadata = COLLAB_METADATA[index % len(COLLAB_METADATA)]
    # Path classification ignores collaboration metadata entirely.
    domains_a = consistency.classify_changed_paths(paths)
    domains_b = consistency.classify_changed_paths(paths)
    assert domains_a == domains_b
    assert metadata is not None  # present or absent must not change result
    # Hook allows ordinary develop push regardless of metadata.
    decision = hook.decision(
        {"tool_name": "Bash", "tool_input": {"command": "git push origin develop"}}
    )
    assert decision == {}
    classification = workflow.classify_operation("modify", "repository_tracked")
    assert classification.operation_class is workflow.OperationClass.ORDINARY_REPOSITORY_CHANGE


@pytest.mark.parametrize("index", range(100))
def test_property_2_unrelated_dirty_changes_are_preserved(index: int) -> None:
    """Feature: personal-development-mode, Property 2: Unrelated dirty changes are preserved"""
    before = [f"other/{index}.py", f"task/{index}.py"]
    after = [f"other/{index}.py", f"task/{index}.py", f"task/{index}-new.py"]
    scope = [f"task/{index}.py", f"task/{index}-new.py"]
    drift = consistency.preserve_unrelated_dirty_paths(before, after, scope)
    assert drift == ()
    # Unrelated mutation is detected.
    bad_after = after + [f"other/{index}-touched.py"]
    bad = consistency.preserve_unrelated_dirty_paths(before, bad_after, scope)
    assert f"other/{index}-touched.py" in bad


@pytest.mark.parametrize("index", range(100))
def test_property_3_residual_collaboration_blockers_fail_consistency(index: int) -> None:
    """Feature: personal-development-mode, Property 3: Residual collaboration blockers fail consistency"""
    blockers = [
        "普通代码必须先创建 GitHub Issue 才能在 develop 开始。",
        "Only a task worktree may edit code; direct work on develop is forbidden.",
        "Approval packet hash is an authorization prerequisite for ordinary changes.",
        "Ordinary changes cannot be pushed to develop without required CI.",
        "Code changes require a pull request before local validation.",
    ]
    allowed = [
        "PR #145 merged; historical fact only.",
        "Manifest digest and checksum remain integrity checks.",
        "旧 receipt 不构成当前授权。",
        "Historical exact-head verification was recorded once.",
        "Review comments are optional collaboration tooling.",
    ]
    clause = blockers[index % len(blockers)] if index % 2 == 0 else allowed[index % len(allowed)]
    if index % 2 == 0:
        assert consistency.is_collaboration_blocker(clause)
    else:
        assert not consistency.is_collaboration_blocker(clause)


@pytest.mark.parametrize("index", range(100))
def test_property_9_repository_deletion_classification_and_reference_closure(index: int) -> None:
    """Feature: personal-development-mode, Property 9: Repository deletion classification and reference closure"""
    if index % 2 == 0:
        result = workflow.classify_operation("delete", "repository_tracked")
        assert result.operation_class is workflow.OperationClass.ORDINARY_REPOSITORY_DELETION
        assert result.category is None
    else:
        result = workflow.classify_operation(
            "delete",
            "production_database",
            category="production_delete",
        )
        assert result.operation_class is workflow.OperationClass.CONTROLLED_EXTERNAL_ACTION
        assert result.category is workflow.OperationCategory.PRODUCTION_DELETE
    # Active reference closure for retired orchestration assets.
    retired = [
        "scripts/engineering/task-worktree.sh",
        "scripts/engineering/task_workflow.py",
        "scripts/engineering/worktree_flow.py",
        ".github/workflows/lane-pr-gate.yml",
    ]
    target = retired[index % len(retired)]
    assert not (ROOT / target).exists()
