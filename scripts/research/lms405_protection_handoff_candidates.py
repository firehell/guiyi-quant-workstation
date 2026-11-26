"""Source-scoped test candidates for removing and replacing an old protective leg."""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from guiyi_quant.lms405.protection_band import active_band, visible_bands
from lms405_replay import ohlc
from lms405_right_side_study import ONE, US
from lms405_sh_lock_lifecycle import signals


@dataclass(frozen=True)
class HandoffPlan:
    contract: str
    old_lock_revision: str
    recovery_revision: str
    recovery_known_at: datetime
    recovery_start: datetime
    recovery_edge: Decimal
    replacement_revision: str
    replacement_known_at: datetime
    replacement_start: datetime
    recovery_clock: str


def handoff_events(series, bands, plan, cutoff):
    """Require a known plan before the reference bar and use completed geometry only."""
    if not series[1]:
        return [], []
    if plan.contract != series[1][0].contract or plan.recovery_clock not in {"FAR_CLOSE", "FAR_CLOSE_THEN_SHAPE"}:
        raise ValueError("LMS_HANDOFF_SCOPE_INVALID")
    recoveries, protections = [], []
    recovery_cut = min(cutoff, plan.replacement_known_at)
    first_bars, active_breaks = [], {}
    previous_end = run_start = None
    for bar in series[1]:
        if bar.start < plan.recovery_start or bar.start <= plan.recovery_known_at:
            continue
        if bar.end + US >= recovery_cut:
            break
        if previous_end != bar.start or bar.close >= plan.recovery_edge:
            run_start = None
        previous_end = bar.end
        if bar.close < plan.recovery_edge:
            if run_start is None:
                run_start = bar
                first_bars.append(bar)
            active_breaks[bar.end] = run_start

    candidates = [(bar.end + US, bar.start, 1, None, bar) for bar in first_bars]
    if plan.recovery_clock == "FAR_CLOSE_THEN_SHAPE":
        candidates = []
        for period in (1, 5):
            for signal in signals(series, period, 1, side="SHORT", start=plan.recovery_start, cut=recovery_cut):
                run_start = active_breaks.get(signal["confirmed_at"])
                shape_start = signal["shape_end"] - period * ONE
                if run_start is not None and run_start.end + US < shape_start:
                    candidates.append((signal["available_at"], shape_start, period, signal, run_start))
    for known, shape_start, period, signal, run_start in candidates:
        ready = known + 5 * US
        if ready < recovery_cut:
            recoveries.append(dict(at=ready, known_at=known, shape_start=shape_start, period=period, signal=signal,
                                   contract=plan.contract, first_break_start=run_start.start,
                                   first_break_known_at=run_start.end + US, recovery_edge=plan.recovery_edge,
                                   revision=plan.recovery_revision, old_lock_revision=plan.old_lock_revision,
                                   clock=plan.recovery_clock))

    for period in (1, 5):
        shapes = {bar.end: bar for bar in series[period]}
        for signal in signals(series, period, 1, side="LONG", start=plan.replacement_start, cut=cutoff):
            known = signal["available_at"]
            ready = known + 5 * US
            if ready >= cutoff:
                continue
            band, _ = active_band(visible_bands(bands, plan.contract, known), known, "SHORT")
            if band is None or band.revision != plan.replacement_revision:
                continue
            latest, _ = active_band(visible_bands(bands, plan.contract, ready), ready, "SHORT")
            shape = shapes[signal["shape_end"]]
            opened, _, low, closed = ohlc(shape)
            if (latest != band or max(band.effective_after, plan.replacement_known_at) >= shape.start
                    or not low <= band.upper < min(opened, closed) or signal["close"] <= band.upper):
                continue
            protections.append(dict(at=ready, known_at=known, shape_start=shape.start, band=band, period=period,
                                    signal=signal, operation="PROTECT_REGULAR", contract=plan.contract,
                                    required_recovery=plan.recovery_revision))
    return sorted(recoveries, key=lambda row: (row["at"], row["period"])), sorted(
        protections, key=lambda row: (row["at"], row["period"]),
    )
