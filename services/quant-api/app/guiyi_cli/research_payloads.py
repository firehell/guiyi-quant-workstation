"""Stable read-only JSON renderers for ``guiyi research``."""

from __future__ import annotations

from decimal import Decimal

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
from app.research.subing.subing_watch_research_service import (
    FORMULA_VERSION,
    SubingWatchRate,
    SubingWatchResearchRequest,
    SubingWatchResearchResult,
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


def _subing_watch_payload(
    request: SubingWatchResearchRequest,
    result: SubingWatchResearchResult,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "command": "research.subing-watch",
        "status": "ok",
        "readonly": True,
        "formula_version": FORMULA_VERSION,
        "since": request.since.isoformat(),
        "through": request.through.isoformat(),
        "symbols": (
            "active"
            if request.symbols == "active"
            else list(sorted(request.symbols))
        ),
        "forward_bars": list(request.forward_bars),
        "products": [
            {
                "symbol": product.symbol,
                "candidate_count": product.candidate_count,
                "direction_counts": dict(sorted(product.direction_counts.items())),
                "candidates_per_trading_day": dict(
                    sorted(product.candidates_per_trading_day.items())
                ),
                "same_direction_clustering": {
                    "adjacent_pair_count": (
                        product.same_direction_clustering.adjacent_pair_count
                    ),
                    "same_direction_pair_count": (
                        product.same_direction_clustering.same_direction_pair_count
                    ),
                    "rate": _watch_rate_payload(
                        product.same_direction_clustering.rate
                    ),
                },
                "session_distribution": dict(
                    sorted(product.session_distribution.items())
                ),
                "context_availability": {
                    "available_count": product.context_availability.available_count,
                    "candidate_count": product.context_availability.candidate_count,
                    "rate": _watch_rate_payload(
                        product.context_availability.rate
                    ),
                },
                "range_state_distribution": dict(
                    product.range_state_distribution
                ),
                "higher_timeframe_alignment_distribution": dict(
                    product.higher_timeframe_alignment_distribution
                ),
                "forward_diagnostics": {
                    str(horizon): {
                        "sample_count": diagnostics.sample_count,
                        "truncated_count": diagnostics.truncated_count,
                        "median_directional_close_change_bps": _optional_decimal(
                            diagnostics.median_directional_close_change_bps
                        ),
                        "median_mfe_bps": _optional_decimal(
                            diagnostics.median_mfe_bps
                        ),
                        "median_mae_bps": _optional_decimal(
                            diagnostics.median_mae_bps
                        ),
                    }
                    for horizon, diagnostics in sorted(
                        product.forward_diagnostics.items()
                    )
                },
            }
            for product in sorted(result.products, key=lambda item: item.symbol)
        ],
    }


def _watch_rate_payload(rate: SubingWatchRate) -> dict[str, object]:
    return {
        "numerator": rate.numerator,
        "denominator": rate.denominator,
        "value": _optional_decimal(rate.value),
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
