from __future__ import annotations

import importlib

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


def test_offline_research_builders_have_one_composition_entrypoint() -> None:
    research_composition = importlib.import_module("app.research.composition")
    assert all(hasattr(research_composition, name) for name in _RESEARCH_BUILDERS)
    assert not any(hasattr(market_data_composition, name) for name in _RESEARCH_BUILDERS)
