"""Unit contracts for impact classification and consistency scanning."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "engineering" / "repository_consistency.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("repository_consistency", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


consistency = _load_module()


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("docs/DEVELOPMENT.md", {"Docs"}),
        ("AGENTS.md", {"Docs"}),
        ("scripts/engineering/preflight.ps1", {"Engineering"}),
        ("tests/engineering/test_personal_workflow.py", {"Engineering"}),
        (".codex/rules/workflow.rules", {"Engineering"}),
        (".github/workflows/optional-ci.yml", {"Engineering"}),
        ("services/quant-api/app/main.py", {"Backend"}),
        ("apps/quant-web/src/pages/market/chart.vue", {"Web"}),
        ("services/quant-api/app/market_data/market_data_service.py", {"Backend", "DataCore"}),
        ("packages/quant-core/guiyi_quant/indicators/htdy_strict.py", {"Backend", "Strategy"}),
        ("services/quant-api/app/services/runtime_health.py", {"Backend", "Runtime"}),
        ("services/quant-api/alembic/versions/0001_init.py", {"Backend", "Migration"}),
    ],
)
def test_classify_changed_paths_maps_domains(path: str, expected: set[str]) -> None:
    domains = {domain.value for domain in consistency.classify_changed_paths([path])}
    assert expected <= domains


def test_docs_only_profile_selection() -> None:
    domains = consistency.classify_changed_paths(["docs/PERSONAL_DEVELOPMENT_WORKFLOW.md"])
    profiles = consistency.select_validation_profiles(domains)
    assert profiles == [consistency.ValidationDomain.DOCS]


def test_mixed_domains_select_deterministic_order() -> None:
    domains = consistency.classify_changed_paths(
        [
            "AGENTS.md",
            "scripts/engineering/validate.ps1",
            "apps/quant-web/package.json",
        ]
    )
    profiles = consistency.select_validation_profiles(domains)
    assert profiles == [
        consistency.ValidationDomain.DOCS,
        consistency.ValidationDomain.ENGINEERING,
        consistency.ValidationDomain.WEB,
    ]


def test_all_safe_profile_is_explicit() -> None:
    assert consistency.select_validation_profiles([], all_safe=True) == [
        consistency.ValidationDomain.ALL_SAFE
    ]


def test_preserve_unrelated_dirty_paths_detects_drift() -> None:
    drift = consistency.preserve_unrelated_dirty_paths(
        before_paths=["other/a.py", "task/b.py"],
        after_paths=["other/a.py", "task/b.py", "other/c.py"],
        task_scope=["task/b.py"],
    )
    assert drift == ("other/c.py",)


def test_preserve_unrelated_dirty_paths_stable_when_scope_only_changes() -> None:
    drift = consistency.preserve_unrelated_dirty_paths(
        before_paths=["other/a.py", "task/b.py"],
        after_paths=["other/a.py", "task/b.py", "task/c.py"],
        task_scope=["task/b.py", "task/c.py"],
    )
    assert drift == ()


def test_active_surface_scan_excludes_its_own_rule_source(tmp_path: Path) -> None:
    scanner = tmp_path / "scripts" / "engineering" / "repository_consistency.py"
    scanner.parent.mkdir(parents=True)
    scanner.write_text(
        'RETIRED_PATHS = ("docs/WORKTREE_RELEASE_WORKFLOW.md",)\n',
        encoding="utf-8",
    )

    assert scanner not in consistency._iter_active_surface_files(tmp_path)


@pytest.mark.parametrize(
    "clause",
    [
        "PR #145 merged commit abc123; this is a completed historical fact, not authorization.",
        "The historical receipt records the observed result and grants no future authority.",
        "Publication validates the Manifest digest, physical checksum, and row count.",
        "旧 packet/hash 只作为历史事实，不构成当前授权。",
    ],
)
def test_scan_allows_historical_and_integrity_facts(clause: str) -> None:
    assert not consistency.is_collaboration_blocker(clause)


@pytest.mark.parametrize(
    "clause",
    [
        "普通代码必须先创建 GitHub Issue 才能在 develop 开始。",
        "Only a task worktree may edit code; direct work on develop is forbidden.",
        "Approval packet hash is an authorization prerequisite for ordinary changes.",
        "Ordinary changes cannot be pushed to develop without required CI.",
        "Code changes require a pull request before local validation.",
    ],
)
def test_scan_rejects_authorization_predicates(clause: str) -> None:
    assert consistency.is_collaboration_blocker(clause)


def test_scan_active_surfaces_reports_findings_for_synthetic_tree(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "decisions").mkdir(parents=True)
    for relative in consistency.ACTIVE_CANONICAL_PATHS:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "personal develop workflow\n"
            "MarketDataService DatasetKey continuous actual_dominant\n"
            "物理完整性异常显式失败，不得静默回退。六项校验\n"
            "historical canonical and live observation 分离\n"
            "月分区以同文件系统临时文件原子替换 part.parquet\n"
            "失败时保留最后有效 canonical\n"
            "生产 DB 正式数据需要一次性执行意图\n"
            "auto_order=false 拒绝订单\n"
            "禁止未来函数 trading-related Decimal\n"
            "backtest strategy trade equity lineage\n"
            "HTDY original observation-only whitelist\n"
            "研究观察 不是交易指令\n"
            "数据、策略、回测、信号或通知语义变化时同一变更更新 deep canonical\n"
            "live Runtime 真实通知 默认关闭\n"
            "release/tag 不授权 Runtime/live\n"
            "repair、replay、backfill、migration 不补发\n"
            "缺失、异常、过期或不一致 保持关闭\n"
            "notification 研究观察 非交易指令\n"
            "不把结果扩写成 盈利 生产就绪\n"
            "凭据 token webhook 不得进入仓库\n"
            "外部输入 类型 格式 范围 允许值\n"
            "RQData staging validation Historical Canonical "
            "八表 Catalog/MainContractMap MarketDataService\n",
            encoding="utf-8",
        )
    (tmp_path / "docs" / "WORKTREE_RELEASE_WORKFLOW.md").write_text("old", encoding="utf-8")
    findings = consistency.scan_active_surfaces(tmp_path)
    types = {item.finding_type for item in findings}
    assert consistency.FindingType.RETAINED_RETIRED_ASSET in types
