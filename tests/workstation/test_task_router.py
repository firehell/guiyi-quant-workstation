from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

# pylint: disable=import-error


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
sys.path.insert(0, str(LIB_DIR))

from route_task import route_task  # noqa: E402
from task_meta import load_task_metadata, validate_task_metadata  # noqa: E402


def write_task(
    tmp_path: Path,
    name: str,
    *,
    task_id: str,
    work_level: str = "L1",
    body: str = "",
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    requested_tier: str = "auto",
    permissions: dict[str, bool] | None = None,
) -> Path:
    metadata = {
        "schema_version": 1,
        "task_id": task_id,
        "work_level": work_level,
        "github_issue": "待创建",
        "branch": f"feature/{task_id.lower()}",
        "worktree": "待 init_task_worktree.sh 回填",
        "status": "REQUIREMENT_READY",
        "owner": "test",
        "allowed_paths": allowed_paths or ["docs/example.md"],
        "forbidden_paths": forbidden_paths or [".env", "data/raw/"],
        "routing": {
            "requested_tier": requested_tier,
            "allow_auto_escalation": True,
            "max_auto_escalations": 1,
        },
        "permissions": {
            "production_access_allowed": False,
            "database_write_allowed": False,
            "external_network_allowed": False,
            "push_allowed": False,
            "merge_allowed": False,
            "deploy_allowed": False,
            "trading_execution_allowed": False,
        },
    }
    if permissions:
        metadata["permissions"].update(permissions)
    path = tmp_path / name
    path.write_text(
        "\n".join(
            [
                f"# {task_id}",
                "",
                "## 0.1 机器可读元数据",
                "",
                "```json",
                json.dumps(metadata, ensure_ascii=False, indent=2),
                "```",
                "",
                "## 5. 目标",
                "",
                body,
                "",
                "## 7. 涉及模块",
                "",
                "**允许修改**：",
                "",
                *[f"- `{item}`" for item in metadata["allowed_paths"]],
                "",
                "**禁止修改**：",
                "",
                *[f"- `{item}`" for item in metadata["forbidden_paths"]],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_task_metadata_machine_json_and_schema_are_loadable(tmp_path: Path) -> None:
    task = write_task(tmp_path, "task.md", task_id="TASK-META-001")

    metadata = load_task_metadata(task)
    schema = json.loads((REPO_ROOT / ".ai" / "schema" / "task.schema.json").read_text())

    assert metadata["task_id"] == "TASK-META-001"
    assert metadata["source"]["mode"] == "machine_json"
    assert validate_task_metadata(metadata) == []
    assert schema["properties"]["routing"]["properties"]["requested_tier"]["enum"] == [
        "auto",
        "fast",
        "standard",
        "deep",
        "critical",
    ]


def test_gitignore_keeps_task_schema_trackable() -> None:
    result = subprocess.run(
        ["git", "check-ignore", ".ai/schema/task.schema.json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1


def test_document_task_routes_fast(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "docs.md",
        task_id="TASK-DOCS",
        work_level="L0",
        body="文档和 README 小修。",
        allowed_paths=["docs/example.md"],
    )

    result = route_task(task, "plan")

    assert result["resolved_tier"] == "fast"
    assert result["profile"] == "guiyi-fast"


def test_regular_web_api_routes_standard(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "web-api.md",
        task_id="TASK-WEB-API",
        body="普通 Web API 单模块开发。",
        allowed_paths=["services/quant-api/app/api/example.py"],
    )

    result = route_task(task, "dev")

    assert result["resolved_tier"] == "standard"
    assert result["sandbox_mode"] == "workspace-write"


def test_runtime_recovery_routes_deep(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "runtime.md",
        task_id="TASK-RUNTIME",
        body="runtime scheduler recovery 修复。",
        allowed_paths=["scripts/runtime/recover.py"],
    )

    result = route_task(task, "fix")

    assert result["resolved_tier"] == "deep"
    assert "deep_runtime" in result["reason_codes"]


def test_indicator_kernel_routes_critical(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "indicator.md",
        task_id="TASK-INDICATOR",
        body="indicator kernel warm-up and NaN semantics.",
        allowed_paths=["packages/quant-core/guiyi_quant/indicators/ema.py"],
    )

    result = route_task(task, "review")

    assert result["resolved_tier"] == "critical"
    assert result["external_review_required"] is True


def test_database_schema_routes_critical(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "schema.md",
        task_id="TASK-SCHEMA",
        body="PostgreSQL schema and Alembic migration.",
        allowed_paths=["services/quant-api/alembic/versions/0001_example.py"],
    )

    result = route_task(task, "plan")

    assert result["resolved_tier"] == "critical"
    assert "critical_database_schema" in result["reason_codes"]


def test_requested_fast_cannot_downgrade_quant_core(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "downgrade.md",
        task_id="TASK-DOWNGRADE",
        body="用户请求 fast，但触及 quant-core 指标内核。",
        allowed_paths=["packages/quant-core/guiyi_quant/indicators/macd.py"],
        requested_tier="fast",
    )

    result = route_task(task, "dev")

    assert result["resolved_tier"] == "critical"
    assert "requested_tier_below_required" in result["reason_codes"]
    assert "requested_tier_fast_below_required_critical" in result["warnings"]


def test_test_and_result_stages_are_deterministic_no_model(tmp_path: Path) -> None:
    task = write_task(tmp_path, "test-stage.md", task_id="TASK-TEST-STAGE")

    test_result = route_task(task, "test")
    result_result = route_task(task, "result")

    assert test_result["profile"] == "deterministic_no_model"
    assert result_result["model_family"] == "deterministic_no_model"
    assert test_result["approval_policy"] == "deterministic_no_model"


def test_plan_and_review_are_always_read_only(tmp_path: Path) -> None:
    task = write_task(tmp_path, "readonly.md", task_id="TASK-READONLY")

    assert route_task(task, "plan")["sandbox_mode"] == "read-only"
    assert route_task(task, "review")["sandbox_mode"] == "read-only"


def test_dev_does_not_auto_grant_production_permissions(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "dev.md",
        task_id="TASK-DEV",
        body="普通单模块开发，不涉及生产权限。",
        allowed_paths=["apps/quant-web/src/views/Example.vue"],
    )

    result = route_task(task, "dev")

    assert result["sandbox_mode"] == "workspace-write"
    assert "production_access_not_granted_by_router" not in result["warnings"]
    assert result["approval_policy"] == "on-request"


def test_same_input_gets_identical_output(tmp_path: Path) -> None:
    task = write_task(tmp_path, "stable.md", task_id="TASK-STABLE")

    first = json.dumps(route_task(task, "plan"), ensure_ascii=False, sort_keys=True)
    second = json.dumps(route_task(task, "plan"), ensure_ascii=False, sort_keys=True)

    assert first == second


def test_shell_wrapper_outputs_json_for_task_file(tmp_path: Path) -> None:
    task = write_task(tmp_path, "shell.md", task_id="TASK-SHELL")

    result = subprocess.run(
        ["scripts/ai/route_task.sh", str(task), "plan", "--json"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    payload = json.loads(result.stdout)

    assert payload["task_id"] == "TASK-SHELL"
    assert payload["stage"] == "plan"
