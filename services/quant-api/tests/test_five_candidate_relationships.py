from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
import json
from pathlib import Path

import pytest

from app.core.env import PROJECT_ROOT
from app.research.candidate_convergence.five_candidate_relationships import (
    CandidateDependencyResult,
    DependencyRole,
    ExistingRelationshipReference,
    FiveCandidateRelationshipProtocol,
    FiveCandidateRelationshipProtocolError,
    FiveCandidateRelationshipReport,
    FiveCandidateRelationshipReportError,
    FiveCandidateRelationshipRequest,
    JdjExactOverlapResult,
    RelationshipCatalogEntry,
    RelationshipKind,
    load_five_candidate_relationship_protocol,
)
from app.research.candidate_convergence.five_candidate_relationships_service import (
    FiveCandidateRelationshipService,
)
from app.research.jdj.jdj_context import JdjContextError
from app.research.jdj.jdj_events import (
    JdjDirection,
    JdjKeyLevelBreakoutTriggerEvent,
    JdjSetupKind,
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    _canonical_key_level_breakout_event_id,
    _canonical_trend_follow_event_id,
    _canonical_trend_reentry_event_id,
)
from app.research.jdj.jdj_research import (
    JDJ_CANDIDATE_SOURCE_EVENT_KINDS,
    JdjBatchResearchResult,
    JdjDetailedCandidateResult,
    JdjEventOutcomeRecord,
    JdjResearchResult,
    JdjSourceUnavailableError,
)
from app.market_data.price_outcome import PriceHorizonEvaluation


CANDIDATES = (
    "subing_lifecycle_v2_candidate_v1",
    "n_structure_5m_candidate_v1",
    "jdj_trend_follow_1m_candidate_v1",
    "jdj_trend_reentry_6_1m_candidate_v1",
    "jdj_key_level_breakout_1m_candidate_v1",
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
DOSSIER_PATH = (
    PROJECT_ROOT
    / "reports/research/candidate_dossier/"
    "five_candidate_research_dossier_v1/"
    "five-candidate-retrospective-evidence-freeze-2026-08-22.json"
)


def test_relationship_protocol_uses_frozen_candidate_ids() -> None:
    dossier = json.loads(DOSSIER_PATH.read_text(encoding="utf-8"))
    protocol = load_five_candidate_relationship_protocol()

    assert tuple(dossier["candidate_order"]) == CANDIDATES
    assert tuple(JDJ_CANDIDATE_SOURCE_EVENT_KINDS) == JDJ_CANDIDATES
    assert protocol.candidate_order == CANDIDATES


def test_relationship_protocol_rejects_equivalent_nonliteral_frozen_at() -> None:
    protocol = load_five_candidate_relationship_protocol()

    with pytest.raises(FiveCandidateRelationshipProtocolError):
        replace(
            protocol,
            frozen_at=datetime.fromisoformat("2026-08-22T06:01:54+00:00"),
        )


def test_relationship_report_rejects_equivalent_nonliteral_frozen_at() -> None:
    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(
            _report(),
            frozen_at=datetime.fromisoformat("2026-08-22T06:01:54+00:00"),
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


@pytest.mark.parametrize(
    ("same_direction_count", "left_unique_count", "right_unique_count"),
    (
        (1, 0, 0),
        (1, 0, 1),
        (1, 1, 0),
        (2, 1, 1),
    ),
)
def test_available_overlap_rows_require_same_direction_match_closure(
    same_direction_count: int,
    left_unique_count: int,
    right_unique_count: int,
) -> None:
    overlap = _overlap_rows()[0]

    with pytest.raises(FiveCandidateRelationshipReportError):
        replace(
            overlap,
            exact_same_boundary_same_direction_count=same_direction_count,
            left_events_with_same_direction_match=left_unique_count,
            right_events_with_same_direction_match=right_unique_count,
        )


def test_available_overlap_rows_accept_closed_zero_and_positive_matches() -> None:
    overlap = _overlap_rows()[0]

    zero_match = replace(
        overlap,
        exact_same_boundary_same_direction_count=0,
        left_events_with_same_direction_match=0,
        right_events_with_same_direction_match=0,
    )
    positive_match = replace(
        overlap,
        exact_same_boundary_same_direction_count=2,
        left_events_with_same_direction_match=1,
        right_events_with_same_direction_match=2,
    )

    assert zero_match.exact_same_boundary_same_direction_count == 0
    assert positive_match.exact_same_boundary_same_direction_count == 2


def _source_events(
    symbol: str,
) -> tuple[
    JdjTrendFollowTriggerEvent,
    JdjTrendReentryTriggerEvent,
    JdjKeyLevelBreakoutTriggerEvent,
]:
    contract = f"{symbol.upper()}2701"
    segment_start = date(2023, 1, 1)
    trading_day = date(2026, 8, 19)
    observed_at = datetime(2026, 8, 19, 1, 20, tzinfo=UTC)
    trend_follow_reaction = observed_at - timedelta(minutes=1)
    trend_reentry_excursion = observed_at - timedelta(minutes=6)
    trend_reentry_reclaimed = observed_at - timedelta(minutes=3)
    trend_reentry_reaction = observed_at - timedelta(minutes=2)
    pivot_at = observed_at - timedelta(minutes=20)
    pivot_confirmed_at = observed_at - timedelta(minutes=15)
    first_break_at = observed_at - timedelta(minutes=10)
    retest_at = observed_at - timedelta(minutes=5)
    trigger_level = Decimal("100")
    pivot_id = ":".join(
        (
            contract,
            segment_start.isoformat(),
            "5m",
            "1",
            "high",
            pivot_at.isoformat(),
        )
    )
    return (
        JdjTrendFollowTriggerEvent(
            event_id=_canonical_trend_follow_event_id(
                candidate_id=TF,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start,
                direction=JdjDirection.LONG,
                reaction_at=trend_follow_reaction,
                observed_at=observed_at,
                trigger_level=trigger_level,
            ),
            source_kind="jdj_1m",
            setup_kind=JdjSetupKind.TREND_FOLLOW,
            candidate_id=TF,
            source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[TF],
            direction=JdjDirection.LONG,
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start,
            trading_day=trading_day,
            observed_at=observed_at,
            segment_bar_index=20,
            trend_snapshot_observed_at=observed_at - timedelta(minutes=2),
            reaction_at=trend_follow_reaction,
            ema20_at_reaction=Decimal("99"),
            trigger_level=trigger_level,
            observation_close=Decimal("101"),
        ),
        JdjTrendReentryTriggerEvent(
            event_id=_canonical_trend_reentry_event_id(
                candidate_id=R6,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start,
                direction=JdjDirection.LONG,
                excursion_started_at=trend_reentry_excursion,
                excursion_extreme=Decimal("95"),
                reclaimed_at=trend_reentry_reclaimed,
                reaction_at=trend_reentry_reaction,
                observed_at=observed_at,
                trigger_level=trigger_level,
            ),
            source_kind="jdj_1m",
            setup_kind=JdjSetupKind.TREND_REENTRY_6,
            candidate_id=R6,
            source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[R6],
            direction=JdjDirection.LONG,
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start,
            trading_day=trading_day,
            observed_at=observed_at,
            segment_bar_index=20,
            trend_snapshot_observed_at=observed_at - timedelta(minutes=4),
            excursion_started_at=trend_reentry_excursion,
            excursion_extreme=Decimal("95"),
            reclaimed_at=trend_reentry_reclaimed,
            reaction_at=trend_reentry_reaction,
            trigger_level=trigger_level,
            observation_close=Decimal("101"),
        ),
        JdjKeyLevelBreakoutTriggerEvent(
            event_id=_canonical_key_level_breakout_event_id(
                candidate_id=KLB,
                symbol=symbol,
                contract=contract,
                segment_start_trading_day=segment_start,
                direction=JdjDirection.LONG,
                trend_epoch=1,
                key_level_pivot_id=pivot_id,
                key_level_price=trigger_level,
                key_level_confirmed_at=pivot_confirmed_at,
                first_break_at=first_break_at,
                retest_at=retest_at,
                observed_at=observed_at,
                trigger_level=trigger_level,
            ),
            source_kind="jdj_1m",
            setup_kind=JdjSetupKind.KEY_LEVEL_BREAKOUT,
            candidate_id=KLB,
            source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[KLB],
            direction=JdjDirection.LONG,
            symbol=symbol,
            contract=contract,
            segment_start_trading_day=segment_start,
            trading_day=trading_day,
            observed_at=observed_at,
            segment_bar_index=20,
            trend_snapshot_observed_at=observed_at - timedelta(minutes=14),
            trend_epoch=1,
            key_level_pivot_id=pivot_id,
            key_level_price=trigger_level,
            key_level_confirmed_at=pivot_confirmed_at,
            first_break_at=first_break_at,
            retest_at=retest_at,
            trigger_level=trigger_level,
            observation_close=Decimal("101"),
        ),
    )


def _batch(symbol: str) -> JdjBatchResearchResult:
    zero = PriceHorizonEvaluation(0, None, None, None)
    details = []
    for candidate_id, event in zip(
        JDJ_CANDIDATES,
        _source_events(symbol),
        strict=True,
    ):
        details.append(
            JdjDetailedCandidateResult(
                result=JdjResearchResult(
                    candidate_id=candidate_id,
                    source_event_kind=JDJ_CANDIDATE_SOURCE_EVENT_KINDS[
                        candidate_id
                    ],
                    products=(symbol,),
                    segment_count=1,
                    evaluable_bar_count=100,
                    trigger_count_long=1,
                    trigger_count_short=0,
                    horizon_summary={
                        horizon: zero for horizon in (3, 5, 8, 20)
                    },
                    events=(event,),
                ),
                event_outcomes=(
                    JdjEventOutcomeRecord(
                        event_id=event.event_id,
                        trading_day=event.trading_day,
                        outcomes={
                            horizon: None for horizon in (3, 5, 8, 20)
                        },
                    ),
                ),
            )
        )
    return JdjBatchResearchResult(
        symbol=symbol,
        observed_since=date(2023, 1, 1),
        observed_through=date(2026, 8, 19),
        candidates=tuple(details),
    )


class _DependencyRunner:
    def __init__(
        self,
        results: dict[str, JdjBatchResearchResult | Exception] | None = None,
    ) -> None:
        self.results = results or {}
        self.calls: list[tuple[str, date, date]] = []

    def run_batch(
        self,
        *,
        symbol: str,
        since: date,
        through: date,
    ) -> JdjBatchResearchResult:
        self.calls.append((symbol, since, through))
        result = self.results.get(symbol)
        if isinstance(result, Exception):
            raise result
        return result or _batch(symbol)


def _dependency_service(
    runner: _DependencyRunner,
    *,
    protocol: FiveCandidateRelationshipProtocol | None = None,
) -> FiveCandidateRelationshipService:
    return FiveCandidateRelationshipService(
        protocol or load_five_candidate_relationship_protocol(),
        jdj_research=runner,
    )


def test_dependency_projection_calls_each_symbol_once_for_exact_n_safe_window() -> None:
    runner = _DependencyRunner()

    rows = _dependency_service(runner).project_n_jdj_dependencies()

    assert runner.calls == [
        (symbol, date(2023, 1, 1), date(2026, 8, 19))
        for symbol in PRODUCTS
    ]
    assert len(rows) == 180
    assert tuple((row.candidate_id, row.symbol) for row in rows) == tuple(
        (candidate_id, symbol)
        for candidate_id in JDJ_CANDIDATES
        for symbol in PRODUCTS
    )


@pytest.mark.parametrize(
    ("field", "drifted_value"),
    (
        ("cross_symbol_products", PRODUCTS[:-1]),
        ("n_jdj_through", date(2026, 8, 20)),
        ("prospective_consumed", True),
    ),
)
def test_dependency_projection_revalidates_exact_protocol_before_runner_calls(
    field: str,
    drifted_value: object,
) -> None:
    protocol = load_five_candidate_relationship_protocol()
    runner = _DependencyRunner()
    service = _dependency_service(runner, protocol=protocol)
    object.__setattr__(protocol, field, drifted_value)

    with pytest.raises(
        FiveCandidateRelationshipProtocolError,
        match="^FIVE_CANDIDATE_RELATIONSHIP_PROTOCOL_INVALID$",
    ):
        service.project_n_jdj_dependencies()

    assert runner.calls == []


def test_dependency_projection_counts_only_immutable_event_lineage() -> None:
    rows = _dependency_service(_DependencyRunner()).project_n_jdj_dependencies()
    tf, r6, klb = (row for row in rows if row.symbol == PRODUCTS[0])

    assert tf.event_count == 1
    assert tf.events_with_trend_snapshot_lineage == tf.event_count
    assert tf.events_with_exact_pivot_lineage is None
    assert r6.event_count == 1
    assert r6.events_with_trend_snapshot_lineage == r6.event_count
    assert r6.events_with_exact_pivot_lineage is None
    assert klb.event_count == 1
    assert klb.events_with_trend_snapshot_lineage == klb.event_count
    assert klb.events_with_exact_pivot_lineage == klb.event_count


def test_dependency_projection_retains_three_typed_unavailable_rows() -> None:
    runner = _DependencyRunner({"ag": JdjSourceUnavailableError()})

    rows = _dependency_service(runner).project_n_jdj_dependencies()

    unavailable = tuple(row for row in rows if row.symbol == "ag")
    assert tuple(row.candidate_id for row in unavailable) == JDJ_CANDIDATES
    assert all(
        row.status == "unavailable"
        and row.reason_code == "JDJ_SOURCE_UNAVAILABLE"
        and row.event_count is None
        and row.events_with_trend_snapshot_lineage is None
        and row.events_with_exact_pivot_lineage is None
        for row in unavailable
    )
    assert len(rows) == 180


@pytest.mark.parametrize(
    "failure",
    (JdjContextError(), RuntimeError("runner corruption")),
)
def test_dependency_projection_does_not_downgrade_non_source_failures(
    failure: Exception,
) -> None:
    runner = _DependencyRunner({PRODUCTS[0]: failure})

    with pytest.raises(type(failure)) as captured:
        _dependency_service(runner).project_n_jdj_dependencies()

    assert captured.value is failure


def test_dependency_projection_rejects_wrong_batch_identity_and_order() -> None:
    wrong_symbol = _DependencyRunner({PRODUCTS[0]: _batch(PRODUCTS[1])})
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(wrong_symbol).project_n_jdj_dependencies()

    reordered = _batch(PRODUCTS[0])
    object.__setattr__(reordered, "candidates", tuple(reversed(reordered.candidates)))
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(
            _DependencyRunner({PRODUCTS[0]: reordered})
        ).project_n_jdj_dependencies()


def test_dependency_projection_rejects_product_or_lineage_corruption() -> None:
    wrong_product = _batch(PRODUCTS[0])
    object.__setattr__(wrong_product.candidates[0].result, "products", ("ag",))
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(
            _DependencyRunner({PRODUCTS[0]: wrong_product})
        ).project_n_jdj_dependencies()

    missing_lineage = _batch(PRODUCTS[0])
    event = missing_lineage.candidates[0].result.events[0]
    object.__setattr__(event, "trend_snapshot_observed_at", None)
    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(
            _DependencyRunner({PRODUCTS[0]: missing_lineage})
        ).project_n_jdj_dependencies()


def _later_trend_follow_event(
    event: JdjTrendFollowTriggerEvent,
) -> JdjTrendFollowTriggerEvent:
    observed_at = event.observed_at + timedelta(minutes=2)
    reaction_at = event.reaction_at + timedelta(minutes=2)
    return replace(
        event,
        event_id=_canonical_trend_follow_event_id(
            candidate_id=event.candidate_id,
            symbol=event.symbol,
            contract=event.contract,
            segment_start_trading_day=event.segment_start_trading_day,
            direction=event.direction,
            reaction_at=reaction_at,
            observed_at=observed_at,
            trigger_level=event.trigger_level,
        ),
        observed_at=observed_at,
        segment_bar_index=event.segment_bar_index + 2,
        trend_snapshot_observed_at=(
            event.trend_snapshot_observed_at + timedelta(minutes=2)
        ),
        reaction_at=reaction_at,
    )


@pytest.mark.parametrize(
    "corruption",
    ("duplicate_identity", "wrong_order", "trigger_count", "event_type"),
)
def test_dependency_projection_revalidates_jdj_result_event_set(
    corruption: str,
) -> None:
    batch = _batch(PRODUCTS[0])
    result = batch.candidates[0].result
    first = result.events[0]

    if corruption == "duplicate_identity":
        object.__setattr__(result, "events", (first, first))
        object.__setattr__(result, "trigger_count_long", 2)
    elif corruption == "wrong_order":
        later = _later_trend_follow_event(first)
        object.__setattr__(result, "events", (later, first))
        object.__setattr__(result, "trigger_count_long", 2)
    elif corruption == "trigger_count":
        object.__setattr__(result, "trigger_count_long", 2)
    else:
        object.__setattr__(
            result,
            "events",
            batch.candidates[1].result.events,
        )

    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(
            _DependencyRunner({PRODUCTS[0]: batch})
        ).project_n_jdj_dependencies()


@pytest.mark.parametrize(
    ("observed_since", "event_trading_day"),
    (
        (date(2023, 1, 2), date(2023, 1, 1)),
        (date(2023, 1, 1), date(2026, 8, 20)),
    ),
)
def test_dependency_projection_rejects_events_outside_batch_or_protocol_window(
    observed_since: date,
    event_trading_day: date,
) -> None:
    batch = _batch(PRODUCTS[0])
    object.__setattr__(batch, "observed_since", observed_since)
    event = batch.candidates[0].result.events[0]
    object.__setattr__(event, "trading_day", event_trading_day)

    with pytest.raises(JdjContextError, match="^JDJ_CONTEXT_INVALID$"):
        _dependency_service(
            _DependencyRunner({PRODUCTS[0]: batch})
        ).project_n_jdj_dependencies()
