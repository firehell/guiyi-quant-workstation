"""Stable read-only JSON renderers for ``guiyi research``."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields
from datetime import date, datetime
from decimal import Decimal
from enum import Enum

from app.research.subing.candidate_validation import (
    CandidateValidationReport,
    CandidateWindowResult,
    ProspectiveOosResult,
    RollingCandidateFold,
)
from app.research.jdj.jdj_research import JdjResearchRequest, JdjResearchResult
from app.research.jdj.jdj_candidate_validation import (
    JdjCandidateValidationReport,
    JdjCandidateWindowResult,
    JdjProspectiveOosResult,
    JdjRollingCandidateFold,
)
from app.research.jdj.jdj_events import JdjTriggerEvent
from app.research.main_force.main_force_mirror_v2_research_service import (
    MainForceMirrorV2ForensicPoint,
    MainForceMirrorV2GroupSpread,
    MainForceMirrorV2HorizonSummary,
    MainForceMirrorV2ResearchRequest,
    MainForceMirrorV2ResearchResult,
    MainForceMirrorV2SensitivitySummary,
)
from app.research.robustness.multi_candidate_robustness import (
    CommonPriceHorizonSummary,
    CrossSymbolCandidateSummary,
    MultiCandidateRobustnessReport,
)
from app.research.robustness.jdj_robustness import (
    JdjActive60RobustnessReport,
    JdjRobustnessHorizonSummary,
    JdjRobustnessSectorSummary,
    JdjRobustnessSymbolResult,
    JdjRobustnessYearSummary,
)
from app.research.n_structure.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchResult,
)
from app.research.n_structure.n_candidate_validation import (
    NCandidateWindowResult,
    NProspectiveOosResult,
    NRollingCandidateFold,
    NStructureCandidateValidationReport,
)
from app.market_data.price_outcome import PriceHorizonEvaluation
from app.market_data.subing_calibration import (
    CalibrationReport,
    HorizonEvaluation,
    ThresholdEvaluation,
)
from app.research.subing.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    CalibrationResearchRequest,
    CalibrationResearchResult,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


def _calibration_payload(
    request: CalibrationResearchRequest,
    result: CalibrationResearchResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "command": "research.subing-calibration",
        "status": "ok",
        "readonly": True,
        "phase": request.phase.value,
        "mode": request.mode.value,
        "frequency": request.frequency.value,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "products": list(result.products),
        **_report_payload(result.report, mode=request.mode),
    }
    if request.phase is CalibrationPhase.ZERO_BAND:
        payload["cohorts"] = {
            name: _report_payload(result.cohorts[name], mode=request.mode)
            for name in ("A", "B")
        }
    return payload


def _jdj_research_payload(
    request: JdjResearchRequest,
    result: JdjResearchResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": "research.jdj-1m",
        "status": "ok",
        "readonly": True,
        "research_only": True,
        "candidate_id": result.candidate_id,
        "source_event_kind": result.source_event_kind,
        "policy_id": "jdj_1m_policy_v1",
        "formula_version": "jdj_1m_v1",
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "products": list(result.products),
        "segment_count": result.segment_count,
        "evaluable_bar_count": result.evaluable_bar_count,
        "trigger_count_long": result.trigger_count_long,
        "trigger_count_short": result.trigger_count_short,
        "horizon_summary": {
            str(horizon): _price_horizon_payload(evaluation)
            for horizon, evaluation in result.horizon_summary.items()
        },
        "events": [_jdj_event_payload(event) for event in result.events],
    }


def _jdj_event_payload(event: JdjTriggerEvent) -> dict[str, object]:
    return {
        field.name: _jdj_json_value(getattr(event, field.name))
        for field in fields(event)
    }


def _jdj_json_value(value: object) -> object:
    if isinstance(value, Decimal):
        return _optional_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if type(value) is date:
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _main_force_mirror_v2_payload(
    request: MainForceMirrorV2ResearchRequest,
    result: MainForceMirrorV2ResearchResult,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": 1,
        "command": "research.main-force-mirror-v2",
        "status": "ok",
        "readonly": True,
        "research_only": True,
        "symbol": request.symbol,
        "series_kind": request.series_kind.value,
        "contract": request.contract,
        "frequency": request.frequency.value,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "indicator_code": result.indicator_code,
        "indicator_version": result.indicator_version,
        "parameters_hash": result.parameters_hash,
        "research_protocol": result.research_protocol,
        "evaluation_classification": result.evaluation_classification,
        "prospective_oos_starts_after": (
            result.prospective_oos_starts_after.isoformat()
        ),
        "member_dataset_id": result.member_dataset_id,
        "products": list(result.products),
        "member_coverage": _optional_decimal(result.member_coverage),
        "caution_ready_bars": result.caution_ready_bars,
        "caution_events": result.caution_events,
        "caution_events_per_1000_ready_bars": _optional_decimal(
            result.caution_events_per_1000_ready_bars
        ),
        "yearly": _main_force_mirror_v2_summary_tree(result.yearly),
        "by_product": _main_force_mirror_v2_summary_tree(result.by_product),
        "pooled": _main_force_mirror_v2_summary_tree(result.pooled),
        "top_bottom_spreads": {
            str(horizon): _main_force_mirror_v2_spread_payload(spread)
            for horizon, spread in result.top_bottom_spreads.items()
        },
        "sensitivity": {
            str(threshold): _main_force_mirror_v2_sensitivity_payload(summary)
            for threshold, summary in result.sensitivity.items()
        },
    }
    payload["sequence_profiles"] = {
        profile_id: {
            "yearly": _main_force_mirror_v2_summary_tree(summary.yearly),
            "by_side": _main_force_mirror_v2_summary_tree(summary.by_side),
            "pooled": _main_force_mirror_v2_summary_tree(summary.pooled),
        }
        for profile_id, summary in result.sequence_profiles.items()
    }
    if request.forensic:
        payload["forensic_points"] = [
            _main_force_mirror_v2_forensic_point_payload(item)
            for item in result.forensic_points or ()
        ]
    return payload


def _multi_candidate_robustness_payload(
    report: MultiCandidateRobustnessReport,
) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "command": "research.candidate-robustness",
        "status": "ok",
        "readonly": report.readonly,
        "research_only": report.research_only,
        "protocol_id": report.protocol_id,
        "frozen_at": report.frozen_at.isoformat(),
        "anchor_symbol": report.anchor_symbol,
        "common_retrospective": {
            "since": report.common_since.isoformat(),
            "through": report.common_through.isoformat(),
        },
        "temporal_dossiers": [
            _temporal_dossier_payload(value) for value in report.temporal_dossiers
        ],
        "cross_symbol_results": [
            _symbol_robustness_payload(value) for value in report.cross_symbol_results
        ],
        "cross_symbol_summaries": [
            _cross_symbol_summary_payload(value)
            for value in report.cross_symbol_summaries
        ],
        "relationships": [
            _relationship_payload(value) for value in report.relationships
        ],
        "metric_compatibility_flags": list(report.metric_compatibility_flags),
        "quality_flags": list(report.quality_flags),
    }


def _jdj_active60_robustness_payload(
    report: JdjActive60RobustnessReport,
) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "command": report.command,
        "protocol_id": report.protocol_id,
        "frozen_at": report.frozen_at.isoformat(),
        "research_only": report.research_only,
        "readonly": report.readonly,
        "common_retrospective": {
            "since": report.common_since.isoformat(),
            "through": report.common_through.isoformat(),
        },
        "embargo_trading_days": [
            value.isoformat() for value in report.embargo_trading_days
        ],
        "prospective_oos": {
            "first_trading_day": (
                report.prospective_first_trading_day.isoformat()
            ),
        },
        "prospective_consumed": report.prospective_consumed,
        "candidate_ids": list(report.candidate_ids),
        "cross_symbol_results": [
            _jdj_robustness_symbol_payload(value)
            for value in report.cross_symbol_results
        ],
        "sector_summaries": [
            _jdj_robustness_sector_payload(value)
            for value in report.sector_summaries
        ],
        "quality_flags": list(report.quality_flags),
    }


def _jdj_robustness_symbol_payload(
    value: JdjRobustnessSymbolResult,
) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,
        "symbol": value.symbol,
        "sector": value.sector,
        "status": value.status.value,
        "reason_code": value.reason_code,
        "observed_since": (
            value.observed_since.isoformat()
            if value.observed_since is not None
            else None
        ),
        "observed_through": (
            value.observed_through.isoformat()
            if value.observed_through is not None
            else None
        ),
        "evaluable_bar_count": value.evaluable_bar_count,
        "event_count": value.event_count,
        "long_event_count": value.long_event_count,
        "short_event_count": value.short_event_count,
        "event_rate_per_1000_evaluable": _optional_decimal(
            value.event_rate_per_1000_evaluable
        ),
        "horizon_summary": _jdj_robustness_horizons_payload(
            value.horizon_summary
        ),
        "yearly": _jdj_robustness_yearly_payload(value.yearly),
    }


def _jdj_robustness_horizons_payload(
    values: Mapping[int, JdjRobustnessHorizonSummary] | None,
) -> dict[str, object] | None:
    if values is None:
        return None
    return {
        str(horizon): {
            "sample_count": value.sample_count,
            "historical_positive_outcome_rate": _optional_decimal(
                value.historical_positive_outcome_rate
            ),
            "median_directional_return_bps": _optional_decimal(
                value.median_directional_return_bps
            ),
            "median_mfe_bps": _optional_decimal(value.median_mfe_bps),
            "median_mae_bps": _optional_decimal(value.median_mae_bps),
        }
        for horizon, value in values.items()
    }


def _jdj_robustness_yearly_payload(
    values: Mapping[int, JdjRobustnessYearSummary] | None,
) -> dict[str, object] | None:
    if values is None:
        return None
    return {
        str(year): {
            "event_count": value.event_count,
            "horizon_summary": {
                str(horizon): {
                    "sample_count": value.horizon_sample_count[horizon],
                    "historical_positive_outcome_rate": _optional_decimal(
                        value.horizon_positive_outcome_rate[horizon]
                    ),
                    "median_directional_return_bps": _optional_decimal(
                        value.horizon_median_directional_return_bps[horizon]
                    ),
                }
                for horizon in value.horizon_sample_count
            },
        }
        for year, value in values.items()
    }


def _jdj_robustness_sector_payload(
    value: JdjRobustnessSectorSummary,
) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,
        "sector": value.sector,
        "symbol_count": value.symbol_count,
        "available_symbol_count": value.available_symbol_count,
        "symbols_with_events": value.symbols_with_events,
        "horizon_summary": {
            str(horizon): {
                "symbols_with_samples": summary.symbols_with_samples,
                "positive_median_symbol_count": (
                    summary.positive_median_symbol_count
                ),
                "zero_median_symbol_count": summary.zero_median_symbol_count,
                "negative_median_symbol_count": (
                    summary.negative_median_symbol_count
                ),
                "median_of_symbol_median_return_bps": _optional_decimal(
                    summary.median_of_symbol_median_return_bps
                ),
            }
            for horizon, summary in value.horizon_summary.items()
        },
    }


def _common_horizons_payload(
    values: Mapping[int, CommonPriceHorizonSummary] | None,
) -> dict[str, object] | None:
    if values is None:
        return None
    return {
        str(horizon): {
            "sample_count": value.sample_count,
            "median_directional_return_bps": _optional_decimal(
                value.median_directional_return_bps
            ),
            "median_mfe_bps": _optional_decimal(value.median_mfe_bps),
            "median_mae_bps": _optional_decimal(value.median_mae_bps),
        }
        for horizon, value in values.items()
    }


def _temporal_dossier_payload(value: object) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,  # type: ignore[attr-defined]
        "candidate_protocol_id": value.candidate_protocol_id,  # type: ignore[attr-defined]
        "source_kind": value.source_kind,  # type: ignore[attr-defined]
        "anchor_symbol": value.anchor_symbol,  # type: ignore[attr-defined]
        "retrospective_since": value.retrospective_since.isoformat(),  # type: ignore[attr-defined]
        "retrospective_through": value.retrospective_through.isoformat(),  # type: ignore[attr-defined]
        "event_unit": value.event_unit,  # type: ignore[attr-defined]
        "retrospective_event_count": value.retrospective_event_count,  # type: ignore[attr-defined]
        "rolling_fold_count": value.rolling_fold_count,  # type: ignore[attr-defined]
        "folds_with_events": value.folds_with_events,  # type: ignore[attr-defined]
        "test_event_count_min": value.test_event_count_min,  # type: ignore[attr-defined]
        "test_event_count_median": str(value.test_event_count_median),  # type: ignore[attr-defined]
        "test_event_count_max": value.test_event_count_max,  # type: ignore[attr-defined]
        "prospective_status": value.prospective_status,  # type: ignore[attr-defined]
        "prospective_first_trading_day": value.prospective_first_trading_day.isoformat(),  # type: ignore[attr-defined]
        "prospective_through": value.prospective_through.isoformat(),  # type: ignore[attr-defined]
        "horizon_semantics": value.horizon_semantics,  # type: ignore[attr-defined]
        "horizon_summary": _common_horizons_payload(value.horizon_summary),  # type: ignore[attr-defined]
        "source_quality_flags": list(value.source_quality_flags),  # type: ignore[attr-defined]
    }


def _symbol_robustness_payload(value: object) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,  # type: ignore[attr-defined]
        "source_kind": value.source_kind,  # type: ignore[attr-defined]
        "symbol": value.symbol,  # type: ignore[attr-defined]
        "status": value.status.value,  # type: ignore[attr-defined]
        "reason_code": value.reason_code,  # type: ignore[attr-defined]
        "event_count": value.event_count,  # type: ignore[attr-defined]
        "evaluable_count": value.evaluable_count,  # type: ignore[attr-defined]
        "evaluable_unit": value.evaluable_unit,  # type: ignore[attr-defined]
        "event_rate_per_1000_evaluable": _optional_decimal(
            value.event_rate_per_1000_evaluable  # type: ignore[attr-defined]
        ),
        "horizon_semantics": value.horizon_semantics,  # type: ignore[attr-defined]
        "horizon_summary": _common_horizons_payload(value.horizon_summary),  # type: ignore[attr-defined]
    }


def _cross_symbol_summary_payload(
    value: CrossSymbolCandidateSummary,
) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,  # type: ignore[attr-defined]
        "product_count": value.product_count,  # type: ignore[attr-defined]
        "available_product_count": value.available_product_count,  # type: ignore[attr-defined]
        "unavailable_product_count": value.unavailable_product_count,  # type: ignore[attr-defined]
        "symbols_with_events": value.symbols_with_events,
        "symbols_without_events": value.symbols_without_events,
        "event_rate_available_count": value.event_rate_available_count,  # type: ignore[attr-defined]
        "event_rate_min": _optional_decimal(value.event_rate_min),  # type: ignore[attr-defined]
        "event_rate_median": _optional_decimal(value.event_rate_median),  # type: ignore[attr-defined]
        "event_rate_max": _optional_decimal(value.event_rate_max),  # type: ignore[attr-defined]
        "horizon_sign_summary": {
            str(horizon): {
                "symbols_with_samples": summary.symbols_with_samples,
                "positive_median_return_symbols": summary.positive_median_return_symbols,
                "zero_median_return_symbols": summary.zero_median_return_symbols,
                "negative_median_return_symbols": summary.negative_median_return_symbols,
            }
            for horizon, summary in value.horizon_sign_summary.items()
        },
    }


def _relationship_payload(value: object) -> dict[str, object]:
    fields = (
        "source_candidate_id",
        "target_candidate_id",
        "source_event_count",
        "target_event_count",
        "exact_same_direction_count",
        "exact_opposite_direction_count",
        "within_3_same_direction_source_count",
        "within_5_same_direction_source_count",
        "within_8_same_direction_source_count",
        "nearest_match_count_within_8",
        "signed_distance_min",
        "signed_distance_max",
        "target_earlier_count",
        "target_same_boundary_count",
        "target_later_count",
        "same_trading_day_count",
        "cross_trading_day_count",
    )
    payload = {field: getattr(value, field) for field in fields}
    payload["signed_distance_median"] = _optional_decimal(
        value.signed_distance_median  # type: ignore[attr-defined]
    )
    return payload


def _main_force_mirror_v2_forensic_point_payload(
    item: MainForceMirrorV2ForensicPoint,
) -> dict[str, object]:
    point = item.point
    sequence = item.sequence
    member = point.member
    member_ready = member is not None and member.status == "ready"
    return {
        "bar_end": point.bar_end.isoformat(),
        "trading_day": point.trading_day.isoformat(),
        "physical_contract": point.physical_contract,
        "pressure_state": point.pressure_state,
        "instant_pressure": point.instant_pressure,
        "accumulated_pressure": point.accumulated_pressure,
        "price_impulse": point.price_impulse,
        "volume_ratio": point.volume_ratio,
        "delta_oi": point.delta_oi,
        "oi_impulse": point.oi_impulse,
        "range_position": point.range_position,
        "caution": point.caution,
        "long_caution_score": point.long_caution_score,
        "short_caution_score": point.short_caution_score,
        "caution_reason_codes": list(point.caution_reason_codes),
        "member_status": member.status if member is not None else "unavailable",
        "member_relation_to_accumulated": (
            member.relation_to_accumulated
            if member_ready and member is not None
            else "unavailable"
        ),
        "member_relation_to_caution": (
            member.relation_to_caution
            if member_ready and member is not None
            else "unavailable"
        ),
        "sequence": {
            "profile_id": "balanced",
            "current_side": sequence.current_side,
            "active_peak_index": sequence.active_peak_index,
            "active_peak_side": sequence.active_peak_side,
            "active_peak_instant_pressure": (
                sequence.active_peak_instant_pressure
            ),
            "active_peak_accumulated_pressure": (
                sequence.active_peak_accumulated_pressure
            ),
            "bars_since_active_peak": sequence.bars_since_active_peak,
            "decay_ratio": _optional_decimal(sequence.decay_ratio),
            "installed_peak_index": sequence.installed_peak_index,
            "installed_peak_side": sequence.installed_peak_side,
            "installed_peak_instant_pressure": (
                sequence.installed_peak_instant_pressure
            ),
            "installed_peak_accumulated_pressure": (
                sequence.installed_peak_accumulated_pressure
            ),
            "peak_seen": sequence.peak_seen,
            "decay_seen": sequence.decay_seen,
            "liquidation_seen": sequence.liquidation_seen,
            "opposite_build_seen": sequence.opposite_build_seen,
            "accumulated_reversal_seen": sequence.accumulated_reversal_seen,
            "state_transition": sequence.state_transition,
        },
    }


def _main_force_mirror_v2_horizon_payload(
    summary: MainForceMirrorV2HorizonSummary,
) -> dict[str, object]:
    return {
        "horizon_bars": summary.horizon_bars,
        "sample_count": summary.sample_count,
        "median_directional_return": _optional_decimal(
            summary.median_directional_return
        ),
        "median_reversal_return": _optional_decimal(
            summary.median_reversal_return
        ),
        "hit_rate": _optional_decimal(summary.hit_rate),
        "median_mfe": _optional_decimal(summary.median_mfe),
        "median_mae": _optional_decimal(summary.median_mae),
    }


def _main_force_mirror_v2_summary_tree(value: object) -> object:
    if isinstance(value, MainForceMirrorV2HorizonSummary):
        return _main_force_mirror_v2_horizon_payload(value)
    if isinstance(value, Mapping):
        return {
            str(key): _main_force_mirror_v2_summary_tree(item)
            for key, item in value.items()
        }
    raise TypeError("main force mirror V2 summary tree is invalid")


def _main_force_mirror_v2_spread_payload(
    spread: MainForceMirrorV2GroupSpread,
) -> dict[str, object]:
    return {
        "horizon_bars": spread.horizon_bars,
        "top_group": spread.top_group,
        "bottom_group": spread.bottom_group,
        "directional_return_spread": _optional_decimal(
            spread.directional_return_spread
        ),
        "top_sample_count": spread.top_sample_count,
        "bottom_sample_count": spread.bottom_sample_count,
    }


def _main_force_mirror_v2_sensitivity_payload(
    summary: MainForceMirrorV2SensitivitySummary,
) -> dict[str, object]:
    return {
        "member_strength_threshold": _optional_decimal(
            summary.member_strength_threshold
        ),
        "by_product": _main_force_mirror_v2_summary_tree(summary.by_product),
        "pooled": _main_force_mirror_v2_summary_tree(summary.pooled),
    }


def _lifecycle_payload(
    request: LifecycleResearchRequest,
    result: SubingLifecycleResearchResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": "research.subing-lifecycle",
        "status": "ok",
        "readonly": True,
        "policy_id": "subing_lifecycle_v2_research_v1",
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "products": list(result.products),
        "segment_count": result.segment_count,
        "evaluable_boundary_count": result.evaluable_boundary_count,
        "funnel_counts": dict(result.funnel_counts),
        "funnel_count_units": dict(result.funnel_count_units),
        "confirmation_source_counts": dict(result.confirmation_source_counts),
        "v1_v2_overlap_counts": dict(result.v1_v2_overlap_counts),
        "v2_to_v1_lead_bars": list(result.v2_to_v1_lead_bars),
        "confirmed_trading_day_span_counts": dict(
            result.confirmed_trading_day_span_counts
        ),
        "risk_reason_counts": dict(result.risk_reason_counts),
        "recovery_reason_counts": dict(result.recovery_reason_counts),
        "close_reason_counts": dict(result.close_reason_counts),
        "horizon_summary": {
            str(horizon): _horizon_payload(evaluation)
            for horizon, evaluation in result.horizon_summary.items()
        },
    }


def _n_structure_payload(
    request: NStructureResearchRequest,
    result: NStructureResearchResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": "research.n-structure",
        "status": "ok",
        "readonly": True,
        "policy_id": "n_structure_5m_v1",
        "formula_version": "n_structure_v1",
        "research_only": True,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "products": list(result.products),
        "segment_count": result.segment_count,
        "evaluable_bar_count": result.evaluable_bar_count,
        "confirmed_pivot_count": result.confirmed_pivot_count,
        "ambiguous_outside_reset_count": result.ambiguous_outside_reset_count,
        "incomplete_attempt_replaced_count": (result.incomplete_attempt_replaced_count),
        "completed_n_counts": dict(result.completed_n_counts),
        "n_break_counts": dict(result.n_break_counts),
        "range_band_reentry_count": result.range_band_reentry_count,
        "structure_established_counts": dict(result.structure_established_counts),
        "structure_break_counts": dict(result.structure_break_counts),
        "horizon_summary": {
            str(horizon): _price_horizon_payload(evaluation)
            for horizon, evaluation in result.horizon_summary.items()
        },
    }


def _price_horizon_payload(
    evaluation: PriceHorizonEvaluation,
) -> dict[str, object]:
    return {
        "sample_count": evaluation.sample_count,
        "median_directional_return_bps": _optional_decimal(
            evaluation.median_directional_return_bps
        ),
        "median_mfe_bps": _optional_decimal(evaluation.median_mfe_bps),
        "median_mae_bps": _optional_decimal(evaluation.median_mae_bps),
    }


def _candidate_payload(report: CandidateValidationReport) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "command": "research.candidate-validation",
        "status": "ok",
        "readonly": True,
        "candidate_id": report.candidate_id,
        "policy_id": report.policy_id,
        "formula_version": report.formula_version,
        "protocol_id": report.protocol_id,
        "research_only": report.research_only,
        "symbol": report.symbol,
        "retrospective": _candidate_window_payload(report.retrospective),
        "rolling_folds": [
            _candidate_fold_payload(fold) for fold in report.rolling_folds
        ],
        "rolling_stability": {
            "fold_count": report.rolling_stability.fold_count,
            "folds_with_entries": report.rolling_stability.folds_with_entries,
            "entry_count_min": report.rolling_stability.entry_count_min,
            "entry_count_max": report.rolling_stability.entry_count_max,
            "entry_count_median": str(report.rolling_stability.entry_count_median),
        },
        "prospective_oos": _prospective_payload(report.prospective_oos),
        "quality_flags": list(report.quality_flags),
    }


def _jdj_candidate_payload(
    report: JdjCandidateValidationReport,
) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "command": "research.candidate-validation",
        "status": "ok",
        "readonly": True,
        "candidate_id": report.candidate_id,
        "source_event_kind": report.source_event_kind,
        "policy_id": report.policy_id,
        "formula_version": report.formula_version,
        "protocol_id": report.protocol_id,
        "research_only": report.research_only,
        "symbol": report.symbol,
        "retrospective": _jdj_candidate_window_payload(
            report.retrospective
        ),
        "rolling_folds": [
            _jdj_candidate_fold_payload(fold)
            for fold in report.rolling_folds
        ],
        "rolling_stability": {
            "fold_count": report.rolling_stability.fold_count,
            "folds_with_events": report.rolling_stability.folds_with_events,
            "event_count_min": report.rolling_stability.event_count_min,
            "event_count_max": report.rolling_stability.event_count_max,
            "event_count_median": str(
                report.rolling_stability.event_count_median
            ),
        },
        "prospective_oos": _jdj_prospective_payload(
            report.prospective_oos
        ),
        "quality_flags": list(report.quality_flags),
    }


def _jdj_candidate_fold_payload(
    fold: JdjRollingCandidateFold,
) -> dict[str, object]:
    return {
        "fold_id": fold.fold_id,
        "reference": _jdj_candidate_window_payload(fold.reference),
        "test": _jdj_candidate_window_payload(fold.test),
    }


def _jdj_candidate_window_payload(
    window: JdjCandidateWindowResult,
) -> dict[str, object]:
    return {
        "window_id": window.window_id,
        "window_kind": window.window_kind.value,
        "since": window.since.isoformat(),
        "through": window.through.isoformat(),
        "products": list(window.products),
        "segment_count": window.segment_count,
        "evaluable_bar_count": window.evaluable_bar_count,
        "trigger_count_long": window.trigger_count_long,
        "trigger_count_short": window.trigger_count_short,
        "horizon_summary": {
            str(horizon): _price_horizon_payload(evaluation)
            for horizon, evaluation in window.horizon_summary.items()
        },
    }


def _jdj_prospective_payload(
    result: JdjProspectiveOosResult,
) -> dict[str, object]:
    return {
        "status": result.status.value,
        "first_trading_day": result.first_trading_day.isoformat(),
        "through": result.through.isoformat(),
        "result": (
            None
            if result.result is None
            else _jdj_candidate_window_payload(result.result)
        ),
    }


def _n_candidate_payload(
    report: NStructureCandidateValidationReport,
) -> dict[str, object]:
    return {
        "schema_version": report.schema_version,
        "command": "research.candidate-validation",
        "status": "ok",
        "readonly": True,
        "candidate_id": report.candidate_id,
        "policy_id": report.policy_id,
        "formula_version": report.formula_version,
        "protocol_id": report.protocol_id,
        "research_only": report.research_only,
        "symbol": report.symbol,
        "retrospective": _n_candidate_window_payload(report.retrospective),
        "rolling_folds": [
            _n_candidate_fold_payload(fold) for fold in report.rolling_folds
        ],
        "rolling_stability": {
            "fold_count": report.rolling_stability.fold_count,
            "folds_with_completed_n": (report.rolling_stability.folds_with_completed_n),
            "completed_n_min": report.rolling_stability.completed_n_min,
            "completed_n_max": report.rolling_stability.completed_n_max,
            "completed_n_median": str(report.rolling_stability.completed_n_median),
        },
        "prospective_oos": _n_prospective_payload(report.prospective_oos),
        "quality_flags": list(report.quality_flags),
    }


def _n_candidate_fold_payload(fold: NRollingCandidateFold) -> dict[str, object]:
    return {
        "fold_id": fold.fold_id,
        "reference": _n_candidate_window_payload(fold.reference),
        "test": _n_candidate_window_payload(fold.test),
    }


def _n_candidate_window_payload(
    window: NCandidateWindowResult,
) -> dict[str, object]:
    return {
        "window_id": window.window_id,
        "window_kind": window.window_kind.value,
        "since": window.since.isoformat(),
        "through": window.through.isoformat(),
        "products": list(window.products),
        "segment_count": window.segment_count,
        "evaluable_bar_count": window.evaluable_bar_count,
        "confirmed_pivot_count": window.confirmed_pivot_count,
        "ambiguous_outside_reset_count": window.ambiguous_outside_reset_count,
        "incomplete_attempt_replaced_count": (window.incomplete_attempt_replaced_count),
        "completed_n_counts": dict(window.completed_n_counts),
        "n_break_counts": dict(window.n_break_counts),
        "range_band_reentry_count": window.range_band_reentry_count,
        "structure_established_counts": dict(window.structure_established_counts),
        "structure_break_counts": dict(window.structure_break_counts),
        "horizon_summary": {
            str(horizon): _price_horizon_payload(evaluation)
            for horizon, evaluation in window.horizon_summary.items()
        },
    }


def _n_prospective_payload(result: NProspectiveOosResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "first_trading_day": result.first_trading_day.isoformat(),
        "through": result.through.isoformat(),
        "result": (
            None
            if result.result is None
            else _n_candidate_window_payload(result.result)
        ),
    }


def _candidate_fold_payload(fold: RollingCandidateFold) -> dict[str, object]:
    return {
        "fold_id": fold.fold_id,
        "reference": _candidate_window_payload(fold.reference),
        "test": _candidate_window_payload(fold.test),
    }


def _candidate_window_payload(window: CandidateWindowResult) -> dict[str, object]:
    return {
        "window_id": window.window_id,
        "window_kind": window.window_kind.value,
        "since": window.since.isoformat(),
        "through": window.through.isoformat(),
        "products": list(window.products),
        "segment_count": window.segment_count,
        "evaluable_boundary_count": window.evaluable_boundary_count,
        "funnel_counts": dict(window.funnel_counts),
        "funnel_count_units": dict(window.funnel_count_units),
        "confirmation_source_counts": dict(window.confirmation_source_counts),
        "v1_v2_overlap_counts": dict(window.v1_v2_overlap_counts),
        "v2_to_v1_lead_bars": list(window.v2_to_v1_lead_bars),
        "confirmed_trading_day_span_counts": dict(
            window.confirmed_trading_day_span_counts
        ),
        "risk_reason_counts": dict(window.risk_reason_counts),
        "recovery_reason_counts": dict(window.recovery_reason_counts),
        "close_reason_counts": dict(window.close_reason_counts),
        "horizon_summary": {
            str(horizon): _horizon_payload(evaluation)
            for horizon, evaluation in window.horizon_summary.items()
        },
    }


def _prospective_payload(result: ProspectiveOosResult) -> dict[str, object]:
    return {
        "status": result.status.value,
        "first_trading_day": result.first_trading_day.isoformat(),
        "through": result.through.isoformat(),
        "result": (
            None if result.result is None else _candidate_window_payload(result.result)
        ),
    }


def _report_payload(
    report: CalibrationReport,
    *,
    mode: CalibrationMode,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "sample_count": report.sample_count,
        "product_sample_counts": dict(report.product_sample_counts),
    }
    if mode is CalibrationMode.DISCOVERY:
        payload["candidate_thresholds"] = (
            None
            if report.candidate_thresholds is None
            else [str(value) for value in report.candidate_thresholds]
        )
        payload["candidate_evaluations"] = [
            _evaluation_payload(evaluation)
            for evaluation in report.candidate_evaluations
        ]
    else:
        payload["threshold_evaluation"] = (
            None
            if report.threshold_evaluation is None
            else _evaluation_payload(report.threshold_evaluation)
        )
    return payload


def _evaluation_payload(evaluation: ThresholdEvaluation) -> dict[str, object]:
    return {
        "threshold": str(evaluation.threshold),
        "sample_count": evaluation.sample_count,
        "horizons": {
            str(horizon): _horizon_payload(metrics)
            for horizon, metrics in evaluation.horizons.items()
        },
    }


def _horizon_payload(evaluation: HorizonEvaluation) -> dict[str, object]:
    return {
        "sample_count": evaluation.sample_count,
        "ema21_sample_count": evaluation.ema21_sample_count,
        "median_directional_return_bps": _optional_decimal(
            evaluation.median_directional_return_bps
        ),
        "median_mfe_bps": _optional_decimal(evaluation.median_mfe_bps),
        "median_mae_bps": _optional_decimal(evaluation.median_mae_bps),
        "ema21_failure_rate": _optional_decimal(evaluation.ema21_failure_rate),
    }


def _optional_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return "0" if value == 0 else str(value)
