from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from datetime import date
from decimal import Decimal
from types import MappingProxyType

import pytest

from app.market_data.n_candidate_validation import (
    NCandidateStabilitySummary,
    NCandidateWindowKind,
    NCandidateWindowResult,
    NProspectiveOosResult,
    NProspectiveOosStatus,
    NRollingCandidateFold,
    NStructureCandidateValidationReport,
    project_n_structure_window,
    summarize_n_rolling_stability,
)
from app.market_data.n_structure_research_service import NStructureResearchResult
from app.market_data.price_outcome import PriceHorizonEvaluation


_SINCE = date(2026, 1, 1)
_THROUGH = date(2026, 3, 31)


def _horizon(sample_count: int = 2) -> PriceHorizonEvaluation:
    return PriceHorizonEvaluation(
        sample_count=sample_count,
        median_directional_return_bps=Decimal("1.25") if sample_count else None,
        median_mfe_bps=Decimal("2.50") if sample_count else None,
        median_mae_bps=Decimal("-0.75") if sample_count else None,
    )


def _source(*, up: int = 2, down: int = 1) -> NStructureResearchResult:
    return NStructureResearchResult(
        products=("jm",),
        segment_count=3,
        evaluable_bar_count=100,
        confirmed_pivot_count=12,
        ambiguous_outside_reset_count=4,
        incomplete_attempt_replaced_count=5,
        completed_n_counts={"up": up, "down": down},
        n_break_counts={"n2_origin_broken": 2, "origin_broken": 1},
        range_band_reentry_count=3,
        structure_established_counts={"bull": 2, "bear": 1, "range": 4},
        structure_break_counts={"bull": 1, "bear": 2},
        horizon_summary={3: _horizon(), 5: _horizon(), 8: _horizon()},
    )


def _window(
    window_id: str,
    kind: NCandidateWindowKind,
    *,
    up: int = 2,
    down: int = 1,
) -> NCandidateWindowResult:
    return project_n_structure_window(
        window_id=window_id,
        window_kind=kind,
        since=_SINCE,
        through=_THROUGH,
        source=_source(up=up, down=down),
    )


def _fold(fold_id: str, *, completed: int) -> NRollingCandidateFold:
    return NRollingCandidateFold(
        fold_id=fold_id,
        reference=_window(
            f"{fold_id}_reference",
            NCandidateWindowKind.ROLLING_REFERENCE,
            up=99,
            down=0,
        ),
        test=_window(
            f"{fold_id}_test",
            NCandidateWindowKind.ROLLING_TEST,
            up=completed,
            down=0,
        ),
    )


def _report(**changes: object) -> NStructureCandidateValidationReport:
    folds = (_fold("fold_01", completed=1), _fold("fold_02", completed=3))
    values: dict[str, object] = {
        "schema_version": 1,
        "candidate_id": "n_structure_5m_candidate_v1",
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "protocol_id": "n_structure_validation_v1",
        "research_only": True,
        "symbol": "jm",
        "retrospective": _window("retrospective", NCandidateWindowKind.RETROSPECTIVE),
        "rolling_folds": folds,
        "rolling_stability": summarize_n_rolling_stability(folds),
        "prospective_oos": NProspectiveOosResult(
            status=NProspectiveOosStatus.PENDING,
            first_trading_day=date(2026, 8, 21),
            through=date(2026, 8, 20),
            result=None,
        ),
        "quality_flags": ("PROSPECTIVE_OOS_PENDING",),
    }
    values.update(changes)
    return NStructureCandidateValidationReport(**values)  # type: ignore[arg-type]


def test_n_projection_copies_every_research_metric_without_recalculation() -> None:
    source = _source()

    result = project_n_structure_window(
        window_id="retrospective",
        window_kind=NCandidateWindowKind.RETROSPECTIVE,
        since=_SINCE,
        through=_THROUGH,
        source=source,
    )

    assert result.products == source.products
    assert result.segment_count == source.segment_count
    assert result.evaluable_bar_count == source.evaluable_bar_count
    assert result.confirmed_pivot_count == source.confirmed_pivot_count
    assert result.ambiguous_outside_reset_count == source.ambiguous_outside_reset_count
    assert (
        result.incomplete_attempt_replaced_count
        == source.incomplete_attempt_replaced_count
    )
    assert dict(result.completed_n_counts) == source.completed_n_counts
    assert dict(result.n_break_counts) == source.n_break_counts
    assert result.range_band_reentry_count == source.range_band_reentry_count
    assert (
        dict(result.structure_established_counts) == source.structure_established_counts
    )
    assert dict(result.structure_break_counts) == source.structure_break_counts
    assert dict(result.horizon_summary) == source.horizon_summary
    assert not hasattr(result, "confirmation_source_counts")
    assert not hasattr(result, "v1_v2_overlap_counts")
    assert not hasattr(result.horizon_summary[3], "ema21_failure_rate")


def test_n_projection_defensively_freezes_source_mappings() -> None:
    completed = dict(_source().completed_n_counts)
    source = replace(_source(), completed_n_counts=completed)

    result = project_n_structure_window(
        window_id="retrospective",
        window_kind=NCandidateWindowKind.RETROSPECTIVE,
        since=_SINCE,
        through=_THROUGH,
        source=source,
    )

    completed["up"] = 99
    assert result.completed_n_counts["up"] == 2
    assert isinstance(result.completed_n_counts, MappingProxyType)
    with pytest.raises(TypeError):
        result.completed_n_counts["up"] = 4  # type: ignore[index]


@pytest.mark.parametrize(
    "source",
    (
        replace(_source(), completed_n_counts={"up": 2}),
        replace(_source(), structure_break_counts={"bull": 1}),
        replace(_source(), horizon_summary={3: _horizon(), 5: _horizon()}),
    ),
)
def test_n_projection_rejects_incomplete_source_contract(
    source: NStructureResearchResult,
) -> None:
    with pytest.raises(ValueError, match="N_CANDIDATE_WINDOW_INVALID"):
        project_n_structure_window(
            window_id="invalid",
            window_kind=NCandidateWindowKind.RETROSPECTIVE,
            since=_SINCE,
            through=_THROUGH,
            source=source,
        )


def test_n_stability_uses_only_test_completed_n_and_decimal_even_median() -> None:
    folds = tuple(
        _fold(f"fold_{index:02d}", completed=completed)
        for index, completed in enumerate((0, 3, 7, 10), 1)
    )

    summary = summarize_n_rolling_stability(folds)

    assert summary == NCandidateStabilitySummary(
        fold_count=4,
        folds_with_completed_n=3,
        completed_n_min=0,
        completed_n_max=10,
        completed_n_median=Decimal("5"),
    )
    assert type(summary.completed_n_median) is Decimal


def test_n_fold_and_prospective_require_exact_window_kinds_and_bounds() -> None:
    with pytest.raises(ValueError, match="N_CANDIDATE_ROLLING_FOLD_INVALID"):
        NRollingCandidateFold(
            "fold_01",
            _window("wrong", NCandidateWindowKind.RETROSPECTIVE),
            _window("test", NCandidateWindowKind.ROLLING_TEST),
        )
    with pytest.raises(ValueError, match="N_CANDIDATE_PROSPECTIVE_OOS_INVALID"):
        NProspectiveOosResult(
            NProspectiveOosStatus.EVALUATED,
            date(2026, 8, 21),
            date(2026, 8, 21),
            None,
        )


def test_n_report_rejects_identity_drift_duplicate_folds_and_unknown_flags() -> None:
    with pytest.raises(ValueError, match="N_CANDIDATE_VALIDATION_REPORT_INVALID"):
        _report(formula_version="n_structure_v2")
    duplicate = (_fold("fold_01", completed=1), _fold("fold_01", completed=2))
    with pytest.raises(ValueError, match="N_CANDIDATE_VALIDATION_REPORT_INVALID"):
        _report(
            rolling_folds=duplicate,
            rolling_stability=summarize_n_rolling_stability(duplicate),
        )
    with pytest.raises(ValueError, match="N_CANDIDATE_VALIDATION_REPORT_INVALID"):
        _report(quality_flags=("PASS_STRATEGY",))


def test_n_report_and_window_are_immutable() -> None:
    report = _report()

    with pytest.raises(FrozenInstanceError):
        report.symbol = "ag"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        report.retrospective.window_id = "changed"  # type: ignore[misc]
