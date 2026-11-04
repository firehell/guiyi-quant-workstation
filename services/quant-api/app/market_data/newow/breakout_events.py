"""Completed-prefix breakout display facts; independent of strategy actions."""
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
from itertools import groupby
import json

from guiyi_quant.newow.breakout_shapes import (
    FORMULA_VERSION, SOURCE_SHA256, compute_breakout_shapes,
)

DISPLAY_VERSION = FORMULA_VERSION


def _hash(value):
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _owner(item):
    bar = item.bar
    return (bar.product, item.frequency.value, bar.physical_contract,
            bar.segment_id, item.calculation_segment_id)


def _visible_key(item):
    return (item.bar.bar_end.isoformat(), *_owner(item))


def _number(value):
    return None if value is None else str(Decimal(str(value)))


def project_breakout_events(bars_or_replay, *, as_of: datetime | None = None, visible_bars=None):
    """Calculate full replay-labelled prefixes, then select visible known Bars.

    Pending and next-Bar confirmation share an identity; each evidence hash
    contains exactly the input known at the respective time. The public minimum
    of twelve Bars delays index-ten wick knowledge until index eleven.
    """
    bars = (tuple(f.bar for f in bars_or_replay.frames)
            if hasattr(bars_or_replay, "frames") else tuple(bars_or_replay))
    if any(not b.bar.completed for b in bars):
        raise ValueError("NEWOW_BREAKOUT_BAR_NOT_COMPLETED")
    bars = tuple(b for b in bars if as_of is None or b.bar.bar_end <= as_of)
    visible = None if visible_bars is None else {_visible_key(b) for b in visible_bars}
    result = []
    for owner, items in groupby(bars, _owner):
        segment = tuple(items)
        if any(a.bar.bar_end >= b.bar.bar_end for a, b in zip(segment, segment[1:])):
            raise ValueError("NEWOW_BREAKOUT_BAR_ORDER_INVALID")
        digest = sha256()
        hashes = []
        for item in segment:
            b = item.bar
            digest.update(json.dumps(
                [*owner, b.bar_end.isoformat(), b.trading_day.isoformat(),
                 str(b.open), str(b.high), str(b.low), str(b.close), b.volume,
                 b.open_interest, b.source_identity, b.completed, b.observation_eligible],
                separators=(",", ":"),
            ).encode())
            digest.update(b"\n")
            hashes.append(digest.hexdigest())
        for shape in compute_breakout_shapes(tuple(b.bar for b in segment)):
            known_index = max(shape.index, 11)
            known, occur = segment[known_index], segment[shape.occur]
            if not known.bar.observation_eligible or not occur.bar.observation_eligible:
                continue
            if visible is not None and (
                _visible_key(known) not in visible
                or _visible_key(segment[shape.index]) not in visible
            ):
                continue
            kind = {"fake_up_ib": "wick_upper", "fake_dn_ib": "wick_lower"}.get(shape.kind, shape.kind)
            family = "B" if kind in {"wick_upper", "wick_lower"} else "A"
            confirmed = family == "A" and kind != "pending"
            threshold = shape.level + (shape.buffer if shape.side == "up" else -shape.buffer)
            result.append(dict(
                event_id=_hash([DISPLAY_VERSION, *owner, occur.bar.bar_end.isoformat(), shape.side, family]),
                display_version=DISPLAY_VERSION, formula_version=FORMULA_VERSION,
                product=owner[0], frequency=owner[1],
                bar_end=segment[shape.index].bar.bar_end.isoformat(), known_at=known.bar.bar_end.isoformat(),
                occur_bar_end=occur.bar.bar_end.isoformat(),
                confirmed_at=known.bar.bar_end.isoformat() if confirmed else None,
                physical_contract=owner[2], segment_id=owner[3], calculation_segment_id=owner[4],
                kind=kind, side=shape.side, level=_number(shape.level), buffer=_number(shape.buffer),
                threshold=_number(threshold), volume_ratio=_number(shape.volume_ratio),
                volume_ok=shape.volume_ok, doubt=shape.doubt, regime=shape.regime,
                occur_high=str(occur.bar.high), occur_low=str(occur.bar.low),
                confirm_close=str(known.bar.close) if confirmed else None,
                bar_gap=1 if confirmed else None,
                source_sha256=SOURCE_SHA256, input_sha256=hashes[known_index], executable=False,
            ))
    return tuple(sorted(result, key=lambda e: (e["bar_end"], e["event_id"])))
