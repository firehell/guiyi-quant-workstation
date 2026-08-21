from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

from app.market_data import composition as market_data_composition


_RESEARCH_BUILDERS = (
    "build_subing_calibration_research_service",
    "build_subing_lifecycle_research_service",
    "build_subing_candidate_validation_service",
    "build_n_structure_research_service",
    "build_n_candidate_validation_service",
    "build_jdj_research_service",
    "build_jdj_candidate_validation_service",
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
