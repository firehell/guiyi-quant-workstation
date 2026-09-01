"""Build immutable requests for ``guiyi research`` commands."""

from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal, TypeAlias

from app.market_data.domain import BarFrequency
from app.research.subing.subing_calibration_service import (
    CalibrationMode,
    CalibrationPhase,
    CalibrationResearchRequest,
    SlopeThresholds,
)
from app.research.subing.subing_lifecycle_research_service import (
    LifecycleResearchRequest,
)
from app.research.subing.subing_watch_research_service import (
    SubingWatchResearchRequest,
)


ResearchRequest: TypeAlias = (
    CalibrationResearchRequest
    | LifecycleResearchRequest
    | SubingWatchResearchRequest
)


def build_research_request(args: argparse.Namespace) -> ResearchRequest:
    """Convert CLI strings into one immutable research request."""
    if args.research_command == "subing-lifecycle":
        return LifecycleResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbol=args.symbol,
        )
    if args.research_command == "subing-watch":
        return SubingWatchResearchRequest(
            since=_day(args.since),
            through=_day(args.through),
            symbols=_symbols(args.symbols),
            forward_bars=_forward_bars(args.forward_bars),
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


def _symbols(value: str) -> tuple[str, ...] | Literal["active"]:
    if value == "active":
        return "active"
    raw = value.split(",")
    symbols = tuple(item.strip().lower() for item in raw)
    if any(not symbol for symbol in symbols):
        raise ValueError("CLI_SYMBOLS_INVALID")
    return tuple(sorted(symbols))


def _forward_bars(value: str) -> tuple[int, ...]:
    if not value:
        return ()
    raw = value.split(",")
    if any(not item or not item.isascii() or not item.isdigit() for item in raw):
        raise ValueError("CLI_FORWARD_BARS_INVALID")
    return tuple(int(item) for item in raw)
