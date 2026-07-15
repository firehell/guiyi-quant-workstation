from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest

from testkit import copy_workstation_scripts, dispatch_env, init_git_repo, write_stubs


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
sys.path.insert(0, str(LIB_DIR))

from github_task_resolver import GitHubTaskError, IssueContext, parse_issue_fields, parse_issue_input  # noqa: E402


TASK_ID = "TASK-GH-001"
BRANCH = "task/ws-gh-001"
TASK_PATH = f"docs/tasks/{TASK_ID}.md"
TASK_ID_NAMESPACE_CASES = ["TASK-001", "WS-GH-001", "DEMO-001", "DATA-FINAL-001", "JM-001"]


def _task_text(*, task_id: str = TASK_ID, branch: str = BRANCH, issue: str = "#123", status: str = "REQUIREMENT_READY") -> str:
    return textwrap.dedent(
        f"""\
        ---
        kind: Task
        schema_version: "3.0"
        task_id: "{task_id}"
        title: "GitHub Issue-first bootstrap test"
        status: {status}
        risk_level: R1
        work_level: L1
        approval_scope: [plan, code]
        allowed_paths: ["scripts/ai/**", "tests/workstation/**"]
        forbidden_paths: [".env", "data/**"]
        required_tests: ["python3 -m pytest -q tests/workstation/test_github_task_resolver.py"]
        branch: "{branch}"
        base_branch: "main"
        github_issue: "{issue}"
        github_pr: "#5"
        created_by: "GPT"
        source: "github"
        ---

        # {task_id}

        ## 18. Tests

        ```bash
        python3 -m pytest -q tests/workstation/test_github_task_resolver.py
        ```
        """
    )


def _issue_body(
    *,
    task_id: str = TASK_ID,
    branch: str = BRANCH,
    task_path: str = TASK_PATH,
    pr: str = "#5",
    status: str = "DRAFT",
) -> str:
    return textwrap.dedent(
        f"""\
        GitHub Issue-first test.

        ## Task Metadata

        | Field | Value |
        | --- | --- |
        | Task ID | `{task_id}` |
        | TASK file path | `{task_path}` |
        | Task branch | `{branch}` |
        | Draft PR | `{pr}` |
        | Risk Level | `R1` |
        | Work Level | `L1` |
        | Approval Scope | `plan, code` |
        | Current Status | `{status}` |
        """
    )


def _issue_yaml_body(
    *,
    task_id: str = TASK_ID,
    branch: str = BRANCH,
    task_path: str = TASK_PATH,
    pr: str = "#5",
    status: str = "DRAFT",
) -> str:
    return textwrap.dedent(
        f"""\
        ---
        task_id: {task_id}
        task_file: {task_path}
        branch: {branch}
        draft_pr: "{pr}"
        status: {status}
        ---

        ## Task Metadata

        | Field | Value |
        | --- | --- |
        | Task ID | `TASK-GH-TABLE` |
        | TASK file path | `docs/tasks/TASK-GH-TABLE.md` |
        | Task branch | `task/table` |
        """
    )


def _write_gh_stub(bin_dir: Path, *, issue_body: str, task_text: str | None = None, state: str = "OPEN") -> None:
    bin_dir.mkdir(parents=True, exist_ok=True)
    issue_json = json.dumps(
        {
            "number": 123,
            "title": "Issue first bootstrap",
            "body": issue_body,
            "state": state,
            "url": "https://github.com/firehell/guiyi-quant-workstation/issues/123",
        },
        ensure_ascii=False,
    )
    encoded_task = base64.b64encode((task_text or _task_text()).encode("utf-8")).decode("ascii")
    api_json = json.dumps({"content": encoded_task})
    gh = bin_dir / "gh"
    gh.write_text(
        textwrap.dedent(
            f"""\
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "$1 $2 $3" == "issue view 123" ]]; then
              cat <<'JSON'
            {issue_json}
            JSON
              exit 0
            fi
            if [[ "$1" == "api" && "$2" == "repos/firehell/guiyi-quant-workstation/contents/{TASK_PATH}" ]]; then
              cat <<'JSON'
            {api_json}
            JSON
              exit 0
            fi
            echo "unexpected gh call: $*" >&2
            exit 9
            """
        ),
        encoding="utf-8",
    )
    gh.chmod(0o755)


def _commit(repo: Path, message: str = "commit") -> None:
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_bootstrap(repo: Path, *args: str, bin_dir: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "bootstrap_github_task.sh"), *args],
        cwd=repo,
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"},
        capture_output=True,
        text=True,
    )


def _prepare_issue_dispatch_repo(
    tmp_path: Path,
    *,
    task_text: str,
    issue_body: str,
) -> tuple[Path, Path, Path]:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True, text=True)

    seed = tmp_path / "seed"
    init_git_repo(seed, branch="main")
    copy_workstation_scripts(seed)
    (seed / ".gitignore").write_text(".ai/\n", encoding="utf-8")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _commit(seed, "main")
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=seed, check=True, capture_output=True, text=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", BRANCH], cwd=seed, check=True, capture_output=True, text=True)
    task_file = seed / TASK_PATH
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(task_text, encoding="utf-8")
    _commit(seed, "add task")
    subprocess.run(["git", "push", "-u", "origin", BRANCH], cwd=seed, check=True, capture_output=True, text=True)

    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), repo], check=True, capture_output=True, text=True)
    copy_workstation_scripts(repo)
    write_stubs(repo)
    _commit(repo, "bootstrap scripts")

    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, issue_body=issue_body)
    worktree_root = tmp_path / "worktrees"
    return repo, bin_dir, worktree_root


def _run_dispatch_issue(
    repo: Path,
    bin_dir: Path,
    worktree_root: Path,
    *args: str,
    dry_run: bool = False,
    include_gh: bool = True,
) -> subprocess.CompletedProcess[str]:
    env = dispatch_env(repo, dry_run=dry_run)
    env["GUIYI_WORKTREE_ROOT"] = str(worktree_root)
    if include_gh:
        env["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "dispatch_task.sh"), *args],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


def test_parse_issue_input_accepts_supported_forms() -> None:
    assert parse_issue_input("#123") == ("issue_number", 123)
    assert parse_issue_input("123") == ("issue_number", 123)
    assert parse_issue_input("TASK-GH-001") == ("task_id", "TASK-GH-001")
    assert parse_issue_input("https://github.com/firehell/guiyi-quant-workstation/issues/123") == ("issue_number", 123)


@pytest.mark.parametrize("task_id", TASK_ID_NAMESPACE_CASES)
def test_parse_issue_input_accepts_task_id_namespaces(task_id: str) -> None:
    assert parse_issue_input(task_id) == ("task_id", task_id)


def test_parse_issue_input_rejects_wrong_repository() -> None:
    with pytest.raises(GitHubTaskError, match="repository mismatch"):
        parse_issue_input("https://github.com/firehell/other/issues/123")


def test_parse_issue_fields_requires_stable_task_links() -> None:
    issue = IssueContext(number=123, title="", body=_issue_body(), state="OPEN", url="")
    fields = parse_issue_fields(issue)
    assert fields["task_id"] == TASK_ID
    assert fields["branch"] == BRANCH
    assert fields["task_file"] == TASK_PATH
    assert fields["draft_pr"] == "#5"

    with pytest.raises(GitHubTaskError, match="missing task metadata"):
        parse_issue_fields(IssueContext(number=123, title="", body="Task ID: TASK-X", state="OPEN", url=""))


@pytest.mark.parametrize("task_id", TASK_ID_NAMESPACE_CASES)
def test_parse_issue_fields_accepts_task_id_namespaces(task_id: str) -> None:
    issue = IssueContext(
        number=123,
        title="",
        body=_issue_body(task_id=task_id, task_path=f"docs/tasks/{task_id}.md"),
        state="OPEN",
        url="",
    )
    fields = parse_issue_fields(issue)
    assert fields["task_id"] == task_id
    assert fields["task_file"] == f"docs/tasks/{task_id}.md"


@pytest.mark.parametrize("task_id", ["123", "", "TASK/001", "WS GH 001", "TASK-001!"])
def test_parse_issue_fields_rejects_invalid_task_ids(task_id: str) -> None:
    issue = IssueContext(
        number=123,
        title="",
        body=_issue_body(task_id=task_id, task_path=f"docs/tasks/{task_id or 'empty'}.md"),
        state="OPEN",
        url="",
    )
    with pytest.raises(GitHubTaskError, match="missing required field|invalid Task ID"):
        parse_issue_fields(issue)


def test_parse_issue_fields_prefers_yaml_frontmatter_over_metadata_table() -> None:
    issue = IssueContext(number=123, title="", body=_issue_yaml_body(), state="OPEN", url="")
    fields = parse_issue_fields(issue)
    assert fields["task_id"] == TASK_ID
    assert fields["branch"] == BRANCH
    assert fields["task_file"] == TASK_PATH
    assert fields["draft_pr"] == "#5"


def test_parse_issue_fields_fails_when_metadata_table_missing_required_field() -> None:
    body = textwrap.dedent(
        f"""\
        ## Task Metadata

        | Field | Value |
        | --- | --- |
        | Task ID | `{TASK_ID}` |
        | TASK file path | `{TASK_PATH}` |
        | Draft PR | `#5` |
        | Current Status | `DRAFT` |
        """
    )
    issue = IssueContext(number=123, title="", body=body, state="OPEN", url="")
    with pytest.raises(GitHubTaskError, match="missing required field\\(s\\): branch"):
        parse_issue_fields(issue)


def test_parse_issue_fields_fails_closed_on_legacy_issue_without_metadata() -> None:
    legacy_body = textwrap.dedent(
        """\
        Task ID: TASK-GH-001
        Branch: task/ws-gh-001
        TASK path: docs/tasks/TASK-GH-001.md
        """
    )
    issue = IssueContext(number=123, title="", body=legacy_body, state="OPEN", url="")
    with pytest.raises(GitHubTaskError, match="missing task metadata"):
        parse_issue_fields(issue)


def test_bootstrap_json_reports_legacy_issue_as_blocked(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo, branch="main")
    copy_workstation_scripts(repo)
    _commit(repo, "bootstrap scripts")

    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, issue_body="Task ID: TASK-GH-001\nBranch: task/ws-gh-001\n")

    result = _run_bootstrap(repo, "--issue", "#123", "--dry-run", "--json", bin_dir=bin_dir)

    assert result.returncode != 0
    payload = json.loads(result.stderr)
    assert payload["ok"] is False
    assert payload["status"] == "blocked"
    assert payload["reason"] == "missing task metadata"


def test_closed_issue_fails_closed() -> None:
    issue = IssueContext(number=123, title="", body=_issue_body(), state="CLOSED", url="")
    with pytest.raises(GitHubTaskError, match="not open"):
        parse_issue_fields(issue)


def test_dry_run_resolves_issue_and_remote_task_without_local_state(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo, branch="main")
    copy_workstation_scripts(repo)
    _commit(repo, "bootstrap scripts")

    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, issue_body=_issue_body(), task_text=_task_text())

    result = _run_bootstrap(repo, "--issue", "#123", "--dry-run", "--json", bin_dir=bin_dir)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["task_id"] == TASK_ID
    assert payload["issue_number"] == 123
    assert payload["pr_number"] == 5
    assert payload["branch"] == BRANCH
    assert payload["task_file"] == TASK_PATH
    assert payload["status"] == "REQUIREMENT_READY"
    assert payload["dry_run"] is True
    assert "dispatch_task.sh TASK-GH-001 plan" in payload["next_command"]
    assert not (repo / ".ai" / "task-runtime" / f"{TASK_ID}.json").exists()


def test_bootstrap_fetches_branch_creates_worktree_and_writes_runtime(tmp_path: Path) -> None:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", remote], check=True, capture_output=True, text=True)

    seed = tmp_path / "seed"
    init_git_repo(seed, branch="main")
    (seed / "README.md").write_text("seed\n", encoding="utf-8")
    _commit(seed, "main")
    subprocess.run(["git", "remote", "add", "origin", str(remote)], cwd=seed, check=True, capture_output=True, text=True)
    subprocess.run(["git", "push", "-u", "origin", "main"], cwd=seed, check=True, capture_output=True, text=True)
    subprocess.run(["git", "checkout", "-b", BRANCH], cwd=seed, check=True, capture_output=True, text=True)
    task_file = seed / TASK_PATH
    task_file.parent.mkdir(parents=True, exist_ok=True)
    task_file.write_text(_task_text(), encoding="utf-8")
    _commit(seed, "add task")
    subprocess.run(["git", "push", "-u", "origin", BRANCH], cwd=seed, check=True, capture_output=True, text=True)

    repo = tmp_path / "repo"
    subprocess.run(["git", "clone", str(remote), repo], check=True, capture_output=True, text=True)
    copy_workstation_scripts(repo)
    _commit(repo, "bootstrap scripts")

    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, issue_body=_issue_body())
    worktree_root = tmp_path / "worktrees"
    result = _run_bootstrap(repo, "--issue", "123", "--json", "--worktree-root", str(worktree_root), bin_dir=bin_dir)

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    worktree = Path(payload["worktree"])
    assert payload["dry_run"] is False
    assert worktree.is_dir()
    assert (worktree / TASK_PATH).is_file()
    current_branch = subprocess.check_output(["git", "branch", "--show-current"], cwd=worktree, text=True).strip()
    assert current_branch == BRANCH

    runtime = json.loads((repo / ".ai" / "task-runtime" / f"{TASK_ID}.json").read_text(encoding="utf-8"))
    assert runtime["task_id"] == TASK_ID
    assert runtime["worktree"] == str(worktree)
    assert runtime["local_branch"] == BRANCH
    assert runtime["issue_number"] == 123
    assert runtime["pr_number"] == 5


def test_dry_run_fails_closed_on_task_schema_mismatch(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    init_git_repo(repo, branch="main")
    copy_workstation_scripts(repo)
    _commit(repo, "bootstrap scripts")

    bin_dir = tmp_path / "bin"
    _write_gh_stub(bin_dir, issue_body=_issue_body(), task_text=_task_text(branch="task/other"))

    result = _run_bootstrap(repo, "--issue", "123", "--dry-run", "--json", bin_dir=bin_dir)
    assert result.returncode != 0
    assert "Branch mismatch" in result.stderr


def test_dispatch_accepts_issue_input_and_runs_plan_through_existing_gates(tmp_path: Path) -> None:
    repo, bin_dir, worktree_root = _prepare_issue_dispatch_repo(
        tmp_path,
        task_text=_task_text(),
        issue_body=_issue_body(),
    )

    result = _run_dispatch_issue(repo, bin_dir, worktree_root, "#123", "plan", "--json")

    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["resolved_from_issue"] is True
    assert payload["github_remote_status"] == "verified"
    assert payload["task_id"] == TASK_ID
    assert payload["stage"] == "plan"
    assert payload["issue_number"] == 123
    assert (worktree_root / "gh-001").is_dir()
    assert "codex_plan.sh --task TASK-GH-001" in (repo / ".ai" / "stub_calls.log").read_text(encoding="utf-8")


def test_dispatch_issue_input_does_not_bypass_approval_gate(tmp_path: Path) -> None:
    repo, bin_dir, worktree_root = _prepare_issue_dispatch_repo(
        tmp_path,
        task_text=_task_text(status="APPROVED_DEV"),
        issue_body=_issue_body(status="APPROVED"),
    )

    result = _run_dispatch_issue(repo, bin_dir, worktree_root, "123", "dev", "--json")

    assert result.returncode != 0
    assert "Approval missing" in result.stderr
    assert not (repo / ".ai" / "stub_calls.log").exists()


def test_dispatch_issue_input_blocks_tampered_issue_body(tmp_path: Path) -> None:
    repo, bin_dir, worktree_root = _prepare_issue_dispatch_repo(
        tmp_path,
        task_text=_task_text(),
        issue_body=_issue_body(task_id="TASK-GH-TAMPERED"),
    )

    result = _run_dispatch_issue(repo, bin_dir, worktree_root, "#123", "plan", "--json")

    assert result.returncode != 0
    assert "TASK ID mismatch" in result.stderr


def test_dispatch_issue_input_fails_when_remote_branch_missing(tmp_path: Path) -> None:
    repo, bin_dir, worktree_root = _prepare_issue_dispatch_repo(
        tmp_path,
        task_text=_task_text(),
        issue_body=_issue_body(branch="task/missing"),
    )

    result = _run_dispatch_issue(repo, bin_dir, worktree_root, "#123", "plan", "--json")

    assert result.returncode != 0
    assert "git fetch origin task/missing failed" in result.stderr


def test_dispatch_issue_offline_uses_existing_runtime_and_marks_remote_unknown(tmp_path: Path) -> None:
    repo, bin_dir, worktree_root = _prepare_issue_dispatch_repo(
        tmp_path,
        task_text=_task_text(),
        issue_body=_issue_body(),
    )
    first = _run_dispatch_issue(repo, bin_dir, worktree_root, "#123", "plan", "--json")
    assert first.returncode == 0, first.stderr

    second = _run_dispatch_issue(repo, bin_dir, worktree_root, "#123", "status", "--offline", "--json", include_gh=False)

    assert second.returncode == 0, second.stderr
    payload = json.loads(second.stdout)
    assert payload["task_id"] == TASK_ID
    assert payload["github_remote_status"] == "unknown"
    assert payload["resolved_from_issue"] is True
