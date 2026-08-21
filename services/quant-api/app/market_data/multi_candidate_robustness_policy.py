from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT


_PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/multi_candidate_robustness_v1.json"
)
_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": "multi_candidate_robustness_v1",
    "research_only": True,
    "frozen_at": "2026-08-20T21:33:00+08:00",
    "anchor_symbol": "jm",
    "candidates": [
        {
            "candidate_id": "subing_lifecycle_v2_candidate_v1",
            "source_kind": "subing_lifecycle",
            "policy_id": "subing_lifecycle_v2_research_v1",
            "formula_version": "subing_lifecycle_v2",
            "candidate_protocol_id": "candidate_validation_v1",
            "baseline_request_through": "2026-08-19",
            "source_event_kind": "entry_confirmed",
            "evaluable_unit": "5m_ready_boundary",
            "horizon_semantics": "same_trading_day_only",
        },
        {
            "candidate_id": "n_structure_5m_candidate_v1",
            "source_kind": "n_structure",
            "policy_id": "n_structure_5m_v1",
            "formula_version": "n_structure_v1",
            "candidate_protocol_id": "n_structure_validation_v1",
            "baseline_request_through": "2026-08-20",
            "source_event_kind": "n_completed",
            "evaluable_unit": "5m_canonical_bar",
            "horizon_semantics": "same_rank1_segment",
        },
    ],
    "common_retrospective": {"since": "2023-01-01", "through": "2026-08-18"},
    "cross_symbol_products": list(_PRODUCTS),
    "event_proximity_bars": [3, 5, 8],
    "parameter_perturbation": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class MultiCandidateRobustnessProtocolError(ValueError):
    code = "MULTI_CANDIDATE_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class RobustnessCandidateRef:
    candidate_id: str
    source_kind: str
    policy_id: str
    formula_version: str
    candidate_protocol_id: str
    baseline_request_through: date
    source_event_kind: str
    evaluable_unit: str
    horizon_semantics: str


@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessProtocol:
    schema_version: int
    protocol_id: str
    research_only: bool
    frozen_at: datetime
    anchor_symbol: str
    candidates: tuple[RobustnessCandidateRef, ...]
    common_since: date
    common_through: date
    cross_symbol_products: tuple[str, ...]
    event_proximity_bars: tuple[int, ...]
    parameter_perturbation: bool
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        expected_refs = tuple(_candidate_ref(value) for value in _EXPECTED["candidates"])
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != "multi_candidate_robustness_v1"
            or self.research_only is not True
            or type(self.frozen_at) is not datetime
            or self.frozen_at != datetime.fromisoformat("2026-08-20T21:33:00+08:00")
            or self.anchor_symbol != "jm"
            or self.candidates != expected_refs
            or self.common_since != date(2023, 1, 1)
            or self.common_through != date(2026, 8, 18)
            or self.cross_symbol_products != _PRODUCTS
            or self.event_proximity_bars != (3, 5, 8)
            or self.parameter_perturbation is not False
            or self.automatic_ranking is not False
            or self.automatic_promotion is not False
        ):
            raise MultiCandidateRobustnessProtocolError()


@dataclass(frozen=True, slots=True)
class MultiCandidateRobustnessRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != "multi_candidate_robustness_v1":
            raise MultiCandidateRobustnessProtocolError()


def load_multi_candidate_robustness_protocol(
    path: Path | None = None,
) -> MultiCandidateRobustnessProtocol:
    try:
        payload = json.loads((path or _PROTOCOL_PATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise MultiCandidateRobustnessProtocolError() from None
    if not _matches_exact(payload, _EXPECTED):
        raise MultiCandidateRobustnessProtocolError()
    assert isinstance(payload, dict)
    return MultiCandidateRobustnessProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        research_only=payload["research_only"],
        frozen_at=datetime.fromisoformat(payload["frozen_at"]),
        anchor_symbol=payload["anchor_symbol"],
        candidates=tuple(_candidate_ref(value) for value in payload["candidates"]),
        common_since=date.fromisoformat(payload["common_retrospective"]["since"]),
        common_through=date.fromisoformat(payload["common_retrospective"]["through"]),
        cross_symbol_products=tuple(payload["cross_symbol_products"]),
        event_proximity_bars=tuple(payload["event_proximity_bars"]),
        parameter_perturbation=payload["parameter_perturbation"],
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )


def _candidate_ref(value: dict[str, Any]) -> RobustnessCandidateRef:
    return RobustnessCandidateRef(
        candidate_id=value["candidate_id"],
        source_kind=value["source_kind"],
        policy_id=value["policy_id"],
        formula_version=value["formula_version"],
        candidate_protocol_id=value["candidate_protocol_id"],
        baseline_request_through=date.fromisoformat(value["baseline_request_through"]),
        source_event_kind=value["source_event_kind"],
        evaluable_unit=value["evaluable_unit"],
        horizon_semantics=value["horizon_semantics"],
    )


def _matches_exact(value: object, expected: object) -> bool:
    if type(value) is not type(expected):
        return False
    if isinstance(expected, dict):
        return (
            isinstance(value, dict)
            and value.keys() == expected.keys()
            and all(_matches_exact(value[key], item) for key, item in expected.items())
        )
    if isinstance(expected, list):
        return isinstance(value, list) and len(value) == len(expected) and all(
            _matches_exact(actual, item)
            for actual, item in zip(value, expected, strict=True)
        )
    return value == expected
