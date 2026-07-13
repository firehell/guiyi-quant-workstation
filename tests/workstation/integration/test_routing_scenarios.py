from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

WORKSTATION_TESTS = Path(__file__).resolve().parents[1]
if str(WORKSTATION_TESTS) not in sys.path:
    sys.path.insert(0, str(WORKSTATION_TESTS))

from testkit import (
    make_scenario_repo,
    read_json,
    route_payload,
    run_bootstrap,
    run_collect,
    run_dispatch,
    run_writer_lock,
    write_approval,
    write_test_result,
)


def test_a_fast_doc_routes_fast_and_dev_workspace_write(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "fast_doc", "FAST_DOC")

    plan_route = route_payload(repo, "FAST_DOC", "plan")
    dev_result = run_dispatch(repo, "FAST_DOC", "dev", "--json", dry_run=True)

    assert plan_route["routing_tier"] == "economy"
    assert plan_route["external_review_required"] is False
    assert dev_result.returncode == 0, dev_result.stderr
    dev_route = json.loads(dev_result.stdout)
    assert dev_route["sandbox"] == "workspace-write"
    assert dev_route["external_review_required"] is False


def test_b_standard_api_routes_standard(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "standard_api", "STANDARD_API")

    route = route_payload(repo, "STANDARD_API", "plan")

    assert route["routing_tier"] == "balanced"
    assert route["resolved_profile"] == "plan-readonly"


def test_c_deep_runtime_routes_deep_with_auto_upgrade(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "deep_runtime", "DEEP_RUNTIME")

    route = route_payload(repo, "DEEP_RUNTIME", "plan")

    assert route["routing_tier"] == "deep"
    assert route["resolved_profile"] == "high-readonly"
    assert "tier_profile_upgrade:deep:high-readonly" in route["override_reason"]


def test_d_critical_indicator_requires_external_review(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "critical", "CRITICAL_INDICATOR", include_collect=True, git_commit=True)
    write_test_result(repo, "CRITICAL_INDICATOR")
    (repo / ".ai" / "results" / "CRITICAL_INDICATOR" / "review.md").write_text("No blocking findings.\n", encoding="utf-8")

    route = route_payload(repo, "CRITICAL_INDICATOR", "plan")
    collect = run_collect(repo, "CRITICAL_INDICATOR")

    assert route["routing_tier"] == "deep"
    assert route["external_review_required"] is True
    assert collect.returncode == 0, collect.stderr
    execution = read_json(repo / ".ai" / "results" / "CRITICAL_INDICATOR" / "execution.json")
    assert execution["external_review_required"] is True
    bundle = read_json(repo / ".ai" / "results" / "CRITICAL_INDICATOR" / "result_bundle.json")
    assert "DELIVERY_READY" not in bundle["next_action"]


def test_e_blocked_production_bootstrap_and_dispatch_fail(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "blocked_prod", "BLOCKED_PRODUCTION")
    source = repo / "source.env"
    source.write_text("APP_ENV=production\n", encoding="utf-8")

    bootstrap = run_bootstrap(
        repo,
        "--source",
        str(source),
        env={**os.environ, "APP_ENV": "production"},
    )
    assert bootstrap.returncode == 1
    assert "--confirm-production" in bootstrap.stderr

    write_approval(repo, "BLOCKED_PRODUCTION")
    dispatch = run_dispatch(repo, "BLOCKED_PRODUCTION", "dev", "--json", dry_run=True)
    assert dispatch.returncode != 0
    assert "Production Write Gate failed" in dispatch.stderr


def test_f_wrong_branch_is_blocked(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "wrong_branch", "WRONG_BRANCH")

    result = run_dispatch(repo, "WRONG_BRANCH", "plan", dry_run=True)

    assert result.returncode != 0
    assert "Branch Gate failed" in result.stderr


def test_g_locked_worktree_blocks_second_dev(tmp_path: Path) -> None:
    repo = make_scenario_repo(tmp_path / "locked", "LOCKED_WORKTREE")
    write_approval(repo, "LOCKED_WORKTREE")

    first = run_writer_lock(
        repo,
        "acquire",
        "--task-id",
        "OTHER-TASK",
        "--worktree",
        str(repo),
        "--branch",
        "feature/test",
        "--writer",
        "cursor",
        "--stage",
        "dev",
        "--pid",
        "424242",
    )
    assert first.returncode == 0, first.stderr

    second = run_dispatch(repo, "LOCKED_WORKTREE", "dev", dry_run=False)
    assert second.returncode != 0
    assert "lock" in second.stderr.lower() or "writer" in second.stderr.lower()


def test_h_missing_mount_fail_closed(tmp_path: Path) -> None:
    missing_mount = tmp_path / "external-disk"
    repo = make_scenario_repo(
        tmp_path / "missing_mount",
        "MISSING_MOUNT",
        missing_mount=str(missing_mount),
    )

    result = run_dispatch(repo, "MISSING_MOUNT", "result", dry_run=False)

    assert result.returncode == 1
    assert f"missing_mount:{missing_mount}" in result.stderr
    env_check = read_json(repo / ".ai" / "results" / "MISSING_MOUNT" / "env_check.json")
    assert env_check["ok"] is False


def test_i_forbidden_path_blocks_result(tmp_path: Path) -> None:
    repo = make_scenario_repo(
        tmp_path / "forbidden",
        "FORBIDDEN_PATH",
        include_collect=True,
        git_commit=True,
    )
    write_test_result(repo, "FORBIDDEN_PATH")
    (repo / ".env").write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")

    result = run_dispatch(repo, "FORBIDDEN_PATH", "result", dry_run=False)

    assert result.returncode == 0, result.stderr
    bundle = read_json(repo / ".ai" / "results" / "FORBIDDEN_PATH" / "result_bundle.json")
    execution = read_json(repo / ".ai" / "results" / "FORBIDDEN_PATH" / "execution.json")
    assert bundle["forbidden_path_check"].startswith("failed")
    assert ".env" in bundle["forbidden_path_check"]
    assert execution["status"] == "blocked"
