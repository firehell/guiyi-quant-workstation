from __future__ import annotations

from datetime import date
import importlib
import importlib.util
from types import MappingProxyType

import pytest


CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)


def _identities_module():
    module_name = "app.research.candidate_convergence.identities"
    assert importlib.util.find_spec(module_name) is not None
    return importlib.import_module(module_name)


def test_candidate_convergence_orders_preserve_frozen_identity() -> None:
    identities = _identities_module()

    assert identities.FIVE_CANDIDATE_ORDER == CANDIDATES
    assert identities.DOSSIER_PAIR_ORDER == (
        (CANDIDATES[0], CANDIDATES[1]),
        (CANDIDATES[0], CANDIDATES[2]),
        (CANDIDATES[0], CANDIDATES[3]),
        (CANDIDATES[0], CANDIDATES[4]),
        (CANDIDATES[1], CANDIDATES[2]),
        (CANDIDATES[1], CANDIDATES[3]),
        (CANDIDATES[1], CANDIDATES[4]),
        (CANDIDATES[2], CANDIDATES[3]),
        (CANDIDATES[2], CANDIDATES[4]),
        (CANDIDATES[3], CANDIDATES[4]),
    )
    assert identities.RELATIONSHIP_PAIR_ORDER == (
        (CANDIDATES[0], CANDIDATES[1]),
        (CANDIDATES[1], CANDIDATES[2]),
        (CANDIDATES[1], CANDIDATES[3]),
        (CANDIDATES[1], CANDIDATES[4]),
        (CANDIDATES[2], CANDIDATES[3]),
        (CANDIDATES[2], CANDIDATES[4]),
        (CANDIDATES[3], CANDIDATES[4]),
        (CANDIDATES[0], CANDIDATES[2]),
        (CANDIDATES[0], CANDIDATES[3]),
        (CANDIDATES[0], CANDIDATES[4]),
    )


def test_candidate_convergence_active60_and_sector_orders_are_exact() -> None:
    identities = _identities_module()

    assert identities.ACTIVE60_PRODUCTS == (
        "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
        "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
        "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
        "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
        "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
        "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
    )
    assert identities.ACTIVE60_SECTORS == (
        "agriculture",
        "precious",
        "nonferrous",
        "energy",
        "chemical",
        "other",
        "building",
        "steel",
        "black",
        "new_energy",
    )


def test_candidate_convergence_mappings_are_deeply_immutable() -> None:
    identities = _identities_module()

    assert isinstance(identities.CANDIDATE_EVENT_KINDS, MappingProxyType)
    assert dict(identities.CANDIDATE_EVENT_KINDS) == {
        CANDIDATES[0]: "entry_confirmed",
        CANDIDATES[1]: "n_completed",
        CANDIDATES[2]: "jdj_trend_follow_triggered",
        CANDIDATES[3]: "jdj_trend_reentry_6_triggered",
        CANDIDATES[4]: "jdj_key_level_breakout_triggered",
    }
    assert isinstance(identities.CANDIDATE_BASELINE_IDENTITIES, MappingProxyType)
    assert identities.CANDIDATE_BASELINE_IDENTITIES[CANDIDATES[0]] == (
        "candidate_validation_v1",
        "subing_lifecycle_v2_research_v1",
        "subing_lifecycle_v2",
        date(2023, 1, 1),
        date(2026, 8, 18),
        date(2026, 8, 19),
        date(2026, 8, 20),
    )
    with pytest.raises(TypeError):
        identities.CANDIDATE_EVENT_KINDS[CANDIDATES[0]] = "changed"
    with pytest.raises(TypeError):
        identities.CANDIDATE_BASELINE_IDENTITIES[CANDIDATES[0]] = ()
