"""``guiyi research`` request construction and read-only JSON rendering."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol, TypeAlias, cast

from app.market_data.candidate_validation import (
    CandidateValidationReport,
    CandidateWindowResult,
    ProspectiveOosResult,
    RollingCandidateFold,
)
from app.market_data.candidate_validation_schedule import (
    CandidateValidationRequest,
)
from app.market_data.domain import BarFrequency, SeriesKind
from app.market_data.main_force_mirror_futures_research_service import (
    MainForceMirrorFuturesHorizonSummary,
    MainForceMirrorFuturesResearchRequest,
    MainForceMirrorFuturesResearchResult,
)
from app.market_data.multi_candidate_robustness import (
    CommonPriceHorizonSummary,
    MultiCandidateRobustnessReport,
)
from app.market_data.multi_candidate_robustness_policy import (
    MultiCandidateRobustnessRequest,
)
from app.market_data.n_structure_research_service import (
    NStructureResearchRequest,
    NStructureResearchResult,
)
from app.market_data.n_candidate_validation import (
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
from app.market_data.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    CalibrationResearchRequest,
    CalibrationResearchResult,
    SlopeThresholds,
)
from app.market_data.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
    SubingLifecycleResearchResult,
)


class _CalibrationResearchService(Protocol):
    def run(self, request: CalibrationResearchRequest) -> CalibrationResearchResult: ...


class _LifecycleResearchService(Protocol):
    def run(
        self, request: LifecycleResearchRequest
    ) -> SubingLifecycleResearchResult: ...


class _NStructureResearchService(Protocol):
    def run(self, request: NStructureResearchRequest) -> NStructureResearchResult: ...


class _CandidateValidationService(Protocol):
    def run(
        self,
        request: CandidateValidationRequest,
    ) -> CandidateValidationReport | NStructureCandidateValidationReport: ...


class _MainForceMirrorFuturesResearchService(Protocol):
    def run(
        self,
        request: MainForceMirrorFuturesResearchRequest,
    ) -> MainForceMirrorFuturesResearchResult: ...


class _MultiCandidateRobustnessService(Protocol):
    def run(
        self, request: MultiCandidateRobustnessRequest
    ) -> MultiCandidateRobustnessReport: ...


ResearchRequest: TypeAlias = (
    CalibrationResearchRequest
    | LifecycleResearchRequest
    | CandidateValidationRequest
    | MainForceMirrorFuturesResearchRequest
    | NStructureResearchRequest
    | MultiCandidateRobustnessRequest
)


def build_research_request(args: argparse.Namespace) -> ResearchRequest:
    """Convert CLI strings into one immutable research request."""
    if args.research_command == "candidate-robustness":
        return MultiCandidateRobustnessRequest(protocol_id=args.protocol)
    if args.research_command == "main-force-mirror-futures":
        return MainForceMirrorFuturesResearchRequest(
            symbol=args.symbol,
            series_kind=SeriesKind(args.series_kind),
            contract=args.contract,
            frequency=BarFrequency(args.frequency),
            since=_day(args.since),
            through=_day(args.through),
        )
    if args.research_command == "candidate-validation":
        return CandidateValidationRequest(
            candidate_id=args.candidate,
            protocol_id=args.protocol,
            symbol=args.symbol,
            through=_day(args.through),
        )
    if args.research_command == "subing-lifecycle":
        return LifecycleResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
        )
    if args.research_command == "n-structure":
        return NStructureResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
        )
    if args.research_command != "subing-calibration":
        raise ValueError("CLI_RESEARCH_COMMAND_INVALID")
    slope_5m = _decimal(args.slope_threshold_5m_bps)
    slope_15m = _decimal(args.slope_threshold_15m_bps)
    slope_thresholds: SlopeThresholds | None = None
    if slope_5m is not None or slope_15m is not None:
        if slope_5m is None or slope_15m is None:
            raise ValueError("CLI_SLOPE_THRESHOLD_PAIR_REQUIRED")
        slope_thresholds = SlopeThresholds(slope_5m, slope_15m)
    return CalibrationResearchRequest(
        phase=CalibrationPhase(args.phase),
        mode=CalibrationMode(args.mode),
        frequency=BarFrequency(args.frequency),
        since=_day(args.since),
        through=_day(args.through),
        symbol=args.symbol,
        slope_threshold_bps=_decimal(args.slope_threshold_bps),
        slope_thresholds=slope_thresholds,
        zero_band_bps=_decimal(args.zero_band_bps),
    )


def run_research_command(
    request: ResearchRequest,
    service: object,
) -> dict[str, object]:
    """Run one Historical-only research command and render its JSON schema."""
    if isinstance(request, MultiCandidateRobustnessRequest):
        robustness_service = cast(_MultiCandidateRobustnessService, service)
        return _multi_candidate_robustness_payload(robustness_service.run(request))
    if isinstance(request, MainForceMirrorFuturesResearchRequest):
        mirror_service = cast(_MainForceMirrorFuturesResearchService, service)
        return _main_force_mirror_futures_payload(
            request,
            mirror_service.run(request),
        )
    if isinstance(request, CandidateValidationRequest):
        candidate_service = cast(_CandidateValidationService, service)
        report = candidate_service.run(request)
        if isinstance(report, NStructureCandidateValidationReport):
            return _n_candidate_payload(report)
        return _candidate_payload(report)
    if isinstance(request, LifecycleResearchRequest):
        lifecycle_service = cast(_LifecycleResearchService, service)
        return _lifecycle_payload(request, lifecycle_service.run(request))
    if isinstance(request, NStructureResearchRequest):
        n_service = cast(_NStructureResearchService, service)
        return _n_structure_payload(request, n_service.run(request))
    calibration_service = cast(_CalibrationResearchService, service)
    result = calibration_service.run(request)
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


def _main_force_mirror_futures_payload(
    request: MainForceMirrorFuturesResearchRequest,
    result: MainForceMirrorFuturesResearchResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": "research.main-force-mirror-futures",
        "status": "ok",
        "readonly": True,
        "symbol": request.symbol,
        "series_kind": request.series_kind.value,
        "contract": request.contract,
        "frequency": request.frequency.value,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "products": list(result.products),
        "bars_valid_count": result.bars_valid_count,
        "bars_state_ready_count": result.bars_state_ready_count,
        "bars_caution_ready_count": result.bars_caution_ready_count,
        "event_count_long": result.event_count_long,
        "event_count_short": result.event_count_short,
        "conflict_count": result.conflict_count,
        "events_per_1000_caution_ready_bars": (
            result.events_per_1000_caution_ready_bars
        ),
        "missing_oi_count": result.missing_oi_count,
        "segment_reset_count": result.segment_reset_count,
        "timestamp_invalid_count": result.timestamp_invalid_count,
        "state_distribution": dict(result.state_distribution),
        "reason_code_distribution": dict(result.reason_code_distribution),
        "score_distribution": list(result.score_distribution),
        "horizon_summary": {
            str(horizon): _main_force_mirror_futures_horizon_payload(summary)
            for horizon, summary in result.horizon_summary.items()
        },
    }


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


def _cross_symbol_summary_payload(value: object) -> dict[str, object]:
    return {
        "candidate_id": value.candidate_id,  # type: ignore[attr-defined]
        "product_count": value.product_count,  # type: ignore[attr-defined]
        "available_product_count": value.available_product_count,  # type: ignore[attr-defined]
        "unavailable_product_count": value.unavailable_product_count,  # type: ignore[attr-defined]
        "products_with_events": value.products_with_events,  # type: ignore[attr-defined]
        "products_without_events": value.products_without_events,  # type: ignore[attr-defined]
        "event_rate_available_count": value.event_rate_available_count,  # type: ignore[attr-defined]
        "event_rate_min": _optional_decimal(value.event_rate_min),  # type: ignore[attr-defined]
        "event_rate_median": _optional_decimal(value.event_rate_median),  # type: ignore[attr-defined]
        "event_rate_max": _optional_decimal(value.event_rate_max),  # type: ignore[attr-defined]
        "horizon_sign_summary": {
            str(horizon): {
                "available_median_return_symbols": summary.available_median_return_symbols,
                "positive_median_return_symbols": summary.positive_median_return_symbols,
                "zero_median_return_symbols": summary.zero_median_return_symbols,
                "negative_median_return_symbols": summary.negative_median_return_symbols,
            }
            for horizon, summary in value.horizon_sign_summary.items()  # type: ignore[attr-defined]
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


def _main_force_mirror_futures_horizon_payload(
    summary: MainForceMirrorFuturesHorizonSummary,
) -> dict[str, object]:
    return {
        "horizon_bars": summary.horizon_bars,
        "sample_count": summary.sample_count,
        "reversal_returns": list(summary.reversal_returns),
        "warning_mfe": list(summary.warning_mfe),
        "warning_mae": list(summary.warning_mae),
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
    return None if value is None else str(value)


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("CLI_DATE_INVALID") from exc


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("CLI_THRESHOLD_INVALID") from exc
