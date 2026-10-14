"""Immutable research facts about EMA21 positions at first signal detection."""

from collections import OrderedDict
from threading import Lock
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import re

from app.alerts.registry import SUBING_SIGNAL_FREQUENCIES
from app.market_data.domain import BarFrequency
from app.market_data.market_read_service import MarketReadWindow
from guiyi_quant.indicators.ema import initial_ema_state, step_ema

POLICY_VERSION = "subing_ema21_alignment_v1"


def build_subing_alignment(
    market_read, decision: MarketReadWindow, *, direction: str, observed_at: datetime
) -> dict[str, object]:
    if (
        direction not in {"buy", "sell"}
        or observed_at.tzinfo is None
        or observed_at < decision.cutoff
    ):
        raise ValueError("SUBING_ALIGNMENT_IDENTITY_INVALID")
    periods = []
    for frequency in SUBING_SIGNAL_FREQUENCIES:
        period = dict(
            frequency=frequency,
            contract=decision.contract,
            bar_end=None,
            close=None,
            ema21=None,
            direction="UNKNOWN",
            reason=None,
            input_snapshot_hash=None,
        )
        try:
            source = market_read.subing_direction_window(
                decision, BarFrequency(frequency)
            )
            if (
                source.symbol != decision.symbol
                or source.contract != decision.contract
                or source.frequency != frequency
                or source.cutoff > decision.cutoff
                or not source.bars
                or source.bars[-1].bar_end != source.cutoff
                or source.after is not None
                or any(bar.bar_end > source.cutoff for bar in source.bars)
                or any(
                    a.bar_end >= b.bar_end for a, b in zip(source.bars, source.bars[1:])
                )
            ):
                raise ValueError("INPUT_IDENTITY_INVALID")
            period.update(_verified_period_facts(decision.contract, frequency, source.cutoff, source.bars))
        except Exception as exc:
            # Preserve the raw signal even when a peer cannot be proved; never substitute a different source.
            period["reason"] = (
                str(exc)
                if re.fullmatch(r"[A-Z][A-Z0-9_]{0,95}", str(exc))
                else "INPUT_UNAVAILABLE"
            )
        periods.append(period)
    wanted = "LONG" if direction == "buy" else "SHORT"
    status = (
        "UNKNOWN"
        if any(p["direction"] == "UNKNOWN" for p in periods)
        else "PASS"
        if all(p["direction"] == wanted for p in periods)
        else "FAIL"
    )
    return dict(
        policy_version=POLICY_VERSION,
        as_of=decision.cutoff.isoformat(),
        observed_at=observed_at.isoformat(),
        status=status,
        periods=periods,
    )


# Facts only: input authority is freshly verified by subing_direction_window.
# Keys hash exactly the original policy's ordered physical close prefix.
_PERIOD_CACHE: OrderedDict[tuple[str, str], tuple[tuple[str, object], ...]] = OrderedDict()
_PERIOD_CACHE_LOCK = Lock()


def _verified_period_facts(contract, frequency, cutoff, bars):
    digest = hashlib.sha256(json.dumps(
        [contract, frequency, [(b.bar_end.isoformat(), b.trading_day.isoformat(), str(b.close)) for b in bars]],
        separators=(",", ":"),
    ).encode()).hexdigest()
    key = (POLICY_VERSION, digest)
    with _PERIOD_CACHE_LOCK:
        previous = _PERIOD_CACHE.get(key)
        if previous is not None:
            _PERIOD_CACHE.move_to_end(key)
            return dict(previous)
    state = initial_ema_state(21, seed_policy="sma_window", round_digits=6)
    point = None
    for bar in bars:
        if not bar.close.is_finite() or bar.close <= 0:
            raise ValueError("INPUT_INVALID")
        state, point = step_ema(state, float(bar.close), bar_end=bar.bar_end.isoformat())
        if not point.valid:
            raise ValueError("INPUT_INVALID")
    last = bars[-1]
    facts = dict(bar_end=last.bar_end.isoformat(), close=str(last.close), input_snapshot_hash=digest)
    if point is None or not point.ready or point.value is None:
        facts["reason"] = "WARMING_UP"
    else:
        ema = Decimal(str(point.value))
        close = Decimal(str(round(float(last.close), 6)))
        facts.update(ema21=str(ema), direction="LONG" if close > ema else "SHORT" if close < ema else "FLAT")
    with _PERIOD_CACHE_LOCK:
        _PERIOD_CACHE[key] = tuple(facts.items())
        _PERIOD_CACHE.move_to_end(key)
        while len(_PERIOD_CACHE) > 384:
            _PERIOD_CACHE.popitem(last=False)
    return facts
