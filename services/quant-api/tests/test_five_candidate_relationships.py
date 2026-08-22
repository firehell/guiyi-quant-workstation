from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path

import pytest

from app.core.env import PROJECT_ROOT
from app.research.candidate_convergence.five_candidate_relationships import (
    CandidateDependencyResult,
    DependencyRole,
    ExistingRelationshipReference,
    FiveCandidateRelationshipProtocolError,
    FiveCandidateRelationshipReport,
    FiveCandidateRelationshipReportError,
    FiveCandidateRelationshipRequest,
    JdjExactOverlapResult,
    RelationshipCatalogEntry,
    RelationshipKind,
    load_five_candidate_relationship_protocol,
)


CANDIDATES = (
    "subing_entry_signal_v1",
    "n_pattern_v1",
    "jdj_interaction_candidate_v1",
    "r6_trend_level_v1",
    "klb_trend_level_v1",
)
SUBING, N, TF, R6, KLB = CANDIDATES
JDJ_CANDIDATES = (TF, R6, KLB)
PRODUCTS = (
    "a", "ag", "al", "ao", "ap", "au", "b", "bu", "bz", "c",
    "cf", "cj", "cu", "eb", "ec", "eg", "fg", "fu", "hc", "i",
    "j", "jd", "jm", "l", "lc", "lh", "m", "ma", "ni", "oi",
    "p", "pb", "pd", "pf", "pg", "pk", "pl", "pp", "pr", "ps",
    "pt", "px", "rb", "rm", "rs", "ru", "sa", "sc", "sf", "sh",
    "si", "sm", "sn", "sr", "ss", "ta", "ur", "v", "y", "zn",
)
PAIR_ORDER = (
    (SUBING, N),
    (N, TF),
    (N, R6),
    (N, KLB),
    (TF, R6),
    (TF, KLB),
    (R6, KLB),
    (SUBING, TF),
    (SUBING, R6),
    (SUBING, KLB),
)
PAIR_KINDS = (
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
JDJ_PAIRS = ((TF, R6), (TF, KLB), (R6, KLB))
PROTOCOL_PATH = (
    PROJECT_ROOT
    / "data/research_protocols/five_candidate_relationship_topology_v1.json"
)


def test_relationship_protocol_has_exact_windows() -> None:
    protocol = load_five_candidate_relationship_protocol()

    assert protocol.n_jdj_since == date(2023, 1, 1)
    assert protocol.n_jdj_through == date(2026, 8, 19)
    assert protocol.jdj_overlap_since == date(2023, 1, 1)
    assert protocol.jdj_overlap_through == date(2026, 8, 20)
    assert protocol.n_jdj_proximity is None
    assert protocol.jdj_overlap_proximity is None
    assert protocol.future_outcomes is False
    assert protocol.prospective_consumed is False


def test_relationship_protocol_has_exact_identity_and_sources() -> None:
    protocol = load_five_candidate_relationship_protocol()

    assert protocol.protocol_id == "five_candidate_relationship_topology_v1"
    assert protocol.frozen_at.isoformat() == "2026-08-22T14:01:54+08:00"
    assert protocol.candidate_order == CANDIDATES
    assert protocol.pair_order == PAIR_ORDER
    assert protocol.cross_symbol_products == PRODUCTS
    assert protocol.relationship_kinds == PAIR_KINDS
    assert protocol.dossier_source.path == (
        "reports/research/candidate_dossier/"
        "five_candidate_research_dossier_v1/"
        "five-candidate-retrospective-evidence-freeze-2026-08-22.json"
    )
    assert protocol.dossier_source.expected_sha256 == (
        "632c7b88bc3dfaf15d9640f32d014b9af0665376959e10c73101956cdc81ee99"
    )
    assert protocol.subing_n_source.path == (
        "reports/research/candidate_robustness/"
        "multi_candidate_robustness_v1/"
        "anchor-jm-active60-retrospective-freeze-2026-08-20.json"
    )
    assert protocol.subing_n_source.expected_sha256 == (
        "6aaa624d13eb3492232eeff44b919efb704bd2018ab9e35503678ffc2c17f433"
    )
    assert protocol.subing_n_recompute is False
    assert protocol.subing_jdj_recompute is False
    assert protocol.research_only is True
    assert protocol.readonly is True
    assert protocol.parameter_perturbation is False
    assert protocol.automatic_scoring is False
    assert protocol.automatic_ranking is False
    assert protocol.automatic_promotion is False


def _write_mutated_protocol(tmp_path: Path, mutator) -> Path:
    payload = json.loads(PROTOCOL_PATH.read_text(encoding="utf-8"))
    mutated = deepcopy(payload)
    mutator(mutated)
    path = tmp_path / "relationship-protocol.json"
    path.write_text(json.dumps(mutated), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["analyses"]["n_jdj_context_dependency"].__setitem__(
            "through", "2026-08-20"
        ),
        lambda payload: payload["analyses"]["jdj_exact_overlap"].__setitem__(
            "through", "2026-08-21"
        ),
        lambda payload: payload["analyses"]["n_jdj_context_dependency"].__setitem__(
            "proximity", 1
        ),
        lambda payload: payload["analyses"]["jdj_exact_overlap"].__setitem__(
            "proximity", 1
        ),
        lambda payload: payload["analyses"]["n_jdj_context_dependency"].__setitem__(
            "future_outcomes", True
        ),
        lambda payload: payload["pair_order"].reverse(),
        lambda payload: payload["dossier_source"].__setitem__(
            "expected_sha256", "0" * 64
        ),
        lambda payload: payload["analyses"]["subing_jdj"].__setitem__(
            "recompute", True
        ),
    ],
    ids=(
        "n-jdj-through",
        "jdj-overlap-through",
        "n-jdj-proximity",
        "jdj-overlap-proximity",
        "future-outcomes",
        "pair-order",
        "dossier-sha",
        "subing-jdj-recompute",
    ),
)
def test_relationship_protocol_rejects_drift(tmp_path: Path, mutator) -> None:
    path = _write_mutated_protocol(tmp_path, mutator)

    with pytest.raises(FiveCandidateRelationshipProtocolError):
        load_five_candidate_relationship_protocol(path)


def test_relationship_enums_and_request_are_exact() -> None:
    assert tuple(RelationshipKind) == (
        RelationshipKind.EXISTING_EVENT_RELATIONSHIP,
        RelationshipKind.STRUCTURAL_CONTEXT_DEPENDENCY,
        RelationshipKind.EXACT_SAME_BOUNDARY_OVERLAP,
        RelationshipKind.UNDEFINED_CROSS_TIMEFRAME,
    )
    assert tuple(DependencyRole) == (
        DependencyRole.TREND_FILTER,
        DependencyRole.TREND_AND_PIVOT_SOURCE,
    )
    request = FiveCandidateRelationshipRequest(
        protocol_id="five_candidate_relationship_topology_v1"
    )
    assert request.protocol_id == "five_candidate_relationship_topology_v1"
    with pytest.raises(FiveCandidateRelationshipProtocolError):
        FiveCandidateRelationshipRequest(protocol_id="other")


def _dependency_rows() -> tuple[CandidateDependencyResult, ...]:
    return tuple(
        CandidateDependencyResult(
            candidate_id=candidate_id,
            symbol=symbol,
            dependency_role=(
                DependencyRole.TREND_AND_PIVOT_SOURCE
                if candidate_id == KLB
                else DependencyRole.TREND_FILTER
            ),
            status="available",
            reason_code=None,
            event_count=2,
            events_with_trend_snapshot_lineage=2,
            events_with_exact_pivot_lineage=2 if candidate_id == KLB else None,
        )
        for candidate_id in JDJ_CANDIDATES
        for symbol in PRODUCTS
    )


def _overlap_rows() -> tuple[JdjExactOverlapResult, ...]:
    return tuple(
        JdjExactOverlapResult(
            left_candidate_id=left,
            right_candidate_id=right,
            symbol=symbol,
            status="available",
            reason_code=None,
            left_event_count=2,
            right_event_count=3,
            exact_same_boundary_same_direction_count=1,
            exact_same_boundary_opposite_direction_count=0,
            left_events_with_same_direction_match=1,
            right_events_with_same_direction_match=1,
        )
        for left, right in JDJ_PAIRS
        for symbol in PRODUCTS
    )


def _report(
    *,
    dependency_rows: tuple[CandidateDependencyResult, ...] | None = None,
    overlap_rows: tuple[JdjExactOverlapResult, ...] | None = None,
    quality_flags: tuple[str, ...] = (),
) -> FiveCandidateRelationshipReport:
    protocol = load_five_candidate_relationship_protocol()
    return FiveCandidateRelationshipReport(
        schema_version=1,
        command=(
            "guiyi research candidate-relationships "
            "--protocol five_candidate_relationship_topology_v1"
        ),
        status="ok",
        protocol_id=protocol.protocol_id,
        frozen_at=protocol.frozen_at,
        research_only=True,
        readonly=True,
        prospective_consumed=False,
        candidate_order=CANDIDATES,
        pair_order=PAIR_ORDER,
        relationship_catalog=tuple(
            RelationshipCatalogEntry(left, right, kind)
            for (left, right), kind in zip(PAIR_ORDER, PAIR_KINDS, strict=True)
        ),
        existing_relationship_references=(
            ExistingRelationshipReference(
                left_candidate_id=SUBING,
                right_candidate_id=N,
                relation_kind=RelationshipKind.EXISTING_EVENT_RELATIONSHIP,
                source=protocol.subing_n_source,
                recompute=False,
            ),
        ),
        n_jdj_dependency_results=(
            dependency_rows if dependency_rows is not None else _dependency_rows()
        ),
        jdj_exact_overlap_results=(
            overlap_rows if overlap_rows is not None else _overlap_rows()
        ),
        quality_flags=quality_flags,
        safety={
            "future_outcomes": False,
            "parameter_perturbation": False,
            "automatic_scoring": False,
            "automatic_ranking": False,
            "automatic_promotion": False,
        },
    )


def test_relationship_report_accepts_exact_synthetic_inventory() -> None:
    report = _report()

    assert len(report.relationship_catalog) == 10
    assert len(report.n_jdj_dependency_results) == 180
    assert len(report.jdj_exact_overlap_results) == 180
    assert tuple(
        (row.candidate_id, row.symbol)
        for row in report.n_jdj_dependency_results
    ) == tuple(
        (candidate_id, symbol)
        for candidate_id in JDJ_CANDIDATES
        for symbol in PRODUCTS
    )
    assert tuple(
        (row.left_candidate_id, row.right_candidate_id, row.symbol)
        for row in report.jdj_exact_overlap_results
    ) == tuple(
        (left, right, symbol)
        for left, right in JDJ_PAIRS
        for symbol in PRODUCTS
    )


def test_relationship_report_rejects_inventory_order_drift() -> None:
    dependencies = _dependency_rows()
    overlaps = _overlap_rows()

    with pytest.raises(FiveCandidateRelationshipReportError):
        _report(dependency_rows=tuple(reversed(dependencies)))
    with pytest.raises(FiveCandidateRelationshipReportError):
        _report(overlap_rows=tuple(reversed(overlaps)))


def test_typed_unavailable_rows_require_every_metric_to_be_null() -> None:
    dependencies = list(_dependency_rows())
    dependencies[0] = CandidateDependencyResult(
        candidate_id=TF,
        symbol=PRODUCTS[0],
        dependency_role=DependencyRole.TREND_FILTER,
        status="unavailable",
        reason_code="JDJ_SOURCE_UNAVAILABLE",
        event_count=None,
        events_with_trend_snapshot_lineage=None,
        events_with_exact_pivot_lineage=None,
    )
    overlaps = list(_overlap_rows())
    overlaps[0] = JdjExactOverlapResult(
        left_candidate_id=TF,
        right_candidate_id=R6,
        symbol=PRODUCTS[0],
        status="unavailable",
        reason_code="JDJ_SOURCE_UNAVAILABLE",
        left_event_count=None,
        right_event_count=None,
        exact_same_boundary_same_direction_count=None,
        exact_same_boundary_opposite_direction_count=None,
        left_events_with_same_direction_match=None,
        right_events_with_same_direction_match=None,
    )

    report = _report(
        dependency_rows=tuple(dependencies),
        overlap_rows=tuple(overlaps),
        quality_flags=("JDJ_SOURCE_UNAVAILABLE_PRESENT",),
    )

    assert report.n_jdj_dependency_results[0].event_count is None
    assert report.jdj_exact_overlap_results[0].left_event_count is None
    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(report.n_jdj_dependency_results[0], event_count=0)
    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(report.jdj_exact_overlap_results[0], left_event_count=0)


def test_available_rows_require_complete_lineage_and_metrics() -> None:
    dependency = _dependency_rows()[0]
    overlap = _overlap_rows()[0]

    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(dependency, events_with_trend_snapshot_lineage=1)
    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(dependency, events_with_exact_pivot_lineage=0)
    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(overlap, left_events_with_same_direction_match=None)
