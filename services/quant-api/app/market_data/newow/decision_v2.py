"""Read-only CDV2 adapter. Source facts remain distinct from batch and account facts."""

from guiyi_quant.newow.composite_explanation import calculate_composite_volatility
from guiyi_quant.newow.composite_decision_v2 import compute_cdv2
from guiyi_quant.newow.cross_period_prices import (
    PriceSource,
    select_cross_period_prices,
)
from guiyi_quant.newow.product_contracts import (
    ProductFrequency,
    FeatureRuntimeStatus,
    MainState,
)
from guiyi_quant.newow.trend_channel_display import build_trend_channel_layer

PERIODS = {
    ProductFrequency.WEEKLY: "week",
    ProductFrequency.DAILY: "day",
    ProductFrequency.HOURLY: "m60",
}
SIGNALS = {
    MainState.BUILD: "buy",
    MainState.HOLD: "hold",
    MainState.CLEAR: "sell",
    MainState.FLAT: "wait",
}


def build_decision_v2(trend, oscillation, main_rise, read, identity):
    cutoff = read.as_of
    current_frames = [
        f
        for f in trend[identity.frequency].frames
        if f.bar.bar.observation_eligible and f.bar.bar.bar_end <= cutoff
    ]

    def interrupted_tail(frame, frequency):
        if frame is None:
            return True
        b = frame.bar.bar
        return any(
            g.physical_contract == b.physical_contract
            and g.segment_id == b.segment_id
            and b.bar_end < g.effective_at <= cutoff
            for g in read.data_interruptions_by_frequency.get(frequency, ())
        ) or any(
            boundary.old_contract == b.physical_contract
            and boundary.old_segment_id == b.segment_id
            and b.bar_end <= boundary.effective_at <= cutoff
            for boundary in read.boundaries
        )

    anchor = current_frames[-1] if current_frames else None
    if interrupted_tail(anchor, identity.frequency):
        anchor = None
    owner = (
        (anchor.bar.bar.physical_contract, anchor.bar.bar.segment_id)
        if anchor
        else None
    )
    states = {"trend": {}, "oscillation": {}}
    ages = {"trend": {}, "oscillation": {}}
    facts = []
    prefixes = {}
    for axis, replays in (("trend", trend), ("oscillation", oscillation)):
        for frequency, period in PERIODS.items():
            replay = replays.get(frequency)
            frames = (
                [
                    f
                    for f in replay.frames
                    if f.bar.bar.observation_eligible and f.bar.bar.bar_end <= cutoff
                ]
                if replay
                else []
            )
            frame = frames[-1] if frames else None
            ready = (
                not interrupted_tail(frame, frequency)
                and frame.availability.status is FeatureRuntimeStatus.READY
                and (frame.bar.bar.physical_contract, frame.bar.bar.segment_id) == owner
            )
            state = SIGNALS.get(frame.main_state) if ready else None
            prefix = (
                [
                    f
                    for f in replay.frames
                    if f.bar.calculation_segment_id == frame.bar.calculation_segment_id
                    and f.bar.bar.observation_eligible
                    and (f.bar.bar.physical_contract, f.bar.bar.segment_id) == owner
                    and f.bar.bar.bar_end <= frame.bar.bar.bar_end
                ]
                if ready
                else []
            )
            actions = [a for f in prefix for a in f.actions]
            last = actions[-1] if actions else None
            positions = {f.bar.bar.bar_end: i for i, f in enumerate(prefix)}
            age = (
                len(prefix) - 1 - positions[last.bar_end]
                if last and last.bar_end in positions
                else -1
            )
            states[axis][period] = state
            ages[axis][period] = age
            prefixes[(axis, frequency)] = prefix
            facts.append(
                {
                    "role": f"{axis}_{period}",
                    "state": state,
                    "age": age,
                    "frequency": frequency.value,
                    "bar_end": frame.bar.bar.bar_end.isoformat() if ready else None,
                    "physical_contract": frame.bar.bar.physical_contract
                    if ready
                    else None,
                    "segment_id": frame.bar.bar.segment_id if ready else None,
                    "formula_versions": list(replay.identity.formula_versions)
                    if replay
                    else [],
                    "source_category": "canonical_strategy_replay",
                    "status": "ready" if ready else "unavailable",
                    "reason": None
                    if ready
                    else "PERIOD_NOT_OPEN"
                    if frequency is ProductFrequency.HOURLY and not replay
                    else "WARMING_OR_OWNER_CONTEXT_UNAVAILABLE",
                }
            )
    daily = prefixes.get(("trend", ProductFrequency.DAILY), [])
    cross = None
    if daily:
        actions = [a for f in daily for a in f.actions]
        if actions and 0 <= ages["trend"]["day"] <= 2:
            cross = {
                "type": "buy" if actions[-1].kind.value == "BUILD" else "sell",
                "bars_ago": ages["trend"]["day"],
                "source": "canonical_daily_replay",
            }
    volatility, vol_pct = None, None
    measured = (
        calculate_composite_volatility(tuple(f.bar for f in daily))
        if len(daily) >= 6
        else None
    )
    if measured:
        volatility, vol_pct = measured.level.value, measured.value_pct
    main_prefix = prefixes.get(("trend", identity.frequency), [])
    recent = (
        [
            f
            for f in main_rise.frames
            if f.bar.bar.observation_eligible
            and f.bar.bar.bar_end <= cutoff
            and (f.bar.bar.physical_contract, f.bar.bar.segment_id) == owner
            and f.availability.status is FeatureRuntimeStatus.READY
            and (
                main_prefix
                and f.bar.calculation_segment_id
                == main_prefix[-1].bar.calculation_segment_id
            )
        ]
        if main_rise
        else []
    )
    j_reduce = any(h.kind == "J" for f in recent[-3:] for h in f.hints)
    cdv2 = compute_cdv2(
        states["trend"],
        states["oscillation"],
        osc_age=ages["oscillation"]["day"],
        cross=cross,
        volatility=volatility,
        j_reduce=j_reduce,
    )
    cdv2.update(
        {
            "as_of": cutoff.isoformat(),
            "basis": "completed",
            "facts": facts,
            "signal_ages": ages,
            "volatility_pct": format(vol_pct, "f") if vol_pct is not None else None,
            "extra_sources": {
                "j_reduce": f"main_rise_{identity.frequency.value}_last_3_completed_bars"
                if main_rise
                else "unavailable",
                "care": "explicitly_disabled",
                "tent": "explicitly_disabled",
            },
            "missing_roles": [f["role"] for f in facts if f["status"] != "ready"],
        }
    )
    prices = None
    if anchor:

        def price_fact(value, product_bar, category):
            b = product_bar.bar
            return PriceSource(
                value,
                product_bar.frequency.value,
                b.bar_end,
                b.physical_contract,
                b.segment_id,
                product_bar.calculation_segment_id,
                b.source_identity,
                category,
            )

        current_bar = daily[-1].bar if daily else anchor.bar
        current = price_fact(
            current_bar.bar.close, current_bar, "canonical_completed_close"
        )
        previous = next(
            (
                f.bar
                for f in reversed(daily)
                if f.bar.bar.bar_end < current_bar.bar.bar_end
                and f.bar.bar.observation_eligible
                and f.bar.calculation_segment_id == current_bar.calculation_segment_id
            ),
            None,
        )
        prev = (
            price_fact(previous.bar.close, previous, "canonical_previous_daily_close")
            if previous
            else None
        )
        channels = {}
        for freq in (ProductFrequency.DAILY, ProductFrequency.WEEKLY):
            prefix = prefixes.get(("trend", freq), [])
            if not prefix:
                continue
            tail = prefix[-1].bar
            physical_prefix = tuple(
                f.bar
                for f in trend[freq].frames
                if f.bar.calculation_segment_id == tail.calculation_segment_id
                and (f.bar.bar.physical_contract, f.bar.bar.segment_id) == owner
                and f.bar.bar.bar_end <= tail.bar.bar_end
            )
            layer = build_trend_channel_layer(physical_prefix, (tail,))
            point = layer.points[-1]
            if point.availability.status is FeatureRuntimeStatus.READY:
                channels[freq] = (
                    price_fact(point.upper, tail, "canonical_channel"),
                    price_fact(point.lower, tail, "canonical_channel"),
                )
        day = channels.get(ProductFrequency.DAILY, (None, None))
        week = channels.get(ProductFrequency.WEEKLY, (None, None))
        prices = select_cross_period_prices(
            as_of=cutoff,
            current=current,
            previous_close=prev,
            daily_signal=states["trend"]["day"],
            weekly_signal=states["trend"]["week"],
            period="week" if identity.frequency is ProductFrequency.WEEKLY else "day",
            target_daily=day[0],
            cost_daily=day[1],
            target_weekly=week[0],
            cost_weekly=week[1],
            weekly_override=week if all(week) else None,
            source_family="canonical_channel",
        )
        prices["adapter_version"] = "guiyi_canonical_channel_cross_period_v1"
        prices["source_note"] = (
            "Canonical HHV10/LLV10; not private batch price facts. Monthly input unavailable."
        )
    return {"cdv2": cdv2, "prices": prices}
