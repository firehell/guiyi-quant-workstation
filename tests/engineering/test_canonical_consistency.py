"""Small executable contracts shared across the active repository surface."""

from __future__ import annotations

import ast
import importlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]

PUBLIC_WEB_ROUTES = {"/market", "/market/chart"}
PUBLIC_OVERLAYS = {"none", "htdy"}
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
    "services/quant-api/app/api/dashboard.py",
    "services/quant-api/app/api/signals.py",
    "services/quant-api/app/api/reviews.py",
    "services/quant-api/app/api/strategies.py",
    "services/quant-api/app/api/watchlists.py",
    "services/quant-api/app/api/futures_research.py",
    "services/quant-api/app/api/data_center.py",
    "services/quant-api/app/repositories/data_center.py",
    "services/quant-api/app/models/signal.py",
    "services/quant-api/app/models/review.py",
    "services/quant-api/app/models/watchlist.py",
    "services/quant-api/app/signal",
    "services/quant-api/app/review",
    "services/quant-api/app/strategy",
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
    "services/quant-api/app/market_data/market_radar.py",
    "services/quant-api/app/research/main_force_mirror_v2_service.py",
    "services/quant-api/app/research",
    "services/quant-api/app/alerts/subing_strategy_runtime.py",
    "services/quant-api/app/alerts/strategy_payload.py",
    "services/quant-api/app/market_data/subing_strategy",
    "services/quant-api/app/market_data/subing_watch",
    "services/quant-api/app/guiyi_cli/research_parser.py",
    "services/quant-api/app/guiyi_cli/research_commands.py",
    "apps/quant-web/src/components/market/SubingPanel.vue",
    "apps/quant-web/src/composables/useSubingWorkbench.ts",
    "apps/quant-web/src/utils/subingDailyWatch.ts",
    "reports/research/candidate_dossier",
    "reports/research/candidate_relationships",
    "apps/quant-web/package-lock.json",
)
RETIRED_HTTP_404_PATHS = (
    "/api/dashboard/summary",
    "/api/signals/latest",
    "/api/signals/events",
    "/api/v1/strategies/registry",
    "/api/reviews",
    "/api/watchlists",
    "/api/v1/market/research/panels",
    "/api/v1/data/summary",
    "/api/v1/data/profiles",
    "/api/v1/data/coverage",
    "/api/v1/market/bars/canonical",
    "/api/v1/market/coverage/canonical",
    "/api/v1/market/research/main-force-mirror",
    "/api/v1/market/research/radar",
    "/api/v1/market/research/subing/history",
    "/api/v1/market/research/subing",
    "/api/v1/market/research/subing-daily-watch/current",
    "/api/v1/market/research/subing-strategy/historical",
    "/api/v1/market/research/subing-strategy/current",
    "/api/v1/market/research/subing-strategy/performance",
    "/api/alerts/strategy-actions/current",
    "/api/v1/backtests/health",
    "/api/execution-review/items",
    "/api/symbols",
)
ACTIVE_PUBLIC_SOURCES = (
    "services/quant-api/app/market_data/market_data_service.py",
    "apps/quant-web/src/api/market.ts",
    "apps/quant-web/src/pages/market/index.vue",
)
RETIRED_SOURCE_NAMES = {
    "apps/quant-web/src/pages/market/index.vue": (
        "MarketAttentionList",
        "MarketFocusList",
        "radar.attention",
    ),
    "apps/quant-web/src/types/market.ts": (
        "attention_count",
        "SubingHistoricalSignal",
    ),
    "apps/quant-web/src/api/market.ts": (
        "getSubingHistoricalSignals",
        "/subing/history",
    ),
    "apps/quant-web/src/pages/market/chart.vue": (
        "useMainForceMirrorV2",
        "main_force_mirror_v2",
    ),
    "apps/quant-web/src/components/kline/KlineHoverLegend.vue": (
        "mainForceMirror",
    ),
    "apps/quant-web/src/utils/klineViewModel.ts": ("mainForceMirror",),
    "apps/quant-web/src/components/common/UiIcon.vue": (
        "name === 'dashboard'",
        "name === 'signal'",
        "name === 'strategy'",
        "name === 'data'",
        "name === 'runtime'",
        "name === 'arrow-up'",
        "name === 'arrow-down'",
    ),
}
RETIRED_MODULE_ATTRIBUTES = {
    "app.market_data.composition": (
        "build_main_force_mirror_v2_service",
        "build_member_rank_snapshot_builder",
        "build_subing_read_service",
        "build_subing_strategy_service",
    ),
}
ALERT_RULE_CODES = frozenset({"htdy_original_15m", "subing_ths_alert_15m_v1"})
SUBING_THS_FORMULA_VERSION = "subing_ths_15m_v3"
BACKEND_ALERT_RULE_LITERAL_EXPECTED = {
    "htdy_original_15m": {
        "services/quant-api/app/alerts/registry.py": 2,
        "services/quant-api/app/schemas/alerts.py": 1,
    },
    "subing_ths_alert_15m_v1": {
        "services/quant-api/app/alerts/registry.py": 2,
        "services/quant-api/app/schemas/alerts.py": 1,
    },
}

ALERT_CANONICAL_REQUIREMENTS = {
    "AGENTS.md": (
        "subing_ths_alert_15m_v1",
        "completed actual_dominant 15m",
        "schema v6",
        "G10",
        "G9",
    ),
    "PROJECT_SOURCE.md": (
        "苏冰预警",
        SUBING_THS_FORMULA_VERSION,
        "EMA(CLOSE, 21)",
        "completed actual_dominant 15m",
        "零轴、Range、量能/OI、ATR、EMA 斜率与多周期共振都不是 V1 Gate",
    ),
    "DECISIONS.md": (
        "subing_ths_alert_15m_v1",
        SUBING_THS_FORMULA_VERSION,
        "exact Event",
        "Event 先提交",
    ),
    "docs/ARCHITECTURE.md": (
        "SubingThs15mEvaluator",
        "single Alert Runtime",
        "S↑/S↓",
        "no SuBing overlay",
    ),
    "TESTING.md": (
        "test_subing_ths_kernel.py",
        "test_subing_scope_activation.py",
        "test_subing_ths_alert_migration.py",
        "GUIYI_ISOLATED_MIGRATION_DATABASE_URL",
    ),
    "openspec/specs/subing-ths-alert/spec.md": (
        "subing_ths_alert_15m_v1",
        SUBING_THS_FORMULA_VERSION,
        "EMA(CLOSE, 21)",
        "G10",
        "G9",
    ),
}


def _assert_backend_alert_rule_literal_ownership(
    sources: dict[str, str],
) -> None:
    actual: dict[str, dict[str, int]] = {code: {} for code in ALERT_RULE_CODES}
    for path, source in sources.items():
        values = tuple(
            node.value
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        )
        counts = {code: values.count(code) for code in ALERT_RULE_CODES}
        for code, count in counts.items():
            if count:
                actual[code][path] = count
    assert actual == BACKEND_ALERT_RULE_LITERAL_EXPECTED, (
        f"backend Alert Rule literal ownership/count mismatch: {actual}"
    )


def _active_backend_alert_rule_sources() -> dict[str, str]:
    return {
        relative.as_posix(): (ROOT / relative).read_text(encoding="utf-8")
        for path in (ROOT / "services/quant-api/app").rglob("*.py")
        if path.is_file()
        for relative in (path.relative_to(ROOT),)
    }


def test_public_entrypoints_are_exact() -> None:
    router_source = (ROOT / "apps/quant-web/src/app/router.ts").read_text(
        encoding="utf-8"
    )
    declared_paths = set(re.findall(r"^\s+path: '([^']+)'", router_source, re.MULTILINE))
    product_routes = {
        f"/{path}" for path in declared_paths if not path.startswith(('/', ':'))
    }
    assert product_routes == PUBLIC_WEB_ROUTES

    indicator_source = (
        ROOT / "apps/quant-web/src/utils/mainIndicators.ts"
    ).read_text(encoding="utf-8")
    overlay_block = indicator_source.split(
        "RESEARCH_OVERLAY_DEFINITIONS", maxsplit=1
    )[1].split("const overlayDefinitionsById", maxsplit=1)[0]
    overlay_ids = set(re.findall(r"^\s+id: '([^']+)'", overlay_block, re.MULTILINE))
    assert overlay_ids == PUBLIC_OVERLAYS

    main_module = importlib.import_module("app.guiyi_cli.main")
    parser = main_module.build_parser()
    domain_action = next(action for action in parser._actions if action.dest == "domain")
    assert set(domain_action.choices) == {"data", "runtime"}


def test_retired_http_surfaces_return_404_and_are_not_mounted() -> None:
    main_module = importlib.import_module("app.main")
    route_paths = {
        route.path for route in main_module.app.routes if hasattr(route, "path")
    }
    client = TestClient(main_module.app)

    for path in RETIRED_HTTP_404_PATHS:
        assert path not in route_paths, path
        assert client.get(path).status_code == 404, path
    assert "/ws/signals" not in route_paths


def test_active_public_sources_do_not_name_retired_backtesting() -> None:
    forbidden_terms = ("回测", "backtest")
    for relative in ACTIVE_PUBLIC_SOURCES:
        source = (ROOT / relative).read_text(encoding="utf-8").lower()
        assert all(term not in source for term in forbidden_terms), relative


def test_retired_names_remain_absent_from_active_sources_and_registries() -> None:
    for relative, names in RETIRED_SOURCE_NAMES.items():
        source = (ROOT / relative).read_text(encoding="utf-8")
        assert all(name not in source for name in names), relative

    for module_name, names in RETIRED_MODULE_ATTRIBUTES.items():
        module = importlib.import_module(module_name)
        assert all(not hasattr(module, name) for name in names), module_name

    indicators = importlib.import_module("guiyi_quant.indicators")
    assert not any(
        code.startswith("main_force_mirror")
        for code in indicators.indicator_registry
    )
    assert not any(
        policy.indicator_family.startswith("MAIN_FORCE_MIRROR")
        for policy in indicators.formal_policy_registry.values()
    )


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
    for relative in RETIRED_ENTRYPOINTS:
        path = ROOT / relative
        if path.is_file():
            raise AssertionError(relative)
        if path.is_dir():
            active_files = [
                child
                for child in path.rglob("*")
                if child.is_file() and "__pycache__" not in child.parts
            ]
            assert not active_files, (relative, active_files)


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
    api = (ROOT / "services/quant-api/app/main.py").read_text(encoding="utf-8")
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
    } == {"1.9.15"}
    assert "version=APP_VERSION" in api
    assert '"version": APP_VERSION' in api


def test_alert_rule_codes_have_one_production_registry_per_language() -> None:
    backend_registry = importlib.import_module("app.alerts.registry")
    assert {
        definition.rule_code for definition in backend_registry.alert_rule_definitions()
    } == ALERT_RULE_CODES

    _assert_backend_alert_rule_literal_ownership(
        _active_backend_alert_rule_sources()
    )
    frontend = subprocess.run(
        ["pnpm", "--dir", "apps/quant-web", "run", "check:alert-rules"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert frontend.stdout.strip().splitlines()[-1] == "[alert-rule-ownership] passed"


def test_active_alert_canonical_matches_the_two_rule_code_contract() -> None:
    registry = importlib.import_module("app.alerts.registry")
    kernel_module = importlib.import_module("guiyi_quant.indicators.subing_ths")

    definitions = {
        definition.rule_code: definition
        for definition in registry.alert_rule_definitions()
    }
    assert frozenset(definitions) == ALERT_RULE_CODES
    assert definitions["htdy_original_15m"].event_mode.value == "first_seen"
    subing = definitions["subing_ths_alert_15m_v1"]
    assert subing.display_name == "苏冰预警"
    assert subing.kind.value == "indicator_observation"
    assert subing.event_mode.value == "exact"
    assert subing.input_frequencies == ("15m",)
    assert subing.series_kind == "actual_dominant"

    kernel = kernel_module.SubingThs15mKernel
    assert kernel.formula_version == SUBING_THS_FORMULA_VERSION
    assert (kernel.fast, kernel.slow, kernel.signal) == (12, 26, 9)
    assert kernel.ema_period == 21
    assert kernel.ema_seed_policy == "sma_window"
    assert kernel.histogram_scale == 2
    assert kernel.round_digits == 6
    kernel_source = (ROOT / "packages/quant-core/guiyi_quant/indicators/subing_ths.py").read_text(
        encoding="utf-8"
    )
    assert "step_ema(state.ema21, close" in kernel_source

    migration_source = (
        ROOT
        / "services/quant-api/alembic/versions/20260902_0044_subing_ths_alert.py"
    ).read_text(encoding="utf-8")
    assert "enabled=False" in migration_source
    assert "scope_product_frequencies={}" in migration_source

    session_migration_source = (
        ROOT
        / "services/quant-api/alembic/versions/20260903_0045_normalize_rqdata_session_anchor.py"
    ).read_text(encoding="utf-8")
    assert '"20260902_0044"' in session_migration_source
    assert "RQDATA_SESSION_ANCHOR_DOWNGRADE_UNSUPPORTED" in session_migration_source

    service_source = (
        ROOT / "services/quant-api/app/alerts/service.py"
    ).read_text(encoding="utf-8")
    scope_method = service_source.split(
        "def set_product_frequency_enabled", maxsplit=1
    )[1].split("def rule_allows_event", maxsplit=1)[0]
    assert scope_method.index("if not rule.enabled:") < scope_method.index(
        "rule.scope_product_frequencies ="
    )

    activation_source = (
        ROOT / "services/quant-api/app/alerts/subing_scope_activation.py"
    ).read_text(encoding="utf-8")
    assert "def activate_subing_ths_scope(" in activation_source
    assert "with_for_update()" in activation_source
    assert "session.commit()" in activation_source
    assert "session.expire_all()" in activation_source
    assert '20260903_0045' in activation_source

    runtime_source = (
        ROOT / "services/quant-api/app/alerts/runtime.py"
    ).read_text(encoding="utf-8")
    prepare_event = runtime_source.split(
        "def _persist_candidate_and_prepare_notification", maxsplit=1
    )[1].split("class AlertRuntime", maxsplit=1)[0]
    assert prepare_event.index("service.create") < prepare_event.index(
        "AlertNotificationMessage("
    )
    send_once = runtime_source.split("def _send_messages_once", maxsplit=1)[1].split(
        "def _record_notification_failure", maxsplit=1
    )[0]
    assert send_once.count("self._sender.send(message)") == 1
    assert "retry" not in send_once.lower()


def test_active_canonical_documents_the_rule_split_and_formula_gates() -> None:
    for relative, required_terms in ALERT_CANONICAL_REQUIREMENTS.items():
        path = ROOT / relative
        assert path.is_file(), relative
        source = path.read_text(encoding="utf-8")
        for term in required_terms:
            assert term in source, (relative, term)

    market_home = (
        ROOT / "openspec/specs/market-home-overview/spec.md"
    ).read_text(encoding="utf-8")
    assert "current Alert Events" in market_home
    assert "Current Alert Events endpoint" in market_home

    subing_spec = (
        ROOT / "openspec/specs/subing-ths-alert/spec.md"
    ).read_text(encoding="utf-8")
    assert subing_spec.index("G10") < subing_spec.index("G9")


def test_release_candidate_excludes_private_sources() -> None:
    tracked = subprocess.run(
        ["git", "-c", "core.fsmonitor=false", "ls-files", "private_sources"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert tracked == ""
