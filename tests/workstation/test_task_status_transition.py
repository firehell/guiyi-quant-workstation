from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

WORKSTATION_TESTS = Path(__file__).resolve().parent
if str(WORKSTATION_TESTS) not in sys.path:
    sys.path.insert(0, str(WORKSTATION_TESTS))

from testkit import REPO_ROOT  # noqa: E402

LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
if str(LIB_DIR) not in sys.path:
    sys.path.insert(0, str(LIB_DIR))

from task_status_transition import transition_task_status  # noqa: E402


def _write_yaml_task(repo: Path, status: str = "REQUIREMENT_READY") -> Path:
    task = repo / "docs" / "tasks" / "TASK-STATUS.md"
    task.parent.mkdir(parents=True, exist_ok=True)
    task.write_text(
        textwrap.dedent(
            f"""\
            ---
            kind: Task
            schema_version: "2.0"
            task_id: TASK-STATUS
            title: Status fixture
            status: {status}
            risk_level: R2
            work_level: L1
            approval_scope: [plan, code]
            allowed_paths:
              - scripts/ai/
            forbidden_paths:
              - .env*
            required_tests:
              - git diff --check
            branch: feature/test
            base_branch: main
            worktree: {repo}
            production_write_requested: false
            production_write_approved: false
            ---

            # TASK-STATUS

            ## 0. 元信息

            | 字段 | 值 |
            |------|-----|
            | Task ID | TASK-STATUS |
            | Status | {status} |
            """
        ),
        encoding="utf-8",
    )
    return task


def test_transition_updates_yaml_status_and_markdown_compatibility(tmp_path: Path) -> None:
    task = _write_yaml_task(tmp_path)

    result = transition_task_status(
        task,
        "PLAN_READY",
        repo_root=tmp_path,
        stage="plan",
        expected_from=["REQUIREMENT_READY"],
    )

    text = task.read_text(encoding="utf-8")
    assert "status: PLAN_READY" in text
    assert "| Status | PLAN_READY |" in text
    assert result.changed is True
    record = json.loads((tmp_path / ".ai" / "results" / "TASK-STATUS" / "status_transition.json").read_text())
    assert record["last_transition"]["from_status"] == "REQUIREMENT_READY"
    assert record["last_transition"]["to_status"] == "PLAN_READY"


def test_transition_is_idempotent(tmp_path: Path) -> None:
    task = _write_yaml_task(tmp_path, status="PLAN_READY")

    result = transition_task_status(
        task,
        "PLAN_READY",
        repo_root=tmp_path,
        stage="plan",
        expected_from=["REQUIREMENT_READY", "PLAN_READY"],
    )

    assert result.changed is False
    assert result.idempotent is True


def test_transition_rejects_invalid_jump(tmp_path: Path) -> None:
    task = _write_yaml_task(tmp_path, status="PLAN_READY")

    try:
        transition_task_status(task, "EXECUTING", repo_root=tmp_path)
    except Exception as exc:
        assert "Invalid status transition" in str(exc)
    else:
        raise AssertionError("invalid transition should fail")
