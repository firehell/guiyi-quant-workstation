"""Project page estimates from the unified reader's completed physical prefixes."""
from __future__ import annotations

from itertools import groupby
from zoneinfo import ZoneInfo

from guiyi_quant.newow.page_performance import PageAction, PageBar, PageSegment, compute_page_performance
from guiyi_quant.newow.product_adapters import build_product_identity, label_calculation_segments, replay_strategy
from guiyi_quant.newow.product_contracts import ActionKind, ProductStrategy, TradeEligibility, lifecycle_input_sha256


def project_page_performance(read, identity, resolved, *, fusion=False, replays=None):
    """Never consume ReferenceTrade pairing or alter the strategy facts.

    Warm-up prefixes remain inside their own physical/calculation owner. A final
    source boundary/gap invalidates terminal marking instead of closing a trade.
    """
    labeled = label_calculation_segments(identity, read.replay_bars, read.data_interruptions)
    labeled = tuple(item for item in labeled if item.bar.bar_end <= resolved.cutoff)
    # groupby iterators must be consumed before advancing the source iterator.
    groups = []
    for owner, values in groupby(labeled, key=lambda item: (
            item.bar.physical_contract, item.bar.segment_id, item.calculation_segment_id)):
        groups.append((owner, tuple(values)))
    actions = {}
    if fusion:
        replays = dict(replays or {})
        for strategy in (ProductStrategy.OSCILLATION, ProductStrategy.TREND):
            if strategy not in replays:
                source_identity = build_product_identity(identity.product, strategy, identity.frequency,
                    input_quality_policy=identity.input_quality_policy)
                replays[strategy] = replay_strategy(source_identity, read.replay_bars,
                    lifecycle_evidence=read.lifecycle_evidence, data_interruptions=read.data_interruptions)
            for action in replays[strategy].actions:
                allowed = (TradeEligibility.ELIGIBLE, TradeEligibility.NO_ELIGIBLE_ENTRY)
                if strategy is ProductStrategy.TREND:
                    allowed = (*allowed, TradeEligibility.INITIAL_CLEAR_NO_ENTRY)
                if action.trade_eligibility not in allowed:
                    continue
                if action.kind not in (ActionKind.BUILD, ActionKind.CLEAR):
                    continue
                owner = (action.physical_contract, action.segment_id, action.calculation_segment_id)
                actions.setdefault(owner, []).append(PageAction(
                    action.bar_end.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
                    "buy" if action.kind is ActionKind.BUILD else "sell", action.reference_price))
    last = max((item.bar.bar_end for item in labeled if item.bar.observation_eligible), default=None)
    terminal_blocked = last is None or not resolved.complete or any(
        gap.effective_at <= resolved.cutoff and gap.effective_at >= last
        for gap in read.data_interruptions)
    # Owner boundaries at/after the final input represent an interruption, not
    # a fresh completed current owner eligible for source terminal marking.
    if last is not None:
        terminal_blocked = terminal_blocked or any(
            boundary.effective_at <= resolved.cutoff and boundary.effective_at >= last
            for boundary in read.boundaries)
    segments = []
    for index, (owner, values) in enumerate(groups):
        bars = tuple(PageBar(
            item.bar.bar_end.astimezone(ZoneInfo("Asia/Shanghai")).isoformat(),
            item.bar.high, item.bar.low, item.bar.close,
            item.bar.observation_eligible, item.bar.trading_day.isoformat()) for item in values)
        dates = {bar.date for bar in bars}
        segments.append(PageSegment("|".join(str(value) for value in owner), bars,
            index == len(groups) - 1 and not terminal_blocked and bool(bars) and bars[-1].observation_eligible,
            tuple(action for action in actions.get(owner, ()) if action.date in dates)))
    result = compute_page_performance(segments, "fusion" if fusion else identity.strategy.value,
        period=identity.frequency.value, since=resolved.requested_since.isoformat(),
        through=resolved.requested_through.isoformat())
    result["input_sha256"] = lifecycle_input_sha256(labeled)
    result["source_evidence_sha256"] = read.reference_source_evidence_sha256
    return result
