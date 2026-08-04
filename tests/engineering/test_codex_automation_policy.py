"""Executable safety contracts for the five-layer task automation."""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "scripts" / "engineering" / "task_workflow.py"
HOOK_PATH = ROOT / ".codex" / "hooks" / "pre_tool_use_policy.py"
TASK_SCRIPT = ROOT / "scripts" / "engineering" / "task-worktree.sh"
RUNTIME_PROMOTION = ROOT / "scripts" / "engineering" / "runtime-promotion.sh"
LANE_PR_WORKFLOW = ROOT / ".github" / "workflows" / "lane-pr-gate.yml"
WORKFLOW_RULES = ROOT / ".codex" / "rules" / "workflow.rules"
DEVELOPMENT_DOC = ROOT / "docs" / "DEVELOPMENT.md"


def _module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_lane_one_accepts_only_isolated_experiment_paths() -> None:
    """A Lane 1 experiment must not be able to change a formal strategy module."""
    policy = _module(POLICY_PATH, "task_workflow_lane_one")

    assert policy.classify_paths(1, ["experiments/example/research.py", "tests/example.py"]) == "ok"
    with pytest.raises(policy.WorkflowError, match="lane_one_path_forbidden"):
        policy.classify_paths(1, ["services/quant-api/app/strategies/formal.py"])


def test_lane_two_rejects_real_write_and_runtime_paths() -> None:
    """Normal engineering automation must stop before a Lane 3 boundary."""
    policy = _module(POLICY_PATH, "task_workflow_lane_two")

    with pytest.raises(policy.WorkflowError, match="lane_two_path_forbidden"):
        policy.classify_paths(2, ["services/quant-api/alembic/versions/20260729_new.py"])
    with pytest.raises(policy.WorkflowError, match="lane_two_path_forbidden"):
        policy.classify_paths(2, ["deploy/launchd/com.guiyi.quant-runtime.plist.template"])
    with pytest.raises(policy.WorkflowError, match="lane_two_path_forbidden"):
        policy.classify_paths(2, ["services/quant-api/app/services/notification_dispatch.py"])
    with pytest.raises(policy.WorkflowError, match="lane_two_path_forbidden"):
        policy.classify_paths(2, ["scripts/configure-live-signal-events.sh"])


def test_develop_merge_classifier_reuses_lane_one_and_two_path_policy() -> None:
    """Bypassing classify_paths for ordinary lanes must let a forbidden path merge."""
    policy = _module(POLICY_PATH, "task_workflow_develop_lane_one_two")

    assert policy.classify_develop_merge(
        1,
        ["experiments/example/research.py", "tests/example.py"],
        ["develop_merge"],
        [],
        change_categories=[],
    ) == "ok"
    assert policy.classify_develop_merge(
        2,
        ["apps/quant-web/src/example.ts"],
        ["develop_merge"],
        [],
        change_categories=["code"],
    ) == "ok"
    with pytest.raises(policy.WorkflowError) as lane_one:
        policy.classify_develop_merge(
            1,
            ["services/quant-api/app/strategies/formal.py"],
            ["develop_merge"],
            [],
            change_categories=[],
        )
    with pytest.raises(policy.WorkflowError) as lane_two:
        policy.classify_develop_merge(
            2,
            ["services/quant-api/alembic/versions/20260729_new.py"],
            ["develop_merge"],
            [],
            change_categories=[],
        )

    assert lane_one.value.error_type == "lane_one_path_forbidden"
    assert lane_two.value.error_type == "lane_two_path_forbidden"


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("services/quant-api/app/services/ordinary_service.py", "code"),
        ("services/quant-api/app/services/new_disabled_adapter.py", "disabled_feature"),
        ("tests/engineering/test_ordinary_service.py", "test"),
        ("scripts/engineering/example_dry_run.py", "dry_run"),
        ("services/quant-api/alembic/versions/20260803_0032_isolated.py", "isolated_migration"),
    ],
)
def test_lane_three_allows_side_effect_free_changes_for_develop_integration(
    path: str,
    category: str,
) -> None:
    """Rejecting a scoped code-only Lane 3 PR would prevent its safe develop integration."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_lane_three_{path.rsplit('/', 1)[-1]}")

    assert policy.classify_develop_merge(
        3, [path], ["develop_merge"], [], change_categories=[category],
    ) == "ok"


@pytest.mark.parametrize(
    "path",
    [
        ".codex/hooks/pre_tool_use_policy.py",
        ".github/workflows/change-rules.yml",
        "data/raw/authoritative-bars.parquet",
        "data/parquet/active-bars.parquet",
        "deploy/launchd/com.guiyi.quant-runtime.plist.template",
        "docs/decisions/ADR-unsafe.md",
        "services/quant-api/alembic/env.py",
        "services/quant-api/app/signal/events.py",
        "services/quant-api/app/tasks/live_worker.py",
        "services/quant-api/app/websocket/live_feed.py",
        "services/quant-api/app/runtime.py",
        "services/quant-api/app/after_market.py",
        "services/quant-api/app/services/live_ingest.py",
        "services/quant-api/app/services/notification_dispatch.py",
        "services/quant-api/app/services/signal_evaluator.py",
        "scripts/configure-live-signal-events.sh",
        "scripts/jm_live_signal.py",
        "scripts/jm_htdy_apply.py",
        "scripts/rqdata_live_ingest.py",
        "scripts/run-runtime.sh",
        "scripts/install-runtime.sh",
        ".env.production",
        "AGENTS.md",
        "DECISIONS.md",
        "PROJECT_SOURCE.md",
    ],
)
def test_lane_three_rejects_every_existing_sensitive_path_surface(path: str) -> None:
    """Treating a Lane 2-forbidden path as code-only must reopen a protected surface."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_lane_three_block_{path.rsplit('/', 1)[-1]}")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3, [path], ["develop_merge"], [], change_categories=["code"],
        )

    assert raised.value.error_type == "lane_two_path_forbidden"


@pytest.mark.parametrize(
    "path",
    [
        "data/reports/run/completion_receipt.json",
        "reports/final-report.json",
        "receipts/merge-receipt.json",
        "canonical.sqlite3",
        "artifacts/cache.duckdb",
    ],
)
@pytest.mark.parametrize(
    "category",
    ["code", "test", "dry_run", "disabled_feature", "isolated_migration"],
)
def test_lane_three_safe_category_claim_cannot_authorize_evidence_or_binary_artifacts(
    path: str,
    category: str,
) -> None:
    """Trusting a digest-bound label alone must let protected artifacts auto-merge."""
    policy = _module(POLICY_PATH, "task_workflow_develop_lane_three_artifact")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3, [path], ["develop_merge"], [], change_categories=[category],
        )

    assert raised.value.error_type == "lane_three_path_forbidden"


@pytest.mark.parametrize(
    ("path", "category"),
    [
        ("tests/engineering/test_example.py", "code"),
        ("scripts/engineering/example_dry_run.py", "code"),
        ("services/quant-api/app/services/example.py", "test"),
    ],
)
def test_lane_three_category_must_match_the_changed_path_surface(
    path: str,
    category: str,
) -> None:
    """A valid category for a different path kind must not authorize this path."""
    policy = _module(POLICY_PATH, "task_workflow_develop_lane_three_category_binding")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3, [path], ["develop_merge"], [], change_categories=[category],
        )

    assert raised.value.error_type == "lane_three_change_category_mismatch"


def test_lane_three_isolated_migration_category_and_path_are_bidirectionally_bound() -> None:
    """A migration path or category without its counterpart must not auto-merge."""
    policy = _module(POLICY_PATH, "task_workflow_develop_lane_three_migration_binding")
    migration = "services/quant-api/alembic/versions/20260803_0032_isolated.py"

    with pytest.raises(policy.WorkflowError) as missing_category:
        policy.classify_develop_merge(
            3, [migration], ["develop_merge"], [], change_categories=["code"],
        )
    with pytest.raises(policy.WorkflowError) as missing_path:
        policy.classify_develop_merge(
            3,
            ["services/quant-api/app/services/example.py"],
            ["develop_merge"],
            [],
            change_categories=["isolated_migration"],
        )

    assert missing_category.value.error_type == "isolated_migration_category_required"
    assert missing_path.value.error_type == "isolated_migration_path_required"
    assert policy.classify_develop_merge(
        3,
        [migration, "tests/engineering/test_migration.py"],
        ["develop_merge"],
        [],
        change_categories=["isolated_migration", "test"],
    ) == "ok"


@pytest.mark.parametrize(
    "path",
    [
        "services/quant-api/alembic/versions/canonical.sqlite3",
        "services/quant-api/alembic/versions/approval_receipt.json",
        "services/quant-api/alembic/versions/production-data.parquet",
        "services/quant-api/alembic/versions/20260803_isolated.py",
        "services/quant-api/alembic/versions/20260803_32_short_revision.py",
        "services/quant-api/alembic/versions/20260803_0032_gate_evidence.py",
        "services/quant-api/alembic/versions/20260803_0032_approval_receipt.py",
        "services/quant-api/alembic/versions/20260803_0032_production_data.py",
    ],
)
def test_isolated_migration_requires_strict_source_filename_and_no_artifact_markers(
    path: str,
) -> None:
    """Treating any file under versions as migration source must admit frozen artifacts."""
    policy = _module(POLICY_PATH, "task_workflow_develop_migration_source_contract")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3,
            [path],
            ["develop_merge"],
            [],
            change_categories=["isolated_migration"],
        )

    assert raised.value.error_type == "lane_three_path_forbidden"


def test_four_argument_classifier_interface_remains_frozen() -> None:
    """Making category evidence positional or required must break existing Lane 1/2 callers."""
    policy = _module(POLICY_PATH, "task_workflow_develop_frozen_interface")

    assert policy.classify_develop_merge(
        1, ["tests/example.py"], ["develop_merge"], [],
    ) == "ok"
    assert policy.classify_develop_merge(
        2, ["apps/quant-web/src/example.ts"], ["develop_merge"], [],
    ) == "ok"
    with pytest.raises(policy.WorkflowError) as lane_three:
        policy.classify_develop_merge(
            3, ["services/quant-api/app/services/example.py"], ["develop_merge"], [],
        )

    assert lane_three.value.error_type == "lane_three_change_categories_required"


@pytest.mark.parametrize("lane", [1, 2])
def test_lane_one_and_two_allow_empty_or_valid_safe_categories(lane: int) -> None:
    """Adding category evidence must not narrow existing Lane 1/2 path behavior."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_lane_{lane}_categories")
    path = "tests/example.py" if lane == 1 else "apps/quant-web/src/example.ts"

    assert policy.classify_develop_merge(
        lane, [path], ["develop_merge"], [], change_categories=[],
    ) == "ok"
    assert policy.classify_develop_merge(
        lane, [path], ["develop_merge"], [], change_categories=["code", "test"],
    ) == "ok"


@pytest.mark.parametrize("lane", [1, 2, 3])
def test_unknown_change_category_fails_closed_for_every_lane(lane: int) -> None:
    """An unrecognized category must not gain authority in any lane."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_lane_{lane}_unknown_category")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            lane,
            ["tests/example.py"],
            ["develop_merge"],
            [],
            change_categories=["unknown"],
        )

    assert raised.value.error_type == "unknown_change_category"


def test_lane_three_requires_at_least_one_change_category() -> None:
    """Missing category evidence must stop Lane 3 even on an otherwise safe code path."""
    policy = _module(POLICY_PATH, "task_workflow_develop_lane_three_empty_categories")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3,
            ["services/quant-api/app/services/example.py"],
            ["develop_merge"],
            [],
            change_categories=[],
        )

    assert raised.value.error_type == "lane_three_change_categories_required"


@pytest.mark.parametrize("operation", ["develop_merge", "merge_readback", "cleanup"])
def test_develop_merge_classifier_accepts_only_known_develop_transition_operations(
    operation: str,
) -> None:
    """Dropping a stage operation from the allowlist must block its safe transition."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_safe_{operation}")

    assert policy.classify_develop_merge(
        3, ["tests/example.py"], [operation], [], change_categories=["test"],
    ) == "ok"


def test_pending_external_gate_requires_manual_gate_for_every_lane() -> None:
    """Ignoring a pending owner Gate must permit code integration beyond its approved boundary."""
    policy = _module(POLICY_PATH, "task_workflow_develop_external_gate")

    for lane in (1, 2, 3):
        with pytest.raises(policy.WorkflowError) as raised:
            policy.classify_develop_merge(
                lane,
                ["tests/example.py"],
                ["develop_merge"],
                ["owner approves production apply"],
                change_categories=[],
            )
        assert raised.value.error_type == "manual_gate_required"


@pytest.mark.parametrize(
    "operation",
    [
        "main",
        "tag",
        "release",
        "runtime",
        "live",
        "notification",
        "data_write",
        "db_write",
        "delete",
        "github_rules",
        "apply",
        "write",
        "enable",
    ],
)
def test_sensitive_real_operation_requires_manual_gate(operation: str) -> None:
    """Removing a sensitive operation from the manual set must authorize a real side effect."""
    policy = _module(POLICY_PATH, f"task_workflow_develop_sensitive_{operation}")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3, ["tests/example.py"], [operation], [], change_categories=["test"],
        )

    assert raised.value.error_type == "manual_gate_required"


@pytest.mark.parametrize(
    "operations",
    [[], ["unknown_operation"], ["develop_merge", "cleanup"]],
)
def test_unknown_or_missing_requested_operation_fails_closed(operations: list[str]) -> None:
    """Treating an absent or unknown operation as safe must let ambiguous authority advance."""
    policy = _module(POLICY_PATH, "task_workflow_develop_unknown_operation")

    with pytest.raises(policy.WorkflowError) as raised:
        policy.classify_develop_merge(
            3, ["tests/example.py"], operations, [], change_categories=["test"],
        )

    assert raised.value.error_type == "unknown_requested_operation"


def test_policy_cli_reads_newline_delimited_paths_without_splitting_spaces(tmp_path: Path) -> None:
    """CI must classify the actual filename even when it includes spaces."""
    path_file = tmp_path / "changed_paths.txt"
    path_file.write_text("apps/quant-web/src/a file.ts\n", encoding="utf-8")

    result = subprocess.run(
        [sys.executable, str(POLICY_PATH), "--lane", "2", "--path-file", str(path_file)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["paths"] == ["apps/quant-web/src/a file.ts"]


def _run_develop_merge_check(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(POLICY_PATH), "develop-merge-check", *args],
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


def test_legacy_policy_cli_shape_and_positional_paths_remain_compatible() -> None:
    result = subprocess.run(
        [sys.executable, str(POLICY_PATH), "--lane", "2", "apps/quant-web/src/example.ts"],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout) == {
        "status": "ok",
        "lane": 2,
        "paths": ["apps/quant-web/src/example.ts"],
    }


def test_develop_merge_check_emits_stable_allow_json() -> None:
    result = _run_develop_merge_check(
        "--lane", "2",
        "--operation", "develop_merge",
        "--change-category", "code",
        "apps/quant-web/src/example.ts",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert list(payload) == sorted(payload)
    assert payload == {
        "action": "develop-merge-check",
        "change_categories": ["code"],
        "decision": "allow",
        "external_gates": [],
        "lane": 2,
        "operation": "develop_merge",
        "paths": ["apps/quant-web/src/example.ts"],
        "schema_version": 1,
        "status": "ok",
        "tool": "scripts/engineering/task_workflow.py",
    }


@pytest.mark.parametrize(
    ("lane", "path", "categories"),
    [
        (2, "apps/quant-web/src/example.ts", []),
        (3, "services/quant-api/app/services/example.py", ["code"]),
        (3, "tests/engineering/test_example.py", ["test"]),
    ],
)
def test_develop_merge_check_allows_only_existing_safe_contracts(
    lane: int,
    path: str,
    categories: list[str],
) -> None:
    category_args = [item for category in categories for item in ("--change-category", category)]
    result = _run_develop_merge_check(
        "--lane", str(lane),
        "--operation", "develop_merge",
        *category_args,
        path,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["decision"] == "allow"


@pytest.mark.parametrize(
    ("path", "error_type"),
    [
        ("services/quant-api/alembic/versions/20260804_0001_example.py", "lane_two_path_forbidden"),
        ("services/quant-api/app/runtime.py", "lane_two_path_forbidden"),
        ("services/quant-api/app/services/notification_dispatch.py", "lane_two_path_forbidden"),
    ],
)
def test_develop_merge_check_rejects_lane_two_protected_paths(path: str, error_type: str) -> None:
    result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", path,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == error_type


def test_develop_merge_check_requires_lane_three_category() -> None:
    result = _run_develop_merge_check(
        "--lane", "3",
        "--operation", "develop_merge",
        "services/quant-api/app/services/example.py",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "lane_three_change_categories_required"


@pytest.mark.parametrize(
    ("path", "categories", "error_type"),
    [
        (
            "services/quant-api/alembic/versions/20260804_0001_example.py",
            ["code"],
            "isolated_migration_category_required",
        ),
        (
            "services/quant-api/app/services/example.py",
            ["isolated_migration"],
            "isolated_migration_path_required",
        ),
    ],
)
def test_develop_merge_check_binds_isolated_migration_path_and_category(
    path: str,
    categories: list[str],
    error_type: str,
) -> None:
    category_args = [item for category in categories for item in ("--change-category", category)]
    result = _run_develop_merge_check(
        "--lane", "3",
        "--operation", "develop_merge",
        *category_args,
        path,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == error_type


def test_develop_merge_check_allows_bound_isolated_migration() -> None:
    result = _run_develop_merge_check(
        "--lane", "3",
        "--operation", "develop_merge",
        "--change-category", "isolated_migration",
        "services/quant-api/alembic/versions/20260804_0001_example.py",
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["decision"] == "allow"


def test_develop_merge_check_rejects_pending_external_gate() -> None:
    result = _run_develop_merge_check(
        "--lane", "2",
        "--operation", "develop_merge",
        "--external-gate", "owner-approval-pending",
        "apps/quant-web/src/example.ts",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "manual_gate_required"


@pytest.mark.parametrize(
    "operation",
    [
        "main", "tag", "release", "runtime", "live", "notification", "data_write",
        "db_write", "delete", "github_rules", "apply", "write", "enable",
    ],
)
def test_develop_merge_check_rejects_manual_gate_operations(operation: str) -> None:
    result = _run_develop_merge_check(
        "--lane", "2", "--operation", operation, "apps/quant-web/src/example.ts",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "manual_gate_required"


@pytest.mark.parametrize("operation", ["unknown", "develop_merge,cleanup"])
def test_develop_merge_check_rejects_unknown_operation(operation: str) -> None:
    result = _run_develop_merge_check(
        "--lane", "2", "--operation", operation, "apps/quant-web/src/example.ts",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "unknown_requested_operation"


@pytest.mark.parametrize("categories", [["unknown"], ["code", "code"]])
def test_develop_merge_check_rejects_unknown_or_duplicate_categories(categories: list[str]) -> None:
    category_args = [item for category in categories for item in ("--change-category", category)]
    result = _run_develop_merge_check(
        "--lane", "2",
        "--operation", "develop_merge",
        *category_args,
        "apps/quant-web/src/example.ts",
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == "unknown_change_category"


@pytest.mark.parametrize(
    ("extra_args", "error_type"),
    [
        ([], "empty_diff"),
        (["/absolute/path.py"], "invalid_changed_path"),
        (["apps/../secrets.txt"], "invalid_changed_path"),
        (["./.env"], "invalid_changed_path"),
        (["./deploy/runtime.sh"], "invalid_changed_path"),
        ([r"deploy\runtime.sh"], "invalid_changed_path"),
        (["apps//quant-web/example.ts"], "invalid_changed_path"),
    ],
)
def test_develop_merge_check_rejects_invalid_path_inputs(
    extra_args: list[str],
    error_type: str,
) -> None:
    result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", *extra_args,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error_type"] == error_type


def test_develop_merge_check_rejects_empty_missing_and_conflicting_path_file(tmp_path: Path) -> None:
    empty = tmp_path / "empty.txt"
    empty.write_text("", encoding="utf-8")
    missing = tmp_path / "missing.txt"

    empty_result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", "--path-file", str(empty),
    )
    missing_result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", "--path-file", str(missing),
    )
    conflict_result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge",
        "--path-file", str(empty), "apps/quant-web/src/example.ts",
    )

    assert empty_result.returncode == 2
    assert json.loads(empty_result.stdout)["error_type"] == "empty_diff"
    assert missing_result.returncode == 2
    assert json.loads(missing_result.stdout)["error_type"] == "path_file_unavailable"
    assert conflict_result.returncode == 2
    assert json.loads(conflict_result.stdout)["error_type"] == "invalid_cli_arguments"


def test_develop_merge_check_rejects_non_utf8_and_nul_path_files(tmp_path: Path) -> None:
    non_utf8 = tmp_path / "non-utf8.txt"
    non_utf8.write_bytes(b"\xff\n")
    nul_path = tmp_path / "nul-path.txt"
    nul_path.write_text("apps/quant-web/src/\x00example.ts\n", encoding="utf-8")

    non_utf8_result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", "--path-file", str(non_utf8),
    )
    nul_result = _run_develop_merge_check(
        "--lane", "2", "--operation", "develop_merge", "--path-file", str(nul_path),
    )

    assert non_utf8_result.returncode == 2
    assert non_utf8_result.stderr == ""
    assert non_utf8_result.stdout.count("\n") == 1
    assert json.loads(non_utf8_result.stdout)["error_type"] == "path_file_unavailable"
    assert nul_result.returncode == 2
    assert json.loads(nul_result.stdout)["error_type"] == "invalid_changed_path"


def test_develop_merge_check_preserves_path_file_spaces_and_order(tmp_path: Path) -> None:
    path_file = tmp_path / "changed-paths.txt"
    path_file.write_text(
        "apps/quant-web/src/a file.ts\napps/quant-web/src/z.ts\n",
        encoding="utf-8",
    )

    result = _run_develop_merge_check(
        "--lane", "2",
        "--operation", "develop_merge",
        "--path-file", str(path_file),
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout)["paths"] == [
        "apps/quant-web/src/a file.ts",
        "apps/quant-web/src/z.ts",
    ]


def test_develop_merge_check_has_no_git_network_or_file_write_capability(tmp_path: Path) -> None:
    tree = ast.parse(POLICY_PATH.read_text(encoding="utf-8"))
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
    assert imported_roots.isdisjoint({"http", "requests", "socket", "subprocess", "urllib"})

    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    before = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))
    result = subprocess.run(
        [
            sys.executable, str(POLICY_PATH), "develop-merge-check",
            "--lane", "2", "--operation", "develop_merge",
            "apps/quant-web/src/example.ts",
        ],
        cwd=tmp_path,
        env={**os.environ, "PATH": str(empty_path), "PYTHONDONTWRITEBYTECODE": "1"},
        text=True,
        capture_output=True,
        check=False,
    )
    after = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*"))

    assert result.returncode == 0, result.stderr + result.stdout
    assert after == before


def test_task_pr_copy_stops_at_draft_without_claiming_manual_merge() -> None:
    source = TASK_SCRIPT.read_text(encoding="utf-8")

    assert "merge remains manual" not in source
    assert "Draft PR does not authorize merge" in source
    assert "expected-head merge commit" in source
    assert "gh pr merge" not in source


def test_workflow_rule_matches_exact_head_connector_contract() -> None:
    source = WORKFLOW_RULES.read_text(encoding="utf-8")

    assert "merge 仍由用户执行" not in source
    assert "Draft PR" in source
    assert "exact-head Gate" in source
    assert "Codex/GitHub Connector" in source
    assert "任务验收" in source
    assert "required CI" in source
    assert "PR head 与 reviewed head 一致" in source
    assert "mergeability 明确" in source
    assert "没有人工 Gate" in source


def test_development_doc_exposes_classifier_without_expanding_authority() -> None:
    source = DEVELOPMENT_DOC.read_text(encoding="utf-8")

    assert "develop-merge-check" in source
    assert "expected-head merge commit" in source
    assert "不是 executor、approval 或 receipt" in source
    assert "不得作为本策略任务自身的唯一批准依据" in source


def test_hook_denies_direct_protected_push_but_allows_controlled_entrypoint() -> None:
    """The Hook blocks a main push but does not block the allowlisted task entrypoint."""
    blocked = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin HEAD:main"}}),
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode == 0, blocked.stderr
    blocked_payload = json.loads(blocked.stdout)
    assert blocked_payload["hookSpecificOutput"]["permissionDecision"] == "deny"

    allowed = subprocess.run(
        [sys.executable, str(HOOK_PATH)],
        input=json.dumps(
            {
                "tool_name": "Bash",
                "tool_input": {
                    "command": "bash scripts/engineering/task-worktree.sh integrate --lane 2 --issue 123 --test-profile engineering --commit-message safe"
                },
            }
        ),
        text=True,
        capture_output=True,
        check=False,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert json.loads(allowed.stdout) == {}


def _task_fixture(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / "repo"
    engineering = repo / "scripts" / "engineering"
    engineering.mkdir(parents=True)
    for source in (POLICY_PATH, TASK_SCRIPT):
        target = engineering / source.name
        target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        target.chmod(0o755)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Automation tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "branch", "develop"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "-b", branch, "develop"], cwd=repo, check=True, capture_output=True, text=True)
    return repo


def test_integrate_dry_run_rejects_protected_branch_before_any_remote_action(tmp_path: Path) -> None:
    """The integration command must fail closed when invoked from develop."""
    repo = _task_fixture(tmp_path, "task-policy-probe")
    subprocess.run(["git", "checkout", "develop"], cwd=repo, check=True, capture_output=True, text=True)

    result = subprocess.run(
        [
            "bash", str(repo / "scripts" / "engineering" / "task-worktree.sh"), "integrate",
            "--lane", "2", "--issue", "123", "--test-profile", "engineering", "--commit-message", "probe", "--json",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "protected branch" in result.stderr


def test_integrate_dry_run_emits_remote_plan_without_running_it(tmp_path: Path) -> None:
    """A valid Lane 1 diff plans a draft PR but leaves local history unchanged."""
    repo = _task_fixture(tmp_path, "research/ISSUE-123-safe-experiment")
    experiment = repo / "experiments" / "safe" / "study.py"
    experiment.parent.mkdir(parents=True)
    experiment.write_text("result = 'research-only'\n", encoding="utf-8")
    before = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    result = subprocess.run(
        [
            "bash", str(repo / "scripts" / "engineering" / "task-worktree.sh"), "integrate",
            "--lane", "1", "--issue", "123", "--test-profile", "engineering", "--commit-message", "research pilot", "--json",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    payload = json.loads(result.stdout)
    assert payload["mode"] == "dry-run"
    assert payload["bound_facts"]["branch"] == "research/ISSUE-123-safe-experiment"
    assert any(command[:3] == ["gh", "pr", "create"] for command in payload["planned_commands"])
    assert not any(command[:3] == ["gh", "pr", "merge"] for command in payload["planned_commands"])
    assert subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip() == before


def test_integrate_classifies_staged_paths_before_planning_remote_actions(tmp_path: Path) -> None:
    """A staged Lane 3 path cannot hide behind an allowed untracked Lane 1 path."""
    repo = _task_fixture(tmp_path, "research/ISSUE-125-staged-path")
    forbidden = repo / "services" / "quant-api" / "app" / "strategies" / "formal.py"
    forbidden.parent.mkdir(parents=True)
    forbidden.write_text("formal = True\n", encoding="utf-8")
    subprocess.run(["git", "add", str(forbidden.relative_to(repo))], cwd=repo, check=True)
    allowed = repo / "experiments" / "safe" / "study.py"
    allowed.parent.mkdir(parents=True)
    allowed.write_text("result = 'research-only'\n", encoding="utf-8")

    result = subprocess.run(
        [
            "bash", str(repo / "scripts" / "engineering" / "task-worktree.sh"), "integrate",
            "--lane", "1", "--issue", "125", "--test-profile", "engineering", "--commit-message", "staged boundary", "--json",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "lane_one_path_forbidden" in result.stderr


def test_task_entrypoint_never_merges_or_requires_a_paid_github_protection_api() -> None:
    """The user owns the merge decision; a private repository needs no paid plan for PR creation."""
    source = TASK_SCRIPT.read_text(encoding="utf-8")

    assert "gh pr merge" not in source
    assert "branches/develop/protection" not in source
    assert "--draft --base develop" in source


def test_lane_pr_workflow_uses_immutable_pull_request_shas_for_its_diff() -> None:
    """A PR check must not race a moving develop ref while the PR is merging."""
    workflow = LANE_PR_WORKFLOW.read_text(encoding="utf-8")

    assert "git fetch origin develop" not in workflow
    assert "${{ github.event.pull_request.base.sha }}" in workflow
    assert "${{ github.event.pull_request.head.sha }}" in workflow


def test_lane_pr_workflow_keeps_generated_path_inventory_outside_the_checkout() -> None:
    """Preflight must not see the workflow's own generated path inventory as dirt."""
    workflow = LANE_PR_WORKFLOW.read_text(encoding="utf-8")

    assert 'changed_paths="$RUNNER_TEMP/changed_paths.txt"' in workflow
    assert "> changed_paths.txt" not in workflow


def test_lane_pr_workflow_uses_an_available_fail_closed_path_matcher() -> None:
    """Module detection must not silently skip verification when a matcher is absent."""
    workflow = LANE_PR_WORKFLOW.read_text(encoding="utf-8")

    assert "command -v grep >/dev/null" in workflow
    assert "grep -Eq '^apps/quant-web/'" in workflow
    assert "grep -Eq '^(services/quant-api|packages/quant-core)/'" in workflow
    assert "rg -q" not in workflow


def test_runtime_promotion_only_verifies_a_detached_runtime_and_never_runs_a_generic_gate(tmp_path: Path) -> None:
    """Runtime promotion is manually packet-bound; a generic --apply is forbidden."""
    repo = tmp_path / "repo"
    script_dir = repo / "scripts" / "engineering"
    script_dir.mkdir(parents=True)
    target = script_dir / "runtime-promotion.sh"
    target.write_text(RUNTIME_PROMOTION.read_text(encoding="utf-8"), encoding="utf-8")
    target.chmod(0o755)
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "tests@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Runtime tests"], cwd=repo, check=True)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "fixture"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "tag", "-a", "v1.2.3", "-m", "fixture release"], cwd=repo, check=True)
    runtime = tmp_path / "runtime"
    subprocess.run(["git", "clone", str(repo), str(runtime)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "--detach", "v1.2.3"], cwd=runtime, check=True, capture_output=True, text=True)
    packet = tmp_path / "approval.json"
    packet.write_text('{"approved": true}\n', encoding="utf-8")
    packet_hash = subprocess.run(
        ["shasum", "-a", "256", str(packet)], check=True, capture_output=True, text=True
    ).stdout.split()[0]
    command = [
        "bash", str(target), "verify", "--runtime-root", str(runtime), "--expected-tag", "v1.2.3",
        "--approval-packet", str(packet), "--approval-hash", packet_hash, "--json",
    ]

    verified = subprocess.run(command, cwd=repo, capture_output=True, text=True, check=False)

    assert verified.returncode == 0, verified.stderr + verified.stdout
    payload = json.loads(verified.stdout)
    assert payload["status"] == "verified_manual_gate_required"
    assert payload["bound_facts"]["runtime_detached"] is True
    blocked_command = [command[0], command[1], "promote", *command[3:-1], "--apply"]
    blocked = subprocess.run(blocked_command, cwd=repo, capture_output=True, text=True, check=False)
    assert blocked.returncode == 2
    assert "generic Runtime promotion is forbidden" in blocked.stderr
