"""Zero-cost, unit-layer reference projection, independent of the funded account."""
from __future__ import annotations

from bisect import bisect_left
from collections import deque
from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext
from hashlib import sha256
from typing import Mapping, Sequence

from .contracts import Bar, FREQUENCIES, Position, Profile, Variant
from .features import PreparedFeatures, prepare_features
from .strategy import evaluate
from .curve import CurveRecorder

D = Decimal


def feature_stream(prepared: PreparedFeatures, frequency: str, bars: Sequence[Bar]):
    contracts = dict.fromkeys(bar.physical_contract for bar in bars)
    return tuple(sorted((f for c in contracts for f in prepared.series(frequency, c)
                         if f.bar.observation_eligible), key=lambda f: f.bar.bar_end))


def higher_at(prepared: PreparedFeatures, base):
    return {frequency: prepared.at(frequency, base.bar.physical_contract, base.bar.confirmed_at,
                                    owner=base.bar.owner)
            for frequency in FREQUENCIES if frequency != base.bar.frequency}


def snapshot(position: Position | None, *, reason: str = "READY", unavailable: bool = False) -> dict:
    return {
        "side": "UNAVAILABLE" if unavailable else "FLAT" if position is None else "LONG" if position.side > 0 else "SHORT",
        "holding_frequency": position.holding_frequency if position else None,
        "entry_reference_price": str(position.entry) if position else None,
        "stop_reference_price": str(position.stop) if position else None,
        "target_reference_price": str(position.entry_target) if position and position.entry_target else None,
        "upgrades": position.upgrades if position else 0,
        "overnight_eligible": position.overnight_eligible if position else False,
        "reason": reason, "executable": False,
    }


def chart_bar(bar: Bar) -> dict:
    return {"bar_end": bar.bar_end.isoformat(), "trading_day": bar.trading_day.isoformat(),
            "open": str(bar.open), "high": str(bar.high), "low": str(bar.low), "close": str(bar.close),
            "volume": str(bar.volume), "physical_contract": bar.physical_contract,
            "owner_segment_id": bar.owner_segment_id, "source_identity": bar.source_identity}


def empty_reference(reason: str) -> dict:
    return {"summary": {"status": reason, "closed_trades": 0, "reference_return_pct": None,
                        "executable": False, "zero_cost": True},
            "snapshot": snapshot(None, reason=reason, unavailable=True), "actions": [], "trades": [],
            "equity": [], "chart": {"bars": [], "frames": []}}


def run_reference(profile: Profile, bars_by_frequency: Mapping[str, Sequence[Bar]],
                  minute_bars: Sequence[Bar], *, prepared: PreparedFeatures | None = None,
                  ticks: Mapping[tuple[str, date], Decimal] | None = None) -> dict:
    with localcontext(Context(prec=28, rounding=ROUND_HALF_EVEN)):
        return _run_reference(profile, bars_by_frequency, minute_bars, prepared=prepared, ticks=ticks)


def _run_reference(profile, bars_by_frequency, minute_bars, *, prepared, ticks):
    """Project known market paths without assuming any funded order was accepted.

    Trade qty counts cumulative fixed reference units opened in this round: one
    core unit plus one for each applied ADD. REDUCE never erases opened units.
    The same count is retained for OPEN, CLOSED, and interrupted rounds; it is
    neither the remaining position quantity nor funded-account contract lots.
    """
    if profile.variant == Variant.TEST3 and profile.frequency == "1w":
        return empty_reference("NOT_APPLICABLE")
    if not minute_bars or not bars_by_frequency.get(profile.frequency):
        return empty_reference("DATA_INSUFFICIENT")
    prepared = prepared or prepare_features(bars_by_frequency)
    features = feature_stream(prepared, profile.frequency, bars_by_frequency[profile.frequency])
    if not features:
        return empty_reference("DATA_INSUFFICIENT")
    ticks = ticks or {}
    minutes = tuple(minute_bars)
    ends = tuple(bar.bar_end for bar in minutes)
    position: Position | None = None
    owner = None
    layers: list[tuple[Decimal, bool]] = []
    actions: list[dict] = []
    trades: list[dict] = []
    chart, frames = deque(maxlen=2000), deque(maxlen=2000)
    curve = CurveRecorder()
    closed_return = D(0)
    round_realized = D(0)
    round_notional = D(0)
    entry = None
    cooldown: datetime | None = None
    status = "COMPLETED"
    last_reason = "READY"
    ready_count = 0
    j = i = 0

    def action(kind: str, bar: Bar, reason: str, price: Decimal) -> None:
        actions.append({"action_id": sha256(f"reference|{profile.profile_id}|{bar.source_identity}|{len(actions)}".encode()).hexdigest(),
                        "at": bar.confirmed_at.isoformat(), "bar_end": bar.bar_end.isoformat(), "action": kind,
                        "side": "LONG" if position and position.side > 0 else "SHORT" if position else "FLAT",
                        "price": str(price), "reference_price": str(price), "reason": reason,
                        "physical_contract": bar.physical_contract, "executable": False,
                        "owner_segment_id": bar.owner_segment_id,
                        "calculation_segment_id": bar.calculation_segment_id,
                        "trading_day": bar.trading_day.isoformat(),
                        "holding_frequency": position.holding_frequency if position else None})

    def close(bar: Bar, reason: str, *, interrupted: bool = False) -> None:
        nonlocal position, layers, entry, closed_return, round_realized, round_notional, cooldown
        if position is None or entry is None:
            return
        price = bar.close
        value = round_realized + sum(((price - cost) * position.side for cost, _ in layers), D(0))
        pct = value / round_notional * 100 if round_notional else D(0)
        trades.append({**entry, "exit_bar_end": None if interrupted else bar.bar_end.isoformat(),
                       "exit_reference_price": None if interrupted else str(price),
                       "reference_return_pct": None if interrupted else str(pct),
                       "status": reason if interrupted else "CLOSED", "reason": reason,
                       "holding_frequency": position.holding_frequency, "added": position.adds > 0,
                       "qty": 1 + position.adds,
                       "overnight": entry["entry_trading_day"] != bar.trading_day.isoformat()})
        if not interrupted:
            action("CLOSE", bar, reason, price)
            closed_return += pct
        position, layers, entry = None, [], None
        round_realized, round_notional = D(0), D(0)
        cooldown = bar.confirmed_at

    while i < len(minutes):
        minute = minutes[i]
        if owner is not None and minute.owner != owner and position is not None:
            prior = minutes[i - 1]
            close(prior, "ROLLOVER_INTERRUPTED", interrupted=True)
            status = "ROLLOVER_INTERRUPTED"
        owner = minute.owner
        if position is not None and (minute.close - position.stop) * position.side <= 0:
            close(minute, "PROTECTIVE_CLOSE")
        if (position is not None and profile.frequency.endswith("m") and minute.session_close_at is not None
                and minute.bar_end >= minute.session_close_at - timedelta(minutes=2)
                and not position.overnight_eligible):
            close(minute, "DAY_ONLY_CLOSE")
        while j < len(features) and features[j].bar.confirmed_at <= minute.bar_end:
            base = features[j]
            j += 1
            if base.bar.owner != minute.owner:
                continue
            chart.append(chart_bar(base.bar))
            tick = ticks.get((base.bar.physical_contract, base.bar.trading_day))
            if tick is None:
                last_reason = "EXECUTION_FACTS_MISSING"
                frames.append({"at": base.bar.bar_end.isoformat(), "bar_end": base.bar.bar_end.isoformat(),
                               **snapshot(position, reason=last_reason, unavailable=True)})
                status = "EXECUTION_FACTS_MISSING"
                continue
            if position is None and cooldown is not None:
                if base.bar.bar_end <= cooldown:
                    continue
                # This complete base Bar is the required flat cooldown, not an entry.
                cooldown = None
                frames.append({"at": base.bar.bar_end.isoformat(), "bar_end": base.bar.bar_end.isoformat(),
                               **snapshot(None, reason="COOLDOWN")})
                continue
            decision = evaluate(profile, base, higher_at(prepared, base), position, tick=tick)
            if decision.reason != "INPUT_UNAVAILABLE":
                ready_count += 1
            last_reason = decision.reason
            if decision.reason == "INPUT_UNAVAILABLE" and position is not None:
                close(base.bar, "DATA_INTERRUPTED", interrupted=True)
                status = "DATA_INTERRUPTED"
            else:
                position = decision.position
                late = (profile.frequency.endswith("m") and base.bar.session_close_at is not None
                        and base.bar.confirmed_at >= base.bar.session_close_at - timedelta(minutes=2))
                if decision.action == "ENTER":
                    if late:
                        position = None
                    else:
                        layers = [(base.bar.close, False)]
                        round_notional = base.bar.close
                        entry = {"reference_trade_id": sha256(f"{profile.profile_id}|{base.bar.source_identity}".encode()).hexdigest(),
                                 "entry_bar_end": base.bar.bar_end.isoformat(), "entry_trading_day": base.bar.trading_day.isoformat(),
                                 "entry_reference_price": str(base.bar.close), "side": "LONG" if position.side > 0 else "SHORT",
                                 "physical_contract": base.bar.physical_contract, "owner_segment_id": base.bar.owner_segment_id}
                        action("OPEN_LONG" if position.side > 0 else "OPEN_SHORT", base.bar, decision.reason, base.bar.close)
                elif decision.action == "CLOSE":
                    close(base.bar, decision.reason)
                elif (position is not None and not position.overnight_eligible and
                      (late or (entry and entry["entry_trading_day"] != base.bar.trading_day.isoformat()))):
                    close(base.bar, "OVERNIGHT_ELIGIBILITY_LOST")
                elif decision.action == "REDUCE" and layers:
                    if len(layers) > 1:
                        cost, _ = layers.pop()
                        round_realized += (base.bar.close - cost) * position.side
                        position = replace(position, reduced=True)
                        action("REDUCE", base.bar, decision.reason, base.bar.close)
                    else:
                        action("WAIT", base.bar, "MIN_LOT_NOT_DIVISIBLE", base.bar.close)
                elif decision.action == "ADD" and not late:
                    layers.append((base.bar.close, True))
                    round_notional += base.bar.close
                    position = replace(position, adds=position.adds + 1)
                    action("ADD", base.bar, decision.reason, base.bar.close)
            frames.append({"at": base.bar.bar_end.isoformat(), "bar_end": base.bar.bar_end.isoformat(),
                           **snapshot(position, reason=last_reason, unavailable=last_reason == "INPUT_UNAVAILABLE")})
        floating = (round_realized + sum(((minute.close - cost) * position.side for cost, _ in layers), D(0))) / round_notional * 100 if position and round_notional else D(0)
        point = {"at": minute.bar_end.isoformat(), "value": str(closed_return + floating),
                 "physical_contract": minute.physical_contract}
        curve.add((minute.trading_day, minute.owner), point)
        i += 1
        if position is None and j < len(features):
            i = max(i, bisect_left(ends, features[j].bar.confirmed_at, lo=i))
        elif position is None and j >= len(features):
            break
    if position is not None and entry is not None:
        mark = minutes[-1]
        value = round_realized + sum(((mark.close - cost) * position.side for cost, _ in layers), D(0))
        trades.append({**entry, "exit_bar_end": None, "exit_reference_price": None,
                       "reference_return_pct": None, "mark_change_pct": str(value / round_notional * 100),
                       "status": "OPEN", "holding_frequency": position.holding_frequency, "added": position.adds > 0,
                       "qty": 1 + position.adds})
    if ready_count == 0 and status == "COMPLETED":
        status = "DATA_INSUFFICIENT"
    return {"summary": {"status": status, "closed_trades": sum(t["status"] == "CLOSED" for t in trades),
                         "reference_return_pct": str(closed_return) if status == "COMPLETED" else None,
                         "executable": False, "zero_cost": True},
            "snapshot": snapshot(position, reason=last_reason, unavailable=status in ("DATA_INSUFFICIENT", "DATA_INTERRUPTED", "EXECUTION_FACTS_MISSING")),
            "actions": actions, "trades": trades, "equity": curve.finish(),
            "chart": {"bars": list(chart), "frames": list(frames)}}
