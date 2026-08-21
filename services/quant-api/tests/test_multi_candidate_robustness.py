from __future__ import annotations

from dataclasses import fields, replace
from datetime import date, datetime
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.research.robustness.multi_candidate_robustness import (
    CandidateRelationshipSummary,
    CandidateSymbolRobustness,
    CandidateSymbolStatus,
    CandidateTemporalDossier,
    CommonPriceHorizonSummary,
    CrossSymbolCandidateSummary,
    HorizonSignSummary,
    MultiCandidateRobustnessReport,
)
from app.research.robustness.multi_candidate_robustness_policy import (
    load_multi_candidate_robustness_protocol,
)


SUBING = "subing_lifecycle_v2_candidate_v1"
N = "n_structure_5m_candidate_v1"


def _empty_horizons() -> dict[int, CommonPriceHorizonSummary]:
    return {
        horizon: CommonPriceHorizonSummary(0, None, None, None) for horizon in (3, 5, 8)
    }


def _available_row(
    candidate_id: str, source_kind: str, symbol: str
) -> CandidateSymbolRobustness:
    if candidate_id == SUBING:
        evaluable_unit = "5m_ready_boundary"
        semantics = "same_trading_day_only"
    else:
        evaluable_unit = "5m_canonical_bar"
        semantics = "same_rank1_segment"
    return CandidateSymbolRobustness(
        candidate_id=candidate_id,
        source_kind=source_kind,
        symbol=symbol,
        status=CandidateSymbolStatus.AVAILABLE,
        reason_code=None,
        event_count=0,
        evaluable_count=0,
        evaluable_unit=evaluable_unit,
        event_rate_per_1000_evaluable=None,
        horizon_semantics=semantics,
        horizon_summary=_empty_horizons(),
    )


def _temporal(candidate_id: str) -> CandidateTemporalDossier:
    if candidate_id == SUBING:
        return CandidateTemporalDossier(
            candidate_id=SUBING,
            candidate_protocol_id="candidate_validation_v1",
            source_kind="subing_lifecycle",
            anchor_symbol="jm",
            retrospective_since=date(2023, 1, 1),
            retrospective_through=date(2026, 8, 18),
            event_unit="entry_confirmed",
            retrospective_event_count=0,
            rolling_fold_count=10,
            folds_with_events=0,
            test_event_count_min=0,
            test_event_count_median=Decimal(0),
            test_event_count_max=0,
            prospective_status="pending",
            prospective_first_trading_day=date(2026, 8, 20),
            prospective_through=date(2026, 8, 19),
            horizon_semantics="same_trading_day_only",
            horizon_summary=_empty_horizons(),
            source_quality_flags=("PROSPECTIVE_OOS_PENDING",),
        )
    return CandidateTemporalDossier(
        candidate_id=N,
        candidate_protocol_id="n_structure_validation_v1",
        source_kind="n_structure",
        anchor_symbol="jm",
        retrospective_since=date(2023, 1, 1),
        retrospective_through=date(2026, 8, 19),
        event_unit="n_completed",
        retrospective_event_count=0,
        rolling_fold_count=10,
        folds_with_events=0,
        test_event_count_min=0,
        test_event_count_median=Decimal(0),
        test_event_count_max=0,
        prospective_status="pending",
        prospective_first_trading_day=date(2026, 8, 21),
        prospective_through=date(2026, 8, 20),
        horizon_semantics="same_rank1_segment",
        horizon_summary=_empty_horizons(),
        source_quality_flags=("PROSPECTIVE_OOS_PENDING",),
    )


def _summary(candidate_id: str) -> CrossSymbolCandidateSummary:
    return CrossSymbolCandidateSummary(
        candidate_id=candidate_id,
        product_count=60,
        available_product_count=60,
        unavailable_product_count=0,
        symbols_with_events=0,
        symbols_without_events=60,
        event_rate_available_count=0,
        event_rate_min=None,
        event_rate_median=None,
        event_rate_max=None,
        horizon_sign_summary={
            horizon: HorizonSignSummary(0, 0, 0, 0) for horizon in (3, 5, 8)
        },
    )


def _relationship(source: str, target: str) -> CandidateRelationshipSummary:
    return CandidateRelationshipSummary(
        source_candidate_id=source,
        target_candidate_id=target,
        source_event_count=0,
        target_event_count=0,
        exact_same_direction_count=0,
        exact_opposite_direction_count=0,
        within_3_same_direction_source_count=0,
        within_5_same_direction_source_count=0,
        within_8_same_direction_source_count=0,
        nearest_match_count_within_8=0,
        signed_distance_min=None,
        signed_distance_median=None,
        signed_distance_max=None,
        target_earlier_count=0,
        target_same_boundary_count=0,
        target_later_count=0,
        same_trading_day_count=0,
        cross_trading_day_count=0,
    )


def _report() -> MultiCandidateRobustnessReport:
    protocol = load_multi_candidate_robustness_protocol()
    rows = tuple(
        _available_row(SUBING, "subing_lifecycle", symbol)
        for symbol in protocol.cross_symbol_products
    ) + tuple(
        _available_row(N, "n_structure", symbol)
        for symbol in protocol.cross_symbol_products
    )
    return MultiCandidateRobustnessReport(
        schema_version=1,
        protocol_id="multi_candidate_robustness_v1",
        frozen_at=datetime.fromisoformat("2026-08-20T21:33:00+08:00"),
        research_only=True,
        readonly=True,
        anchor_symbol="jm",
        common_since=date(2023, 1, 1),
        common_through=date(2026, 8, 18),
        temporal_dossiers=(_temporal(SUBING), _temporal(N)),
        cross_symbol_results=rows,
        cross_symbol_summaries=(_summary(SUBING), _summary(N)),
        relationships=(_relationship(SUBING, N), _relationship(N, SUBING)),
        metric_compatibility_flags=(
            "EVALUABLE_UNIT_DIFFERS",
            "HORIZON_SEMANTICS_DIFFERS",
        ),
        quality_flags=(
            "BASELINE_PROSPECTIVE_PENDING_SUBING",
            "BASELINE_PROSPECTIVE_PENDING_N",
            "SYMBOL_WITHOUT_EVENT",
            "HORIZON_WITHOUT_SAMPLE",
        ),
    )


def test_valid_report_is_exactly_ordered_and_immutable() -> None:
    report = _report()

    assert len(report.cross_symbol_results) == 120
    assert tuple(row.symbol for row in report.cross_symbol_results[:60]) == (
        load_multi_candidate_robustness_protocol().cross_symbol_products
    )
    assert tuple(item.candidate_id for item in report.temporal_dossiers) == (SUBING, N)
    assert tuple(item.source_candidate_id for item in report.relationships) == (
        SUBING,
        N,
    )
    assert isinstance(report.cross_symbol_results[0].horizon_summary, MappingProxyType)




@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("protocol_id", "other"),
        ("anchor_symbol", "ag"),
        ("common_through", date(2026, 8, 19)),
        ("research_only", False),
        ("readonly", False),
    ),
)
def test_report_rejects_identity_or_boundary_drift(field: str, value: object) -> None:
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(_report(), **{field: value})


def test_report_rejects_candidate_or_relationship_order_drift() -> None:
    report = _report()
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(report, temporal_dossiers=tuple(reversed(report.temporal_dossiers)))
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(report, relationships=tuple(reversed(report.relationships)))
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(report, cross_symbol_results=report.cross_symbol_results[:-1])


def test_available_row_requires_exact_decimal_rate_and_exact_horizons() -> None:
    base = _available_row(SUBING, "subing_lifecycle", "jm")
    valid = replace(
        base,
        event_count=1,
        evaluable_count=2,
        event_rate_per_1000_evaluable=Decimal(500),
    )
    assert valid.event_rate_per_1000_evaluable == Decimal(500)

    for invalid_rate in (500, 500.0, Decimal("500.1"), None):
        with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
            replace(
                base,
                event_count=1,
                evaluable_count=2,
                event_rate_per_1000_evaluable=invalid_rate,  # type: ignore[arg-type]
            )
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(base, horizon_summary={3: _empty_horizons()[3]})
    with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
        replace(base, event_rate_per_1000_evaluable=Decimal(0))


def test_unavailable_row_requires_stable_reason_and_all_metrics_null() -> None:
    base = CandidateSymbolRobustness(
        candidate_id=N,
        source_kind="n_structure",
        symbol="jm",
        status=CandidateSymbolStatus.UNAVAILABLE,
        reason_code="MULTI_CANDIDATE_SOURCE_UNAVAILABLE",
        event_count=None,
        evaluable_count=None,
        evaluable_unit="5m_canonical_bar",
        event_rate_per_1000_evaluable=None,
        horizon_semantics="same_rank1_segment",
        horizon_summary=None,
    )
    mutations = (
        {"reason_code": "MARKET_DATA_ERROR"},
        {"event_count": 0},
        {"evaluable_count": 0},
        {"event_rate_per_1000_evaluable": Decimal(0)},
        {"horizon_summary": _empty_horizons()},
    )
    for mutation in mutations:
        with pytest.raises(ValueError, match="MULTI_CANDIDATE_REPORT_INVALID"):
            replace(base, **mutation)


def test_horizon_mapping_is_defensively_copied() -> None:
    source = _empty_horizons()
    row = _available_row(SUBING, "subing_lifecycle", "jm")
    row = replace(row, horizon_summary=source)
    source[3] = CommonPriceHorizonSummary(
        1,
        Decimal(1),
        Decimal(2),
        Decimal(-1),
    )

    assert row.horizon_summary is not None
    assert row.horizon_summary[3].sample_count == 0
    with pytest.raises(TypeError):
        row.horizon_summary[3] = source[3]  # type: ignore[index]


def test_exported_report_surface_has_no_decision_or_ranking_fields() -> None:
    types = (
        CommonPriceHorizonSummary,
        CandidateSymbolRobustness,
        CandidateTemporalDossier,
        CandidateRelationshipSummary,
        HorizonSignSummary,
        CrossSymbolCandidateSummary,
        MultiCandidateRobustnessReport,
    )
    forbidden = {
        "score",
        "rank",
        "winner",
        "better_candidate",
        "keep",
        "drop",
        "promote",
        "profitability",
        "expected_profit",
    }

    assert all(
        field.name.lower() not in forbidden for kind in types for field in fields(kind)
    )
