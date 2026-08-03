"""Black-box and integration contracts for the read-only Execution Plan."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import ast
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENGINEERING = ROOT / "scripts" / "engineering"
CLI_PATH = ENGINEERING / "lean_matrix_team.py"


def _charter(**overrides: object) -> dict[str, object]:
    charter: dict[str, object] = {
        "schema_version": 1,
        "issue_number": 107,
        "task_id": "AI-TEAM-004",
        "kind": "feature",
        "slug": "execution-contracts",
        "title": "Build execution contracts",
        "value": "Keep later orchestration deterministic.",
        "goal": "Render one execution plan.",
        "current_facts": ["The Charter contract is frozen."],
        "lane": 2,
        "domains": [],
        "allowed_paths": ["scripts/engineering/lean_matrix/"],
        "forbidden_paths": ["Runtime is out of scope."],
        "acceptance": ["Contracts serialize deterministically."],
        "external_gates": [],
    }
    charter.update(overrides)
    return charter


def _import_kernel() -> tuple[object, object, object]:
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.contracts import TaskCharterV1
        from lean_matrix.git_readonly import resolve_base_sha
        from lean_matrix.planning import build_execution_plan
    finally:
        sys.path.pop(0)
    return TaskCharterV1, resolve_base_sha, build_execution_plan


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _isolated_cli_repo(root: Path) -> tuple[Path, Path, str]:
    """Create a checkout whose local origin/develop ref is fully test-controlled."""
    repo = root / "repo"
    isolated_scripts = repo / "scripts" / "engineering"
    isolated_scripts.mkdir(parents=True)
    isolated_cli = isolated_scripts / CLI_PATH.name
    shutil.copyfile(CLI_PATH, isolated_cli)
    shutil.copyfile(ENGINEERING / "task_workflow.py", isolated_scripts / "task_workflow.py")
    shutil.copytree(
        ENGINEERING / "lean_matrix",
        isolated_scripts / "lean_matrix",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )

    _git(repo, "init")
    _git(repo, "add", "scripts")
    _git(
        repo,
        "-c",
        "user.name=Lean Matrix Tests",
        "-c",
        "user.email=lean-matrix-tests@example.invalid",
        "commit",
        "-m",
        "test fixture",
    )
    expected_sha = _git(repo, "rev-parse", "HEAD^{commit}")
    _git(repo, "update-ref", "refs/remotes/origin/develop", expected_sha)
    return repo, isolated_cli, expected_sha


def test_execution_plan_matches_the_fixed_schema_without_legacy_dispatch_fields() -> None:
    """The new plan cannot leak the Charter-only mode or session_count fields."""
    TaskCharterV1, _, build_execution_plan = _import_kernel()
    charter = TaskCharterV1.from_mapping(_charter())

    plan = build_execution_plan(charter, base_ref="origin/develop", base_sha="1" * 40)

    assert plan.to_dict() == {
        "schema_version": 1,
        "status": "ok",
        "charter_digest": plan.charter_digest,
        "task": {
            "issue_number": 107,
            "task_id": "AI-TEAM-004",
            "branch": "feature/AI-TEAM-004-execution-contracts",
            "worktree": "/Volumes/扩展盘/GuiyiWorktrees/tasks/AI-TEAM-004-execution-contracts",
        },
        "base": {"ref": "origin/develop", "expected_sha": "1" * 40},
        "dispatch": {
            "model": "Terra",
            "reasoning_effort": "medium",
            "roles": [
                "ai-project-lead",
                "technical-lead",
                "implementer",
                "independent-quality-reviewer",
            ],
            "specialists": [],
            "independence_requirements": [
                "implementer and independent-quality-reviewer use separate contexts",
            ],
        },
        "scope": {
            "allowed_paths": ["scripts/engineering/lean_matrix/"],
            "forbidden_paths": ["Runtime is out of scope."],
        },
        "validation": {
            "test_profile": "all-safe",
            "required_checks": [
                "independent-review",
                "exact-head-ci",
                "diff-check",
                "secret-scan",
            ],
        },
        "transitions": [
            "task-create",
            "implementation-complete",
            "draft-pr",
            "review-complete",
            "develop-merge",
            "cleanup",
        ],
        "external_gates": [],
    }
    assert "mode" not in plan.to_dict()["dispatch"]
    assert "session_count" not in plan.to_dict()["dispatch"]


def test_lane_three_plan_preserves_sol_routing_and_the_required_external_gate() -> None:
    """A plan-only Lane 3 Charter cannot lose the human Gate that blocks real execution."""
    TaskCharterV1, _, build_execution_plan = _import_kernel()
    charter = TaskCharterV1.from_mapping(_charter(
        lane=3,
        domains=["quant-research", "backtest-audit"],
        external_gates=["User approves formal strategy semantics."],
    ))

    plan = build_execution_plan(charter, base_ref="origin/develop", base_sha="1" * 40)

    assert plan.dispatch.model == "Sol"
    assert plan.dispatch.reasoning_effort == "high"
    assert plan.dispatch.specialists == (
        "quant-research-specialist",
        "backtest-audit-specialist",
    )
    assert plan.external_gates == ("User approves formal strategy semantics.",)


def test_read_only_git_resolver_binds_the_local_origin_develop_without_writes(tmp_path: Path) -> None:
    """The resolver must read the exact remote-tracking commit and leave the repository byte-identical."""
    _, resolve_base_sha, _ = _import_kernel()
    _git(tmp_path, "init")
    _git(tmp_path, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", "base")
    expected_sha = _git(tmp_path, "rev-parse", "HEAD")
    _git(tmp_path, "update-ref", "refs/remotes/origin/develop", expected_sha)
    before = _snapshot(tmp_path)

    actual_sha = resolve_base_sha(tmp_path)

    assert actual_sha == expected_sha
    assert _snapshot(tmp_path) == before


def test_git_resolver_ignores_inherited_repository_redirection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GIT_DIR and related inherited state cannot redirect observation to another repository."""
    _, resolve_base_sha, _ = _import_kernel()
    target = tmp_path / "target"
    attacker = tmp_path / "attacker"
    target.mkdir()
    attacker.mkdir()
    for repo, message in ((target, "target"), (attacker, "attacker")):
        _git(repo, "init")
        _git(repo, "-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "--allow-empty", "-m", message)
        _git(repo, "update-ref", "refs/remotes/origin/develop", _git(repo, "rev-parse", "HEAD"))
    target_sha = _git(target, "rev-parse", "origin/develop^{commit}")
    attacker_sha = _git(attacker, "rev-parse", "origin/develop^{commit}")
    assert target_sha != attacker_sha
    monkeypatch.setenv("GIT_DIR", str(attacker / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(attacker))
    monkeypatch.setenv("GIT_OBJECT_DIRECTORY", str(attacker / ".git" / "objects"))

    assert resolve_base_sha(target) == target_sha


def test_git_resolver_uses_one_fixed_argv_shell_false_and_optional_locks_disabled() -> None:
    """The production adapter cannot accept an arbitrary Git command or enable shell execution."""
    _, resolve_base_sha, _ = _import_kernel()
    calls: list[tuple[object, dict[str, object]]] = []

    def runner(argv: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, stdout="a" * 40 + "\n", stderr="")

    assert resolve_base_sha(ROOT, runner=runner) == "a" * 40
    assert len(calls) == 1
    argv, kwargs = calls[0]
    assert argv == [
        "git", "-c", "core.fsmonitor=false", "rev-parse", "--verify", "origin/develop^{commit}",
    ]
    assert kwargs["shell"] is False
    assert kwargs["check"] is False
    assert kwargs["capture_output"] is True
    assert kwargs["text"] is True
    assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"  # type: ignore[index]
    assert "GIT_DIR" not in kwargs["env"]  # type: ignore[operator]
    assert "GIT_WORK_TREE" not in kwargs["env"]  # type: ignore[operator]


@pytest.mark.parametrize(
    ("result", "error_type"),
    [
        (subprocess.CompletedProcess([], 1, stdout="", stderr="missing"), "base_ref_unavailable"),
        (subprocess.CompletedProcess([], 0, stdout="a" * 40 + "\n" + "b" * 40 + "\n", stderr=""), "invalid_base_sha"),
        (subprocess.CompletedProcess([], 0, stdout="ABC\n", stderr=""), "invalid_base_sha"),
    ],
)
def test_git_resolver_fails_closed_without_fallback(
    result: subprocess.CompletedProcess[str], error_type: str,
) -> None:
    """A missing ref or malformed Git output cannot fall back to develop or HEAD."""
    _, resolve_base_sha, _ = _import_kernel()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    with pytest.raises(LeanMatrixError) as raised:
        resolve_base_sha(ROOT, runner=lambda *args, **kwargs: result)
    assert raised.value.error_type == error_type


def test_git_resolver_reports_missing_executable_without_traceback() -> None:
    """An unavailable Git binary must use the same stable blocked error boundary."""
    _, resolve_base_sha, _ = _import_kernel()
    sys.path.insert(0, str(ENGINEERING))
    try:
        from lean_matrix.errors import LeanMatrixError
    finally:
        sys.path.pop(0)

    def missing(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("git")

    with pytest.raises(LeanMatrixError) as raised:
        resolve_base_sha(ROOT, runner=missing)
    assert raised.value.error_type == "git_unavailable"


def test_plan_cli_emits_json_and_markdown_bound_to_current_origin_develop(tmp_path: Path) -> None:
    """Both formats must describe the same exact local base without creating a receipt."""
    repo, isolated_cli, expected_sha = _isolated_cli_repo(tmp_path)
    payload = json.dumps(_charter())
    json_result = subprocess.run(
        [sys.executable, str(isolated_cli), "plan", "--charter", "-", "--format", "json"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        cwd=repo,
    )
    markdown_result = subprocess.run(
        [sys.executable, str(isolated_cli), "plan", "--charter", "-", "--format", "markdown"],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        cwd=repo,
    )

    assert json_result.returncode == 0, json_result.stderr
    plan = json.loads(json_result.stdout)
    assert plan["base"] == {"ref": "origin/develop", "expected_sha": expected_sha}
    assert markdown_result.returncode == 0, markdown_result.stderr
    assert markdown_result.stdout.startswith("# Execution Plan\n")
    assert f"- Expected SHA: {expected_sha}" in markdown_result.stdout
    assert "This plan performs no transition or external operation." in markdown_result.stdout


def test_plan_cli_from_an_empty_cwd_creates_no_files_or_bytecode(tmp_path: Path) -> None:
    """Reading a plan from stdin cannot create a receipt, cache, or other cwd artifact."""
    repo, isolated_cli, _ = _isolated_cli_repo(tmp_path)
    empty_cwd = tmp_path / "empty-cwd"
    empty_cwd.mkdir()
    result = subprocess.run(
        [sys.executable, str(isolated_cli), "plan", "--charter", "-", "--format", "json"],
        input=json.dumps(_charter()),
        text=True,
        capture_output=True,
        check=False,
        cwd=empty_cwd,
    )

    assert result.returncode == 0, result.stderr
    assert list(empty_cwd.iterdir()) == []
    assert not any(path.name == "__pycache__" for path in repo.rglob("__pycache__"))


def test_charter_cli_does_not_require_or_invoke_git() -> None:
    """The compatible Charter path must remain usable when no Git executable is on PATH."""
    result = subprocess.run(
        [sys.executable, str(CLI_PATH), "charter", "--input", "-", "--format", "json"],
        input=json.dumps(_charter()),
        text=True,
        capture_output=True,
        check=False,
        cwd=ROOT,
        env={**os.environ, "PATH": ""},
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "ok"


def test_production_modules_limit_process_network_and_write_capabilities_to_fixed_adapters() -> None:
    """Only reviewed Git/task adapters and the ignored workspace may own their narrow capabilities."""
    package = ENGINEERING / "lean_matrix"
    imports_by_file: dict[str, set[str]] = {}
    forbidden_network = {
        "socket", "urllib", "requests", "http", "httpx", "aiohttp", "ftplib", "telnetlib",
    }
    forbidden_writes = {
        "write_text", "write_bytes", "touch", "mkdir", "unlink", "rmdir", "rename", "replace",
        "chmod", "symlink_to", "hardlink_to", "remove", "makedirs", "mkstemp", "mkdtemp",
        "copy", "copy2", "move", "rmtree",
    }

    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        imports_by_file[path.name] = imports
        assert not (imports & forbidden_network), path.name
        call_names = {
            node.func.id if isinstance(node.func, ast.Name) else node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, (ast.Name, ast.Attribute))
        }
        if path.name == "workspace.py":
            assert call_names & forbidden_writes
        else:
            assert not (call_names & forbidden_writes), path.name

    process_importers = {name for name, imports in imports_by_file.items() if "subprocess" in imports}
    assert process_importers == {
        "adapters.py",
        "git_readonly.py",
        "observing.py",
        "review_git.py",
    }
