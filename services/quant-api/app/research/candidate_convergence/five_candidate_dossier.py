from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from app.core.env import PROJECT_ROOT
from app.market_data.exact_json_contract import load_exact_json
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    SourceArtifactRef,
)


_PROTOCOL_PATH = (
    PROJECT_ROOT / "data/research_protocols/five_candidate_research_dossier_v1.json"
)
_CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
_SOURCE_ARTIFACTS = (
    (
        "subing_lifecycle_v2_candidate_v1",
        "reports/research/candidate_validation/subing_lifecycle_v2_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-19.json",
        "1a1b3064dcb9084adc7347e024c001a2fe7c4bb7ba909c6c80f31659ecc3b3d1",
    ),
    (
        "n_structure_5m_candidate_v1",
        "reports/research/candidate_validation/n_structure_5m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-20.json",
        "12fed018751ae54d5bfd2d24897cc077c513560ac1377935e5fddd14a36a3fc6",
    ),
    (
        "jdj_trend_follow_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_trend_follow_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "63a9f3021ae30eab777d838c39493f1ef195c07edc49f5471cbbb2de98621fef",
    ),
    (
        "jdj_trend_reentry_6_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_trend_reentry_6_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "63f9dfdd29eabfa2c7b44fbe24aa31198dddffae60fab856e9d1b2684cb35bea",
    ),
    (
        "jdj_key_level_breakout_1m_candidate_v1",
        "reports/research/candidate_validation/jdj_key_level_breakout_1m_candidate_v1/"
        "jm-retrospective-baseline-freeze-2026-08-21.json",
        "6e06b894bb05a0de2c857be0143cdd44d0b7479b33ad712a0db88197bbdcab10",
    ),
    (
        "multi_candidate_robustness_v1",
        "reports/research/candidate_robustness/multi_candidate_robustness_v1/"
        "anchor-jm-active60-retrospective-freeze-2026-08-20.json",
        "6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433",
    ),
    (
        "jdj_active60_robustness_v1",
        "reports/research/candidate_robustness/jdj_active60_robustness_v1/"
        "active60-retrospective-freeze-2026-08-21.json",
        "f6078a5bc9d3071cb6f0366982dc709cf95087b5ec8b1872b72d1fd4b7790d87",
    ),
)
_PAIR_ORDER = (
    (_CANDIDATES[0], _CANDIDATES[1]),
    (_CANDIDATES[0], _CANDIDATES[2]),
    (_CANDIDATES[0], _CANDIDATES[3]),
    (_CANDIDATES[0], _CANDIDATES[4]),
    (_CANDIDATES[1], _CANDIDATES[2]),
    (_CANDIDATES[1], _CANDIDATES[3]),
    (_CANDIDATES[1], _CANDIDATES[4]),
    (_CANDIDATES[2], _CANDIDATES[3]),
    (_CANDIDATES[2], _CANDIDATES[4]),
    (_CANDIDATES[3], _CANDIDATES[4]),
)
_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": "five_candidate_research_dossier_v1",
    "frozen_at": "2026-08-22T11:43:34+08:00",
    "research_only": True,
    "readonly": True,
    "candidate_order": list(_CANDIDATES),
    "source_artifacts": [
        {
            "artifact_id": artifact_id,
            "path": path,
            "expected_sha256": expected_sha256,
        }
        for artifact_id, path, expected_sha256 in _SOURCE_ARTIFACTS
    ],
    "comparability_pair_order": [list(pair) for pair in _PAIR_ORDER],
    "prospective_consumed": False,
    "new_metric_calculation": False,
    "new_relationship_calculation": False,
    "parameter_perturbation": False,
    "automatic_scoring": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class FiveCandidateDossierProtocolError(ValueError):
    code = "FIVE_CANDIDATE_DOSSIER_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class FiveCandidateDossierProtocol:
    schema_version: int
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    candidate_order: tuple[str, ...]
    source_artifacts: tuple[SourceArtifactRef, ...]
    comparability_pair_order: tuple[tuple[str, str], ...]
    prospective_consumed: bool
    new_metric_calculation: bool
    new_relationship_calculation: bool
    parameter_perturbation: bool
    automatic_scoring: bool
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != "five_candidate_research_dossier_v1"
            or self.frozen_at
            != datetime.fromisoformat("2026-08-22T11:43:34+08:00")
            or self.research_only is not True
            or self.readonly is not True
            or self.candidate_order != _CANDIDATES
            or self.source_artifacts
            != tuple(SourceArtifactRef(*values) for values in _SOURCE_ARTIFACTS)
            or self.comparability_pair_order != _PAIR_ORDER
            or self.prospective_consumed is not False
            or self.new_metric_calculation is not False
            or self.new_relationship_calculation is not False
            or self.parameter_perturbation is not False
            or self.automatic_scoring is not False
            or self.automatic_ranking is not False
            or self.automatic_promotion is not False
        ):
            raise FiveCandidateDossierProtocolError()


@dataclass(frozen=True, slots=True)
class FiveCandidateDossierRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != "five_candidate_research_dossier_v1":
            raise FiveCandidateDossierProtocolError()


def load_five_candidate_dossier_protocol(
    path: Path | None = None,
) -> FiveCandidateDossierProtocol:
    payload = load_exact_json(
        path or _PROTOCOL_PATH,
        _EXPECTED,
        FiveCandidateDossierProtocolError,
    )
    try:
        source_artifacts = tuple(
            SourceArtifactRef(
                artifact_id=value["artifact_id"],
                path=value["path"],
                expected_sha256=value["expected_sha256"],
            )
            for value in payload["source_artifacts"]
        )
    except FiveCandidateDossierSourceError:
        raise FiveCandidateDossierProtocolError() from None
    return FiveCandidateDossierProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        frozen_at=datetime.fromisoformat(payload["frozen_at"]),
        research_only=payload["research_only"],
        readonly=payload["readonly"],
        candidate_order=tuple(payload["candidate_order"]),
        source_artifacts=source_artifacts,
        comparability_pair_order=tuple(
            tuple(pair) for pair in payload["comparability_pair_order"]
        ),
        prospective_consumed=payload["prospective_consumed"],
        new_metric_calculation=payload["new_metric_calculation"],
        new_relationship_calculation=payload["new_relationship_calculation"],
        parameter_perturbation=payload["parameter_perturbation"],
        automatic_scoring=payload["automatic_scoring"],
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )
