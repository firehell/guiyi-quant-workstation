"""Exact repository facts that must remain true after governance cleanup."""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import tomllib
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


def _is_allowed_governance_document(relative: str) -> bool:
    parts = Path(relative).parts
    return (
        len(parts) == 4
        and parts[:2] == ("docs", "superpowers")
        and parts[2] in {"plans", "specs"}
        and Path(parts[3]).suffix == ".md"
    )


def _tracked_governance_documents() -> tuple[str, ...]:
    return tuple(
        subprocess.run(
            [
                "git",
                "-c",
                "core.fsmonitor=false",
                "ls-files",
                "docs/superpowers",
                "docs/tasks",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.splitlines()
    )


def test_governance_document_path_policy_is_narrow() -> None:
    allowed = (
        "docs/superpowers/plans/task-plan.md",
        "docs/superpowers/specs/task-design.md",
    )
    rejected = (
        "docs/tasks/task.md",
        "docs/superpowers/notes/task.md",
        "docs/superpowers/plans/archive/task-plan.md",
        "docs/superpowers/specs/archive/task-design.md",
        "docs/superpowers/plans/task-plan.txt",
    )

    assert all(_is_allowed_governance_document(relative) for relative in allowed)
    assert all(not _is_allowed_governance_document(relative) for relative in rejected)

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
    tracked_governance_docs = _tracked_governance_documents()
    assert not any(relative.startswith("docs/tasks/") for relative in tracked_governance_docs)
    assert all(
        _is_allowed_governance_document(relative)
        for relative in tracked_governance_docs
    )


def test_active_docs_and_cli_match_current_surfaces() -> None:
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    execution_review = (ROOT / "docs/EXECUTION_REVIEW.md").read_text(
        encoding="utf-8"
    )
    development = (ROOT / "docs/DEVELOPMENT.md").read_text(encoding="utf-8")
    backend_readme = (ROOT / "services/quant-api/README.md").read_text(
        encoding="utf-8"
    )
    project_source = (ROOT / "PROJECT_SOURCE.md").read_text(encoding="utf-8")
    core_readme = (ROOT / "packages/quant-core/README.md").read_text(
        encoding="utf-8"
    )

    assert "当前 production、Runtime、Scope 与待完成 Gate 只看 `STATUS.md`" in agents
    assert "WeCom" not in execution_review
    assert "v1.4 Runtime" not in execution_review
    assert "v1.4 release" not in execution_review
    assert "Lane 3" not in execution_review
    assert "G9 cleanup" not in development
    research_parser = importlib.import_module("app.guiyi_cli.research_parser")
    cli_main = importlib.import_module("app.guiyi_cli.main")
    parser = cli_main.build_parser()
    domain_action = next(
        action for action in parser._actions if action.dest == "domain"
    )
    research_subparser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_subparser._actions
        if action.dest == "research_command"
    )
    expected_commands = set(research_parser.RESEARCH_COMMAND_NAMES)
    assert set(command_action.choices) == expected_commands
    command_pattern = re.compile(r"`guiyi research ([a-z0-9-]+)(?:\s|`)")
    assert set(command_pattern.findall(backend_readme)) == expected_commands
    assert set(command_pattern.findall(project_source)) == expected_commands
    assert "当前 Web 仅 Market" not in core_readme


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


def test_architecture_convergence_canonicals_describe_only_retained_surface() -> None:
    canonical_paths = (
        "AGENTS.md",
        "STATUS.md",
        "PROJECT_SOURCE.md",
        "DECISIONS.md",
        "README.md",
        "TESTING.md",
        "docs/ARCHITECTURE.md",
        "docs/DEVELOPMENT.md",
        "docs/INDICATOR_KERNEL.md",
        "services/quant-api/README.md",
    )
    canonicals = {
        relative: (ROOT / relative).read_text(encoding="utf-8")
        for relative in canonical_paths
    }
    combined = "\n".join(canonicals.values())
    agents = canonicals["AGENTS.md"]
    project = canonicals["PROJECT_SOURCE.md"]
    status = canonicals["STATUS.md"]
    architecture = canonicals["docs/ARCHITECTURE.md"]
    indicator_kernel = canonicals["docs/INDICATOR_KERNEL.md"]
    backend_readme = canonicals["services/quant-api/README.md"]

    assert "一个 SuBing 产品" in project
    assert all(
        projection in project
        for projection in ("Daily Context", "Current Signal State", "Formal Event")
    )
    assert "operational universe × 七个正式周期" in project
    assert "symbol × frequency" in agents
    assert "无 | 苏冰 | 日进斗金参考回放 | 火天大有" in project
    assert "N Structure 与 raw JDJ Candidate 只保留在内部研究面" in project
    assert "Generic Robustness relationship metrics" in project
    assert "pending prospective OOS" in status
    assert "Alert Application Domain 仍只有 `alert_rules` 与 `alert_events` 两张表" in agents
    assert "无逐收件人 DB 状态、retry、queue、replay、backfill、fallback 或订单路径" in agents
    assert "RQAlpha 工作台是 local-only conditional keep" in project
    assert "Execution Review roll" in status
    assert "Alembic migration history" in project
    assert "`futures_member_ranks` table identity" in project
    assert "EMA/MACD/ATR/HTDY" in indicator_kernel
    assert "MarketDataService" in architecture
    assert "`guiyi research candidate-robustness`" in backend_readme

    retired_active_terms = (
        "MarketTrendFocus",
        "MarketAttentionList",
        "main-force-mirror",
        "main_force_mirror",
        "MainForceMirror",
        "candidate-dossier",
        "candidate-relationships",
        "MFM Diagnostic",
    )
    assert all(term not in combined for term in retired_active_terms)

    active_skills = tuple((ROOT / ".agents/skills").iterdir())
    assert {path.name for path in active_skills if path.is_dir()} == {
        "database-modeling",
        "futures-data",
        "market-kline-workbench",
        "quant-backend",
        "quant-frontend",
        "ui-bugfix",
    }
    assert "main-force-mirror-futures" not in (
        ROOT / ".agents/skills/quant-backend/SKILL.md"
    ).read_text(encoding="utf-8")


def test_architecture_convergence_contract_is_backed_by_code_and_paths() -> None:
    overlays = (
        ROOT / "apps/quant-web/src/utils/mainIndicators.ts"
    ).read_text(encoding="utf-8")
    market_types = (ROOT / "apps/quant-web/src/types/market.ts").read_text(
        encoding="utf-8"
    )
    parser = importlib.import_module("app.guiyi_cli.research_parser")
    main = (ROOT / "services/quant-api/app/main.py").read_text(encoding="utf-8")
    roll_composition = (
        ROOT / "services/quant-api/app/execution_review/composition.py"
    ).read_text(encoding="utf-8")

    assert "ResearchOverlayId = 'none' | 'subing' | 'jdj_strategy' | 'htdy'" in market_types
    assert all(
        fragment in overlays
        for fragment in (
            "id: 'none'",
            "label: '无'",
            "id: 'subing'",
            "label: '苏冰'",
            "id: 'jdj_strategy'",
            "label: '日进斗金参考回放'",
            "id: 'htdy'",
            "label: '火天大有'",
        )
    )
    assert not {"candidate-dossier", "candidate-relationships"} & set(
        parser.RESEARCH_COMMAND_NAMES
    )
    assert set(parser.RESEARCH_COMMAND_NAMES) == {
        "subing-calibration",
        "subing-lifecycle",
        "n-structure",
        "jdj-1m",
        "candidate-validation",
        "candidate-robustness",
    }

    retired_paths = (
        "services/quant-api/app/market_data/market_trend_focus.py",
        "services/quant-api/app/research/main_force_mirror_v2_service.py",
        "services/quant-api/app/research/main_force_mirror_diagnostic.py",
        "data/research_protocols/main_force_mirror_diagnostic_phase_a_v1.json",
        "reports/research/candidate_dossier",
        "reports/research/candidate_relationships",
        "docs/CODE_REVIEW.md",
        ".github/ISSUE_TEMPLATE/config.yml",
        ".github/ISSUE_TEMPLATE/optional_backlog.md",
        "docs/superpowers/specs/2026-08-24-subing-daily-watch-v1-design.md",
        "docs/superpowers/plans/2026-08-24-subing-daily-watch-v1.md",
        "docs/superpowers/specs/2026-08-24-jdj-active60-1m-strategy-design.md",
        "docs/superpowers/plans/2026-08-24-jdj-active60-1m-strategy.md",
        "docs/superpowers/plans/2026-08-24-no-watch-reliability-v1.md",
    )
    assert all(not (ROOT / relative).exists() for relative in retired_paths)
    assert not any(
        "member_rank" in path.name
        for path in (ROOT / "services/quant-api/app").rglob("*.py")
    )
    assert (ROOT / "services/quant-api/alembic/versions/20260718_0024_backtest_binding_snapshot.py").is_file()
    assert (ROOT / "services/quant-api/alembic/versions/20260707_0017_futures_member_ranks.py").is_file()
    assert (ROOT / "services/quant-api/tests/data_foundation/test_models.py").is_file()
    assert (ROOT / "services/quant-api/app/research/robustness/multi_candidate_events.py").is_file()
    assert (ROOT / "services/quant-api/app/research/robustness/multi_candidate_robustness_service.py").is_file()
    assert (ROOT / "services/quant-api/tests/test_multi_candidate_events.py").is_file()
    assert (ROOT / "data/research_protocols/multi_candidate_robustness_v1.json").is_file()
    assert (ROOT / "reports/research/candidate_robustness").is_dir()

    assert (ROOT / "services/quant-api/app/backtest/local_app.py").is_file()
    assert "backtest" not in main
    assert (ROOT / "openspec/specs/rqalpha-research-backtest-workbench/spec.md").is_file()
    assert (ROOT / "docs/superpowers/specs/2026-08-25-htdy-all-frequency-active60-design.md").is_file()
    assert (ROOT / "docs/superpowers/plans/2026-08-25-htdy-all-frequency-active60.md").is_file()
    assert (ROOT / "docs/superpowers/specs/2026-08-25-architecture-convergence-v1-design.md").is_file()
    assert (ROOT / "docs/superpowers/plans/2026-08-25-architecture-convergence-v1.md").is_file()
    assert 'execution_review_roll_marker_state() == "enabled"' in roll_composition
    assert '"ROLL_RECONCILIATION_REQUIRED"' in roll_composition


def test_daily_watch_storage_contract_is_explicit_and_backed_by_store() -> None:
    data_center = (ROOT / "docs/DATA_CENTER.md").read_text(encoding="utf-8")
    store = (
        ROOT / "services/quant-api/app/market_data/subing_daily_watch_store.py"
    ).read_text(encoding="utf-8")
    for contract in (
        "GUIYI_SUBING_OBSERVATION_ROOT",
        "history/<target>.json",
        "current.json",
        "generation-status.json",
        "同目录以原子替换",
        "current regression",
        "stale candidate fallback",
        "不得手工 backfill",
    ):
        assert contract in data_center
    for implementation in (
        "SUBING_OBSERVATION_ROOT_ENV",
        'root / "current.json"',
        'root / "generation-status.json"',
        "_atomic_write(",
        "CURRENT_TARGET_REGRESSION",
    ):
        assert implementation in store


def test_futures_mirror_production_sources_have_no_test_only_injection() -> None:
    chart = (
        ROOT / "apps/quant-web/src/components/kline/KlineChart.vue"
    ).read_text(encoding="utf-8")

    assert "__GUIYI_TEST_ALERT_MARKERS__" not in chart


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

    assert versions == {"1.8.4"}
    assert "version=APP_VERSION" in api
    assert '"version": APP_VERSION' in api


def test_isolated_postgresql_tests_are_separate_from_the_local_baseline() -> None:
    pyproject = tomllib.loads(
        (ROOT / "services/quant-api/pyproject.toml").read_text(encoding="utf-8")
    )
    testing = (ROOT / "TESTING.md").read_text(encoding="utf-8")
    service_tree = ast.parse(
        (
            ROOT
            / "services/quant-api/tests/execution_review/test_isolated_postgresql_concurrency.py"
        ).read_text(encoding="utf-8")
    )
    migration_tree = ast.parse(
        (
            ROOT
            / "services/quant-api/tests/alembic/test_execution_review_v1_migration.py"
        ).read_text(encoding="utf-8")
    )

    markers = pyproject["tool"]["pytest"]["ini_options"]["markers"]
    assert any(marker.startswith("isolated_postgresql:") for marker in markers)
    assert 'pytest -q -m "not isolated_postgresql" services/quant-api/tests' in testing
    assert "pytest -q -m isolated_postgresql services/quant-api/tests" in testing

    postgresql_tests = [
        node
        for node in service_tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_postgresql_")
    ]
    migration_tests = [
        node
        for node in migration_tree.body
        if isinstance(node, ast.FunctionDef)
        and any(arg.arg == "isolated_migration_context" for arg in node.args.args)
    ]
    assert postgresql_tests
    assert migration_tests
    for test in (*postgresql_tests, *migration_tests):
        decorators = {ast.unparse(decorator) for decorator in test.decorator_list}
        assert "pytest.mark.isolated_postgresql" in decorators, test.name


def test_alert_rule_codes_have_one_production_registry_per_language() -> None:
    rule_codes = ("htdy_original_15m", "subing_entry_signal_v1")
    backend_sources = tuple(
        path
        for path in (ROOT / "services/quant-api/app").rglob("*.py")
        if any(code in path.read_text(encoding="utf-8") for code in rule_codes)
    )
    frontend_sources = tuple(
        path
        for path in (ROOT / "apps/quant-web/src").rglob("*")
        if path.suffix in {".ts", ".vue"}
        and any(code in path.read_text(encoding="utf-8") for code in rule_codes)
    )

    assert {path.relative_to(ROOT).as_posix() for path in backend_sources} == {
        "services/quant-api/app/alerts/registry.py"
    }
    assert {path.relative_to(ROOT).as_posix() for path in frontend_sources} == {
        "apps/quant-web/src/utils/alertRules.ts"
    }


def test_htdy_all_frequency_alert_contract_matches_active_canonical() -> None:
    registry = importlib.import_module("app.alerts.registry")
    models = importlib.import_module("app.alerts.models")
    service_module = importlib.import_module("app.alerts.service")

    assert registry.HTDY_RULE.rule_code == "htdy_original_15m"
    assert registry.HTDY_RULE.input_frequencies == (
        "1m",
        "5m",
        "15m",
        "30m",
        "60m",
        "1d",
        "1w",
    )

    service = service_module.AlertService(object(), operational_products=("jm",))
    htdy_rule = models.AlertRule(
        rule_code=registry.HTDY_RULE.rule_code,
        scope_products=[],
        scope_product_frequencies={"jm": ["15m"]},
    )
    subing_rule = models.AlertRule(
        rule_code=registry.SUBING_RULE.rule_code,
        scope_products=["jm"],
        scope_product_frequencies={},
    )
    assert service.rule_allows_event(htdy_rule, symbol="jm", frequency="15m")
    assert not service.rule_allows_event(htdy_rule, symbol="jm", frequency="5m")
    assert service.rule_allows_event(subing_rule, symbol="jm", frequency="5m")

    storage_keys = {
        tuple(column.name for column in constraint.columns)
        for constraint in models.AlertEvent.__table__.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert storage_keys == {("rule_id", "symbol", "frequency", "bar_end")}

    def canonical_text(relative: str) -> str:
        return " ".join((ROOT / relative).read_text(encoding="utf-8").split())

    indicator = canonical_text("docs/INDICATOR_KERNEL.md")
    project = canonical_text("PROJECT_SOURCE.md")
    agents = canonical_text("AGENTS.md")
    development = canonical_text("docs/DEVELOPMENT.md")
    decisions = canonical_text("DECISIONS.md")

    assert "`1m/5m/15m/30m/60m/1d/1w` 七个正式周期" in indicator
    assert "稳定 Rule code 保持 `htdy_original_15m`" in project
    assert "HTDY 唯一 Scope authority 为 `scope_product_frequencies`" in project
    assert "SuBing 唯一 Scope authority 为 `scope_products`" in project
    assert "`(rule_id, symbol, frequency, bar_end)`" in project
    assert "SuBing 的业务 Event identity 保持 `rule_id + symbol + bar_end`" in project
    assert "D1/W1 只由 `market:state(reason=canonical_updated)`" in project
    assert "htdy_original_15m × 该 Rule 显式 symbol-frequency pair Scope" in agents
    assert "htdy_original_15m × 该 Rule 显式 symbol-frequency pair Scope" in development
    assert "不新增第二套 scheduler 或 Scope 表" in decisions


def test_exact_contract_and_jdj_identity_have_one_implementation() -> None:
    market_data = ROOT / "services/quant-api/app/market_data"
    research = ROOT / "services/quant-api/app/research"
    jdj_context = research / "jdj/jdj_context.py"
    exact_contract = ROOT / "services/quant-api/app/core/exact_json_contract.py"
    assert exact_contract.is_file()
    exact_source = exact_contract.read_text(encoding="utf-8")
    for function in (
        "matches_exact_json",
        "load_exact_json",
        "freeze_json",
        "matches_exact_frozen",
    ):
        assert f"def {function}(" in exact_source

    duplicate_exact_definitions = []
    duplicate_jdj_definitions = []
    for path in (*market_data.glob("*.py"), *research.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        if path != exact_contract and re.search(
            r"^def _?(?:matches_exact|load_exact|freeze_json|matches_exact_json|matches_exact_frozen)\(",
            source,
            re.MULTILINE,
        ):
            duplicate_exact_definitions.append(path.name)
        if path != jdj_context and re.search(
            r"^def _?valid_context_fact_identity\(", source, re.MULTILINE
        ):
            duplicate_jdj_definitions.append(path.name)

    assert duplicate_exact_definitions == []
    assert duplicate_jdj_definitions == []
    assert "def valid_context_fact_identity(" in jdj_context.read_text(
        encoding="utf-8"
    )


def test_release_candidate_excludes_private_sources() -> None:
    tracked_private_sources = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", "private_sources"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    assert tracked_private_sources == ""
