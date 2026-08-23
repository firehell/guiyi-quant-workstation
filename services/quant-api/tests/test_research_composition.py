from __future__ import annotations

import ast
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
    assert builders
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


@pytest.mark.parametrize(
    ("candidate_builder", "research_builder", "service_name", "extra_args"),
    (
        (
            "build_subing_candidate_validation_service",
            "build_subing_lifecycle_research_service",
            "SubingCandidateValidationService",
            (),
        ),
        (
            "build_n_candidate_validation_service",
            "build_n_structure_research_service",
            "NStructureCandidateValidationService",
            (),
        ),
    ),
)
def test_candidate_builders_reuse_corresponding_research_service(
    monkeypatch: pytest.MonkeyPatch,
    candidate_builder: str,
    research_builder: str,
    service_name: str,
    extra_args: tuple[object, ...],
) -> None:
    research = object()
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        research_builder,
        lambda _session: research,
    )
    monkeypatch.setattr(
        research_composition,
        service_name,
        lambda source, **kwargs: (
            captured.update(source=source, **kwargs) or result
        ),
    )
    if service_name == "SubingCandidateValidationService":
        monkeypatch.setattr(
            research_composition, "load_candidate_manifest", object
        )
        monkeypatch.setattr(
            research_composition, "load_candidate_validation_protocol", object
        )
    else:
        monkeypatch.setattr(
            research_composition, "load_n_candidate_manifest", object
        )
        monkeypatch.setattr(
            research_composition, "load_n_candidate_validation_protocol", object
        )

    built = getattr(research_composition, candidate_builder)(
        object(), *extra_args
    )

    assert built is result
    assert captured["source"] is research


def test_n_research_builder_reuses_one_market_data_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    loader = SimpleNamespace(market_data=market_data)
    calls: list[object] = []
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda session: calls.append(session) or market_data,
    )
    monkeypatch.setattr(
        research_composition,
        "ActualDominantResearchSegmentLoader",
        lambda value: loader if value is market_data else pytest.fail("wrong MDS"),
    )
    monkeypatch.setattr(
        research_composition, "load_active_products", lambda: ("jm",)
    )
    monkeypatch.setattr(
        research_composition, "load_n_structure_policy", object
    )
    monkeypatch.setattr(
        research_composition,
        "NStructureResearchService",
        lambda loader_arg, **kwargs: (
            captured.update(loader=loader_arg, **kwargs) or result
        ),
    )
    session = object()

    assert research_composition.build_n_structure_research_service(session) is result
    assert calls == [session]
    assert captured["loader"] is loader


def test_jdj_research_builder_reuses_one_mds_and_no_write_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    loader = object()
    calls: list[tuple[str, object]] = []
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda session: calls.append(("market_data", session)) or market_data,
    )
    monkeypatch.setattr(
        research_composition,
        "ActualDominantResearchSegmentLoader",
        lambda value: loader if value is market_data else pytest.fail("wrong MDS"),
    )
    monkeypatch.setattr(
        research_composition, "load_active_products", lambda: ("jm",)
    )
    monkeypatch.setattr(research_composition, "load_jdj_policy", object)
    monkeypatch.setattr(
        research_composition, "load_n_structure_policy", object
    )
    monkeypatch.setattr(
        research_composition,
        "JdjResearchService",
        lambda loader_arg, **kwargs: (
            captured.update(loader=loader_arg, **kwargs) or result
        ),
    )
    for name in ("build_historical_data_manager", "build_live_market_service"):
        monkeypatch.setattr(
            research_composition,
            name,
            _fail_dependency(name),
            raising=False,
        )
    session = object()

    assert research_composition.build_jdj_research_service(session) is result
    assert calls == [("market_data", session)]
    assert captured["loader"] is loader


def test_jdj_candidate_builder_checks_calendar_before_reusing_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[tuple[str, object]] = []
    research = object()
    result = object()
    monkeypatch.setattr(
        research_composition,
        "assert_jdj_prospective_calendar",
        lambda session: order.append(("calendar", session)),
    )
    monkeypatch.setattr(
        research_composition,
        "build_jdj_research_service",
        lambda session: order.append(("research", session)) or research,
    )
    monkeypatch.setattr(
        research_composition, "load_jdj_candidate_manifest", lambda _id: object()
    )
    monkeypatch.setattr(
        research_composition, "load_jdj_candidate_validation_protocol", object
    )
    monkeypatch.setattr(
        research_composition,
        "JdjCandidateValidationService",
        lambda source, **_kwargs: result if source is research else None,
    )
    session = object()

    assert (
        research_composition.build_jdj_candidate_validation_service(
            session,
            "jdj_trend_follow_1m_candidate_v1",
        )
        is result
    )
    assert order == [("calendar", session), ("research", session)]


def test_jdj_active60_robustness_builder_reuses_existing_jdj_research(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    protocol = object()
    jdj_research = object()
    session = object()
    constructor_calls: list[tuple[object, object]] = []
    expected = object()
    monkeypatch.setattr(
        research_composition,
        "load_jdj_active60_robustness_protocol",
        lambda: protocol,
    )
    monkeypatch.setattr(
        research_composition,
        "build_jdj_research_service",
        lambda value: jdj_research if value is session else None,
    )
    monkeypatch.setattr(
        research_composition,
        "JdjActive60RobustnessService",
        lambda value, *, jdj_research: (
            constructor_calls.append((value, jdj_research)) or expected
        ),
    )

    service = research_composition.build_jdj_active60_robustness_service(
        session  # type: ignore[arg-type]
    )

    assert service is expected
    assert constructor_calls == [(protocol, jdj_research)]


def test_main_force_research_reuses_web_v2_service_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    mirror_service = SimpleNamespace(market_data=market_data)
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        "build_main_force_mirror_v2_service",
        lambda _session: mirror_service,
    )
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        _fail_dependency("duplicate MarketDataService"),
    )
    monkeypatch.setattr(
        research_composition,
        "MainForceMirrorV2ResearchService",
        lambda **kwargs: captured.update(kwargs) or result,
    )

    assert (
        research_composition.build_main_force_mirror_v2_research_service(object())
        is result
    )
    assert captured == {
        "market_data": market_data,
        "mirror_service": mirror_service,
    }


def test_main_force_diagnostic_reuses_one_v2_service_and_its_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    market_data = object()
    previous_trading_day = object()
    mirror_service = SimpleNamespace(
        market_data=market_data,
        coverage=SimpleNamespace(previous_trading_day=previous_trading_day),
    )
    captured: dict[str, object] = {}
    result = object()
    monkeypatch.setattr(
        research_composition,
        "build_main_force_mirror_v2_service",
        lambda _session: mirror_service,
    )
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        _fail_dependency("duplicate MarketDataService"),
    )
    monkeypatch.setattr(
        research_composition,
        "MainForceMirrorDiagnosticService",
        lambda **kwargs: captured.update(kwargs) or result,
    )
    for name in (
        "build_historical_data_manager",
        "build_live_market_service",
        "build_alert_runtime",
        "build_notification_sender_from_env",
    ):
        monkeypatch.setattr(
            research_composition,
            name,
            _fail_dependency(name),
            raising=False,
        )

    assert (
        research_composition.build_main_force_mirror_diagnostic_service(object())
        is result
    )
    assert captured == {
        "market_data": market_data,
        "mirror_service": mirror_service,
        "previous_trading_day": previous_trading_day,
    }


def test_robustness_builder_reuses_one_mds_and_frozen_active60(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    products = ("ag", "jm")
    protocol = SimpleNamespace(cross_symbol_products=products)
    market_data = object()
    build_calls: list[object] = []
    source_calls: list[tuple[str, object, tuple[str, ...]]] = []
    subing = object()
    n_structure = object()
    result = object()
    monkeypatch.setattr(
        research_composition,
        "load_multi_candidate_robustness_protocol",
        lambda: protocol,
    )
    monkeypatch.setattr(
        research_composition, "load_active_products", lambda: products
    )
    monkeypatch.setattr(
        research_composition,
        "build_market_data_service",
        lambda session: build_calls.append(session) or market_data,
    )
    monkeypatch.setattr(
        research_composition, "load_accepted_subing_calibration", object
    )
    monkeypatch.setattr(
        research_composition, "load_subing_lifecycle_policy", object
    )
    monkeypatch.setattr(
        research_composition, "load_n_structure_policy", object
    )
    monkeypatch.setattr(
        research_composition,
        "SubingLifecycleResearchService",
        lambda mds, *, products, **_kwargs: (
            source_calls.append(("subing", mds, products)) or subing
        ),
    )
    monkeypatch.setattr(
        research_composition,
        "ActualDominantResearchSegmentLoader",
        lambda mds: SimpleNamespace(market_data=mds),
    )
    monkeypatch.setattr(
        research_composition,
        "NStructureResearchService",
        lambda loader, *, products, **_kwargs: (
            source_calls.append(("n", loader.market_data, products)) or n_structure
        ),
    )
    monkeypatch.setattr(
        research_composition,
        "SubingCandidateValidationService",
        lambda source, **_kwargs: SimpleNamespace(source=source),
    )
    monkeypatch.setattr(
        research_composition,
        "NStructureCandidateValidationService",
        lambda source, **_kwargs: SimpleNamespace(source=source),
    )
    for name in (
        "load_candidate_manifest",
        "load_candidate_validation_protocol",
        "load_n_candidate_manifest",
        "load_n_candidate_validation_protocol",
    ):
        monkeypatch.setattr(research_composition, name, object)
    monkeypatch.setattr(
        research_composition,
        "MultiCandidateRobustnessService",
        lambda *_args, **_kwargs: result,
    )
    session = object()

    assert research_composition.build_multi_candidate_robustness_service(session) is result
    assert build_calls == [session]
    assert source_calls == [
        ("subing", market_data, products),
        ("n", market_data, products),
    ]
