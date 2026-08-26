"""Small executable contracts shared across the active repository surface."""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

PUBLIC_OVERLAYS = {"none", "subing", "jdj_strategy", "htdy"}
RESEARCH_COMMANDS = {
    "subing-calibration",
    "subing-lifecycle",
    "n-structure",
    "jdj-1m",
    "candidate-validation",
    "candidate-robustness",
}
MARKET_TABLES = {
    "exchanges",
    "instruments",
    "contracts",
    "trading_calendars",
    "trading_sessions",
    "main_contract_map",
    "market_datasets",
    "market_partitions",
}
RETIRED_ENTRYPOINTS = (
    "services/quant-api/app/backtest",
    "services/quant-api/app/execution_review",
    "services/quant-api/app/api/execution_review.py",
    "services/quant-api/app/schemas/execution_review.py",
    "apps/quant-web/src/pages/backtests",
    "apps/quant-web/src/pages/trade-records",
    "openspec/specs/rqalpha-research-backtest-workbench",
    "docs/EXECUTION_REVIEW.md",
    "services/quant-api/app/worker.py",
    "services/quant-api/app/queue.py",
    "services/quant-api/app/market_data/market_trend_focus.py",
    "services/quant-api/app/research/main_force_mirror_v2_service.py",
    "services/quant-api/app/research/main_force_mirror_diagnostic.py",
    "reports/research/candidate_dossier",
    "reports/research/candidate_relationships",
    "apps/quant-web/package-lock.json",
)


def test_public_entrypoints_are_exact() -> None:
    indicator_source = (
        ROOT / "apps/quant-web/src/utils/mainIndicators.ts"
    ).read_text(encoding="utf-8")
    overlay_block = indicator_source.split(
        "RESEARCH_OVERLAY_DEFINITIONS", maxsplit=1
    )[1].split("const overlayDefinitionsById", maxsplit=1)[0]
    overlay_ids = set(re.findall(r"^\s+id: '([^']+)'", overlay_block, re.MULTILINE))
    assert overlay_ids == PUBLIC_OVERLAYS

    parser_module = importlib.import_module("app.guiyi_cli.research_parser")
    main_module = importlib.import_module("app.guiyi_cli.main")
    parser = main_module.build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    research_parser = domain_action.choices["research"]
    command_action = next(
        action
        for action in research_parser._actions
        if action.dest == "research_command"
    )
    assert set(parser_module.RESEARCH_COMMAND_NAMES) == RESEARCH_COMMANDS
    assert set(command_action.choices) == RESEARCH_COMMANDS


def test_retired_rqalpha_and_execution_review_are_not_mounted() -> None:
    main_module = importlib.import_module("app.main")
    route_paths = {
        route.path for route in main_module.app.routes if hasattr(route, "path")
    }
    assert not any("backtest" in path for path in route_paths)
    assert not any("execution-review" in path for path in route_paths)


def test_market_identity_and_no_order_contracts_are_executable() -> None:
    domain = importlib.import_module("app.market_data.domain")
    market_tables = importlib.import_module("app.models.market_tables")
    policy = importlib.import_module(
        "guiyi_quant.indicators.realtime_observation_policy"
    )

    assert set(domain.DatasetKey.__dataclass_fields__) == {
        "kind",
        "symbol",
        "series_or_contract",
        "frequency",
    }
    model_names = {
        name
        for name, value in vars(market_tables).items()
        if isinstance(value, type) and getattr(value, "__tablename__", None)
    }
    assert {
        getattr(market_tables, name).__tablename__ for name in model_names
    } == MARKET_TABLES
    assert policy.RealtimeRepaintingObservationPolicy().auto_order is False
    assert policy.ClosedBarRealtimeObservationPolicy().auto_order is False


def test_retired_entrypoints_remain_absent() -> None:
    assert all(not (ROOT / relative).exists() for relative in RETIRED_ENTRYPOINTS)


def test_public_websocket_route_matches_nginx() -> None:
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
    version_module = ast.parse(
        (ROOT / "services/quant-api/app/version.py").read_text(encoding="utf-8")
    )
    web = json.loads((ROOT / "apps/quant-web/package.json").read_text(encoding="utf-8"))

    lock_versions = {
        package["version"]
        for package in lock["package"]
        if package["name"] == "quant-api" and package.get("source") == {"editable": "."}
    }
    app_versions = {
        node.value.value
        for node in version_module.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "APP_VERSION"
            for target in node.targets
        )
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    assert {
        pyproject["project"]["version"],
        web["version"],
        *lock_versions,
        *app_versions,
    } == {"1.8.3"}


def test_alert_rule_codes_have_one_production_registry_per_language() -> None:
    rule_codes = ("htdy_original_15m", "subing_entry_signal_v1")
    backend_sources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "services/quant-api/app").rglob("*.py")
        if any(code in path.read_text(encoding="utf-8") for code in rule_codes)
    }
    frontend_sources = {
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "apps/quant-web/src").rglob("*")
        if path.suffix in {".ts", ".vue"}
        and any(code in path.read_text(encoding="utf-8") for code in rule_codes)
    }
    assert backend_sources == {"services/quant-api/app/alerts/registry.py"}
    assert frontend_sources == {"apps/quant-web/src/utils/alertRules.ts"}


def test_release_candidate_excludes_private_sources() -> None:
    tracked = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", "private_sources"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tracked == ""
