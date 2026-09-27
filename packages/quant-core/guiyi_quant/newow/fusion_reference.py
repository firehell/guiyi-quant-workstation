"""Independent, zero-cost long/flat fusion reference. Never an account model."""

from __future__ import annotations

from dataclasses import dataclass
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


@dataclass(frozen=True, slots=True)
class FusionReferenceReplayState:
    model_version: str = MODEL_VERSION


def build_fusion_stream_identity(product: str, frequency: str):
    """Independent reference projection identity; never a third base kernel."""
    from .product_adapters import build_product_identity
    from .product_contracts import ProductFrequency, INTRADAY_PRODUCT_FREQUENCIES
    from .product_identity import futures_adaptation_version
    from ..reference_trading import StreamIdentity
    selected = ProductFrequency(frequency)
    if selected not in INTRADAY_PRODUCT_FREQUENCIES:
        raise ValueError("NEWOW_FUSION_FREQUENCY_UNSUPPORTED")
    trend = build_product_identity(product, ProductStrategy.TREND, selected)
    oscillation = build_product_identity(product, ProductStrategy.OSCILLATION, selected)
    return StreamIdentity(
        strategy_code="newow_dual_fusion",
        formula_versions=trend.formula_versions + oscillation.formula_versions,
        profile_id=f"newow_dual_fusion_{selected.value}_v1",
        reference_model_version=MODEL_VERSION,
        futures_adaptation_version=futures_adaptation_version(selected.value),
        product=product, frequency=selected.value, series_kind="actual_dominant",
        recording_mode="historical_replay", observation_policy_version=None,
    )


def fusion_trade_id(trend_identity, oscillation_identity, entry_signal_id: str) -> str:
    identity = (trend_identity.product, trend_identity.frequency.value,
                trend_identity.formula_versions, oscillation_identity.formula_versions,
                MODEL_VERSION)
    return sha256(json.dumps([identity, entry_signal_id], sort_keys=True).encode()).hexdigest()


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
    *,
    record_limit: int | None = 200,
) -> dict[str, object]:
    """Replay both accepted source strategies over identical complete inputs.

    SELL before BUY; oscillation before trend; clear-without-own-entry remains
    usable to close a fusion entry from the other strategy. No terminal force-close.
    """
    if record_limit is not None and (type(record_limit) is not int or record_limit <= 0):
        raise ValueError("NEWOW_FUSION_RECORD_LIMIT_INVALID")
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
        digest = fusion_trade_id(trend.identity, oscillation.identity, holding.signal_id)
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
                "exit_trading_day": exit_action.trading_day.isoformat()
                if exit_action else None,
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
    revision = sha256(json.dumps({
        "model": identity,
        "profiles": [trend.identity.profile_id, oscillation.identity.profile_id],
        "window": [window.since.isoformat(), window.through.isoformat(), window.cutoff.isoformat()],
        "rows": rows,
        "input": [
            [frame.bar.source_bar_sha256, frame.bar.calculation_segment_id,
             frame.bar.bar.bar_end.isoformat(), frame.bar.bar.physical_contract,
             frame.bar.bar.segment_id, str(frame.bar.bar.close), frame.bar.bar.observation_eligible]
            for frame in trend.frames if frame.bar.bar.bar_end <= window.cutoff
        ],
    }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    records = list(reversed(rows))
    return {
        "snapshot_schema": "newow_fusion_reference_snapshot_v2",
        "reference_revision": revision,
        "summary": groups[-1],
        "curve": sorted(closed, key=lambda row: (row["exit_bar_end"], row["reference_trade_id"])),
        "source_profiles": [trend.identity.profile_id, oscillation.identity.profile_id],
        "product": trend.identity.product,
        "frequency": trend.identity.frequency.value,
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
        "items": records if record_limit is None else records[:record_limit],
        "records_truncated": record_limit is not None and len(rows) > record_limit,
    }
