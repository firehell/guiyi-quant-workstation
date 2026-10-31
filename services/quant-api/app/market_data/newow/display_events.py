"""Public page display projections. No actions, fills, returns or account effects.

Always consume the full authenticated calculation prefix, then let the caller
select the visible window. IDs deliberately exclude windows and request times.
"""

from dataclasses import replace
from decimal import Decimal
from hashlib import sha256
from itertools import groupby
import json
from math import floor

from guiyi_quant.newow.main_rise import MAIN_RISE_PAGE_V1, calculate_main_rise_series
from guiyi_quant.newow.oscillation_attack import (
    calculate_oscillation_attack,
    FORMULA_VERSION as ZLGJ_FORMULA_VERSION,
)
from guiyi_quant.newow.oscillation_channel import (
    calculate_oscillation_series,
    OSCILLATION_FORMULA_VERSION,
)
from guiyi_quant.newow.product_identity import build_signal_id
from guiyi_quant.newow.trend_reversal import (
    calculate_trend_reversal,
    TREND_REVERSAL_FORMULA_VERSION,
)

DISPLAY_VERSION = "newow_public_display_v3431_v1"


def cents(value: Decimal) -> int:
    # Public JS uses Math.round(Number(price) * 100), not contract ticks or
    # Decimal.quantize. Prices are positive; retain its IEEE-754 boundary.
    return floor(float(value) * 100 + 0.5)


def event(bar, kind, strategy, formula, **extra):
    raw = bar.bar
    fields = dict(
        display_version=DISPLAY_VERSION,
        kind=kind,
        source_strategy=strategy,
        formula_version=formula,
        frequency=bar.frequency.value,
        bar_end=raw.bar_end.isoformat(),
        known_at=raw.bar_end.isoformat(),
        physical_contract=raw.physical_contract,
        segment_id=raw.segment_id,
        calculation_segment_id=bar.calculation_segment_id,
        source_build_id=None,
        build_bar_end=None,
        build_threshold=None,
        observed_close=str(raw.close),
        signal_kind=None,
        page_parity=True,
        executable=False,
        quantity_effect="none",
        **extra,
    )
    fields["event_id"] = sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()
    return fields


def breakdown_events(bars, signals, strategy, formula, build_id):
    """Signals are main-chart signals, never the reference-return replay."""
    entry = None
    emitted = False
    result = []
    for index, (bar, actions) in enumerate(zip(bars, signals, strict=True)):
        # Explicit source order: clear/stop before build. A new build resets
        # the one-shot latch, including a genuine same-Bar reentry.
        for sequence, action in enumerate(actions):
            if action.action.value == "CLEAR":
                entry = None
                emitted = False
        for sequence, action in enumerate(actions):
            if action.action.value == "BUILD":
                entry = (
                    action.price,
                    bar.bar.bar_end.isoformat(),
                    build_id(index, sequence),
                )
                emitted = False
        if entry is not None and not emitted and cents(bar.bar.close) < cents(entry[0]):
            emitted = True  # warmup also consumes the first event, never reemit at a page boundary
            if bar.bar.observation_eligible:
                item = event(bar, "OSC_BREAKDOWN", strategy, formula)
                item.update(
                    source_build_id=entry[2],
                    build_bar_end=entry[1],
                    build_threshold=str(entry[0]),
                )
                # Include association in the stable content identity.
                item["event_id"] = sha256(
                    json.dumps(
                        {k: v for k, v in item.items() if k != "event_id"},
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                result.append(item)
    return result


def shared_events(bars, *, include_j=True, include_zlgj=False):
    raw = tuple(b.bar for b in bars)
    result = []
    if include_j and len(raw) >= 10:
        main = calculate_main_rise_series(raw)
        attack = calculate_oscillation_attack(raw)
        for bar, rise, zlgj in zip(bars, main, attack, strict=True):
            if include_zlgj and bar.bar.observation_eligible and zlgj["j_warning"]:
                result.append(
                    event(bar, "ZLGJ_J", "oscillation_attack", ZLGJ_FORMULA_VERSION)
                )
            if (
                bar.bar.observation_eligible
                and rise.reduce_signal is not None
                and not zlgj["j_warning"]
            ):
                result.append(
                    event(
                        bar,
                        "MAIN_RISE_J",
                        "main_rise",
                        MAIN_RISE_PAGE_V1.j_reduce_formula,
                    )
                )
    reversal = calculate_trend_reversal(raw)
    if reversal is not None:
        for bar, rebound, adjust in zip(
            bars, reversal.rebound, reversal.adjust, strict=True
        ):
            if bar.bar.observation_eligible and (rebound or adjust):
                item = event(
                    bar,
                    "TREND_REVERSAL",
                    "trend_reversal",
                    TREND_REVERSAL_FORMULA_VERSION,
                )
                item["signal_kind"] = "rebound" if rebound else "adjust"
                item["event_id"] = sha256(
                    json.dumps(
                        {k: v for k, v in item.items() if k != "event_id"},
                        sort_keys=True,
                    ).encode()
                ).hexdigest()
                result.append(item)
    return result


def project_display_events(replay):
    result = []
    for _, frames in groupby(
        replay.frames,
        lambda f: (
            f.bar.bar.physical_contract,
            f.bar.bar.segment_id,
            f.bar.calculation_segment_id,
        ),
    ):
        bars = tuple(f.bar for f in frames)
        result.extend(
            shared_events(bars, include_j=replay.identity.strategy.value != "main_rise")
        )
        if replay.identity.strategy.value == "oscillation":
            # The existing kernel advances warmup state but masks its signals.
            # This shadow only reveals those same transitions for display ownership.
            steps = calculate_oscillation_series(
                tuple(replace(b.bar, observation_eligible=True) for b in bars)
            )
            result.extend(
                breakdown_events(
                    bars,
                    (s.signals for s in steps),
                    "oscillation",
                    OSCILLATION_FORMULA_VERSION,
                    lambda i, seq: build_signal_id(
                        replay.identity,
                        bars[i].bar.physical_contract,
                        bars[i].bar.segment_id,
                        bars[i].bar.bar_end,
                        "BUILD",
                        seq,
                        bars[i].calculation_segment_id,
                    ),
                )
            )
    return tuple(sorted(result, key=lambda e: (e["bar_end"], e["kind"])))
