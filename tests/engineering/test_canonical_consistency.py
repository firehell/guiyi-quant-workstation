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
    for command in research_parser.RESEARCH_COMMAND_NAMES:
        assert command in backend_readme
        assert command in project_source
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
    assert "MainForceMirrorV2Service" in architecture
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
