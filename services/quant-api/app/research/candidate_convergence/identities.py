"""Shared immutable identities for the five-Candidate convergence boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from types import MappingProxyType
from typing import Final


FIVE_CANDIDATE_ORDER: Final = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)

DOSSIER_PAIR_ORDER: Final = (
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[1]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[2]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[2]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[2], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[2], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[3], FIVE_CANDIDATE_ORDER[4]),
)

RELATIONSHIP_PAIR_ORDER: Final = (
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[1]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[2]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[1], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[2], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[2], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[3], FIVE_CANDIDATE_ORDER[4]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[2]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[3]),
    (FIVE_CANDIDATE_ORDER[0], FIVE_CANDIDATE_ORDER[4]),
)

JDJ_CANDIDATE_ORDER: Final = FIVE_CANDIDATE_ORDER[2:]
JDJ_RELATIONSHIP_PAIR_ORDER: Final = RELATIONSHIP_PAIR_ORDER[4:7]
SUBING_JDJ_PAIR_ORDER: Final = RELATIONSHIP_PAIR_ORDER[7:]

ACTIVE60_PRODUCTS: Final = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)

ACTIVE60_SECTORS: Final = (
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

CANDIDATE_EVENT_KINDS: Final[Mapping[str, str]] = MappingProxyType(
    {
        FIVE_CANDIDATE_ORDER[0]: "entry_confirmed",
        FIVE_CANDIDATE_ORDER[1]: "n_completed",
        FIVE_CANDIDATE_ORDER[2]: "jdj_trend_follow_triggered",
        FIVE_CANDIDATE_ORDER[3]: "jdj_trend_reentry_6_triggered",
        FIVE_CANDIDATE_ORDER[4]: "jdj_key_level_breakout_triggered",
    }
)

CANDIDATE_BASELINE_IDENTITIES: Final[
    Mapping[str, tuple[str, str, str, date, date, date, date]]
] = MappingProxyType(
    {
        FIVE_CANDIDATE_ORDER[0]: (
            "candidate_validation_v1",
            "subing_lifecycle_v2_research_v1",
            "subing_lifecycle_v2",
            date(2023, 1, 1),
            date(2026, 8, 18),
            date(2026, 8, 19),
            date(2026, 8, 20),
        ),
        FIVE_CANDIDATE_ORDER[1]: (
            "n_structure_validation_v1",
            "n_structure_5m_v1",
            "n_structure_v1",
            date(2023, 1, 1),
            date(2026, 8, 19),
            date(2026, 8, 20),
            date(2026, 8, 21),
        ),
        FIVE_CANDIDATE_ORDER[2]: (
            "jdj_candidate_validation_v1",
            "jdj_1m_policy_v1",
            "jdj_1m_v1",
            date(2023, 1, 1),
            date(2026, 8, 20),
            date(2026, 8, 21),
            date(2026, 8, 24),
        ),
        FIVE_CANDIDATE_ORDER[3]: (
            "jdj_candidate_validation_v1",
            "jdj_1m_policy_v1",
            "jdj_1m_v1",
            date(2023, 1, 1),
            date(2026, 8, 20),
            date(2026, 8, 21),
            date(2026, 8, 24),
        ),
        FIVE_CANDIDATE_ORDER[4]: (
            "jdj_candidate_validation_v1",
            "jdj_1m_policy_v1",
            "jdj_1m_v1",
            date(2023, 1, 1),
            date(2026, 8, 20),
            date(2026, 8, 21),
            date(2026, 8, 24),
        ),
    }
)
