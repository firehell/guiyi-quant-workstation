from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.research.subing.candidate_validation import (
    CandidateStabilitySummary,
    CandidateValidationReport,
    CandidateWindowKind,
    CandidateWindowResult,
    ProspectiveOosResult,
    ProspectiveOosStatus,
    RollingCandidateFold,
    project_lifecycle_window,
    summarize_rolling_stability,
)
from app.market_data.subing_calibration import HorizonEvaluation
from app.research.subing.subing_lifecycle_research_service import (
    SubingLifecycleResearchResult,
)


_DAY_ONE = date(2026, 1, 1)
_DAY_TWO = date(2026, 3, 31)


def _horizon(sample_count: int = 2) -> HorizonEvaluation:
    return HorizonEvaluation(
        sample_count=sample_count,
        ema21_sample_count=sample_count,
        median_directional_return_bps=Decimal("1.25") if sample_count else None,
        median_mfe_bps=Decimal("2.50") if sample_count else None,
        median_mae_bps=Decimal("-0.75") if sample_count else None,
        ema21_failure_rate=Decimal("0.25") if sample_count else None,
    )


def _source(entries: int = 3) -> SubingLifecycleResearchResult:
    return SubingLifecycleResearchResult(
        products=("jm",),
        segment_count=2,
        evaluable_boundary_count=10,
        funnel_counts={
            "DATA_READY": 10,
            "DIRECTION_CONTEXT_ALIGNED": 8,
            "SETUP_ARMED": 5,
            "TRIGGER_OBSERVED": 4,
            "ENTRY_CONFIRMED": entries,
        },
        funnel_count_units={
            "DATA_READY": "boundary_occupancy",
            "DIRECTION_CONTEXT_ALIGNED": "boundary_occupancy",
            "SETUP_ARMED": "boundary_event",
            "TRIGGER_OBSERVED": "boundary_event",
            "ENTRY_CONFIRMED": "boundary_event",
        },
        confirmation_source_counts={
            "FORMAL_V1": 1,
            "MOMENTUM_HOLD": 1,
            "PIVOT_BREAK_HOLD": 1,
            "PIVOT_RETEST_REBREAK": 0,
        },
        v1_v2_overlap_counts={"V1_AND_V2": 1, "V2_ONLY": 2, "V1_ONLY": 0},
        v2_to_v1_lead_bars=(1, 2),
        confirmed_trading_day_span_counts={"SAME_DAY": 2, "CROSS_DAY": 1},
        risk_reason_counts={"EMA21_SOFT_RISK": 2},
        recovery_reason_counts={"EMA21_RECOVERED": 1},
        close_reason_counts={"DIRECTION_INVALIDATED": 1},
        horizon_summary={3: _horizon(), 5: _horizon(), 8: _horizon()},
    )


def _window(
    window_id: str,
    kind: CandidateWindowKind,
    entries: int = 3,
) -> CandidateWindowResult:
    return project_lifecycle_window(
        window_id=window_id,
        window_kind=kind,
        since=_DAY_ONE,
        through=_DAY_TWO,
        source=_source(entries),
    )


def _fold(fold_id: str, entries: int) -> RollingCandidateFold:
    return RollingCandidateFold(
        fold_id=fold_id,
        reference=_window(
            f"{fold_id}_reference", CandidateWindowKind.ROLLING_REFERENCE
        ),
        test=_window(f"{fold_id}_test", CandidateWindowKind.ROLLING_TEST, entries),
    )


def _report(**changes: object) -> CandidateValidationReport:
    folds = (_fold("fold_01", 1), _fold("fold_02", 3))
    values: dict[str, object] = {
        "schema_version": 1,
        "candidate_id": "subing_lifecycle_v2_candidate_v1",
        "policy_id": "subing_lifecycle_v2_research_v1",
        "formula_version": "subing_lifecycle_v2",
        "protocol_id": "candidate_validation_v1",
        "research_only": True,
        "symbol": "jm",
        "retrospective": _window("retrospective", CandidateWindowKind.RETROSPECTIVE),
        "rolling_folds": folds,
        "rolling_stability": summarize_rolling_stability(folds),
        "prospective_oos": ProspectiveOosResult(
            ProspectiveOosStatus.PENDING,
            date(2026, 8, 20),
            date(2026, 8, 19),
            None,
        ),
        "quality_flags": ("PROSPECTIVE_OOS_PENDING",),
    }
    values.update(changes)
    return CandidateValidationReport(**values)  # type: ignore[arg-type]


def test_projection_copies_existing_facts_without_recalculation() -> None:
    source = _source()
    result = project_lifecycle_window(
        window_id="retrospective",
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=_DAY_ONE,
        through=_DAY_TWO,
        source=source,
    )

    assert result.products == source.products
    assert result.segment_count == source.segment_count
    assert result.evaluable_boundary_count == source.evaluable_boundary_count
    assert dict(result.funnel_counts) == source.funnel_counts
    assert dict(result.confirmation_source_counts) == source.confirmation_source_counts
    assert dict(result.v1_v2_overlap_counts) == source.v1_v2_overlap_counts
    assert result.v2_to_v1_lead_bars == source.v2_to_v1_lead_bars
    assert (
        dict(result.confirmed_trading_day_span_counts)
        == source.confirmed_trading_day_span_counts
    )
    assert dict(result.risk_reason_counts) == source.risk_reason_counts
    assert dict(result.recovery_reason_counts) == source.recovery_reason_counts
    assert dict(result.close_reason_counts) == source.close_reason_counts
    assert dict(result.horizon_summary) == source.horizon_summary


def test_projection_defensively_freezes_source_mappings() -> None:
    funnel = dict(_source().funnel_counts)
    source = replace(_source(), funnel_counts=funnel)
    result = project_lifecycle_window(
        window_id="retrospective",
        window_kind=CandidateWindowKind.RETROSPECTIVE,
        since=_DAY_ONE,
        through=_DAY_TWO,
        source=source,
    )

    funnel["ENTRY_CONFIRMED"] = 99
    assert result.funnel_counts["ENTRY_CONFIRMED"] == 3
    assert isinstance(result.funnel_counts, MappingProxyType)
    with pytest.raises(TypeError):
        result.funnel_counts["ENTRY_CONFIRMED"] = 4  # type: ignore[index]


@pytest.mark.parametrize(
    "source",
    (replace(_source(), funnel_counts={"ENTRY_CONFIRMED": 3}),),
)
def test_projection_rejects_incomplete_source_contract(
    source: SubingLifecycleResearchResult,
) -> None:
    with pytest.raises(ValueError):
        project_lifecycle_window(
            window_id="invalid",
            window_kind=CandidateWindowKind.RETROSPECTIVE,
            since=_DAY_ONE,
            through=_DAY_TWO,
            source=source,
        )


def test_fold_requires_reference_and_test_kinds() -> None:
    with pytest.raises(ValueError):
        RollingCandidateFold(
            "fold_01",
            _window("wrong", CandidateWindowKind.RETROSPECTIVE),
            _window("test", CandidateWindowKind.ROLLING_TEST),
        )


def test_stability_uses_only_test_entry_counts_and_decimal_even_median() -> None:
    folds = tuple(
        _fold(f"fold_{index:02d}", entries)
        for index, entries in enumerate((1, 3, 7, 9), 1)
    )

    summary = summarize_rolling_stability(folds)

    assert summary == CandidateStabilitySummary(
        fold_count=4,
        folds_with_entries=4,
        entry_count_min=1,
        entry_count_max=9,
        entry_count_median=Decimal("5"),
    )
    assert type(summary.entry_count_median) is Decimal


def test_prospective_status_requires_matching_result_presence() -> None:
    with pytest.raises(ValueError):
        ProspectiveOosResult(
            ProspectiveOosStatus.PENDING,
            date(2026, 8, 20),
            date(2026, 8, 19),
            _window("oos", CandidateWindowKind.PROSPECTIVE_OOS),
        )
    with pytest.raises(ValueError):
        ProspectiveOosResult(
            ProspectiveOosStatus.EVALUATED,
            date(2026, 8, 20),
            date(2026, 8, 20),
            None,
        )


def test_report_accepts_authority_owned_identities_and_rejects_duplicate_fold_ids() -> (
    None
):
    report = _report(
        candidate_id="candidate_v2",
        policy_id="policy_v2",
        formula_version="formula_v2",
        protocol_id="protocol_v2",
    )

    assert report.candidate_id == "candidate_v2"
    assert report.policy_id == "policy_v2"
    assert report.formula_version == "formula_v2"
    assert report.protocol_id == "protocol_v2"

    with pytest.raises(ValueError):
        _report(candidate_id="")
    duplicate = (_fold("fold_01", 1), _fold("fold_01", 2))
    with pytest.raises(ValueError):
        _report(
            rolling_folds=duplicate,
            rolling_stability=summarize_rolling_stability(duplicate),
        )


def test_window_accepts_generic_horizons_before_authority_projection() -> None:
    window = _window("generic", CandidateWindowKind.RETROSPECTIVE)
    generic = {
        2: _horizon(),
        4: _horizon(),
    }

    assert replace(window, horizon_summary=generic).horizon_summary == generic


def test_report_and_window_are_immutable() -> None:
    report = _report()

    with pytest.raises(FrozenInstanceError):
        report.symbol = "ag"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.retrospective.window_id = "changed"  # type: ignore[misc]
