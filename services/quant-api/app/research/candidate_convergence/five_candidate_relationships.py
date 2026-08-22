from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import Any

from app.core.env import PROJECT_ROOT
from app.market_data.exact_json_contract import load_exact_json
from app.research.candidate_convergence.artifact_source import (
    FiveCandidateDossierSourceError,
    SourceArtifactRef,
)


_PROTOCOL_ID = "five_candidate_relationship_topology_v1"
_PROTOCOL_PATH = (
    PROJECT_ROOT
    / "data/research_protocols/five_candidate_relationship_topology_v1.json"
)
_FROZEN_AT_TEXT = "2026-08-22T14:01:54+08:00"

RELATIONSHIP_CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
)
_SUBING, _N, _TF, _R6, _KLB = RELATIONSHIP_CANDIDATES
RELATIONSHIP_JDJ_CANDIDATES = (_TF, _R6, _KLB)
RELATIONSHIP_PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
RELATIONSHIP_PAIR_ORDER = (
    (_SUBING, _N),
    (_N, _TF),
    (_N, _R6),
    (_N, _KLB),
    (_TF, _R6),
    (_TF, _KLB),
    (_R6, _KLB),
    (_SUBING, _TF),
    (_SUBING, _R6),
    (_SUBING, _KLB),
)
RELATIONSHIP_JDJ_PAIRS = ((_TF, _R6), (_TF, _KLB), (_R6, _KLB))
_SUBING_JDJ_PAIRS = ((_SUBING, _TF), (_SUBING, _R6), (_SUBING, _KLB))
_N_JDJ_SINCE = date(2023, 1, 1)
_N_JDJ_THROUGH = date(2026, 8, 19)
_JDJ_OVERLAP_SINCE = date(2023, 1, 1)
_JDJ_OVERLAP_THROUGH = date(2026, 8, 20)
_DOSSIER_SOURCE_VALUES = (
    "five_candidate_research_dossier_v1",
    "reports/research/candidate_dossier/"
    "five_candidate_research_dossier_v1/"
    "five-candidate-retrospective-evidence-freeze-2026-08-22.json",
    "632c7b88bc3dfaf15d9640f32d014b9af0665376959e10c73101956cdc81ee99",
)
_SUBING_N_SOURCE_VALUES = (
    "multi_candidate_robustness_v1",
    "reports/research/candidate_robustness/multi_candidate_robustness_v1/"
    "anchor-jm-active60-retrospective-freeze-2026-08-20.json",
    "6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433",
)


class RelationshipKind(StrEnum):
    EXISTING_EVENT_RELATIONSHIP = "EXISTING_EVENT_RELATIONSHIP"
    STRUCTURAL_CONTEXT_DEPENDENCY = "STRUCTURAL_CONTEXT_DEPENDENCY"
    EXACT_SAME_BOUNDARY_OVERLAP = "EXACT_SAME_BOUNDARY_OVERLAP"
    UNDEFINED_CROSS_TIMEFRAME = "UNDEFINED_CROSS_TIMEFRAME"


class DependencyRole(StrEnum):
    TREND_FILTER = "trend_filter"
    TREND_AND_PIVOT_SOURCE = "trend_and_pivot_source"


_RELATIONSHIP_KINDS = (
    RelationshipKind.EXISTING_EVENT_RELATIONSHIP,
    RelationshipKind.STRUCTURAL_CONTEXT_DEPENDENCY,
    RelationshipKind.STRUCTURAL_CONTEXT_DEPENDENCY,
    RelationshipKind.STRUCTURAL_CONTEXT_DEPENDENCY,
    RelationshipKind.EXACT_SAME_BOUNDARY_OVERLAP,
    RelationshipKind.EXACT_SAME_BOUNDARY_OVERLAP,
    RelationshipKind.EXACT_SAME_BOUNDARY_OVERLAP,
    RelationshipKind.UNDEFINED_CROSS_TIMEFRAME,
    RelationshipKind.UNDEFINED_CROSS_TIMEFRAME,
    RelationshipKind.UNDEFINED_CROSS_TIMEFRAME,
)
_DEPENDENCY_ROLES = (
    (_TF, DependencyRole.TREND_FILTER),
    (_R6, DependencyRole.TREND_FILTER),
    (_KLB, DependencyRole.TREND_AND_PIVOT_SOURCE),
)
_SAFETY = {
    "future_outcomes": False,
    "parameter_perturbation": False,
    "automatic_scoring": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


def _artifact_json(values: tuple[str, str, str]) -> dict[str, str]:
    artifact_id, path, expected_sha256 = values
    return {
        "artifact_id": artifact_id,
        "path": path,
        "expected_sha256": expected_sha256,
    }


_EXPECTED: dict[str, Any] = {
    "schema_version": 1,
    "protocol_id": _PROTOCOL_ID,
    "frozen_at": _FROZEN_AT_TEXT,
    "research_only": True,
    "readonly": True,
    "candidate_order": list(RELATIONSHIP_CANDIDATES),
    "pair_order": [list(pair) for pair in RELATIONSHIP_PAIR_ORDER],
    "relationship_catalog": [
        {
            "left_candidate_id": left,
            "right_candidate_id": right,
            "relation_kind": kind.value,
        }
        for (left, right), kind in zip(
            RELATIONSHIP_PAIR_ORDER,
            _RELATIONSHIP_KINDS,
            strict=True,
        )
    ],
    "cross_symbol_products": list(RELATIONSHIP_PRODUCTS),
    "dossier_source": _artifact_json(_DOSSIER_SOURCE_VALUES),
    "analyses": {
        "subing_n": {
            "relation_kind": RelationshipKind.EXISTING_EVENT_RELATIONSHIP.value,
            "source": _artifact_json(_SUBING_N_SOURCE_VALUES),
            "recompute": False,
        },
        "n_jdj_context_dependency": {
            "relation_kind": RelationshipKind.STRUCTURAL_CONTEXT_DEPENDENCY.value,
            "since": "2023-01-01",
            "through": "2026-08-19",
            "candidates": list(RELATIONSHIP_JDJ_CANDIDATES),
            "dependency_roles": [
                {"candidate_id": candidate_id, "role": role.value}
                for candidate_id, role in _DEPENDENCY_ROLES
            ],
            "proximity": None,
            "future_outcomes": False,
        },
        "jdj_exact_overlap": {
            "relation_kind": RelationshipKind.EXACT_SAME_BOUNDARY_OVERLAP.value,
            "since": "2023-01-01",
            "through": "2026-08-20",
            "pairs": [list(pair) for pair in RELATIONSHIP_JDJ_PAIRS],
            "proximity": None,
            "future_outcomes": False,
        },
        "subing_jdj": {
            "relation_kind": RelationshipKind.UNDEFINED_CROSS_TIMEFRAME.value,
            "pairs": [list(pair) for pair in _SUBING_JDJ_PAIRS],
            "recompute": False,
        },
    },
    "prospective_consumed": False,
    "parameter_perturbation": False,
    "automatic_scoring": False,
    "automatic_ranking": False,
    "automatic_promotion": False,
}


class FiveCandidateRelationshipProtocolError(ValueError):
    code = "FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class FiveCandidateRelationshipSourceError(ValueError):
    code = "FIVE_CANDIDATE_RELATIONSHIP_SOURCE_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


class FiveCandidateRelationshipReportError(ValueError):
    code = "FIVE_CANDIDATE_RELATIONSHIP_REPORT_INVALID"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class FiveCandidateRelationshipProtocol:
    schema_version: int
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    candidate_order: tuple[str, ...]
    pair_order: tuple[tuple[str, str], ...]
    relationship_kinds: tuple[RelationshipKind, ...]
    cross_symbol_products: tuple[str, ...]
    dossier_source: SourceArtifactRef
    subing_n_source: SourceArtifactRef
    subing_n_recompute: bool
    n_jdj_candidate_order: tuple[str, ...]
    n_jdj_dependency_roles: tuple[tuple[str, DependencyRole], ...]
    n_jdj_since: date
    n_jdj_through: date
    n_jdj_proximity: int | None
    n_jdj_future_outcomes: bool
    jdj_overlap_pair_order: tuple[tuple[str, str], ...]
    jdj_overlap_since: date
    jdj_overlap_through: date
    jdj_overlap_proximity: int | None
    jdj_overlap_future_outcomes: bool
    subing_jdj_pair_order: tuple[tuple[str, str], ...]
    subing_jdj_recompute: bool
    prospective_consumed: bool
    parameter_perturbation: bool
    automatic_scoring: bool
    automatic_ranking: bool
    automatic_promotion: bool

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.protocol_id != _PROTOCOL_ID
            or type(self.frozen_at) is not datetime
            or self.frozen_at.isoformat() != _FROZEN_AT_TEXT
            or self.research_only is not True
            or self.readonly is not True
            or self.candidate_order != RELATIONSHIP_CANDIDATES
            or self.pair_order != RELATIONSHIP_PAIR_ORDER
            or self.relationship_kinds != _RELATIONSHIP_KINDS
            or self.cross_symbol_products != RELATIONSHIP_PRODUCTS
            or self.dossier_source != SourceArtifactRef(*_DOSSIER_SOURCE_VALUES)
            or self.subing_n_source != SourceArtifactRef(*_SUBING_N_SOURCE_VALUES)
            or self.subing_n_recompute is not False
            or self.n_jdj_candidate_order != RELATIONSHIP_JDJ_CANDIDATES
            or self.n_jdj_dependency_roles != _DEPENDENCY_ROLES
            or self.n_jdj_since != _N_JDJ_SINCE
            or self.n_jdj_through != _N_JDJ_THROUGH
            or self.n_jdj_proximity is not None
            or self.n_jdj_future_outcomes is not False
            or self.jdj_overlap_pair_order != RELATIONSHIP_JDJ_PAIRS
            or self.jdj_overlap_since != _JDJ_OVERLAP_SINCE
            or self.jdj_overlap_through != _JDJ_OVERLAP_THROUGH
            or self.jdj_overlap_proximity is not None
            or self.jdj_overlap_future_outcomes is not False
            or self.subing_jdj_pair_order != _SUBING_JDJ_PAIRS
            or self.subing_jdj_recompute is not False
            or self.prospective_consumed is not False
            or self.parameter_perturbation is not False
            or self.automatic_scoring is not False
            or self.automatic_ranking is not False
            or self.automatic_promotion is not False
        ):
            raise FiveCandidateRelationshipProtocolError()

    @property
    def future_outcomes(self) -> bool:
        return self.n_jdj_future_outcomes or self.jdj_overlap_future_outcomes


@dataclass(frozen=True, slots=True)
class FiveCandidateRelationshipRequest:
    protocol_id: str

    def __post_init__(self) -> None:
        if self.protocol_id != _PROTOCOL_ID:
            raise FiveCandidateRelationshipProtocolError()


@dataclass(frozen=True, slots=True)
class RelationshipCatalogEntry:
    left_candidate_id: str
    right_candidate_id: str
    relation_kind: RelationshipKind

    def __post_init__(self) -> None:
        identity = (self.left_candidate_id, self.right_candidate_id)
        try:
            index = RELATIONSHIP_PAIR_ORDER.index(identity)
        except ValueError:
            raise FiveCandidateRelationshipReportError() from None
        if (
            type(self.relation_kind) is not RelationshipKind
            or self.relation_kind is not _RELATIONSHIP_KINDS[index]
        ):
            raise FiveCandidateRelationshipReportError()


@dataclass(frozen=True, slots=True)
class ExistingRelationshipReference:
    left_candidate_id: str
    right_candidate_id: str
    relation_kind: RelationshipKind
    source: SourceArtifactRef
    recompute: bool

    def __post_init__(self) -> None:
        if (
            (self.left_candidate_id, self.right_candidate_id)
            != RELATIONSHIP_PAIR_ORDER[0]
            or self.relation_kind
            is not RelationshipKind.EXISTING_EVENT_RELATIONSHIP
            or self.source != SourceArtifactRef(*_SUBING_N_SOURCE_VALUES)
            or self.recompute is not False
        ):
            raise FiveCandidateRelationshipReportError()


@dataclass(frozen=True, slots=True)
class CandidateDependencyResult:
    candidate_id: str
    symbol: str
    dependency_role: DependencyRole
    status: str
    reason_code: str | None
    event_count: int | None
    events_with_trend_snapshot_lineage: int | None
    events_with_exact_pivot_lineage: int | None

    def __post_init__(self) -> None:
        expected_roles = dict(_DEPENDENCY_ROLES)
        if (
            self.candidate_id not in expected_roles
            or self.symbol not in RELATIONSHIP_PRODUCTS
            or type(self.dependency_role) is not DependencyRole
            or self.dependency_role is not expected_roles[self.candidate_id]
            or self.status not in {"available", "unavailable"}
        ):
            raise FiveCandidateRelationshipReportError()
        metrics = (
            self.event_count,
            self.events_with_trend_snapshot_lineage,
            self.events_with_exact_pivot_lineage,
        )
        if self.status == "unavailable":
            if (
                self.reason_code != "JDJ_SOURCE_UNAVAILABLE"
                or any(value is not None for value in metrics)
            ):
                raise FiveCandidateRelationshipReportError()
            return
        if (
            self.reason_code is not None
            or not _nonnegative_int(self.event_count)
            or self.events_with_trend_snapshot_lineage != self.event_count
        ):
            raise FiveCandidateRelationshipReportError()
        expected_pivot_lineage = self.event_count if self.candidate_id == _KLB else None
        if self.events_with_exact_pivot_lineage != expected_pivot_lineage:
            raise FiveCandidateRelationshipReportError()


@dataclass(frozen=True, slots=True)
class JdjExactOverlapResult:
    left_candidate_id: str
    right_candidate_id: str
    symbol: str
    status: str
    reason_code: str | None
    left_event_count: int | None
    right_event_count: int | None
    exact_same_boundary_same_direction_count: int | None
    exact_same_boundary_opposite_direction_count: int | None
    left_events_with_same_direction_match: int | None
    right_events_with_same_direction_match: int | None

    def __post_init__(self) -> None:
        if (
            (self.left_candidate_id, self.right_candidate_id)
            not in RELATIONSHIP_JDJ_PAIRS
            or self.symbol not in RELATIONSHIP_PRODUCTS
            or self.status not in {"available", "unavailable"}
        ):
            raise FiveCandidateRelationshipReportError()
        metrics = (
            self.left_event_count,
            self.right_event_count,
            self.exact_same_boundary_same_direction_count,
            self.exact_same_boundary_opposite_direction_count,
            self.left_events_with_same_direction_match,
            self.right_events_with_same_direction_match,
        )
        if self.status == "unavailable":
            if (
                self.reason_code != "JDJ_SOURCE_UNAVAILABLE"
                or any(value is not None for value in metrics)
            ):
                raise FiveCandidateRelationshipReportError()
            return
        if self.reason_code is not None or any(
            not _nonnegative_int(value) for value in metrics
        ):
            raise FiveCandidateRelationshipReportError()
        assert self.left_event_count is not None
        assert self.right_event_count is not None
        assert self.exact_same_boundary_same_direction_count is not None
        assert self.exact_same_boundary_opposite_direction_count is not None
        assert self.left_events_with_same_direction_match is not None
        assert self.right_events_with_same_direction_match is not None
        if (
            self.left_events_with_same_direction_match > self.left_event_count
            or self.right_events_with_same_direction_match > self.right_event_count
            or self.exact_same_boundary_same_direction_count
            < self.left_events_with_same_direction_match
            or self.exact_same_boundary_same_direction_count
            < self.right_events_with_same_direction_match
            or self.exact_same_boundary_same_direction_count
            > self.left_events_with_same_direction_match
            * self.right_events_with_same_direction_match
            or self.exact_same_boundary_same_direction_count
            + self.exact_same_boundary_opposite_direction_count
            > self.left_event_count * self.right_event_count
        ):
            raise FiveCandidateRelationshipReportError()


@dataclass(frozen=True, slots=True)
class FiveCandidateRelationshipReport:
    schema_version: int
    command: str
    status: str
    protocol_id: str
    frozen_at: datetime
    research_only: bool
    readonly: bool
    prospective_consumed: bool
    candidate_order: tuple[str, ...]
    pair_order: tuple[tuple[str, str], ...]
    relationship_catalog: tuple[RelationshipCatalogEntry, ...]
    existing_relationship_references: tuple[ExistingRelationshipReference, ...]
    n_jdj_dependency_results: tuple[CandidateDependencyResult, ...]
    jdj_exact_overlap_results: tuple[JdjExactOverlapResult, ...]
    quality_flags: tuple[str, ...]
    safety: Mapping[str, bool]

    def __post_init__(self) -> None:
        catalog = tuple(self.relationship_catalog)
        references = tuple(self.existing_relationship_references)
        dependency_rows = tuple(self.n_jdj_dependency_results)
        overlap_rows = tuple(self.jdj_exact_overlap_results)
        quality_flags = tuple(self.quality_flags)
        safety = dict(self.safety)
        expected_dependencies = tuple(
            (candidate_id, symbol)
            for candidate_id in RELATIONSHIP_JDJ_CANDIDATES
            for symbol in RELATIONSHIP_PRODUCTS
        )
        expected_overlaps = tuple(
            (left, right, symbol)
            for left, right in RELATIONSHIP_JDJ_PAIRS
            for symbol in RELATIONSHIP_PRODUCTS
        )
        has_unavailable = any(
            row.status == "unavailable"
            for row in (*dependency_rows, *overlap_rows)
            if isinstance(row, (CandidateDependencyResult, JdjExactOverlapResult))
        )
        expected_quality_flags = (
            ("JDJ_SOURCE_UNAVAILABLE_PRESENT",) if has_unavailable else ()
        )
        if (
            type(self.schema_version) is not int
            or self.schema_version != 1
            or self.command
            != (
                "guiyi research candidate-relationships "
                "--protocol five_candidate_relationship_topology_v1"
            )
            or self.status != "ok"
            or self.protocol_id != _PROTOCOL_ID
            or type(self.frozen_at) is not datetime
            or self.frozen_at.isoformat() != _FROZEN_AT_TEXT
            or self.research_only is not True
            or self.readonly is not True
            or self.prospective_consumed is not False
            or tuple(self.candidate_order) != RELATIONSHIP_CANDIDATES
            or tuple(self.pair_order) != RELATIONSHIP_PAIR_ORDER
            or len(catalog) != 10
            or any(not isinstance(item, RelationshipCatalogEntry) for item in catalog)
            or tuple(
                (item.left_candidate_id, item.right_candidate_id, item.relation_kind)
                for item in catalog
            )
            != tuple(
                (left, right, kind)
                for (left, right), kind in zip(
                    RELATIONSHIP_PAIR_ORDER,
                    _RELATIONSHIP_KINDS,
                    strict=True,
                )
            )
            or references
            != (
                ExistingRelationshipReference(
                    left_candidate_id=_SUBING,
                    right_candidate_id=_N,
                    relation_kind=RelationshipKind.EXISTING_EVENT_RELATIONSHIP,
                    source=SourceArtifactRef(*_SUBING_N_SOURCE_VALUES),
                    recompute=False,
                ),
            )
            or len(dependency_rows) != 180
            or any(
                not isinstance(item, CandidateDependencyResult)
                for item in dependency_rows
            )
            or tuple((item.candidate_id, item.symbol) for item in dependency_rows)
            != expected_dependencies
            or len(overlap_rows) != 180
            or any(not isinstance(item, JdjExactOverlapResult) for item in overlap_rows)
            or tuple(
                (item.left_candidate_id, item.right_candidate_id, item.symbol)
                for item in overlap_rows
            )
            != expected_overlaps
            or quality_flags != expected_quality_flags
            or safety != _SAFETY
            or any(type(value) is not bool for value in safety.values())
        ):
            raise FiveCandidateRelationshipReportError()
        object.__setattr__(self, "candidate_order", tuple(self.candidate_order))
        object.__setattr__(self, "pair_order", tuple(self.pair_order))
        object.__setattr__(self, "relationship_catalog", catalog)
        object.__setattr__(self, "existing_relationship_references", references)
        object.__setattr__(self, "n_jdj_dependency_results", dependency_rows)
        object.__setattr__(self, "jdj_exact_overlap_results", overlap_rows)
        object.__setattr__(self, "quality_flags", quality_flags)
        object.__setattr__(self, "safety", MappingProxyType(safety))


def load_five_candidate_relationship_protocol(
    path: Path | None = None,
) -> FiveCandidateRelationshipProtocol:
    payload = load_exact_json(
        path or _PROTOCOL_PATH,
        _EXPECTED,
        FiveCandidateRelationshipProtocolError,
    )
    analyses = payload["analyses"]
    subing_n = analyses["subing_n"]
    dependency = analyses["n_jdj_context_dependency"]
    overlap = analyses["jdj_exact_overlap"]
    subing_jdj = analyses["subing_jdj"]
    try:
        dossier_source = _source_ref(payload["dossier_source"])
        subing_n_source = _source_ref(subing_n["source"])
    except FiveCandidateDossierSourceError:
        raise FiveCandidateRelationshipProtocolError() from None
    return FiveCandidateRelationshipProtocol(
        schema_version=payload["schema_version"],
        protocol_id=payload["protocol_id"],
        frozen_at=datetime.fromisoformat(payload["frozen_at"]),
        research_only=payload["research_only"],
        readonly=payload["readonly"],
        candidate_order=tuple(payload["candidate_order"]),
        pair_order=tuple(tuple(pair) for pair in payload["pair_order"]),
        relationship_kinds=tuple(
            RelationshipKind(item["relation_kind"])
            for item in payload["relationship_catalog"]
        ),
        cross_symbol_products=tuple(payload["cross_symbol_products"]),
        dossier_source=dossier_source,
        subing_n_source=subing_n_source,
        subing_n_recompute=subing_n["recompute"],
        n_jdj_candidate_order=tuple(dependency["candidates"]),
        n_jdj_dependency_roles=tuple(
            (item["candidate_id"], DependencyRole(item["role"]))
            for item in dependency["dependency_roles"]
        ),
        n_jdj_since=date.fromisoformat(dependency["since"]),
        n_jdj_through=date.fromisoformat(dependency["through"]),
        n_jdj_proximity=dependency["proximity"],
        n_jdj_future_outcomes=dependency["future_outcomes"],
        jdj_overlap_pair_order=tuple(tuple(pair) for pair in overlap["pairs"]),
        jdj_overlap_since=date.fromisoformat(overlap["since"]),
        jdj_overlap_through=date.fromisoformat(overlap["through"]),
        jdj_overlap_proximity=overlap["proximity"],
        jdj_overlap_future_outcomes=overlap["future_outcomes"],
        subing_jdj_pair_order=tuple(tuple(pair) for pair in subing_jdj["pairs"]),
        subing_jdj_recompute=subing_jdj["recompute"],
        prospective_consumed=payload["prospective_consumed"],
        parameter_perturbation=payload["parameter_perturbation"],
        automatic_scoring=payload["automatic_scoring"],
        automatic_ranking=payload["automatic_ranking"],
        automatic_promotion=payload["automatic_promotion"],
    )


def _source_ref(value: Mapping[str, str]) -> SourceArtifactRef:
    return SourceArtifactRef(
        artifact_id=value["artifact_id"],
        path=value["path"],
        expected_sha256=value["expected_sha256"],
    )


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0
