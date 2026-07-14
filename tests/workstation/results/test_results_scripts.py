from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import textwrap


REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_ID = "TASK-RESULTS"


def test_failed_tests_block_execution_status(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    write_test_result(repo, exit_code=1, status="FAIL", command="git diff --check")

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    execution = read_json(repo / ".ai" / "results" / TASK_ID / "execution.json")
    bundle = read_json(repo / ".ai" / "results" / TASK_ID / "result_bundle.json")
    assert execution["status"] == "blocked"
    assert execution["tests"]["status"] == "failed"
    assert "tests failed" in execution["warnings"]
    assert "DELIVERY_READY" not in bundle["next_action"]


def test_forbidden_path_is_detected(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    (repo / ".env").write_text("SAFE_PLACEHOLDER=1\n", encoding="utf-8")

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    bundle = read_json(repo / ".ai" / "results" / TASK_ID / "result_bundle.json")
    assert bundle["forbidden_path_check"].startswith("failed")
    assert ".env" in bundle["forbidden_path_check"]


def test_secret_values_are_redacted(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    out_dir = repo / ".ai" / "results" / TASK_ID
    (out_dir / "commands_executed.tsv").write_text("1\techo token=abcdef1234567890\n", encoding="utf-8")
    (repo / "scripts" / "ai" / "generated_secret.sh").write_text(
        "password: verysecretvalue12345\n",
        encoding="utf-8",
    )

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    raw = (out_dir / "result_bundle.json").read_text(encoding="utf-8")
    bundle = json.loads(raw)
    assert "abcdef1234567890" not in raw
    assert "verysecretvalue12345" not in raw
    assert "[REDACTED]" in raw
    assert bundle["sensitive_data_check"].startswith("failed")


def test_result_stage_does_not_call_model(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = subprocess.run(
        [str(repo / "scripts" / "ai" / "route_task.sh"), TASK_ID, "result", "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    route = json.loads(result.stdout)
    assert route["calls_model"] is False
    assert route["sandbox"] == "none"
    assert route["command"] == ["scripts/ai/collect_result.sh", "--task", TASK_ID]


def test_review_target_conflict_fails_before_model_call(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = subprocess.run(
        [str(repo / "scripts" / "ai" / "codex_review.sh"), "--task", TASK_ID, "--uncommitted", "--base", "main"],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Review target conflict" in result.stderr
    assert not (repo / ".ai" / "results" / TASK_ID / "review.md").exists()


def test_critical_external_review_flag_is_retained(tmp_path: Path) -> None:
    repo = make_repo(tmp_path, critical=True)
    write_test_result(repo, exit_code=0, status="PASS", command="git diff --check")
    (repo / ".ai" / "results" / TASK_ID / "review.md").write_text("No blocking findings.\n", encoding="utf-8")

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    execution = read_json(repo / ".ai" / "results" / TASK_ID / "execution.json")
    assert execution["external_review_required"] is True
    assert "external review required" in execution["warnings"]


def test_execution_json_schema_is_stable(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    execution = read_json(repo / ".ai" / "results" / TASK_ID / "execution.json")
    expected_keys = {
        "schema_version",
        "task_id",
        "stage",
        "status",
        "resolved_profile",
        "reasoning_effort",
        "sandbox_mode",
        "started_at",
        "finished_at",
        "duration",
        "exit_code",
        "branch",
        "base_branch",
        "commit_before",
        "commit_after",
        "changed_files",
        "tests",
        "review_status",
        "warnings",
        "external_review_required",
        "approval_reference",
    }
    assert set(execution) == expected_keys
    assert execution["task_id"] == TASK_ID
    assert execution["stage"] == "result"
    assert (repo / ".ai" / "results" / TASK_ID / "execution_summary.md").exists()
    assert (repo / ".ai" / "results" / TASK_ID / "changed_files.txt").exists()
    assert (repo / ".ai" / "results" / TASK_ID / "diff_stat.txt").exists()


def make_repo(path: Path, *, critical: bool = False) -> Path:
    repo = path
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-b", "feature/test"], cwd=repo, check=True, capture_output=True, text=True)

    scripts_dir = repo / "scripts" / "ai"
    env_scripts_dir = repo / "scripts" / "env"
    lib_dir = scripts_dir / "lib"
    docs_dir = repo / "docs" / "tasks"
    for directory in [scripts_dir, env_scripts_dir, lib_dir, docs_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    for name in [
        "collect_result.sh",
        "make_delivery_summary.sh",
        "codex_review.sh",
        "route_task.sh",
        "_work_level_lib.sh",
        "_approve_lib.sh",
        "_evidence_lib.sh",
        "redact_evidence.sh",
    ]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / name, scripts_dir / name)
    for name in ["task_meta.py", "task_runtime.py", "route_task.py", "writer_lock.py", "result_bundler.py"]:
        shutil.copy2(REPO_ROOT / "scripts" / "ai" / "lib" / name, lib_dir / name)

    task_extra = "| Critical | true |\n" if critical else ""
    (docs_dir / f"{TASK_ID}.md").write_text(
        textwrap.dedent(
            f"""\
            # {TASK_ID}: Results Fixture

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | {TASK_ID} |
            | Work Level | L1 |
            | GitHub Issue | 待创建 |
            | Branch | feature/test |
            | Worktree | {repo} |
            | Status | TESTING |
            | Required Env | - |
            | Required Mounts | - |
            {task_extra}
            ## 7. 涉及模块

            **允许修改**：

            - `scripts/ai/`
            - `tests/workstation/`

            **禁止修改**：

            - `.env`
            - `data/raw/`

            ## 18. 测试清单

            ### 18.0 自动化测试命令

            ```bash
            git diff --check
            ```
            """
        ),
        encoding="utf-8",
    )

    (repo / "scripts" / "ai" / "fixture.sh").write_text("echo ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-m", "initial"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )

    out_dir = repo / ".ai" / "results" / TASK_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    write_test_result(repo, exit_code=0, status="PASS", command="git diff --check")
    return repo


def write_test_result(repo: Path, *, exit_code: int, status: str, command: str) -> None:
    out_dir = repo / ".ai" / "results" / TASK_ID
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "commands_executed.tsv").write_text(f"1\t{command}\n", encoding="utf-8")
    (out_dir / "test_results.tsv").write_text(f"1\t{exit_code}\t{status}\t{command}\n", encoding="utf-8")
    (out_dir / "skipped_tests.txt").write_text("", encoding="utf-8")


def run_collect(repo: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["GUIYI_SKIP_CODEX_ENV_CHECK"] = "1"
    return subprocess.run(
        [str(repo / "scripts" / "ai" / "collect_result.sh"), "--task", TASK_ID],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
    )


# ── WS-V2-007: Evidence index & statement classification ───────────

def test_evidence_index_generated(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    evidence_index_path = repo / ".ai" / "results" / TASK_ID / "evidence_index.json"
    assert evidence_index_path.exists(), f"evidence_index.json should exist, got: {list((repo / '.ai' / 'results' / TASK_ID).iterdir())}"
    idx = read_json(evidence_index_path)
    assert idx["schema_version"] == 1
    assert idx["total_files"] >= 1
    assert "entries" in idx
    for entry in idx["entries"]:
        assert "path" in entry
        assert "sha256_checksum" in entry
        assert "size_bytes" in entry


def test_statement_classification_in_bundle(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    bundle = read_json(repo / ".ai" / "results" / TASK_ID / "result_bundle.json")
    assert "statement_classifications" in bundle
    classifications = bundle["statement_classifications"]
    assert len(classifications) >= 1
    for c in classifications:
        assert "path" in c
        assert "classification" in c
        assert c["classification"] in {"fact", "inference", "unverified"}


def test_result_bundle_includes_evidence_and_classifications(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    out = repo / ".ai" / "results" / TASK_ID
    bundle = read_json(out / "result_bundle.json")
    # Bundle should include statement_classifications
    assert "statement_classifications" in bundle
    # evidence_index.json should be at the out_dir level
    idx_path = out / "evidence_index.json"
    assert idx_path.exists()


def test_secret_values_are_redacted_still(tmp_path: Path) -> None:
    """Verify existing redaction still works with new result_bundler module."""
    repo = make_repo(tmp_path)
    out_dir = repo / ".ai" / "results" / TASK_ID
    (out_dir / "commands_executed.tsv").write_text("1\techo token=abcdef1234567890\n", encoding="utf-8")
    (repo / "scripts" / "ai" / "generated_secret.sh").write_text(
        "password: verysecretvalue12345\n",
        encoding="utf-8",
    )

    result = run_collect(repo)

    assert result.returncode == 0, result.stderr
    raw = (out_dir / "result_bundle.json").read_text(encoding="utf-8")
    bundle = json.loads(raw)
    assert "abcdef1234567890" not in raw
    assert "verysecretvalue12345" not in raw
    assert "[REDACTED]" in raw
    assert bundle["sensitive_data_check"].startswith("failed")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
