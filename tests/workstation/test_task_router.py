from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# pylint: disable=import-error


REPO_ROOT = Path(__file__).resolve().parents[2]
LIB_DIR = REPO_ROOT / "scripts" / "ai" / "lib"
sys.path.insert(0, str(LIB_DIR))

from route_task import RouteError, resolve_route  # noqa: E402
from task_meta import parse_task_file  # noqa: E402


def write_task(
    tmp_path: Path,
    name: str,
    *,
    task_id: str,
    work_level: str = "L1",
    body: str = "",
    allowed_paths: list[str] | None = None,
    forbidden_paths: list[str] | None = None,
    task_type: str = "普通开发",
    critical: bool = False,
    model_profile: str = "balanced",
    production_write_requested: bool = False,
) -> Path:
    allowed = allowed_paths or ["docs/example.md"]
    forbidden = forbidden_paths or [".env", "data/raw/"]
    path = tmp_path / name
    path.write_text(
        "\n".join(
            [
                "---",
                "kind: Task",
                'schema_version: "2.0"',
                f'task_id: "{task_id}"',
                f'title: "{task_id} router fixture"',
                "status: REQUIREMENT_READY",
                "risk_level: R2",
                f"work_level: {work_level}",
                "approval_scope: [plan, code]",
                "allowed_paths:",
                *[f'  - "{item}"' for item in allowed],
                "forbidden_paths:",
                *[f'  - "{item}"' for item in forbidden],
                'required_tests: ["git diff --check"]',
                f'branch: "feature/{task_id.lower()}"',
                'base_branch: "main"',
                'github_issue: ""',
                'github_pr: ""',
                f"model_profile: {model_profile}",
                f"critical: {str(critical).lower()}",
                f"production_write_requested: {str(production_write_requested).lower()}",
                "---",
                "",
                f"# {task_id}",
                "",
                "## 2. 任务类型",
                task_type,
                "",
                "## 5. 目标",
                "",
                body,
                "",
                "## 7. 涉及模块",
                "",
                "**允许修改**：",
                "",
                *[f"- `{item}`" for item in allowed],
                "",
                "**禁止修改**：",
                "",
                *[f"- `{item}`" for item in forbidden],
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_task_metadata_yaml_frontmatter_and_schema_are_loadable(tmp_path: Path) -> None:
    task = write_task(tmp_path, "task.md", task_id="TASK-META-001")

    metadata = parse_task_file(task, repo_root=REPO_ROOT)
    schema = json.loads((REPO_ROOT / "configs" / "ai" / "schemas" / "task-v2.0.schema.json").read_text())

    assert metadata.task_id == "TASK-META-001"
    assert metadata.schema_version == "2.0"
    assert metadata.model_profile == "balanced"
    assert schema["properties"]["model_profile"]["enum"] == [
        "economy",
        "balanced",
        "deep",
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
        task_type="文档修改",
    )

    result = resolve_route(task, "plan", repo_root=REPO_ROOT)

    assert result["routing_tier"] == "fast"
    assert result["resolved_profile"] == "plan-readonly"
    assert result["sandbox"] == "read-only"


def test_regular_web_api_routes_standard(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "web-api.md",
        task_id="TASK-WEB-API",
        body="普通 Web API 单模块开发。",
        allowed_paths=["services/quant-api/app/api/example.py"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["routing_tier"] == "standard"
    assert result["resolved_profile"] == "dev-workspace-write"
    assert result["sandbox"] == "workspace-write"
    assert result["approval_required"] is True
    assert result["write_lock_required"] is True


def test_runtime_recovery_routes_deep(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "runtime.md",
        task_id="TASK-RUNTIME",
        body="runtime scheduler recovery 修复。",
        allowed_paths=["scripts/runtime/recover.py"],
    )

    result = resolve_route(task, "fix", repo_root=REPO_ROOT)

    assert result["routing_tier"] == "deep"
    assert result["resolved_profile"] == "high-workspace-write"
    assert result["override_reason"] == "tier_profile_upgrade:deep:high-workspace-write"


def test_indicator_kernel_routes_critical_with_external_review(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "indicator.md",
        task_id="TASK-INDICATOR",
        body="indicator kernel warm-up and NaN semantics.",
        allowed_paths=["packages/quant-core/guiyi_quant/indicators/ema.py"],
        task_type="指标开发",
        critical=True,
    )

    result = resolve_route(task, "review", repo_root=REPO_ROOT)

    assert result["routing_tier"] == "critical"
    assert result["resolved_profile"] == "review-readonly"
    assert result["external_review_required"] is True


def test_database_schema_routes_critical_with_external_review(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "schema.md",
        task_id="TASK-SCHEMA",
        body="PostgreSQL schema and Alembic migration.",
        allowed_paths=["services/quant-api/alembic/versions/0001_example.py"],
        task_type="数据库",
        critical=True,
    )

    result = resolve_route(task, "plan", repo_root=REPO_ROOT)

    assert result["routing_tier"] == "critical"
    assert result["resolved_profile"] == "plan-readonly"
    assert result["external_review_required"] is True


def test_requested_profile_cannot_downgrade_deep_task(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "downgrade.md",
        task_id="TASK-DOWNGRADE",
        body="触及 quant-core 指标内核 warm-up 语义。",
        allowed_paths=["packages/quant-core/guiyi_quant/indicators/macd.py"],
        task_type="指标开发",
        critical=True,
    )

    with pytest.raises(RouteError, match="profile downgrade is not allowed"):
        resolve_route(task, "dev", repo_root=REPO_ROOT, requested_profile="plan-readonly")


def test_test_and_result_stages_are_deterministic_no_model(tmp_path: Path) -> None:
    task = write_task(tmp_path, "test-stage.md", task_id="TASK-TEST-STAGE")

    test_result = resolve_route(task, "test", repo_root=REPO_ROOT)
    result_result = resolve_route(task, "result", repo_root=REPO_ROOT)

    assert test_result["resolved_profile"] == "no-model"
    assert result_result["resolved_profile"] == "no-model"
    assert test_result["calls_model"] is False
    assert result_result["sandbox"] == "none"


def test_plan_and_review_are_always_read_only(tmp_path: Path) -> None:
    task = write_task(tmp_path, "readonly.md", task_id="TASK-READONLY")

    assert resolve_route(task, "plan", repo_root=REPO_ROOT)["sandbox"] == "read-only"
    assert resolve_route(task, "review", repo_root=REPO_ROOT)["sandbox"] == "read-only"


def test_dev_does_not_auto_grant_production_permissions(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "dev.md",
        task_id="TASK-DEV",
        body="普通单模块开发，不涉及外部写入。",
        allowed_paths=["apps/quant-web/src/views/Example.vue"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["sandbox"] == "workspace-write"
    assert result["production_write_requested"] is False
    assert result["production_write_approved"] is False
    assert result["approval_required"] is True


def test_docs_only_task_does_not_request_production_write(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "docs.md",
        task_id="TASK-DOCS",
        task_type="文档更新",
        body="只更新 WorkBuddy 文档，不执行生产写入。",
        allowed_paths=["docs/workflows/ai_delivery_workflow.md"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["production_write_requested"] is False


def test_negative_sentence_does_not_request_production_write(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "negative.md",
        task_id="TASK-NEGATIVE",
        body="禁止修改 production 配置，不执行生产数据库真实写入。",
        allowed_paths=["docs/tasks/TASK-NEGATIVE.md"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["production_write_requested"] is False


def test_database_migration_requests_production_write(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "migration.md",
        task_id="TASK-MIGRATION",
        task_type="database migration",
        body="Add an Alembic migration.",
        allowed_paths=["migrations/versions/001_add_table.py"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["production_write_requested"] is True


def test_production_deploy_requests_production_write(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "deploy.md",
        task_id="TASK-DEPLOY",
        task_type="production deploy",
        body="Deploy current release to production.",
        allowed_paths=["deploy/production/guiyi.toml"],
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["production_write_requested"] is True


def test_structured_production_write_requested_field(tmp_path: Path) -> None:
    task = write_task(
        tmp_path,
        "explicit.md",
        task_id="TASK-EXPLICIT-PROD",
        production_write_requested=True,
    )

    result = resolve_route(task, "dev", repo_root=REPO_ROOT)

    assert result["production_write_requested"] is True


def test_same_input_gets_identical_output(tmp_path: Path) -> None:
    task = write_task(tmp_path, "stable.md", task_id="TASK-STABLE")

    first_payload = resolve_route(task, "plan", repo_root=REPO_ROOT)
    second_payload = resolve_route(task, "plan", repo_root=REPO_ROOT)
    first_payload.pop("generated_at")
    second_payload.pop("generated_at")
    first = json.dumps(first_payload, ensure_ascii=False, sort_keys=True)
    second = json.dumps(second_payload, ensure_ascii=False, sort_keys=True)

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
