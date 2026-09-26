"""Independent, zero-cost long/flat fusion reference. Never an account model."""

from __future__ import annotations

from decimal import Decimal, localcontext
from hashlib import sha256
import json

from .product_contracts import (
    ActionKind,
    DataInterruption,
    OwnerBoundary,
    ProductStrategy,
    StrategyReplay,
    TradeEligibility,
)
from .reference_trades import ReferenceTradeProjector
from .product_identity import REFERENCE_MODEL_VERSION
from .reference_statistics import PerformanceWindow, summarize_reference

MODEL_VERSION = "newow_dual_fusion_reference_zero_cost_v1"


def _return(entry: Decimal, exit_: Decimal) -> Decimal:
    with localcontext() as context:
        context.prec = 28
        return (exit_ / entry - Decimal(1)) * Decimal(100)


def fusion_reference_comparison(
    trend: StrategyReplay,
    oscillation: StrategyReplay,
    boundaries: tuple[OwnerBoundary, ...],
    interruptions: tuple[DataInterruption, ...],
    window: PerformanceWindow,
) -> dict[str, object]:
    """Replay both accepted source strategies over identical complete inputs.

    SELL before BUY; oscillation before trend; clear-without-own-entry remains
    usable to close a fusion entry from the other strategy. No terminal force-close.
    """
    if (
        trend.identity.strategy is not ProductStrategy.TREND
        or oscillation.identity.strategy is not ProductStrategy.OSCILLATION
    ):
        raise ValueError("NEWOW_FUSION_SOURCE_IDENTITY_CONFLICT")
    if (
        trend.identity.product,
        trend.identity.frequency,
        trend.identity.input_quality_policy,
    ) != (
        oscillation.identity.product,
        oscillation.identity.frequency,
        oscillation.identity.input_quality_policy,
    ):
        raise ValueError("NEWOW_FUSION_SOURCE_IDENTITY_CONFLICT")
    if tuple(f.bar for f in trend.frames) != tuple(f.bar for f in oscillation.frames):
        raise ValueError("NEWOW_FUSION_INPUT_CONFLICT")
    sources = (oscillation, trend)
    by_bar = {}
    for replay in sources:
        for action in sorted(
            replay.actions, key=lambda a: (a.bar_end, a.sequence, a.signal_id)
        ):
            if action.bar_end <= window.cutoff and action.trade_eligibility in (
                TradeEligibility.ELIGIBLE,
                TradeEligibility.NO_ELIGIBLE_ENTRY,
            ):
                by_bar.setdefault(action.bar_end, []).append(action)
    rows = []
    holding = None
    mark = None
    bars_held = 0
    identity = (
        trend.identity.product,
        trend.identity.frequency.value,
        trend.identity.formula_versions,
        oscillation.identity.formula_versions,
        MODEL_VERSION,
    )

    def finish(status, exit_action=None, interruption=None):
        nonlocal holding, mark, bars_held
        if holding is None:
            return
        digest = sha256(
            json.dumps([identity, holding.signal_id], sort_keys=True).encode()
        ).hexdigest()
        rows.append(
            {
                "reference_trade_id": digest,
                "reference_model_version": MODEL_VERSION,
                "physical_contract": holding.physical_contract,
                "segment_id": holding.segment_id,
                "calculation_segment_id": holding.calculation_segment_id,
                "entry_source": holding.identity.strategy.value,
                "entry_signal_id": holding.signal_id,
                "entry_bar_end": holding.bar_end.isoformat(),
                "entry_trading_day": holding.trading_day.isoformat(),
                "entry_reference_price": format(holding.reference_price, "f"),
                "exit_source": exit_action.identity.strategy.value
                if exit_action
                else None,
                "exit_signal_id": exit_action.signal_id if exit_action else None,
                "exit_bar_end": exit_action.bar_end.isoformat()
                if exit_action
                else None,
                "exit_reference_price": format(exit_action.reference_price, "f")
                if exit_action
                else None,
                "status": status,
                "holding_bars": bars_held,
                "reference_return_pct": format(
                    _return(holding.reference_price, exit_action.reference_price), "f"
                )
                if exit_action
                else None,
                "mark_bar_end": mark.bar.bar_end.isoformat() if mark else None,
                "mark_reference_price": format(mark.bar.close, "f") if mark else None,
                "mark_change_pct": format(
                    _return(holding.reference_price, mark.bar.close), "f"
                )
                if mark
                else None,
                "interrupted_at": interruption.isoformat() if interruption else None,
                "statistics_membership": "entry_in_window_v1"
                if window.since <= holding.trading_day <= window.through
                else "initial_before_window",
            }
        )
        holding = None
        mark = None
        bars_held = 0

    events = [
        (f.bar.bar.bar_end, 1, f.bar)
        for f in trend.frames
        if f.bar.bar.bar_end <= window.cutoff and f.bar.bar.observation_eligible
    ]
    events += [
        (b.effective_at, 0, b) for b in boundaries if b.effective_at <= window.cutoff
    ]
    events += [
        (g.effective_at, 0, g) for g in interruptions if g.effective_at <= window.cutoff
    ]
    for timestamp, kind, event in sorted(events, key=lambda e: (e[0], e[1])):
        if kind == 0:
            old_segment = getattr(
                event, "old_segment_id", getattr(event, "segment_id", None)
            )
            if holding is not None and holding.segment_id == old_segment:
                finish(
                    "ROLLOVER_INTERRUPTED"
                    if hasattr(event, "old_contract")
                    else "DATA_INTERRUPTED",
                    interruption=timestamp,
                )
            continue
        bar = event.bar
        if holding is not None and (
            holding.physical_contract,
            holding.segment_id,
            holding.calculation_segment_id,
        ) != (bar.physical_contract, bar.segment_id, event.calculation_segment_id):
            finish(
                "ROLLOVER_INTERRUPTED"
                if holding.physical_contract != bar.physical_contract
                or holding.segment_id != bar.segment_id
                else "DATA_INTERRUPTED",
                interruption=timestamp,
            )
        if not bar.observation_eligible:
            if holding is not None:
                finish("DATA_INTERRUPTED", interruption=timestamp)
            continue
        if holding is not None:
            mark = event
            bars_held += 1
        actions = [
            a
            for a in by_bar.get(timestamp, ())
            if (a.physical_contract, a.segment_id, a.calculation_segment_id)
            == (bar.physical_contract, bar.segment_id, event.calculation_segment_id)
        ]
        sells = [a for a in actions if a.kind is ActionKind.CLEAR]
        buys = [a for a in actions if a.kind is ActionKind.BUILD]
        if holding is not None and sells:
            finish("CLOSED", sells[0])
        if holding is None and buys:
            holding, mark, bars_held = buys[0], event, 0
    finish("OPEN")
    members = [r for r in rows if r["statistics_membership"] == "entry_in_window_v1"]
    closed = [r for r in members if r["status"] == "CLOSED"]
    with localcontext() as context:
        context.prec = 28
        total = (
            sum((Decimal(r["reference_return_pct"]) for r in closed), Decimal(0))
            if closed
            else None
        )
    groups = []
    for replay in (trend, oscillation):
        projection = ReferenceTradeProjector().project(
            replay, boundaries, window.cutoff, data_interruptions=interruptions
        )
        summary = summarize_reference(projection, window)
        groups.append(
            {
                "model": replay.identity.strategy.value,
                "reference_model_version": REFERENCE_MODEL_VERSION,
                "closed_count": summary.closed_count,
                "sum_return_percentage_points": format(
                    summary.sum_return_percentage_points, "f"
                )
                if summary.sum_return_percentage_points is not None
                else None,
                "open_count": summary.open_count,
                "interrupted_count": summary.interrupted_count,
            }
        )
    groups.append(
        {
            "model": "fusion",
            "reference_model_version": MODEL_VERSION,
            "closed_count": len(closed),
            "sum_return_percentage_points": format(total, "f")
            if total is not None
            else None,
            "open_count": sum(r["status"] == "OPEN" for r in members),
            "interrupted_count": sum(
                r["status"].endswith("INTERRUPTED") for r in members
            ),
        }
    )
    return {
        "reference_model_version": MODEL_VERSION,
        "performance_since": window.since.isoformat(),
        "performance_through": window.through.isoformat(),
        "reference_cutoff": window.cutoff.isoformat(),
        "page_parity": True,
        "executable": False,
        "source_formula_versions": list(
            trend.identity.formula_versions + oscillation.identity.formula_versions
        ),
        "groups": groups,
        "items": list(reversed(rows))[:200],
        "records_truncated": len(rows) > 200,
    }
