"""Exact repository facts that must remain true after governance cleanup."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

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


def test_governance_surface_has_one_executable_entrypoint() -> None:
    assert (ROOT / "scripts/engineering/secret_scan.py").is_file()
    assert all(not (ROOT / relative).exists() for relative in RETIRED_ASSETS)


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


def test_release_candidate_has_no_active_references_to_deleted_contracts() -> None:
    active_guidance = (
        ".agents/skills/futures-data/SKILL.md",
        "docs/superpowers/specs/2026-08-11-market-research-workspace-post-foundation-design.md",
        "docs/superpowers/plans/2026-08-11-market-research-workspace-post-foundation-p0.md",
    )
    retired_contracts = (
        "docs/tasks/GY-DATA-CORE-V2.md",
        "docs/superpowers/specs/2026-08-10-market-research-workspace-design.md",
        "docs/superpowers/plans/2026-08-10-market-research-workspace-p0.md",
    )

    for relative in active_guidance:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for retired in retired_contracts:
            assert retired not in text, f"{relative} still references {retired}"


def test_release_candidate_versions_are_consistently_1_0_0() -> None:
    pyproject = (ROOT / "services/quant-api/pyproject.toml").read_text(encoding="utf-8")
    api = (ROOT / "services/quant-api/app/main.py").read_text(encoding="utf-8")
    version_module = (ROOT / "services/quant-api/app/version.py").read_text(
        encoding="utf-8"
    )
    web = (ROOT / "apps/quant-web/package.json").read_text(encoding="utf-8")

    assert 'version = "1.0.0"' in pyproject
    assert 'APP_VERSION = "1.0.0"' in version_module
    assert "version=APP_VERSION" in api
    assert '"version": "1.0.0"' in web
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
