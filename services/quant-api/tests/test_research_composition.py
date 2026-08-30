from __future__ import annotations

import ast
from datetime import date
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data import composition as market_data_composition
from app.research import composition as research_composition


_QUANT_API_ROOT = Path(__file__).resolve().parents[1]
_APP_ROOT = _QUANT_API_ROOT / "app"
_RESEARCH_ROOT = _APP_ROOT / "research"
_RESEARCH_COMPOSITION_PATH = _RESEARCH_ROOT / "composition.py"
_RUNTIME_BOUNDARY_PATHS = (
    _APP_ROOT / "alerts",
    _APP_ROOT / "market_data",
    _APP_ROOT / "api",
    _APP_ROOT / "runtime_entry.py",
)


def _local_research_builders() -> tuple[str, ...]:
    tree = ast.parse(
        _RESEARCH_COMPOSITION_PATH.read_text(encoding="utf-8"),
        filename=str(_RESEARCH_COMPOSITION_PATH),
    )
    return tuple(
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("build_")
    )


def _research_implementation_modules() -> tuple[str, ...]:
    return tuple(
        "app." + ".".join(path.relative_to(_APP_ROOT).with_suffix("").parts)
        for path in sorted(_RESEARCH_ROOT.rglob("*.py"))
        if path.name not in {"__init__.py", "composition.py"}
    )


def _assert_no_offline_research_imports(path: Path) -> None:
    assert not _offline_research_imports(path), path


def _offline_research_imports(path: Path) -> tuple[str, ...]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            relative_name = "." * node.level + (node.module or "")
            if node.level:
                module_parts = path.relative_to(_QUANT_API_ROOT).with_suffix("").parts
                module = importlib.util.resolve_name(
                    relative_name,
                    ".".join(module_parts[:-1]),
                )
            else:
                module = relative_name
            imported_modules.append(module)
            imported_modules.extend(
                f"{module}.{alias.name}"
                for alias in node.names
                if alias.name != "*"
            )
    return tuple(
        module
        for module in imported_modules
        if (
            module == "app.research" or module.startswith("app.research.")
        )
    )


def test_offline_research_builders_have_one_composition_entrypoint() -> None:
    research_composition = importlib.import_module("app.research.composition")
    builders = _local_research_builders()
    assert builders == (
        "build_subing_calibration_research_service",
        "build_subing_lifecycle_research_service",
        "build_subing_candidate_validation_service",
    )
    assert all(hasattr(research_composition, name) for name in builders)
    assert not any(hasattr(market_data_composition, name) for name in builders)


def test_offline_research_implementation_has_one_physical_package() -> None:
    modules = _research_implementation_modules()
    assert modules
    for module in modules:
        assert importlib.util.find_spec(module) is not None, module


@pytest.mark.parametrize(
    "statement",
    (
        "from app.research import composition",
        "import app.research.composition",
    ),
)
def test_runtime_dependency_guard_rejects_both_import_syntaxes(
    tmp_path: Path,
    statement: str,
) -> None:
    source = tmp_path / "runtime_boundary.py"
    source.write_text(statement, encoding="utf-8")

    with pytest.raises(AssertionError):
        _assert_no_offline_research_imports(source)


def test_runtime_dependency_guard_resolves_relative_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app_root = tmp_path / "app"
    source = app_root / "market_data" / "runtime_boundary.py"
    source.parent.mkdir(parents=True)
    monkeypatch.setitem(
        _assert_no_offline_research_imports.__globals__,
        "_QUANT_API_ROOT",
        tmp_path,
    )

    source.write_text("from .domain import BarFrequency", encoding="utf-8")
    _assert_no_offline_research_imports(source)

    source.write_text("from ..research import composition", encoding="utf-8")
    with pytest.raises(AssertionError):
        _assert_no_offline_research_imports(source)


def test_runtime_market_and_alert_do_not_import_offline_research() -> None:
    source_paths: list[Path] = []
    for boundary in _RUNTIME_BOUNDARY_PATHS:
        source_paths.extend(
            boundary.rglob("*.py") if boundary.is_dir() else (boundary,)
        )
    for path in source_paths:
        _assert_no_offline_research_imports(path)


def _fail_dependency(name: str):
    def fail(*_args: object, **_kwargs: object) -> object:
        pytest.fail(f"{name} must not be constructed")

    return fail


def test_calibration_builder_uses_only_historical_market_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    captured: dict[str, object] = {}
    service = object()
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        research_composition,
        "load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        research_composition,
        "SubingCalibrationResearchService",
        lambda **kwargs: captured.update(kwargs) or service,
    )
    for name in (
        "build_historical_data_manager",
        "build_live_market_service",
        "build_market_read_service",
    ):
        monkeypatch.setattr(
            research_composition,
            name,
            _fail_dependency(name),
            raising=False,
        )

    assert (
        research_composition.build_subing_calibration_research_service(object())
        is service
    )
    assert captured == {"market_data": market_data, "products": ("jm",)}


def test_lifecycle_builder_uses_only_historical_market_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    calibration = object()
    policy = object()
    captured: dict[str, object] = {}
    service = object()
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda _session: market_data,
    )
    monkeypatch.setattr(
        research_composition,
        "load_active_products",
        lambda: ("jm",),
    )
    monkeypatch.setattr(
        research_composition,
        "load_accepted_subing_calibration",
        lambda: calibration,
    )
    monkeypatch.setattr(
        research_composition,
        "load_subing_lifecycle_policy",
        lambda: policy,
    )
    monkeypatch.setattr(
        research_composition,
        "SubingLifecycleResearchService",
        lambda market_data_arg, **kwargs: (
            captured.update(market_data=market_data_arg, **kwargs) or service
        ),
    )
    for name in (
        "build_historical_data_manager",
        "build_live_market_service",
        "build_market_read_service",
    ):
        monkeypatch.setattr(
            research_composition,
            name,
            _fail_dependency(name),
            raising=False,
        )

    assert (
        research_composition.build_subing_lifecycle_research_service(object())
        is service
    )
    assert captured == {
        "market_data": market_data,
        "products": ("jm",),
        "calibration": calibration,
        "policy": policy,
    }


def test_subing_candidate_builder_reuses_lifecycle_research_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    research = object()
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        "build_subing_lifecycle_research_service",
        lambda _session: research,
    )
    monkeypatch.setattr(
        research_composition,
        "SubingCandidateValidationService",
        lambda source, **kwargs: (
            captured.update(source=source, **kwargs) or result
        ),
    )
    monkeypatch.setattr(research_composition, "load_candidate_manifest", object)
    monkeypatch.setattr(
        research_composition, "load_candidate_validation_protocol", object
    )

    built = research_composition.build_subing_candidate_validation_service(object())

    assert built is result
    assert captured["source"] is research


def test_current_strategy_builder_uses_read_only_authoritative_seams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = object()
    products = ("jm",)
    catalog_reads = 0

    def list_latest_dominants():
        nonlocal catalog_reads
        catalog_reads += 1
        return (
            SimpleNamespace(
                symbol="jm",
                product_name="焦煤",
                sector="黑色",
            ),
        )

    market_data = SimpleNamespace(
        list_latest_dominants=list_latest_dominants,
        dominant_segment_for_day=lambda symbol, target: (symbol, target),
    )
    market_read = object()
    loader = object()
    projector = object()
    resolved = {date(2026, 8, 4): object()}
    resolver = SimpleNamespace(resolve=lambda _symbol, _days: resolved)
    store = SimpleNamespace(read_current=lambda: "snapshot")
    expected = object()
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        market_data_composition,
        "load_active_products",
        lambda: products,
    )
    monkeypatch.setattr(
        market_data_composition,
        "build_market_data_service",
        lambda value: market_data if value is session else None,
    )
    monkeypatch.setattr(
        market_data_composition,
        "build_market_read_service",
        lambda value: market_read if value is session else None,
    )
    monkeypatch.setattr(
        market_data_composition,
        "ActualDominantResearchSegmentLoader",
        lambda value: loader if value is market_data else None,
    )
    monkeypatch.setattr(
        market_data_composition,
        "ActualDominantStitchedResearchLoader",
        lambda value: SimpleNamespace(market_data=value),
    )
    monkeypatch.setattr(
        market_data_composition,
        "SubingDailyWatchItemProjector",
        lambda **_kwargs: projector,
    )
    monkeypatch.setattr(
        market_data_composition,
        "SubingStrategyDirectionContextResolver",
        lambda **_kwargs: resolver,
    )
    monkeypatch.setattr(
        market_data_composition,
        "SubingDailyWatchStore",
        lambda *_args, **_kwargs: store,
    )
    monkeypatch.setattr(
        market_data_composition,
        "_subing_daily_watch_v2_root",
        lambda: Path("/tmp/subing-v2"),
    )
    monkeypatch.setattr(
        market_data_composition,
        "load_accepted_subing_calibration",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        market_data_composition,
        "load_subing_lifecycle_policy",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        market_data_composition,
        "load_subing_strategy_policy",
        lambda: object(),
    )

    def construct(segment_loader, **kwargs):
        captured.update(segment_loader=segment_loader, **kwargs)
        return expected

    monkeypatch.setattr(
        market_data_composition,
        "SubingStrategyCurrentProjectionService",
        construct,
        raising=False,
    )

    result = market_data_composition.build_subing_strategy_current_service(session)

    assert result is expected
    assert catalog_reads == 0
    assert captured["segment_loader"] is loader
    assert captured["market_read"] is market_read
    lazy_resolver = captured["historical_direction_context_resolver"]
    assert lazy_resolver.resolve("jm", (date(2026, 8, 4),)) is resolved
    assert catalog_reads == 1
    assert captured["current_snapshot_store"].read_current() == "snapshot"
    assert captured["products"] == products
    assert "cache" not in captured
    assert "event_history" not in captured
