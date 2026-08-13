"""``guiyi research`` request construction for read-only Calibration."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Protocol

from app.market_data.domain import BarFrequency
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


class _ResearchService(Protocol):
    def run(self, request: CalibrationResearchRequest) -> CalibrationResearchResult: ...


def build_research_request(args: argparse.Namespace) -> CalibrationResearchRequest:
    """Convert validated CLI strings into the fixed Task2 request interface."""
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
    request: CalibrationResearchRequest,
    service: _ResearchService,
) -> dict[str, object]:
    """Run historical-only Calibration and render its explicit JSON schema."""
    result = service.run(request)
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
