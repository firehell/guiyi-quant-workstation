"""Exact repository facts that must remain true after governance cleanup."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

MAIN_FORCE_MIRROR_V0_SOURCE_SHA256 = (
    "0f5b10db28d485c000846d721010efd3f1042aa7e4dae90fa479946539b5f503"
)

RETIRED_ASSETS = (
    "Makefile",
    ".github/workflows/optional-ci.yml",
    "docs/PERSONAL_DEVELOPMENT_WORKFLOW.md",
    "scripts/engineering/personal_workflow.py",
    "scripts/engineering/preflight.ps1",
    "scripts/engineering/reference_closure.py",
    "scripts/engineering/release-tag.ps1",
    "scripts/engineering/replacement_gate.py",
    "scripts/engineering/repository_consistency.py",
    "scripts/engineering/script_disposition.py",
    "scripts/engineering/secret-scan.ps1",
    "scripts/engineering/validate.ps1",
    "scripts/dev/dev-up.sh",
    "scripts/dev/dev-down.sh",
    "scripts/dev/dev-status.sh",
    "scripts/dev/dev-healthcheck.sh",
    "scripts/ops/macos/post-reboot-verify.sh",
    "scripts/ops/linux/server-status.sh",
    "deploy/systemd/guiyi-quant-api.service",
    "deploy/systemd/guiyi-quant.env.example",
    "deploy/systemd/guiyi-quant.target",
)

ACTIVE_CANONICAL = (
    "AGENTS.md",
    "STATUS.md",
    "PROJECT_SOURCE.md",
    "DECISIONS.md",
    "TESTING.md",
    "docs/DEVELOPMENT.md",
    "docs/ARCHITECTURE.md",
    "docs/DATA_CENTER.md",
    "openspec/specs/canonical-market-storage/spec.md",
    "openspec/specs/data-foundation-metadata/spec.md",
    "openspec/specs/historical-data-maintenance/spec.md",
    "openspec/specs/market-series-query/spec.md",
)

RETIRED_AI_ASSISTANCE = (
    ".agents/skills/futures-strategy",
    ".agents/skills/quant-safety-review",
    ".agents/skills/risk-center",
    ".codex/agents/risk-reviewer.toml",
)

ACTIVE_PROJECT_SKILLS = {
    "database-modeling",
    "docs-product-manager",
    "futures-data",
    "git-commit-workflow",
    "market-kline-workbench",
    "project-governor",
    "quant-backend",
    "quant-frontend",
    "testing-quality",
    "ui-bugfix",
}

ACTIVE_CODEX_REVIEWERS = {
    "architecture-reviewer.toml",
    "frontend-reviewer.toml",
    "product-reviewer.toml",
}

CURSOR_OPENSPEC_COMMANDS = {
    "opsx-apply.md",
    "opsx-archive.md",
    "opsx-explore.md",
    "opsx-propose.md",
    "opsx-sync.md",
    "opsx-update.md",
}


def test_governance_surface_has_one_executable_entrypoint() -> None:
    assert (ROOT / "scripts/engineering/secret_scan.py").is_file()
    assert all(not (ROOT / relative).exists() for relative in RETIRED_ASSETS)


def test_project_assistance_matches_the_active_market_architecture() -> None:
    assert all(not (ROOT / relative).exists() for relative in RETIRED_AI_ASSISTANCE)
    assert {
        path.parent.name for path in (ROOT / ".agents/skills").glob("*/SKILL.md")
    } == ACTIVE_PROJECT_SKILLS
    assert {
        path.name for path in (ROOT / ".codex/agents").glob("*.toml")
    } == ACTIVE_CODEX_REVIEWERS
    assert not (ROOT / ".cursor/skills").exists()
    assert {
        path.name for path in (ROOT / ".cursor/commands").glob("opsx-*.md")
    } == CURSOR_OPENSPEC_COMMANDS
    guidance = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "项目辅助只服务当前 active 架构" in guidance
    assert "每项任务默认主 agent，最多增加一个必要的 specialist 或 reviewer" in guidance


def test_active_canonical_has_no_retired_entrypoint_references() -> None:
    for relative in ACTIVE_CANONICAL:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for retired in RETIRED_ASSETS:
            assert retired not in text, f"{relative} still references {retired}"


def test_current_architecture_facts_are_explicit() -> None:
    architecture = (ROOT / "docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    project = (ROOT / "PROJECT_SOURCE.md").read_text(encoding="utf-8")
    status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
    data_contract = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in ACTIVE_CANONICAL
        if relative.startswith("openspec/specs/")
    )

    assert "MarketDataService" in architecture
    assert "HistoricalDataManager" in architecture
    assert "MainForceMirrorFuturesResearchService" in architecture
    assert "RQData" in architecture
    assert "auto_order=false" in project
    assert "active 60" in status
    for fact in (
        "DatasetKey",
        "八表 active 模型",
        "最小月度 Catalog",
        "actual_dominant",
        "schema、identity、主键单调唯一、OHLCV、session/frequency、coverage 和物理可读性",
    ):
        assert fact in data_contract


def test_futures_mirror_production_sources_have_no_test_only_injection() -> None:
    chart = (
        ROOT / "apps/quant-web/src/components/kline/KlineChart.vue"
    ).read_text(encoding="utf-8")

    assert "__GUIYI_TEST_ALERT_MARKERS__" not in chart


def test_futures_mirror_shadow_uses_a_static_kernel_dependency() -> None:
    service = (
        ROOT
        / "services/quant-api/app/market_data/main_force_mirror_futures_research_service.py"
    ).read_text(encoding="utf-8")

    assert "import importlib" not in service
    assert "_load_main_force_mirror_futures_kernel" not in service


def test_main_force_mirror_v0_runtime_source_is_frozen() -> None:
    source = (
        ROOT / "packages/quant-core/guiyi_quant/indicators/main_force_mirror.py"
    ).read_bytes()

    assert hashlib.sha256(source).hexdigest() == MAIN_FORCE_MIRROR_V0_SOURCE_SHA256


def test_retired_application_surfaces_are_not_restored() -> None:
    forbidden_paths = (
        "services/quant-api/app/worker.py",
        "services/quant-api/app/queue.py",
        "apps/quant-web/src/types/common.ts",
        "apps/quant-web/package-lock.json",
    )
    assert all(not (ROOT / relative).exists() for relative in forbidden_paths)


def test_public_websocket_route_matches_market_api_contract() -> None:
    healthcheck = (ROOT / "scripts/ops/network/public-healthcheck.sh").read_text(
        encoding="utf-8"
    )
    nginx = (ROOT / "deploy/nginx/guiyi-quant.conf").read_text(encoding="utf-8")

    assert "/api/v1/market/ws?" in healthcheck
    assert "/ws/signals" not in healthcheck
    assert "proxy_set_header Upgrade $http_upgrade;" in nginx
    assert 'proxy_set_header Connection "upgrade";' in nginx
    assert "location /ws/" not in nginx


def test_release_versions_are_consistent() -> None:
    pyproject = tomllib.loads(
        (ROOT / "services/quant-api/pyproject.toml").read_text(encoding="utf-8")
    )
    lock = tomllib.loads(
        (ROOT / "services/quant-api/uv.lock").read_text(encoding="utf-8")
    )
    api = (ROOT / "services/quant-api/app/main.py").read_text(encoding="utf-8")
    version_module = ast.parse(
        (ROOT / "services/quant-api/app/version.py").read_text(encoding="utf-8")
    )
    web = json.loads(
        (ROOT / "apps/quant-web/package.json").read_text(encoding="utf-8")
    )

    lock_packages = [
        package
        for package in lock["package"]
        if package["name"] == "quant-api"
        and package.get("source") == {"editable": "."}
    ]
    app_version_assignments = [
        node.value.value
        for node in version_module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "APP_VERSION"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    ]

    assert len(lock_packages) == 1
    assert len(app_version_assignments) == 1
    versions = {
        pyproject["project"]["version"],
        lock_packages[0]["version"],
        app_version_assignments[0],
        web["version"],
    }

    assert len(versions) == 1
    assert re.fullmatch(r"\d+\.\d+\.\d+", versions.pop())
    assert "version=APP_VERSION" in api
    assert '"version": APP_VERSION' in api


def test_release_candidate_excludes_private_sources_and_retired_ai_guidance() -> None:
    tracked_private_sources = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", "private_sources"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert tracked_private_sources == ""
    git_workflow = (ROOT / ".agents/skills/git-commit-workflow/SKILL.md").read_text(
        encoding="utf-8"
    )
    assert "AI Agent 默认不允许 push" not in git_workflow
    assert "git pull --rebase" not in git_workflow

    architecture_reviewer = (ROOT / ".codex/agents/architecture-reviewer.toml").read_text(
        encoding="utf-8"
    )
    frontend_reviewer = (ROOT / ".codex/agents/frontend-reviewer.toml").read_text(
        encoding="utf-8"
    )
    governor = (ROOT / ".agents/skills/project-governor/SKILL.md").read_text(
        encoding="utf-8"
    )
    kline = (ROOT / ".agents/skills/market-kline-workbench/SKILL.md").read_text(
        encoding="utf-8"
    )

    for retired_phrase in ("高频行情", "回测计算是否支持并行化", "交易接口是否有环境隔离"):
        assert retired_phrase not in architecture_reviewer
    for retired_phrase in ("资金曲线", "回撤曲线", "策略、回测、复盘闭环"):
        assert retired_phrase not in frontend_reviewer
    assert "数据 -> 策略 -> 回测 -> 报告 -> 复盘 -> 信号" not in governor
    assert "信号 marker" not in kline

    all_project_skills = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / ".agents/skills").glob("*/SKILL.md"))
    )
    for retired_phrase in (
        "uv run python -m alembic upgrade head",
        "把 V1.5/V2/V3 功能塞进 V1",
        "、`app/models/market_tables.py`。",
        "已卸（勿当现行页面）：Dashboard、数据中心、策略中心、回测任务/报告、信号扫描、复盘中心、系统设置、Live 模式",
    ):
        assert retired_phrase not in all_project_skills
