from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import date
from decimal import Decimal

import pytest

from app.research.jdj.jdj_candidate_validation import (
    JdjCandidateStabilitySummary,
    JdjCandidateValidationReport,
    JdjCandidateWindowKind,
    JdjCandidateWindowResult,
    JdjProspectiveOosResult,
    JdjProspectiveOosStatus,
    JdjRollingCandidateFold,
    project_jdj_window,
    summarize_jdj_rolling_stability,
)
from app.research.jdj.jdj_research import JdjResearchResult
from app.market_data.price_outcome import PriceHorizonEvaluation


_CANDIDATE = "jdj_trend_follow_1m_candidate_v1"


def _horizon(sample_count: int = 1) -> PriceHorizonEvaluation:
    value = Decimal("1") if sample_count else None
    return PriceHorizonEvaluation(sample_count, value, value, value)


def _source() -> JdjResearchResult:
    return JdjResearchResult(
        candidate_id=_CANDIDATE,
        source_event_kind="jdj_trend_follow_triggered",
        products=("jm",),
        segment_count=2,
        evaluable_bar_count=100,
        trigger_count_long=0,
        trigger_count_short=0,
        horizon_summary={
            3: _horizon(),
            5: _horizon(),
            8: _horizon(),
            20: _horizon(),
        },
        events=(),
    )


def _window(
    *,
    window_id: str,
    kind: JdjCandidateWindowKind,
    triggers: int = 0,
) -> JdjCandidateWindowResult:
    return JdjCandidateWindowResult(
        window_id=window_id,
        window_kind=kind,
        since=date(2024, 1, 1),
        through=date(2024, 3, 31),
        products=("jm",),
        segment_count=1,
        evaluable_bar_count=100,
        trigger_count_long=triggers,
        trigger_count_short=0,
        horizon_summary={
            3: _horizon(),
            5: _horizon(),
            8: _horizon(),
            20: _horizon(),
        },
    )


def test_window_projects_exact_source_aggregates_and_freezes_horizons() -> None:
    window = project_jdj_window(
        window_id="retrospective",
        window_kind=JdjCandidateWindowKind.RETROSPECTIVE,
        since=date(2023, 1, 1),
        through=date(2026, 8, 20),
        source=_source(),
    )

    assert tuple(field.name for field in fields(window)) == (
        "window_id",
        "window_kind",
        "since",
        "through",
        "products",
        "segment_count",
        "evaluable_bar_count",
        "trigger_count_long",
        "trigger_count_short",
        "horizon_summary",
    )
    assert window.trigger_count_long == 0
    assert window.trigger_count_short == 0
    assert tuple(window.horizon_summary) == (3, 5, 8, 20)
    with pytest.raises(TypeError):
        window.horizon_summary[3] = _horizon()  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        window.trigger_count_long = 4  # type: ignore[misc]


def test_window_contract_contains_no_decision_or_execution_fields() -> None:
    names = {field.name for field in fields(JdjCandidateWindowResult)}

    assert names.isdisjoint(
        {
            "winner",
            "rank",
            "decision",
            "promotion",
            "keep",
            "drop",
            "profit",
            "fill",
            "order",
            "position",
            "pnl",
        }
    )


def test_fold_stability_prospective_and_report_are_exact_frozen_contracts() -> None:
    folds = tuple(
        JdjRollingCandidateFold(
            fold_id=f"fold_{index:02d}",
            reference=_window(
                window_id=f"fold_{index:02d}_reference",
                kind=JdjCandidateWindowKind.ROLLING_REFERENCE,
            ),
            test=_window(
                window_id=f"fold_{index:02d}_test",
                kind=JdjCandidateWindowKind.ROLLING_TEST,
                triggers=index - 1,
            ),
        )
        for index in range(1, 3)
    )
    stability = summarize_jdj_rolling_stability(folds)
    prospective = JdjProspectiveOosResult(
        status=JdjProspectiveOosStatus.PENDING,
        first_trading_day=date(2026, 8, 24),
        through=date(2026, 8, 21),
        result=None,
    )
    report = JdjCandidateValidationReport(
        schema_version=1,
        candidate_id=_CANDIDATE,
        source_event_kind="jdj_trend_follow_triggered",
        policy_id="jdj_1m_policy_v1",
        formula_version="jdj_1m_v1",
        protocol_id="jdj_candidate_validation_v1",
        research_only=True,
        symbol="jm",
        retrospective=project_jdj_window(
            window_id="retrospective",
            window_kind=JdjCandidateWindowKind.RETROSPECTIVE,
            since=date(2023, 1, 1),
            through=date(2026, 8, 20),
            source=_source(),
        ),
        rolling_folds=folds,
        rolling_stability=stability,
        prospective_oos=prospective,
        quality_flags=("PROSPECTIVE_OOS_PENDING",),
    )

    assert stability == JdjCandidateStabilitySummary(
        fold_count=2,
        folds_with_events=1,
        event_count_min=0,
        event_count_max=1,
        event_count_median=Decimal("0.5"),
    )
    assert tuple(field.name for field in fields(report)) == (
        "schema_version",
        "candidate_id",
        "source_event_kind",
        "policy_id",
        "formula_version",
        "protocol_id",
        "research_only",
        "symbol",
        "retrospective",
        "rolling_folds",
        "rolling_stability",
        "prospective_oos",
        "quality_flags",
    )
    assert report.prospective_oos.status is JdjProspectiveOosStatus.PENDING
    with pytest.raises(FrozenInstanceError):
        report.symbol = "ag"  # type: ignore[misc]


def test_report_contract_contains_no_decision_or_execution_fields() -> None:
    names = {field.name for field in fields(JdjCandidateValidationReport)}

    assert names.isdisjoint(
        {
            "winner",
            "rank",
            "decision",
            "promotion",
            "keep",
            "drop",
            "profit",
            "fill",
            "order",
            "position",
            "pnl",
        }
    )
