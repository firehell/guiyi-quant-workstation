"""Bind the public path presentation to one completed physical/calculation owner."""

from zoneinfo import ZoneInfo
from datetime import datetime

from guiyi_quant.newow.historical_path import build_historical_path
from guiyi_quant.newow.page_performance import (
    PageBar,
    PageSegment,
    PageAction,
    compute_page_performance,
)
from guiyi_quant.newow.product_contracts import (
    FeatureRuntimeStatus,
    TradeEligibility,
)


def project_historical_path(
    *,
    replay,
    daily,
    weekly,
    cutoff,
    prices,
    frequency,
    strategy=None,
    fusion_peer=None,
    fusion_weekly=None,
    price_overrides=None,
    calendar_context=None,
    snapshot_trading_day=None,
):
    def stamp(value):
        return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat()

    requested_strategy = strategy or (replay.identity.strategy.value if replay else None)
    unified_empty = requested_strategy in ("oscillation", "fusion", "osc-test5")
    def empty(reason):
        return dict(
            version="guiyi_futures_historical_path_v1",
            reference_policy="unified_trueup" if unified_empty else "ordinary",
            status="unavailable",
            reason=reason,
            buys=[],
            sells=[],
            background=[],
            eta=None,
            holding=False,
            current=None,
            target=None,
            cost=None,
            page_parity=False,
            executable=False,
        )
    frames = (
        [
            f
            for f in replay.frames
            if f.bar.bar.bar_end <= cutoff and f.bar.bar.observation_eligible
        ]
        if replay
        else []
    )
    if (
        not frames
        or not prices
        or frames[-1].availability.status is not FeatureRuntimeStatus.READY
    ):
        return empty("CURRENT_CONTEXT_UNAVAILABLE")
    anchor = frames[-1].bar
    owner = (
        anchor.bar.physical_contract,
        anchor.bar.segment_id,
        anchor.calculation_segment_id,
    )
    frames = [
        f
        for f in frames
        if (
            f.bar.bar.physical_contract,
            f.bar.bar.segment_id,
            f.bar.calculation_segment_id,
        )
        == owner
    ]
    bars = tuple(
        PageBar(
            stamp(f.bar.bar.bar_end),
            f.bar.bar.high,
            f.bar.bar.low,
            f.bar.bar.close,
            True,
            f.bar.bar.trading_day.isoformat(),
        )
        for f in frames
    )
    strategy = strategy or replay.identity.strategy.value
    display_strategy = strategy
    open_reference = None
    event_driven = strategy in ("oscillation", "fusion", "osc-test5")
    if strategy == "osc-test5":
        strategy = "oscillation"
    if strategy.startswith("osc-test"):
        from guiyi_quant.newow.oscillation_experiments import (
            ExperimentKind,
            run_experiment_reference,
        )

        result = run_experiment_reference(
            tuple(f.bar.bar for f in frames), ExperimentKind(strategy)
        )
        trades = [
            dict(
                buyDate=stamp(datetime.fromisoformat(t["entry_bar_end"])),
                sellDate=stamp(datetime.fromisoformat(t["exit_bar_end"])),
                buyPrice=t["entry_reference_price"],
                sellPrice=t["exit_reference_price"],
                forceClose=t["force_close"],
            )
            for t in (result or {}).get("trades", [])
        ]
    else:
        actions = []
        if event_driven:
            if strategy == "fusion" and fusion_peer is None:
                return empty("FUSION_CONTEXT_UNAVAILABLE")
            for src in ((fusion_peer, replay) if strategy == "fusion" else (replay,)):
                for f in src.frames:
                    if (
                        f.bar.bar.physical_contract,
                        f.bar.bar.segment_id,
                        f.bar.calculation_segment_id,
                    ) != owner or f.bar.bar.bar_end > cutoff:
                        continue
                    for a in f.actions:
                        allowed = (
                            TradeEligibility.ELIGIBLE,
                            TradeEligibility.NO_ELIGIBLE_ENTRY,
                        )
                        if src.identity.strategy.value == "trend":
                            allowed = (
                                *allowed,
                                TradeEligibility.INITIAL_CLEAR_NO_ENTRY,
                            )
                        if (
                            a.kind.value in ("BUILD", "CLEAR")
                            and a.trade_eligibility in allowed
                        ):
                            actions.append(
                                PageAction(
                                    stamp(a.bar_end),
                                    "buy" if a.kind.value == "BUILD" else "sell",
                                    a.reference_price,
                                )
                            )
        result = compute_page_performance(
            [PageSegment("|".join(owner), bars, True, tuple(actions))],
            strategy,
            period=frequency,
            selected_mode="ordinary", event_driven=event_driven,
        )
        ordinary = result.get("ordinary") or {}
        trades = ordinary.get("trades", [])
        opened = ordinary.get("open_references", [])
        open_reference = opened[-1] if opened else None

    trading_days = {f.bar.bar.bar_end: f.bar.bar.trading_day.isoformat() for f in frames}
    for trade in [*trades, *([open_reference] if open_reference else [])]:
        for field, output in (("buyDate", "buyTradingDay"), ("sellDate", "sellTradingDay")):
            value = trade.get(field)
            trade[output] = trading_days.get(datetime.fromisoformat(str(value))) if value else None

    def owned(other):
        seq = (
            [
                f
                for f in other.frames
                if f.bar.bar.bar_end <= cutoff
                and f.bar.bar.observation_eligible
                and (f.bar.bar.physical_contract, f.bar.bar.segment_id) == owner[:2]
            ]
            if other
            else []
        )
        if not seq:
            return []
        calc = seq[-1].bar.calculation_segment_id
        return [f for f in seq if f.bar.calculation_segment_id == calc]

    daily_frames = owned(daily)
    weekly_frames = owned(weekly)

    def raw(source):
        return source["raw"] if source else None

    day = prices["status_card"]
    path = build_historical_path(
        trades=trades, open_reference=open_reference, unified_trueup=event_driven,
        kline_dates=[stamp(f.bar.bar.bar_end) for f in frames],
        daily_dates=[stamp(f.bar.bar.bar_end) for f in daily_frames],
        period=frequency,
        today=stamp(cutoff)[:10],
        trading_day=snapshot_trading_day.isoformat() if snapshot_trading_day else None,
        current=raw(prices["current_price"]),
        target=(price_overrides or {}).get("target", raw(day["target"])),
        cost=(price_overrides or {}).get("cost", raw(day["absorb"])),
        weekly_signals=[
            dict(
                date=stamp(a.bar_end), type="buy" if a.kind.value == "BUILD" else "sell"
            )
            for f in weekly_frames
            for a in f.actions
            if a.kind.value in ("BUILD", "CLEAR")
        ],
    )
    if (
        not weekly_frames
        or strategy == "fusion"
        or not any(f.actions for f in weekly_frames)
    ):
        path["background"] = []
    from .path_calendar import apply_path_date
    if snapshot_trading_day is not None:
        apply_path_date(path, calendar_context, snapshot_trading_day)
    elif path.get("eta"):
        path["eta"] = dict(status="unavailable", reason="SNAPSHOT_TRADING_DAY_UNAVAILABLE")
    path["source"] = {
        "physical_contract": owner[0],
        "segment_id": owner[1],
        "calculation_segment_id": owner[2],
        "bar_end": stamp(anchor.bar.bar_end),
        "as_of": stamp(cutoff),
        "strategy": display_strategy,
        "frequency": frequency,
        "trading_day": anchor.bar.trading_day.isoformat(),
        "snapshot_trading_day": snapshot_trading_day.isoformat() if snapshot_trading_day else None,
        "calendar_identity": (calendar_context or {}).get("identity"),
        "price_source": "canonical_channel_not_private_batch",
        "background_status": "ready" if path["background"] else "unavailable",
    }
    return path
