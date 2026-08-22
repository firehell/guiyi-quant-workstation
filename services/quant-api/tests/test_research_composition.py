from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.market_data import composition as market_data_composition
from app.research import composition as research_composition


_RESEARCH_BUILDERS = (
    "build_subing_calibration_research_service",
    "build_subing_lifecycle_research_service",
    "build_subing_candidate_validation_service",
    "build_n_structure_research_service",
    "build_n_candidate_validation_service",
    "build_jdj_research_service",
    "build_jdj_candidate_validation_service",
    "build_jdj_active60_robustness_service",
    "build_multi_candidate_robustness_service",
    "build_main_force_mirror_v2_research_service",
)

_RESEARCH_IMPLEMENTATION_MODULES = (
    "app.research.common.candidate_validation_schedule",
    "app.research.subing.subing_calibration_service",
    "app.research.subing.subing_lifecycle_research_service",
    "app.research.subing.candidate_validation",
    "app.research.subing.candidate_validation_policy",
    "app.research.subing.subing_candidate_validation_service",
    "app.research.n_structure.n_structure_policy",
    "app.research.n_structure.n_structure_swing",
    "app.research.n_structure.n_structure_pattern",
    "app.research.n_structure.n_structure_state",
    "app.research.n_structure.n_structure_segment",
    "app.research.n_structure.n_structure_research_service",
    "app.research.n_structure.n_candidate_validation",
    "app.research.n_structure.n_candidate_validation_policy",
    "app.research.n_structure.n_candidate_validation_service",
    "app.research.jdj.jdj_policy",
    "app.research.jdj.jdj_context",
    "app.research.jdj.jdj_events",
    "app.research.jdj.jdj_trend_follow",
    "app.research.jdj.jdj_trend_reentry",
    "app.research.jdj.jdj_key_level_breakout",
    "app.research.jdj.jdj_research",
    "app.research.jdj.jdj_research_service",
    "app.research.jdj.jdj_candidate_validation",
    "app.research.jdj.jdj_candidate_validation_calendar",
    "app.research.jdj.jdj_candidate_validation_policy",
    "app.research.jdj.jdj_candidate_validation_service",
    "app.research.main_force.main_force_mirror_v2_research_service",
    "app.research.robustness.multi_candidate_robustness",
    "app.research.robustness.multi_candidate_events",
    "app.research.robustness.multi_candidate_robustness_policy",
    "app.research.robustness.multi_candidate_robustness_service",
    "app.research.robustness.jdj_robustness",
    "app.research.robustness.jdj_robustness_service",
)

_RUNTIME_BOUNDARY_PATHS = (
    Path("services/quant-api/app/alerts"),
    Path("services/quant-api/app/market_data"),
    Path("services/quant-api/app/api/market.py"),
    Path("services/quant-api/app/api/market_live.py"),
)


def test_offline_research_builders_have_one_composition_entrypoint() -> None:
    research_composition = importlib.import_module("app.research.composition")
    assert all(hasattr(research_composition, name) for name in _RESEARCH_BUILDERS)
    assert not any(hasattr(market_data_composition, name) for name in _RESEARCH_BUILDERS)


def test_offline_research_implementation_has_one_physical_package() -> None:
    for module in _RESEARCH_IMPLEMENTATION_MODULES:
        assert importlib.util.find_spec(module) is not None, module
        old_module = f"app.market_data.{module.rsplit('.', 1)[-1]}"
        assert importlib.util.find_spec(old_module) is None, old_module


def test_runtime_market_and_alert_do_not_import_offline_research() -> None:
    source_paths: list[Path] = []
    for boundary in _RUNTIME_BOUNDARY_PATHS:
        source_paths.extend(
            boundary.rglob("*.py") if boundary.is_dir() else (boundary,)
        )
    for path in source_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imports = (
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        )
        assert not any(
            module == "app.research" or module.startswith("app.research.")
            for module in imports
        ), path


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
